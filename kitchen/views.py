import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from core.mixins import ActiveStaffMixin, CashCollectionMixin, OrderCompletionMixin
from core.models import StaffFilter
from core.ratelimit import rate_limit
from core.timeutils import local_day_bounds
from ordering.models import Order, OrderItem, OrderItemAddOn, WorkStatus
from ordering.services import (
    confirm_cash_payment,
    expire_overdue_unpaid_cash_orders,
    get_cash_payment_timeout_minutes,
    sync_order_status,
)
from kitchen.services import trigger_kds_refresh

logger = logging.getLogger(__name__)


def _first_name(full_name):
    return (full_name.split()[0] if full_name else "")[:20]


def _safe_image_url(image_value):
    if not image_value:
        return ""
    return image_value if isinstance(image_value, str) else ""


def _can_run_bulk_order_action(user):
    return bool(
        user.is_owner or (
            user.allow_order_completion and user.allow_view_all_orders
        )
    )


def _effective_item_status(item, addon_rows):
    statuses = [item.prep_status] + [addon.prep_status for addon in addon_rows]
    if statuses and all(status == WorkStatus.COMPLETED for status in statuses):
        return WorkStatus.COMPLETED
    if WorkStatus.PREPARING in statuses:
        return WorkStatus.PREPARING
    if WorkStatus.PENDING in statuses:
        return WorkStatus.PENDING
    return item.prep_status


def _addon_preview(addon_rows):
    return [
        {
            "id": str(addon.id),
            "name": addon.addon_name,
            "qty": addon.quantity,
            "status": addon.prep_status,
        }
        for addon in addon_rows
    ]


def _build_item_work_unit(item, addon_rows):
    dining_label = (
        "Parcel"
        if item.dining_option == item.DiningOption.PARCEL
        else "Dine in"
    )
    category_name = ""
    if item.menu_item_id and item.menu_item and item.menu_item.item_type_id and item.menu_item.item_type:
        category_name = item.menu_item.item_type.name or ""

    return {
        "id": str(item.id),
        "kind": "item",
        "menu_item_id": str(item.menu_item_id) if item.menu_item_id else "",
        "status": _effective_item_status(item, addon_rows),
        "name": item.menu_item_name,
        "qty": item.quantity,
        "detail": dining_label,
        "dining_option_label": dining_label,
        "is_parcel": item.dining_option == item.DiningOption.PARCEL,
        "spice_level": item.get_spice_level_display() if item.spice_level else "",
        "has_addons": bool(addon_rows),
        "attached_addons": _addon_preview(addon_rows),
        "image_url": _safe_image_url(
            item.menu_item.image if item.menu_item_id and item.menu_item else None
        ),
        "category_name": category_name,
    }


def _serialize_order_for_status(order, target_status):
    work_units = []
    menu_item_ids = set()

    for item in order.items.all():
        addon_rows = list(item.addons.all())
        effective_status = _effective_item_status(item, addon_rows)
        if effective_status != target_status:
            continue

        if item.menu_item_id:
            menu_item_ids.add(str(item.menu_item_id))
        work_units.append(_build_item_work_unit(item, addon_rows))

    if not work_units:
        return None

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "customer": _first_name(order.customer_name),
        "table": order.table_number,
        "status": order.status,
        "total": str(order.total),
        "created_at": order.created_at.isoformat(),
        "menu_item_ids": sorted(menu_item_ids),
        "work_units": work_units,
    }


