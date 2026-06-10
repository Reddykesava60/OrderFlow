# owner/views.py
import csv
import io
import logging
import secrets
import string
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import logout as auth_logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum, Count, Q, Exists, OuterRef
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View

from core.mixins import OwnerRequiredMixin
from core.models import (
    AddOn, ItemType, MenuItem, MenuItemAddOn,
    OwnerAuditLog, PlatformFeeRecord, Restaurant, RestaurantPaymentConfig, StaffFilter, User,
)
from core.ratelimit import rate_limit
from core.storage import get_supabase_storage_config, upload_bytes_public, upload_public_image
from core.timeutils import local_day_bounds
from kitchen.models import PaymentEvent
from ordering.models import Order, OrderItem, OrderItemAddOn
from ordering.services import expire_overdue_unpaid_cash_orders

logger = logging.getLogger(__name__)


def _csv_safe(value):
    """Escape CSV cell values that could be interpreted as formulas by spreadsheet apps."""
    s = str(value) if value is not None else ''
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r', '\n'):
        return "'" + s
    return s


# ── Helpers ───────────────────────────────────────────────────────────────────

def _today_stats(restaurant):
    """
    Return gross revenue, total platform fees, net revenue, and
    order counts for today, derived entirely from the immutable ledger.
    """
    from ordering.models import RestaurantLedger
    today = timezone.localdate()
    today_start, today_end = local_day_bounds(today)

    ledger_entries = RestaurantLedger.objects.filter(
        restaurant=restaurant,
        created_at__gte=today_start,
        created_at__lt=today_end,
    )

    # Gross revenue = sum of all CREDIT_ORDER
    gross = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.CREDIT_ORDER
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    # Total fees = sum of all DEBIT_PLATFORM_FEE (stored as negative)
    total_fees_negative = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_fees = abs(total_fees_negative)

    net = gross - total_fees

    # Breakdowns by order payment method
    cash_total = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.CREDIT_ORDER,
        order__payment_method=Order.PaymentMethod.CASH
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    upi_total = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.CREDIT_ORDER,
        order__payment_method=Order.PaymentMethod.UPI
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    post_total = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.CREDIT_ORDER,
        order__payment_method=Order.PaymentMethod.POST_PAYMENT
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    order_counts = Order.objects.filter(
        restaurant=restaurant,
        status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED, Order.Status.COMPLETED],
        created_at__gte=today_start,
        created_at__lt=today_end,
    ).aggregate(
        total=Count('id'),
        cash=Count('id', filter=Q(payment_method=Order.PaymentMethod.CASH)),
        upi=Count('id',  filter=Q(payment_method=Order.PaymentMethod.UPI)),
        post=Count('id', filter=Q(payment_method=Order.PaymentMethod.POST_PAYMENT)),
    )

    return {
        'gross':        gross,
        'fees':         total_fees,
        'net':          net,
        'cash_total':   cash_total,
        'upi_total':    upi_total,
        'post_total':   post_total,
        'order_total':  order_counts['total'],
        'order_cash':   order_counts['cash'],
        'order_upi':    order_counts['upi'],
        'order_post':   order_counts['post'],
    }