def _serialize_all_order(order):
    items = []
    menu_item_ids = set()

    for item in order.items.all():
        addon_rows = list(item.addons.all())
        if item.menu_item_id:
            menu_item_ids.add(str(item.menu_item_id))
        items.append({
            "id": str(item.id),
            "menu_item_id": str(item.menu_item_id) if item.menu_item_id else "",
            "name": item.menu_item_name,
            "qty": item.quantity,
            "status": _effective_item_status(item, addon_rows),
            "image_url": _safe_image_url(
                item.menu_item.image if item.menu_item_id and item.menu_item else None
            ),
            "dining_option_label": (
                "Parcel"
                if item.dining_option == item.DiningOption.PARCEL
                else "Dine in"
            ),
            "is_parcel": item.dining_option == item.DiningOption.PARCEL,
            "spice_level": item.get_spice_level_display() if item.spice_level else "",
            "has_addons": bool(addon_rows),
            "addons": _addon_preview(addon_rows),
        })

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "customer": _first_name(order.customer_name),
        "table": order.table_number,
        "status": order.status,
        "payment_method": order.get_payment_method_display(),
        "total": str(order.total),
        "created_at": order.created_at.isoformat(),
        "menu_item_ids": sorted(menu_item_ids),
        "items": items,
    }


def _start_item_group(item, user):
    now = timezone.now()
    changed = False
    update_fields = []

    addon_rows = list(
        OrderItemAddOn.objects.select_for_update().filter(order_item=item)
    )
    pending_addons = [addon for addon in addon_rows if addon.prep_status == WorkStatus.PENDING]

    if item.prep_status == WorkStatus.PENDING or (
        item.prep_status == WorkStatus.COMPLETED and pending_addons
    ):
        item.prep_status = WorkStatus.PREPARING
        item.prep_started_at = item.prep_started_at or now
        item.prep_started_by = item.prep_started_by or user
        item.completed_at = None
        item.completed_by = None
        update_fields.extend([
            "prep_status",
            "prep_started_at",
            "prep_started_by",
            "completed_at",
            "completed_by",
        ])
        changed = True

    if update_fields:
        item.save(update_fields=update_fields)

    for addon in pending_addons:
        addon.prep_status = WorkStatus.PREPARING
        addon.prep_started_at = addon.prep_started_at or now
        addon.prep_started_by = addon.prep_started_by or user
        addon.completed_at = None
        addon.completed_by = None
        addon.save(update_fields=[
            "prep_status",
            "prep_started_at",
            "prep_started_by",
            "completed_at",
            "completed_by",
        ])
        changed = True

    return changed


def _complete_item_group(item, user):
    now = timezone.now()
    changed = False

    addon_rows = list(
        OrderItemAddOn.objects.select_for_update().filter(order_item=item)
    )

    if item.prep_status != WorkStatus.COMPLETED:
        if not item.prep_started_at:
            item.prep_started_at = now
        if not item.prep_started_by:
            item.prep_started_by = user
        item.prep_status = WorkStatus.COMPLETED
        item.completed_at = now
        item.completed_by = user
        item.save(update_fields=[
            "prep_started_at",
            "prep_started_by",
            "prep_status",
            "completed_at",
            "completed_by",
        ])
        changed = True

    for addon in addon_rows:
        if addon.prep_status == WorkStatus.COMPLETED:
            continue
        if not addon.prep_started_at:
            addon.prep_started_at = now
        if not addon.prep_started_by:
            addon.prep_started_by = user
        addon.prep_status = WorkStatus.COMPLETED
        addon.completed_at = now
        addon.completed_by = user
        addon.save(update_fields=[
            "prep_started_at",
            "prep_started_by",
            "prep_status",
            "completed_at",
            "completed_by",
        ])
        changed = True

    return changed


class KDSView(ActiveStaffMixin, View):
    def get(self, request):
        return render(request, "kitchen/kds.html", {
            "user": request.user,
            "restaurant": self.get_restaurant(),
def _incr_metric(key):
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=None)

def _track_active_screen(restaurant_id, screen_session_key):
    redis_url = getattr(settings, "REDIS_URL", None)
    if redis_url:
        import redis, time
        try:
            client = redis.from_url(redis_url)
            now = int(time.time())
            client.zadd("kds_active_restaurants", {str(restaurant_id): now})
            client.zadd(f"kds_screens_{restaurant_id}", {str(screen_session_key): now})
        except Exception:
            pass

@method_decorator(rate_limit('kds_poll', limit=600, window=60), name='dispatch')
class KDSPollView(ActiveStaffMixin, View):
    def _build_restaurant_payload(self, restaurant, today_start, today_end):
        import time
        start_time = time.time()
        
        item_prefetch = Prefetch(
            "items",
            queryset=(
                OrderItem.objects
                .select_related("menu_item", "menu_item__item_type")
                .prefetch_related(
                    Prefetch(
                        "addons",
                        queryset=OrderItemAddOn.objects.select_related("addon"),
                    )
                )
            ),
        )

        active_orders = (
            Order.objects
            .filter(
                restaurant=restaurant,
                created_at__gte=today_start,
                created_at__lt=today_end,
                status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED],
            )
            .prefetch_related(item_prefetch)
            .order_by("created_at")
        )

        kitchen_data = []
        preparing_data = []
        for order in active_orders:
            kitchen_payload = _serialize_order_for_status(order, WorkStatus.PENDING)
            preparing_payload = _serialize_order_for_status(order, WorkStatus.PREPARING)
            if kitchen_payload:
                kitchen_data.append(kitchen_payload)
            if preparing_payload:
                preparing_data.append(preparing_payload)

        payment_orders = [
            {
                "id": str(order.id),
                "order_number": order.order_number,
                "customer": _first_name(order.customer_name),
                "table": order.table_number,
                "status": order.status,
                "total": str(order.total),
                "created_at": order.created_at.isoformat(),
                "items": [
                    {
                        "id": str(item.id),
                        "name": item.menu_item_name,
                        "qty": item.quantity,
                        "is_parcel": item.dining_option == item.DiningOption.PARCEL,
                    }
                    for item in order.items.all()
                ],
            }
            for order in (
                Order.objects
                .filter(
                    restaurant=restaurant,
                    created_at__gte=today_start,
                    created_at__lt=today_end,
                    status=Order.Status.UNPAID,
                    payment_method=Order.PaymentMethod.CASH,
                )
                .prefetch_related(Prefetch("items", queryset=OrderItem.objects.all()))
                .order_by("created_at")
            )
        ]

        all_orders = [
            _serialize_all_order(order)
            for order in (
                Order.objects
                .filter(
                    restaurant=restaurant,
                    created_at__gte=today_start,
                    created_at__lt=today_end,
                )
                .prefetch_related(item_prefetch)
                .order_by("-created_at")
            )
        ]

        filter_queryset = (
            StaffFilter.objects
            .filter(restaurant=restaurant)
            .prefetch_related("items")
            .order_by("name")
        )
        staff_filters = [
            {
                "id": str(staff_filter.id),
                "name": staff_filter.name,
                "item_ids": [
                    str(item_id)
                    for item_id in staff_filter.items.values_list("id", flat=True)
                ],
            }
            for staff_filter in filter_queryset
        ]

        payload = {
            "server_time": timezone.now().isoformat(),
            "cash_timeout_minutes": get_cash_payment_timeout_minutes(),
            "staff_filters": staff_filters,
            "kitchen": kitchen_data,
            "preparing": preparing_data,
            "payments": payment_orders,
            "all_orders": all_orders,
            "tab_counts": {
                "kitchen": len(kitchen_data),
                "preparing": len(preparing_data),
                "payments": len(payment_orders),
                "all_orders": len(all_orders),
            },
        }
        
        rebuild_ms = int((time.time() - start_time) * 1000)
        logger.info("metric kds_payload_rebuild_ms %d restaurant_id=%s", rebuild_ms, restaurant.id)
        cache.set("kds_metrics_payload_rebuild_ms", rebuild_ms, timeout=None)
        return payload

    def get(self, request):
        import time
        logger.info("metric kds_poll_requests_total 1 restaurant_id=%s", request.user.restaurant_id)
        _incr_metric("kds_metrics_requests_total")
        
        restaurant = self.get_restaurant()
        user = request.user
        
        # Track Active Screen / Restaurant
        session_key = request.session.session_key or str(user.id)
        _track_active_screen(restaurant.id, session_key)
        today = timezone.localdate()
        today_start, today_end = local_day_bounds(today)

        # Rate-limit expiration sweep: max once per 30s per restaurant
        expiry_key = f"cash_expiry_lock_{restaurant.id}"
        if cache.add(expiry_key, 1, timeout=30):
            expire_overdue_unpaid_cash_orders(restaurant=restaurant)

        # Get cache version
        version_key = f"kds_version_{restaurant.id}"
        version_val = cache.get(version_key, 1)
        # Ensure version is an int for stale math
        try:
            version = int(version_val)
        except (ValueError, TypeError):
            version = 1

        # Build unique cache key normalized to restaurant and version
        cache_key = f"kds_payload_{restaurant.id}_v{version}"
        lock_key = f"{cache_key}_lock"

        cached_payload = cache.get(cache_key)
        
        if cached_payload:
            logger.info("metric kds_cache_hit 1 restaurant_id=%s", restaurant.id)
            _incr_metric("kds_metrics_cache_hits")
            master_payload = cached_payload
        else:
            logger.info("metric kds_cache_miss 1 restaurant_id=%s", restaurant.id)
            _incr_metric("kds_metrics_cache_misses")
            # Try to acquire lock
            if cache.add(lock_key, "locked", timeout=5):
                try:
                    master_payload = self._build_restaurant_payload(restaurant, today_start, today_end)
                    cache.set(cache_key, master_payload, timeout=300)
                finally:
                    cache.delete(lock_key)
            else:
                # Lock is held, we are in a thundering herd. Fall back to stale cache!
                stale_version = version - 1
                stale_key = f"kds_payload_{restaurant.id}_v{stale_version}"
                stale_payload = cache.get(stale_key)
                
                if stale_payload:
                    logger.info("metric kds_stale_served 1 restaurant_id=%s", restaurant.id)
                    _incr_metric("kds_metrics_stale_served")
                    master_payload = stale_payload
                else:
                    # Rare: Stale is gone. Enter short retry backoff up to 350ms total
                    for delay in [0.05, 0.1, 0.2]:
                        time.sleep(delay)
                        cached_payload = cache.get(cache_key)
                        if cached_payload:
                            break
                            
                    if cached_payload:
                        logger.info("metric kds_cache_hit 1 restaurant_id=%s", restaurant.id)
                        _incr_metric("kds_metrics_cache_hits")
                        master_payload = cached_payload
                    else:
                        # Desperation fallback
                        master_payload = self._build_restaurant_payload(restaurant, today_start, today_end)
                        cache.set(cache_key, master_payload, timeout=300)

        # Apply User Permissions Filter
        response_payload = master_payload.copy()
        response_payload["tab_counts"] = master_payload.get("tab_counts", {}).copy()
        
        if not (user.allow_cash_collection or user.is_owner):
            response_payload["payments"] = []
            response_payload["tab_counts"]["payments"] = 0
            
        if not (user.allow_view_all_orders or user.is_owner):
            response_payload["all_orders"] = []
            response_payload["tab_counts"]["all_orders"] = 0

        response_payload["permissions"] = {
            "can_complete": user.allow_order_completion or user.is_owner,
            "can_collect": user.allow_cash_collection or user.is_owner,
            "can_view_all": user.allow_view_all_orders or user.is_owner,
            "can_bulk_update": _can_run_bulk_order_action(user),
        }

        if getattr(settings, 'DEBUG', False) and request.GET.get("debug_permissions") == "1":
            response_payload["debug_permissions"] = {
                "username": user.username,
                "is_owner": user.is_owner,
                "allow_cash_collection": user.allow_cash_collection,
                "allow_order_completion": user.allow_order_completion,
                "allow_view_all_orders": user.allow_view_all_orders,
            }

        response = JsonResponse(response_payload)
        
        # Optionally inject STALE header for debugging
        if 'stale_payload' in locals() and stale_payload:
            response["X-Cache"] = "STALE"
            
        return response