def _month_stats(restaurant):
    """
    Return month-to-date stats derived entirely from the immutable ledger.
    """
    from ordering.models import RestaurantLedger
    today = timezone.localdate()
    month_start = today.replace(day=1)

    ledger_entries = RestaurantLedger.objects.filter(
        restaurant=restaurant,
        created_at__gte=month_start
    )

    # Gross revenue = sum of all CREDIT_ORDER
    gross = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.CREDIT_ORDER
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    # Total fees = sum of all DEBIT_PLATFORM_FEE (stored as negative)
    total_fees_negative = ledger_entries.filter(
        entry_type=RestaurantLedger.EntryType.DEBIT_PLATFORM_FEE
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    total_fees = abs(total_fees_negative)

    net = gross - total_fees

    return {
        'gross': gross,
        'fees': total_fees,
        'net': net,
    }


def _gen_temp_password(length=12):
    """Cryptographically random temp password — shown once, never stored in plain text."""
    alphabet = string.ascii_letters + string.digits + '!@#$%'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _write_owner_audit(*, restaurant, user, action, customer=None, details=None):
    OwnerAuditLog.objects.create(
        restaurant=restaurant,
        user=user,
        customer=customer,
        action=action,
        details=details or {},
    )


# ── Dashboard ─────────────────────────────────────────────────────────────────

def _dashboard_inventory_cards(restaurant):
    today = timezone.localdate()
    today_start, today_end = local_day_bounds(today)
    active_statuses = [
        Order.Status.PENDING,
        Order.Status.PREP_STARTED,
        Order.Status.COMPLETED,
    ]

    item_sales = {
        row['menu_item_id']: row['sold_today']
        for row in (
            OrderItem.objects
            .filter(
                order__restaurant=restaurant,
                order__created_at__gte=today_start,
                order__created_at__lt=today_end,
                order__status__in=active_statuses,
                menu_item_id__isnull=False,
            )
            .values('menu_item_id')
            .annotate(sold_today=Sum('quantity'))
        )
    }

    addon_sales = {
        row['addon_id']: row['sold_today']
        for row in (
            OrderItemAddOn.objects
            .filter(
                order_item__order__restaurant=restaurant,
                order_item__order__created_at__gte=today_start,
                order_item__order__created_at__lt=today_end,
                order_item__order__status__in=active_statuses,
                addon_id__isnull=False,
            )
            .values('addon_id')
            .annotate(sold_today=Sum('quantity'))
        )
    }

    item_ids_with_addons = set(
        MenuItemAddOn.objects
        .filter(menu_item__restaurant=restaurant, addon__is_active=True)
        .values_list('menu_item_id', flat=True)
    )

    items = list(
        MenuItem.objects
        .filter(restaurant=restaurant)
        .select_related('item_type')
        .order_by('name')
    )
    for item in items:
        item.sold_today = item_sales.get(item.id, 0) or 0
        item.stock_label = 'Unlimited' if item.stock is None else str(item.stock)
        item.stock_state = 'out' if item.stock == 0 else 'limited' if item.stock is not None else 'unlimited'
        item.has_addons = item.id in item_ids_with_addons
    items.sort(key=lambda menu_item: (-menu_item.sold_today, menu_item.name.lower()))

    addons = list(
        AddOn.objects
        .filter(restaurant=restaurant)
        .select_related()
        .order_by('name')
    )
    for addon in addons:
        addon.sold_today = addon_sales.get(addon.id, 0) or 0
        addon.stock_label = 'Unlimited' if addon.stock is None else str(addon.stock)
        addon.stock_state = 'out' if addon.stock == 0 else 'limited' if addon.stock is not None else 'unlimited'
    addons.sort(key=lambda addon_item: (-addon_item.sold_today, addon_item.name.lower()))

    return items, addons


def _parse_optional_stock(raw_value):
    raw_value = (raw_value or '').strip()
    if raw_value == '':
        return None
    return int(raw_value)


def _apply_owner_item_stock_settings(item, data):
    stock_value = _parse_optional_stock(data.get('stock'))
    item.stock = stock_value

    requested_available = 'is_available' in data
    if stock_value == 0:
        item.is_available = False
        item.auto_hidden_due_to_stock = True
    else:
        item.is_available = requested_available
        item.auto_hidden_due_to_stock = False


def _store_menu_item_image(restaurant, item, uploaded_file):
    image_url = upload_public_image(
        bucket='menu-images',
        path=f"{restaurant.id}/{item.id}.webp",
        uploaded_file=uploaded_file,
    )
    item.image = image_url
    item.save(update_fields=['image'])
    return image_url


def _store_addon_image(restaurant, addon, uploaded_file):
    image_url = upload_public_image(
        bucket='menu-images',
        path=f"{restaurant.id}/addons/{addon.id}.webp",
        uploaded_file=uploaded_file,
    )
    addon.image = image_url
    addon.save(update_fields=['image'])
    return image_url


class SecureLogoutView(View):
    http_method_names = ['post']

    def post(self, request):
        auth_logout(request)
        return redirect('owner:login')


@method_decorator(rate_limit('owner_login', limit=10, window=300), name='dispatch')
class OwnerLoginView(LoginView):
    template_name = 'owner/login.html'


class ChangePasswordView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('owner:login')
        return render(request, 'owner/change_password.html', {
            'must_change': getattr(request.user, 'must_change_password', False),
        })

    def post(self, request):
        if not request.user.is_authenticated:
            return redirect('owner:login')

        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('owner:change_password')

        try:
            validate_password(new_password, user=request.user)
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
            return redirect('owner:change_password')

        request.user.set_password(new_password)
        request.user.must_change_password = False
        request.user.save(update_fields=['password', 'must_change_password'])
        update_session_auth_hash(request, request.user)
        messages.success(request, 'Password updated.')

        if request.user.is_owner:
            return redirect('owner:dashboard')
        return redirect('kitchen:kds')


class DashboardView(OwnerRequiredMixin, View):
    def get(self, request):
        restaurant = self.get_restaurant()
        expire_overdue_unpaid_cash_orders(restaurant=restaurant)
        today = timezone.localdate()
        stats = _today_stats(restaurant)
        month_stats = _month_stats(restaurant)
        item_cards, addon_cards = _dashboard_inventory_cards(restaurant)
        today_start, today_end = local_day_bounds(today)
        today_orders = (
            Order.objects
            .filter(restaurant=restaurant, created_at__gte=today_start, created_at__lt=today_end)
            .order_by('-created_at')
        )
        from ordering.models import RestaurantLedger, Settlement
        last_entry = RestaurantLedger.objects.filter(restaurant=restaurant).order_by('-created_at').first()
        available_balance = last_entry.balance_after if last_entry else Decimal('0.00')
        pending_settlements = Settlement.objects.filter(
            restaurant=restaurant, 
            status__in=[Settlement.Status.PENDING, Settlement.Status.PROCESSING]
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

        return render(request, 'owner/dashboard.html', {
            'restaurant': restaurant,
            'stats': stats,
            'month_stats': month_stats,
            'available_balance': available_balance,
            'pending_settlements': pending_settlements,
            'item_cards': item_cards,
            'addon_cards': addon_cards,
            'today_orders': today_orders,
        })


class OwnerOrderReceiptView(OwnerRequiredMixin, View):
    def get(self, request, order_id):
        restaurant = self.get_restaurant()
        expire_overdue_unpaid_cash_orders(restaurant=restaurant)
        order = get_object_or_404(
            Order.objects.select_related('restaurant').prefetch_related('items__addons'),
            id=order_id,
            restaurant=restaurant,
        )
        return render(request, 'owner/order_receipt.html', {
            'restaurant': restaurant,
            'order': order,
        })


# ── Menu ──────────────────────────────────────────────────────────────────────

class MenuView(OwnerRequiredMixin, View):
    """List all menu items with availability toggle."""
    def get(self, request):
        restaurant = self.get_restaurant()
        has_active_addon = Exists(
            MenuItemAddOn.objects.filter(
                menu_item=OuterRef('pk'), addon__is_active=True
            )
        )
        items = (
            MenuItem.objects
            .filter(restaurant=restaurant)
            .select_related('item_type')
            .annotate(has_addons=has_active_addon)
            .order_by('item_type__sort_order', 'sort_order', 'name')
        )
        item_types = ItemType.objects.filter(restaurant=restaurant).order_by('sort_order')
        addons = AddOn.objects.filter(restaurant=restaurant).select_related().order_by('name')
        
        return render(request, 'owner/menu.html', {
            'restaurant': restaurant,
            'items': items,
            'item_types': item_types,
            'addons': addons,
        })

class MenuItemCreateView(OwnerRequiredMixin, View):
    def get(self, request):
        restaurant = self.get_restaurant()
        return render(request, 'owner/menu_item_form.html', {
            'restaurant': restaurant,
            'item_types': ItemType.objects.filter(restaurant=restaurant),
            'all_addons': AddOn.objects.filter(restaurant=restaurant, is_active=True),
            'item':       None,
        })

    def post(self, request):
        restaurant = self.get_restaurant()
        data       = request.POST

        item = MenuItem(
            restaurant       = restaurant,
            item_type        = ItemType.objects.filter(
                                   id=data.get('item_type'), restaurant=restaurant
                               ).first() if data.get('item_type') else None,
            name             = data.get('name', '').strip(),
            description      = data.get('description', '').strip(),
            base_price       = data.get('base_price', '0'),
            parcel_surcharge = data.get('parcel_surcharge', '0') or '0',
            is_veg           = 'is_veg' in data,
            spice_configurable = 'spice_configurable' in data,
            sort_order       = int(data.get('sort_order') or 0),
        )
        _apply_owner_item_stock_settings(item, data)

        try:
            item.full_clean()
            item.save()
            if request.FILES.get('image'):
                try:
                    _store_menu_item_image(restaurant, item, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception("Menu image upload failed for item %s", item.id)
                    messages.warning(request, f"Item created but image upload failed: {upload_err}")
            # Attach selected add-ons
            for addon_id in data.getlist('addons'):
                addon = AddOn.objects.filter(id=addon_id, restaurant=restaurant).first()
                if addon:
                    MenuItemAddOn.objects.get_or_create(menu_item=item, addon=addon)
            messages.success(request, f"'{item.name}' created.")
            return redirect('owner:menu')
        except Exception as e:
            messages.error(request, str(e))
            return render(request, 'owner/menu_item_form.html', {
                'restaurant': restaurant,
                'item_types': ItemType.objects.filter(restaurant=restaurant),
                'all_addons': AddOn.objects.filter(restaurant=restaurant, is_active=True),
                'item':       None,
                'data':       data,
            })


class MenuItemEditView(OwnerRequiredMixin, View):
    def get(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        linked_addon_ids = set(
            MenuItemAddOn.objects.filter(menu_item=item).values_list('addon_id', flat=True)
        )
        return render(request, 'owner/menu_item_form.html', {
            'restaurant':     restaurant,
            'item_types':     ItemType.objects.filter(restaurant=restaurant),
            'all_addons':     AddOn.objects.filter(restaurant=restaurant, is_active=True),
            'item':           item,
            'linked_addon_ids': linked_addon_ids,
        })

    def post(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        data = request.POST

        item.name             = data.get('name', '').strip()
        item.description      = data.get('description', '').strip()
        item.base_price       = data.get('base_price', '0')
        item.parcel_surcharge = data.get('parcel_surcharge', '0') or '0'
        item.is_veg           = 'is_veg' in data
        item.spice_configurable = 'spice_configurable' in data
        item.sort_order       = int(data.get('sort_order') or 0)
        item.item_type        = ItemType.objects.filter(
                                    id=data.get('item_type'), restaurant=restaurant
                                ).first() if data.get('item_type') else None
        _apply_owner_item_stock_settings(item, data)

        try:
            item.full_clean()
            item.save()
            if request.FILES.get('image'):
                try:
                    _store_menu_item_image(restaurant, item, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception("Menu image upload failed for item %s", item.id)
                    messages.warning(request, f"Image upload failed: {upload_err}")
            # Sync add-on links
            selected = set(data.getlist('addons'))
            existing = set(
                str(aid) for aid in
                MenuItemAddOn.objects.filter(menu_item=item).values_list('addon_id', flat=True)
            )
            # Add new links
            for addon_id in selected - existing:
                addon = AddOn.objects.filter(id=addon_id, restaurant=restaurant).first()
                if addon:
                    MenuItemAddOn.objects.get_or_create(menu_item=item, addon=addon)
            # Remove deselected links
            MenuItemAddOn.objects.filter(
                menu_item=item, addon_id__in=(existing - selected)
            ).delete()

            messages.success(request, f"'{item.name}' updated.")
            return redirect('owner:menu')
        except Exception as e:
            messages.error(request, str(e))
            return redirect('owner:menu_edit', item_id=item_id)


class MenuItemDeleteView(OwnerRequiredMixin, View):
    def post(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)

        # Block delete if referenced in active orders
        active = OrderItem.objects.filter(
            menu_item=item,
            order__status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED],
        ).exists()
        if active:
            messages.error(request, f"Cannot delete '{item.name}' — it has active orders.")
            return redirect('owner:menu')

        name = item.name
        item.delete()
        messages.success(request, f"'{name}' deleted.")
        return redirect('owner:menu')


class ToggleAvailabilityView(OwnerRequiredMixin, View):
    """POST /owner/menu/toggle/{item_id}/ — Alpine.js inline toggle."""
    def post(self, request, item_id):
        restaurant = self.get_restaurant()
        item = get_object_or_404(MenuItem, id=item_id, restaurant=restaurant)
        if not item.is_available and item.stock == 0:
            payload = {
                'is_available': False,
                'has_addons': MenuItemAddOn.objects.filter(
                    menu_item=item, addon__is_active=True
                ).exists(),
                'message': 'Cannot enable an item while stock is 0.',
            }
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse(payload, status=409)
            messages.error(request, payload['message'])
            return redirect('owner:menu')

        item.is_available = not item.is_available
        item.auto_hidden_due_to_stock = False
        item.save(update_fields=['is_available', 'auto_hidden_due_to_stock'])

        has_addons = MenuItemAddOn.objects.filter(
            menu_item=item, addon__is_active=True
        ).exists()

        payload = {
            'is_available': item.is_available,
            'has_addons':   has_addons,
        }
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse(payload)

        messages.success(
            request,
            f"'{item.name}' is now {'available' if item.is_available else 'hidden from customers'}.",
        )
        return redirect('owner:menu')


# ── Add-ons ───────────────────────────────────────────────────────────────────

class AddOnCreateView(OwnerRequiredMixin, View):
    def post(self, request):
        restaurant = self.get_restaurant()
        data       = request.POST
        try:
            addon = AddOn(
                restaurant = restaurant,
                name       = data.get('name', '').strip(),
                price      = data.get('price', '0'),
                max_qty    = int(data.get('max_qty') or 5),
                stock      = _parse_optional_stock(data.get('stock')),
                is_active  = True,
            )
            addon.full_clean()
            addon.save()
            if request.FILES.get('image'):
                try:
                    _store_addon_image(restaurant, addon, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception("Add-on image upload failed for add-on %s", addon.id)
                    messages.warning(request, f"Add-on created but image upload failed: {upload_err}")
            messages.success(request, "Add-on created.")
        except Exception as e:
            messages.error(request, str(e))
        return redirect('owner:menu')


class AddOnEditView(OwnerRequiredMixin, View):
    def get(self, request, addon_id):
        restaurant = self.get_restaurant()
        addon = get_object_or_404(AddOn, id=addon_id, restaurant=restaurant)
        return render(request, 'owner/addon_form.html', {
            'restaurant': restaurant,
            'addon': addon,
        })

    def post(self, request, addon_id):
        restaurant = self.get_restaurant()
        addon = get_object_or_404(AddOn, id=addon_id, restaurant=restaurant)
        data = request.POST

        addon.name = data.get('name', '').strip()
        addon.price = data.get('price', '0')
        addon.max_qty = int(data.get('max_qty') or 5)
        addon.stock = _parse_optional_stock(data.get('stock'))

        try:
            addon.full_clean()
            addon.save()
            if request.FILES.get('image'):
                try:
                    _store_addon_image(restaurant, addon, request.FILES['image'])
                except Exception as upload_err:
                    logger.exception("Add-on image upload failed for add-on %s", addon.id)
                    messages.warning(request, f"Image upload failed: {upload_err}")
            messages.success(request, f"'{addon.name}' updated.")
            return redirect('owner:menu')
        except Exception as e:
            messages.error(request, str(e))
            return render(request, 'owner/addon_form.html', {
                'restaurant': restaurant,
                'addon': addon,
            })


class AddOnToggleView(OwnerRequiredMixin, View):
    def post(self, request, addon_id):
        restaurant = self.get_restaurant()
        addon = get_object_or_404(AddOn, id=addon_id, restaurant=restaurant)
        addon.is_active = not addon.is_active
        addon.save(update_fields=['is_active'])
        messages.success(request, f"'{addon.name}' {'activated' if addon.is_active else 'deactivated'}.")
        return redirect('owner:menu')


# ── Item types ────────────────────────────────────────────────────────────────

class ItemTypeCreateView(OwnerRequiredMixin, View):
    def post(self, request):
        restaurant = self.get_restaurant()
        name = request.POST.get('name', '').strip()
        if name:
            ItemType.objects.get_or_create(
                restaurant=restaurant,
                name=name,
                defaults={'sort_order': 0},
            )
            messages.success(request, f"Category '{name}' created.")
        return redirect('owner:menu')


class StaffFilterView(OwnerRequiredMixin, View):
    def get(self, request):
        restaurant = self.get_restaurant()
        filters = (
            StaffFilter.objects
            .filter(restaurant=restaurant)
            .prefetch_related('items')
            .order_by('name')
        )
        menu_items = MenuItem.objects.filter(restaurant=restaurant).order_by('name')
        return render(request, 'owner/staff_filters.html', {
            'restaurant': restaurant,
            'filters': filters,
            'menu_items': menu_items,
        })

    def post(self, request):
        restaurant = self.get_restaurant()
        name = request.POST.get('name', '').strip()
        raw_item_ids = request.POST.getlist('item_ids') or request.POST.getlist('items')
        selected_item_ids = list(
            MenuItem.objects
            .filter(restaurant=restaurant, id__in=raw_item_ids)
            .values_list('id', flat=True)
        )
        if not name:
            messages.error(request, "Filter name is required.")
            return redirect('owner:staff_filters')

        staff_filter = StaffFilter(restaurant=restaurant, name=name)
        try:
            staff_filter.full_clean()
            staff_filter.save()
            staff_filter.items.set(selected_item_ids)
            messages.success(request, f"Filter '{staff_filter.name}' created.")
        except Exception as e:
            messages.error(request, str(e))

        return redirect('owner:staff_filters')


class StaffFilterEditView(OwnerRequiredMixin, View):
    def post(self, request, filter_id):
        restaurant = self.get_restaurant()
        staff_filter = get_object_or_404(StaffFilter, id=filter_id, restaurant=restaurant)
        name = request.POST.get('name', '').strip()
        raw_item_ids = request.POST.getlist('item_ids') or request.POST.getlist('items')
        selected_item_ids = list(
            MenuItem.objects
            .filter(restaurant=restaurant, id__in=raw_item_ids)
            .values_list('id', flat=True)
        )
        if not name:
            messages.error(request, "Filter name is required.")
            return redirect('owner:staff_filters')

        staff_filter.name = name
        try:
            staff_filter.full_clean()
            staff_filter.save()
            staff_filter.items.set(selected_item_ids)
            messages.success(request, f"Filter '{staff_filter.name}' updated.")
        except Exception as e:
            messages.error(request, str(e))

        return redirect('owner:staff_filters')


class StaffFilterDeleteView(OwnerRequiredMixin, View):
    def post(self, request, filter_id):
        restaurant = self.get_restaurant()
        staff_filter = get_object_or_404(StaffFilter, id=filter_id, restaurant=restaurant)
        filter_name = staff_filter.name
        staff_filter.delete()
        messages.success(request, f"Filter '{filter_name}' deleted.")
        return redirect('owner:staff_filters')


# ── Staff management ──────────────────────────────────────────────────────────

class StaffView(OwnerRequiredMixin, View):
    def get(self, request):
        restaurant = self.get_restaurant()
        staff = (
            User.objects
            .filter(restaurant=restaurant, role=User.Role.STAFF)
            .order_by('role', 'username')
        )
        return render(request, 'owner/staff.html', {
            'restaurant': restaurant,
            'staff':      staff,
            'staff_count': staff.count(),
        })


class StaffCreateView(OwnerRequiredMixin, View):
    def post(self, request):
        restaurant = self.get_restaurant()
        data       = request.POST
        username   = data.get('username', '').strip().lower()

        if not username:
            messages.error(request, "Username is required.")
            return redirect('owner:staff')

        if User.objects.filter(username__iexact=username, restaurant=restaurant).exists():
            messages.error(request, f"Username '{username}' already exists in this restaurant.")
            return redirect('owner:staff')

        temp_password = data.get('password', '').strip() or _gen_temp_password()

        with transaction.atomic():
            user = User.objects.create_user(
                username               = username,
                password               = temp_password,
                restaurant             = restaurant,
                role                   = User.Role.STAFF,
                allow_cash_collection  = 'allow_cash_collection' in data,
                allow_view_all_orders  = 'allow_view_all_orders' in data,
                allow_order_completion = 'allow_order_completion' in data,
                must_change_password   = True,
                is_active              = True,
            )
            _write_owner_audit(
                restaurant=restaurant,
                user=request.user,
                action=OwnerAuditLog.ActionType.CREATE_STAFF,
                details={
                    'username': username,
                    'permissions': {
                        'allow_cash_collection': user.allow_cash_collection,
                        'allow_view_all_orders': user.allow_view_all_orders,
                        'allow_order_completion': user.allow_order_completion,
                    },
                },
            )

        # Store temp password in session for one-time display
        request.session[f'temp_pw_{user.id}'] = temp_password
        messages.success(request, f"Staff account '{username}' created.")
        return redirect('owner:staff_created', user_id=user.id)


class StaffDeleteView(OwnerRequiredMixin, View):
    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        username = user.username
        _write_owner_audit(
            restaurant=restaurant,
            user=request.user,
            action=OwnerAuditLog.ActionType.DELETE_STAFF,
            details={
                'username': username,
                'permissions': {
                    'allow_cash_collection': user.allow_cash_collection,
                    'allow_view_all_orders': user.allow_view_all_orders,
                    'allow_order_completion': user.allow_order_completion,
                },
            },
        )
        user.delete()
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user_id)
        messages.success(request, f"'{username}' removed.")
        return redirect('owner:staff')


class StaffCreatedView(OwnerRequiredMixin, View):
    """Show temp password exactly once then clear it from session."""
    def get(self, request, user_id):
        restaurant = self.get_restaurant()
        user       = get_object_or_404(User, id=user_id, restaurant=restaurant)
        temp_pw    = request.session.pop(f'temp_pw_{user.id}', None)

        if not temp_pw:
            # Already viewed — don't show again
            return redirect('owner:staff')

        return render(request, 'owner/staff_created.html', {
            'restaurant': restaurant,
            'new_user':   user,
            'temp_pw':    temp_pw,
        })


class StaffEditView(OwnerRequiredMixin, View):
    def get(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        return render(request, 'owner/staff_edit.html', {
            'restaurant': restaurant,
            'staff_user': user,
        })

    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        data = request.POST
        before = {
            'allow_cash_collection': user.allow_cash_collection,
            'allow_view_all_orders': user.allow_view_all_orders,
            'allow_order_completion': user.allow_order_completion,
            'is_active': user.is_active,
        }

        user.allow_cash_collection  = 'allow_cash_collection' in data
        user.allow_view_all_orders  = 'allow_view_all_orders' in data
        user.allow_order_completion = 'allow_order_completion' in data
        user.is_active = 'is_active' in data
        user.save(update_fields=[
            'allow_cash_collection',
            'allow_view_all_orders',
            'allow_order_completion',
            'is_active',
        ])
        _write_owner_audit(
            restaurant=restaurant,
            user=request.user,
            action=OwnerAuditLog.ActionType.EDIT_STAFF,
            details={
                'username': user.username,
                'before': before,
                'after': {
                    'allow_cash_collection': user.allow_cash_collection,
                    'allow_view_all_orders': user.allow_view_all_orders,
                    'allow_order_completion': user.allow_order_completion,
                    'is_active': user.is_active,
                },
            },
        )

        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user.id)

        messages.success(request, f"'{user.username}' updated.")
        return redirect('owner:staff')


class StaffResetPasswordView(OwnerRequiredMixin, View):
    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)

        temp_password = _gen_temp_password()
        user.set_password(temp_password)
        user.must_change_password = True
        user.save()
        _write_owner_audit(
            restaurant=restaurant,
            user=request.user,
            action=OwnerAuditLog.ActionType.RESET_STAFF_PASSWORD,
            details={'username': user.username},
        )

        request.session[f'temp_pw_{user.id}'] = temp_password
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user.id)
        messages.success(request, f"Password reset for '{user.username}'.")
        return redirect('owner:staff_created', user_id=user.id)


class StaffPermissionToggleView(OwnerRequiredMixin, View):
    """POST /owner/staff/<user_id>/toggle-permission/ — AJAX toggle for permissions."""
    def post(self, request, user_id):
        restaurant = self.get_restaurant()
        user = get_object_or_404(User, id=user_id, restaurant=restaurant, role=User.Role.STAFF)
        permission = request.POST.get('permission')
        
        valid_permissions = [
            'allow_cash_collection',
            'allow_order_completion',
            'allow_view_all_orders',
            'is_active',
        ]
        
        if permission not in valid_permissions:
            return JsonResponse({'error': 'Invalid permission'}, status=400)
            
        # Toggle the boolean value
        current_val = getattr(user, permission)
        setattr(user, permission, not current_val)
        user.save(update_fields=[permission])
        _write_owner_audit(
            restaurant=restaurant,
            user=request.user,
            action=OwnerAuditLog.ActionType.TOGGLE_STAFF_PERMISSION,
            details={
                'username': user.username,
                'permission': permission,
                'before': current_val,
                'after': getattr(user, permission),
            },
        )
        
        from kitchen.services import broadcast_user_disconnect
        broadcast_user_disconnect(user.id)
        
        return JsonResponse({
            'status': 'success',
            'permission': permission,
            'value': getattr(user, permission)
        })


# ── Config ────────────────────────────────────────────────────────────────────

class ConfigView(OwnerRequiredMixin, View):
    def get(self, request):
        restaurant = self.get_restaurant()
        payment_config, _ = RestaurantPaymentConfig.objects.get_or_create(restaurant=restaurant)
        return render(request, 'owner/config.html', {
            'restaurant': restaurant,
            'config':     restaurant.config,
            'payment_config': payment_config,
            'menu_public_url': request.build_absolute_uri(
                reverse('ordering:menu', args=[restaurant.slug])
            ),
        })

    def post(self, request):
        restaurant = self.get_restaurant()
        config     = restaurant.config
        payment_config, _ = RestaurantPaymentConfig.objects.get_or_create(restaurant=restaurant)
        data       = request.POST
        before_config = {
            'is_open': config.is_open,
            'reopen_message': config.reopen_message,
            'cash_enabled': config.cash_enabled,
            'upi_enabled': config.upi_enabled,
            'slug': restaurant.slug,
        }
        before_payment = {
            'account_name': payment_config.account_name,
            'razorpay_key_id_present': bool(payment_config.razorpay_key_id),
            'razorpay_key_secret_present': bool(payment_config.get_razorpay_key_secret()),
            'razorpay_webhook_secret_present': bool(payment_config.get_razorpay_webhook_secret()),
            'is_active': payment_config.is_active,
        }

        # is_open toggle
        config.is_open        = 'is_open' in data
        config.reopen_message = data.get('reopen_message', '').strip()

        # Payment methods — at least one must remain enabled
        cash = 'cash_enabled' in data
        upi  = 'upi_enabled' in data
        if not cash and not upi:
            messages.error(request, "At least one payment method must be enabled.")
            return redirect('owner:config')

        payment_config.account_name = data.get('account_name', '').strip()
        payment_config.razorpay_key_id = data.get('razorpay_key_id', '').strip()

        key_secret = data.get('razorpay_key_secret', '').strip()
        webhook_secret = data.get('razorpay_webhook_secret', '').strip()
        if key_secret:
            payment_config.set_razorpay_key_secret(key_secret)
        if webhook_secret:
            payment_config.set_razorpay_webhook_secret(webhook_secret)
        payment_config.is_active = 'razorpay_is_active' in data

        if upi and not payment_config.is_usable:
            messages.error(
                request,
                "To enable UPI, complete and activate this restaurant's Razorpay settings first.",
            )
            return redirect('owner:config')

        config.cash_enabled = cash
        config.upi_enabled  = upi
        config.save()
        payment_config.save()

        # Slug change
        new_slug = data.get('slug', '').strip().lower()
        if new_slug and new_slug != restaurant.slug:
            from django.utils.text import slugify
            clean_slug = slugify(new_slug)
            if not clean_slug:
                messages.error(request, "Invalid slug.")
                return redirect('owner:config')
            if Restaurant.objects.filter(slug=clean_slug).exclude(id=restaurant.id).exists():
                messages.error(request, f"Slug '{clean_slug}' is already taken.")
                return redirect('owner:config')
            restaurant.slug = clean_slug
            restaurant.menu_qr_code_url = ''
            restaurant.save(update_fields=['slug', 'menu_qr_code_url'])
            messages.info(request, f"Slug changed to '{clean_slug}'. Update your QR code.")

        messages.success(request, "Settings saved.")
        _write_owner_audit(
            restaurant=restaurant,
            user=request.user,
            action=OwnerAuditLog.ActionType.UPDATE_RESTAURANT_CONFIG,
            details={
                'restaurant_config_before': before_config,
                'restaurant_config_after': {
                    'is_open': config.is_open,
                    'reopen_message': config.reopen_message,
                    'cash_enabled': config.cash_enabled,
                    'upi_enabled': config.upi_enabled,
                    'slug': restaurant.slug,
                },
                'payment_config_before': before_payment,
                'payment_config_after': {
                    'account_name': payment_config.account_name,
                    'razorpay_key_id_present': bool(payment_config.razorpay_key_id),
                    'razorpay_key_secret_present': bool(payment_config.get_razorpay_key_secret()),
                    'razorpay_webhook_secret_present': bool(payment_config.get_razorpay_webhook_secret()),
                    'is_active': payment_config.is_active,
                },
            },
        )
        return redirect('owner:config')


class MenuQrCodeDownloadView(OwnerRequiredMixin, View):
    """
    GET /owner/config/qr-code/menu.png
    Generates a QR code pointing to the public menu URL and returns it as a download.
    Also uploads the PNG to Supabase Storage if configured (bucket: qr-codes).
    """

    def get(self, request):
        restaurant = self.get_restaurant()
        menu_path = reverse('ordering:menu', args=[restaurant.slug])
        menu_url = request.build_absolute_uri(menu_path)

        import qrcode

        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(menu_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buf = io.BytesIO()
        img.save(buf)
        png_bytes = buf.getvalue()

        if get_supabase_storage_config():
            try:
                public_url = upload_bytes_public(
                    bucket='qr-codes',
                    path=f"{restaurant.id}.png",
                    content=png_bytes,
                    content_type='image/png',
                )
                restaurant.menu_qr_code_url = public_url
                restaurant.save(update_fields=['menu_qr_code_url'])
            except Exception:
                logger.exception("Failed uploading menu QR code to Supabase Storage for %s", restaurant.id)

        response = HttpResponse(png_bytes, content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="{restaurant.slug}_menu_qr.png"'
        return response


# ── Reconciliation ────────────────────────────────────────────────────────────

class ReconcileView(OwnerRequiredMixin, View):
    def get(self, request):
        restaurant = self.get_restaurant()
        today      = timezone.localdate()
        date_str   = request.GET.get('date', str(today))

        try:
            from datetime import date
            filter_date = date.fromisoformat(date_str)
        except ValueError:
            filter_date = today
        filter_start, filter_end = local_day_bounds(filter_date)

        events = (
            PaymentEvent.objects
            .filter(restaurant=restaurant, created_at__gte=filter_start, created_at__lt=filter_end)
            .select_related('staff_user', 'order')
            .order_by('-created_at')
        )

        fee_records = (
            PlatformFeeRecord.objects
            .filter(restaurant=restaurant, created_at__gte=filter_start, created_at__lt=filter_end)
            .order_by('-created_at')
        )

        # Digital revenue tracking
        digital_events = events.filter(
            event_type__in=[
                PaymentEvent.EventType.RAZORPAY_CONFIRMED,
                PaymentEvent.EventType.DIGITAL_PAYMENT_CONFIRMED,
            ]
        )
        digital_total = digital_events.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        digital_count = digital_events.count()

        # Cash revenue tracking
        cash_events = events.filter(
            event_type=PaymentEvent.EventType.CASH_COLLECTED,
        )
        cash_total = cash_events.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
        cash_count = cash_events.count()

        # Post-payment tracking (from Orders, since they aren't paid immediately)
        post_orders = Order.objects.filter(
            restaurant=restaurant,
            created_at__gte=filter_start,
            created_at__lt=filter_end,
            payment_method=Order.PaymentMethod.POST_PAYMENT,
            status__in=[Order.Status.PENDING, Order.Status.PREP_STARTED, Order.Status.COMPLETED],
        )
        post_total = post_orders.aggregate(t=Sum('total'))['t'] or Decimal('0.00')
        post_count = post_orders.count()

        gross = cash_total + digital_total + post_total

        total_fees = fee_records.filter(
            is_refunded=False
        ).aggregate(t=Sum('fee_amount'))['t'] or Decimal('0.00')

        net = gross - total_fees

        # Build fee lookup by order_id for template
        fee_map = {
            str(fr.order_id): fr for fr in fee_records if fr.order_id
        }

        cash_by_staff = list(
            cash_events
            .values('staff_user__username')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )
        post_count = post_orders.count()

        if request.GET.get('export') == 'csv':
            return self._export_csv(restaurant, events, fee_records, filter_date)

        return render(request, 'owner/reconcile.html', {
            'restaurant':  restaurant,
            'events':      events,
            'fee_records': fee_records,
            'fee_map':     fee_map,
            'filter_date': filter_date,
            'gross':       gross,
            'total_fees':  total_fees,
            'net':         net,
            'cash_total':  cash_total,
            'cash_count':  cash_count,
            'cash_by_staff': cash_by_staff,
            'digital_total': digital_total,
            'digital_count': digital_count,
            'post_total':    post_total,
            'post_count':    post_count,
            'month_stats':   _month_stats(restaurant),
        })

    def _export_csv(self, restaurant, events, fee_records, filter_date):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="dineflow_{restaurant.slug}_{filter_date}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow([
            'Time', 'Order ref', 'Event type', 'Amount',
            'Fee amount', 'Fee rate %', 'Refunded', 'Staff'
        ])

        fee_map = {fr.order_ref: fr for fr in fee_records}

        for ev in events:
            fr = fee_map.get(ev.order_ref)
            writer.writerow([
                ev.created_at.strftime('%H:%M'),
                _csv_safe(ev.order_ref),
                _csv_safe(ev.event_type),
                ev.amount,
                fr.fee_amount        if fr else '',
                fr.fee_rate_snapshot if fr else '',
                'Yes' if (fr and fr.is_refunded) else 'No' if fr else '',
                _csv_safe(ev.staff_user.username) if ev.staff_user else '',
            ])
        return response