class StartPrepView(OrderCompletionMixin, View):
    def post(self, request, order_id):
        restaurant = self.get_restaurant()

        if not _can_run_bulk_order_action(request.user):
            return JsonResponse({
                "error": "BULK_ACTION_PERMISSION_REQUIRED",
                "message": "Bulk order actions require full-order visibility and completion access.",
            }, status=403)

        try:
            with transaction.atomic():
                order = (
                    Order.objects
                    .select_for_update()
                    .get(id=order_id, restaurant=restaurant)
                )
                if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED, Order.Status.COMPLETED):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": f"Order is {order.status}.",
                    }, status=409)

                now = timezone.now()
                item_count = (
                    OrderItem.objects
                    .filter(order=order, prep_status=WorkStatus.PENDING)
                    .update(
                        prep_status=WorkStatus.PREPARING,
                        prep_started_at=now,
                        prep_started_by=request.user,
                    )
                )
                addon_count = (
                    OrderItemAddOn.objects
                    .filter(order_item__order=order, prep_status=WorkStatus.PENDING)
                    .update(
                        prep_status=WorkStatus.PREPARING,
                        prep_started_at=now,
                        prep_started_by=request.user,
                    )
                )
                if item_count == 0 and addon_count == 0:
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": "No pending work remains on this order.",
                    }, status=409)

                order = sync_order_status(order)
        except Order.DoesNotExist:
            raise Http404

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "order_id": str(order.id),
            "order_status": order.status,
        })


class StartItemPrepView(OrderCompletionMixin, View):
    def post(self, request, item_id):
        restaurant = self.get_restaurant()

        try:
            with transaction.atomic():
                item = (
                    OrderItem.objects
                    .select_for_update()
                    .select_related("order")
                    .get(id=item_id, order__restaurant=restaurant)
                )
                order = item.order
                if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED, Order.Status.COMPLETED):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": f"Order is {order.status}.",
                    }, status=409)

                if not _start_item_group(item, request.user):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": "This item is already in progress.",
                    }, status=409)

                order = sync_order_status(order)
        except OrderItem.DoesNotExist:
            raise Http404

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "item_id": str(item.id),
            "order_status": order.status,
        })


class StartAddOnPrepView(OrderCompletionMixin, View):
    def post(self, request, addon_id):
        restaurant = self.get_restaurant()

        try:
            with transaction.atomic():
                addon = (
                    OrderItemAddOn.objects
                    .select_for_update()
                    .select_related("order_item__order")
                    .get(id=addon_id, order_item__order__restaurant=restaurant)
                )
                item = (
                    OrderItem.objects
                    .select_for_update()
                    .get(id=addon.order_item_id)
                )
                order = item.order
                if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED, Order.Status.COMPLETED):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": f"Order is {order.status}.",
                    }, status=409)

                if not _start_item_group(item, request.user):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": "This item is already in progress.",
                    }, status=409)

                order = sync_order_status(order)
        except OrderItemAddOn.DoesNotExist:
            raise Http404

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "item_id": str(item.id),
            "order_status": order.status,
        })


class CompleteItemView(OrderCompletionMixin, View):
    def post(self, request, item_id):
        restaurant = self.get_restaurant()

        try:
            with transaction.atomic():
                item = (
                    OrderItem.objects
                    .select_for_update()
                    .select_related("order")
                    .get(id=item_id, order__restaurant=restaurant)
                )
                order = item.order
                if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED, Order.Status.COMPLETED):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": f"Order is {order.status}.",
                    }, status=409)

                if not _complete_item_group(item, request.user):
                    return JsonResponse({
                        "error": "ALREADY_COMPLETE",
                        "message": "This item is already done.",
                    }, status=409)

                order = sync_order_status(order)
        except OrderItem.DoesNotExist:
            raise Http404

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "item_id": str(item.id),
            "order_status": order.status,
        })


class CompleteAddOnView(OrderCompletionMixin, View):
    def post(self, request, addon_id):
        restaurant = self.get_restaurant()

        try:
            with transaction.atomic():
                addon = (
                    OrderItemAddOn.objects
                    .select_for_update()
                    .select_related("order_item__order")
                    .get(id=addon_id, order_item__order__restaurant=restaurant)
                )
                item = (
                    OrderItem.objects
                    .select_for_update()
                    .get(id=addon.order_item_id)
                )
                order = item.order
                if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED, Order.Status.COMPLETED):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": f"Order is {order.status}.",
                    }, status=409)

                if not _complete_item_group(item, request.user):
                    return JsonResponse({
                        "error": "ALREADY_COMPLETE",
                        "message": "This item is already done.",
                    }, status=409)

                order = sync_order_status(order)
        except OrderItemAddOn.DoesNotExist:
            raise Http404

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "item_id": str(item.id),
            "order_status": order.status,
        })


class CompleteAllView(OrderCompletionMixin, View):
    def post(self, request, order_id):
        restaurant = self.get_restaurant()

        if not _can_run_bulk_order_action(request.user):
            return JsonResponse({
                "error": "BULK_ACTION_PERMISSION_REQUIRED",
                "message": "Bulk order actions require full-order visibility and completion access.",
            }, status=403)

        try:
            with transaction.atomic():
                order = (
                    Order.objects
                    .select_for_update()
                    .get(id=order_id, restaurant=restaurant)
                )
                if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED, Order.Status.COMPLETED):
                    return JsonResponse({
                        "error": "INVALID_STATUS",
                        "message": f"Order is {order.status}.",
                    }, status=409)

                now = timezone.now()
                pending_items = OrderItem.objects.filter(order=order).exclude(prep_status=WorkStatus.COMPLETED)
                pending_addons = OrderItemAddOn.objects.filter(order_item__order=order).exclude(
                    prep_status=WorkStatus.COMPLETED
                )
                if not pending_items.exists() and not pending_addons.exists():
                    return JsonResponse({
                        "error": "ALREADY_COMPLETE",
                        "message": "All work already done.",
                    }, status=409)

                pending_items.update(
                    prep_status=WorkStatus.COMPLETED,
                    completed_at=now,
                    completed_by=request.user,
                    prep_started_at=now,
                    prep_started_by=request.user,
                )
                pending_addons.update(
                    prep_status=WorkStatus.COMPLETED,
                    completed_at=now,
                    completed_by=request.user,
                    prep_started_at=now,
                    prep_started_by=request.user,
                )
                order = sync_order_status(order)
        except Order.DoesNotExist:
            raise Http404

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "order_id": str(order.id),
            "order_status": order.status,
        })


class CashCollectView(CashCollectionMixin, View):
    def post(self, request, order_id):
        restaurant = self.get_restaurant()

        expire_overdue_unpaid_cash_orders(restaurant=restaurant)

        try:
            order = Order.objects.get(
                id=order_id,
                restaurant=restaurant,
                payment_method=Order.PaymentMethod.CASH,
            )
        except Order.DoesNotExist:
            raise Http404

        if order.status == Order.Status.CANCELLED:
            return JsonResponse({
                "error": "PAYMENT_TIMEOUT",
                "message": "This cash order has already expired.",
            }, status=409)

        try:
            order, fee_amount = confirm_cash_payment(order, request.user)
        except Exception as exc:
            logger.exception("Cash collection error for order %s", order_id)
            message = getattr(exc, "message", str(exc))
            return JsonResponse({
                "error": getattr(exc, "code", "CASH_COLLECTION_ERROR"),
                "message": message,
            }, status=409)

        trigger_kds_refresh(restaurant.id)

        return JsonResponse({
            "ok": True,
            "order_id": str(order.id),
            "order_status": order.status,
            "fee_amount": str(fee_amount),
        })
