# ordering/views.py
import hashlib
import json
import logging

import razorpay
from django.core.cache import cache
from django.db.models import Exists, OuterRef, Prefetch
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from core.models import ItemType, MenuItem, MenuItemAddOn, Restaurant, Customer
from core.ratelimit import client_ip, rate_limit
from kitchen.models import PaymentEvent

from .models import Order, PaymentProvider, PaymentState, PaymentTransaction
from .checkout.services import CartError, PaymentConfigurationError, create_razorpay_order, get_restaurant_payment_config, place_cash_order, place_upi_order, place_post_payment_order
from .orders.services import expire_overdue_unpaid_cash_orders, get_cash_payment_timeout_minutes

logger = logging.getLogger(__name__)
POST_PAYMENT_PIN_LIMIT = 5
POST_PAYMENT_PIN_WINDOW_SECONDS = 300


def _get_open_restaurant(slug):
    """
    Returns (restaurant, config, is_closed).
    Raises Http404 if slug is invalid or restaurant is inactive.
    """
    try:
        restaurant = (
            Restaurant.objects
            .select_related('config')
            .get(slug=slug, is_active=True)
        )
    except Restaurant.DoesNotExist:
        raise Http404

    config = restaurant.config
    return restaurant, config, not config.is_open


def _post_payment_pin_key(request, restaurant, serial_number):
    raw = f"{restaurant.id}:{serial_number}:{client_ip(request)}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"postpay-pin:{digest}"


def _post_payment_pin_limited(request, restaurant, serial_number):
    try:
        return (cache.get(_post_payment_pin_key(request, restaurant, serial_number)) or 0) >= POST_PAYMENT_PIN_LIMIT
    except Exception:
        logger.exception("Post-payment PIN rate limiter failed open")
        return False


def _record_post_payment_pin_failure(request, restaurant, serial_number):
    key = _post_payment_pin_key(request, restaurant, serial_number)
    try:
        if not cache.add(key, 1, timeout=POST_PAYMENT_PIN_WINDOW_SECONDS):
            cache.incr(key)
    except Exception:
        logger.exception("Post-payment PIN rate limiter failed open")


def _clear_post_payment_pin_failures(request, restaurant, serial_number):
    try:
        cache.delete(_post_payment_pin_key(request, restaurant, serial_number))
    except Exception:
        logger.exception("Post-payment PIN rate limiter cleanup failed")


@method_decorator(rate_limit('menu', limit=60, window=60), name='dispatch')
class MenuView(View):
    """
    GET /r/{slug}/
    Public. No authentication required.

    The full rendered response is cached for 30 seconds per restaurant
    to avoid repeated DB hits during ordering rush.
    """

    # Cache timeout in seconds for the rendered menu page
    MENU_CACHE_TIMEOUT = 30

    def get(self, request, slug):
        restaurant, config, is_closed = _get_open_restaurant(slug)
        upi_available = config.admin_upi_enabled and config.upi_enabled and restaurant.has_active_razorpay

        if is_closed:
            return render(request, 'ordering/closed.html', {
                'restaurant': restaurant,
                'reopen_message': config.reopen_message,
            }, status=200)

        # ── Check response cache ─────────────────────────────────────
        menu_cache_key = f"menu_html_{restaurant.id}"
        cached_response = cache.get(menu_cache_key)
        if cached_response is not None:
            return cached_response

        has_active_addon = Exists(
            MenuItemAddOn.objects.filter(
                menu_item=OuterRef('pk'),
                addon__is_active=True,
            )
        )
        items = (
            MenuItem.objects
            .filter(
                restaurant=restaurant,
                is_available=True,
            )
            .select_related('item_type')
            .annotate(has_addons=has_active_addon)
            .prefetch_related(
                Prefetch(
                    'menuitemaddon_set',
                    queryset=(
                        MenuItemAddOn.objects
                        .filter(
                            addon__is_active=True,
                        )
                        .select_related('addon')
                    ),
                )
            )
            .order_by('item_type__sort_order', 'sort_order', 'name')
        )

        grouped = {}
        ungrouped = []
        for item in items:
            if item.item_type:
                grouped.setdefault(item.item_type, []).append(item)
            else:
                ungrouped.append(item)

        response = render(request, 'ordering/menu.html', {
            'restaurant': restaurant,
            'config': config,
            'upi_available': upi_available,
            'grouped': grouped,
            'ungrouped': ungrouped,
        })

        # Cache the rendered response
        cache.set(menu_cache_key, response, timeout=self.MENU_CACHE_TIMEOUT)
        return response


@method_decorator(rate_limit('menu', limit=60, window=60), name='dispatch')
class MenuByIdView(View):
    """
    GET /r/menu/{restaurant_id}/
    Public entrypoint used by QR codes.
    """
    def get(self, request, restaurant_id):
        try:
            restaurant = Restaurant.objects.get(id=restaurant_id, is_active=True)
        except Restaurant.DoesNotExist:
            raise Http404
        return MenuView().get(request, slug=restaurant.slug)


@method_decorator(rate_limit('checkout', limit=30, window=60), name='dispatch')
class CheckoutView(View):
    """
    POST /r/{slug}/checkout/
    Accepts JSON body. CSRF required (sent by Alpine.js via X-CSRFToken header).
    """

    def post(self, request, slug):
        restaurant, config, is_closed = _get_open_restaurant(slug)

        if is_closed:
            return JsonResponse({
                'error': 'RESTAURANT_CLOSED',
                'message': 'Ordering is paused.',
            }, status=403)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'INVALID_JSON'}, status=400)

        if not data.get('consent_given'):
            return JsonResponse({
                'error': 'CONSENT_REQUIRED',
                'message': 'Please accept the data consent.',
            }, status=422)

        payment_method = data.get('payment_method', 'CASH').upper()
        if payment_method not in ('CASH', 'UPI', 'POST_PAYMENT'):
            return JsonResponse({'error': 'INVALID_PAYMENT_METHOD', 'message': 'Invalid payment method selected.'}, status=422)

        if payment_method == 'CASH' and not (config.admin_cash_enabled and config.cash_enabled):
            return JsonResponse({'error': 'PAYMENT_METHOD_DISABLED', 'message': 'Cash payment is currently disabled. Please choose another option.'}, status=403)

        if payment_method == 'UPI' and (not (config.admin_upi_enabled and config.upi_enabled) or not restaurant.has_active_razorpay):
            return JsonResponse({'error': 'PAYMENT_METHOD_DISABLED', 'message': 'UPI payment is currently unavailable. Please choose another option.'}, status=403)

        if payment_method == 'POST_PAYMENT' and not (config.admin_post_payment_enabled and config.post_payment_enabled):
            return JsonResponse({'error': 'PAYMENT_METHOD_DISABLED', 'message': 'Post Payment (Tab) is currently disabled. Please choose another option.'}, status=403)

        customer_name = (data.get('customer_name') or '').strip()
        if payment_method != 'POST_PAYMENT' and not customer_name:
            return JsonResponse({
                'error': 'NAME_REQUIRED',
                'message': 'Please enter your name.',
            }, status=422)

        table_number = (data.get('table_number') or '').strip()
        cart_lines = data.get('cart', [])
        idempotency_key = data.get('idempotency_key')

        if len(customer_name) > 200 or len(table_number) > 20:
            return JsonResponse({'error': 'INVALID_CUSTOMER_DETAILS'}, status=422)
        if not isinstance(cart_lines, list):
            return JsonResponse({'error': 'INVALID_CART'}, status=422)

        try:
            if payment_method == 'CASH':
                order = place_cash_order(
                    restaurant,
                    cart_lines,
                    customer_name,
                    table_number,
                    idempotency_key=idempotency_key,
                    staff_user=request.user if request.user.is_authenticated else None,
                )
                return JsonResponse({
                    'status': 'ok',
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'redirect': f'/r/{slug}/receipt/{order.id}/',
                })

            if payment_method == 'POST_PAYMENT':
                serial_number = str(data.get('customer_serial') or '').strip()
                pin = str(data.get('customer_pin') or '').strip()
                
                if not serial_number or not pin:
                    return JsonResponse({'error': 'CUSTOMER_CREDENTIALS_REQUIRED', 'message': 'Customer ID and PIN are required.'}, status=422)

                if _post_payment_pin_limited(request, restaurant, serial_number):
                    return JsonResponse({
                        'error': 'RATE_LIMITED',
                        'message': 'Too many failed attempts. Please wait and try again.',
                    }, status=429)

                if not pin.isdigit() or not (4 <= len(pin) <= 6):
                    _record_post_payment_pin_failure(request, restaurant, serial_number)
                    return JsonResponse({
                        'error': 'INVALID_CUSTOMER_CREDENTIALS',
                        'message': 'Invalid Customer ID or PIN.',
                    }, status=422)
                
                try:
                    customer = Customer.objects.get(restaurant=restaurant, serial_number=int(serial_number))
                except (Customer.DoesNotExist, ValueError):
                    _record_post_payment_pin_failure(request, restaurant, serial_number)
                    return JsonResponse({'error': 'INVALID_CUSTOMER_CREDENTIALS', 'message': 'Invalid Customer ID or PIN.'}, status=422)
                    
                try:
                    order = place_post_payment_order(
                        restaurant=restaurant,
                        cart_lines=cart_lines,
                        customer=customer,
                        plain_pin=pin,
                        table_number=table_number,
                        idempotency_key=idempotency_key
                    )
                except CartError as e:
                    if e.code == 'INVALID_PIN':
                        _record_post_payment_pin_failure(request, restaurant, serial_number)
                        return JsonResponse({
                            'error': 'INVALID_CUSTOMER_CREDENTIALS',
                            'message': 'Invalid Customer ID or PIN.',
                        }, status=409)
                    raise
                _clear_post_payment_pin_failures(request, restaurant, serial_number)
                return JsonResponse({
                    'status': 'ok',
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'redirect': f'/r/{slug}/receipt/{order.id}/',
                })

            payment_config = get_restaurant_payment_config(restaurant)
            order = place_upi_order(
                restaurant,
                cart_lines,
                customer_name,
                table_number,
                idempotency_key=idempotency_key,
            )

            try:
                rz_order = create_razorpay_order(order)
            except Exception:
                logger.exception("Razorpay order creation failed")
                from .services import cancel_upi_payment

                try:
                    cancel_upi_payment(order, PaymentEvent.EventType.PAYMENT_FAILED)
                except Exception:
                    logger.exception(
                        "Failed to release UPI reservation after Razorpay create error for order %s",
                        order.id,
                    )
                return JsonResponse({
                    'error': 'RAZORPAY_ERROR',
                    'message': 'Payment gateway error. Please try cash or retry.',
                }, status=502)

            return JsonResponse({
                'status': 'razorpay_pending',
                'order_id': str(order.id),
                'order_number': order.order_number,
                'razorpay_order_id': rz_order['id'],
                'razorpay_key_id': payment_config.razorpay_key_id,
                'total_paise': int(order.total * 100),
                'customer_name': customer_name,
                'receipt_url': f'/r/{slug}/receipt/{order.id}/',
            })

        except CartError as e:
            logger.warning("Checkout CartError: code=%s, message=%s, item=%s", e.code, e.message, e.item_name)
            return JsonResponse({
                'error': e.code,
                'message': e.message,
                'item_name': e.item_name,
            }, status=409)
        except PaymentConfigurationError as e:
            return JsonResponse({
                'error': 'PAYMENT_METHOD_DISABLED',
                'message': str(e),
            }, status=503)
        except Exception:
            logger.exception("Unexpected checkout error for restaurant %s", slug)
            return JsonResponse({
                'error': 'SERVER_ERROR',
                'message': 'Something went wrong. Please try again.',
            }, status=500)


@method_decorator(rate_limit('receipt', limit=30, window=60), name='dispatch')
class ReceiptView(View):
    """
    GET /r/{slug}/receipt/{order_id}/
    Public. No auth. 404 on invalid or cross-restaurant UUID.
    """

    def get(self, request, slug, order_id):
        restaurant, _, _ = _get_open_restaurant(slug)

        from django.core.cache import cache
        expiry_key = f"cash_expiry_lock_{restaurant.id}"
        if cache.add(expiry_key, 1, timeout=30):
            expire_overdue_unpaid_cash_orders(restaurant=restaurant)

        try:
            order = (
                Order.objects
                .select_related('restaurant')
                .prefetch_related('items__addons')
                .get(id=order_id, restaurant=restaurant)
            )
        except (Order.DoesNotExist, ValueError):
            raise Http404

        fee_record = order.fee_records.first()

        context = {
            'restaurant': restaurant,
            'order': order,
            'fee_record': fee_record,
        }

        if order.payment_method == Order.PaymentMethod.CASH and order.status == Order.Status.UNPAID:
            context['cash_timeout_minutes'] = get_cash_payment_timeout_minutes(restaurant)
            
        if order.payment_method == Order.PaymentMethod.POST_PAYMENT:
            ledger_entry = order.ledger_entries.first()
            context['ledger_entry'] = ledger_entry
            if ledger_entry:
                context['prev_balance'] = ledger_entry.balance_after - ledger_entry.amount

        return render(request, 'ordering/receipt_v2.html', context)


@method_decorator(rate_limit('razorpay_verify', limit=60, window=300), name='dispatch')
class RazorpayVerifyView(View):
    """
    POST /payments/razorpay/verify/

    Fast-path operational confirmation for Razorpay payments.

    Verification flow:
      1. Verify checkout signature (proves checkout flow completed)
      2. Backend payment.fetch() (proves payment is actually captured)
      3. mark_paid() (confirm order, create ledger entries)

    Webhooks serve as the authoritative async reconciliation safety net.
    This endpoint provides low-latency confirmation for kitchen/KDS responsiveness.
    """

    def post(self, request):
        from ordering.payments.contracts import ProviderWebhookEvent
        from ordering.payments.services import PaymentMutationService

        try:
            payload = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'INVALID_JSON'}, status=400)

        rz_order_id = (payload.get('razorpay_order_id') or '').strip()
        rz_payment_id = (payload.get('razorpay_payment_id') or '').strip()
        rz_signature = (payload.get('razorpay_signature') or '').strip()

        if not rz_order_id or not rz_payment_id or not rz_signature:
            return JsonResponse({'error': 'MISSING_FIELDS'}, status=400)

        logger.info(
            "payment_verify_received rz_order_id=%s rz_payment_id=%s",
            rz_order_id, rz_payment_id,
        )

        try:
            order = (
                Order.objects
                .get(razorpay_order_id=rz_order_id)
            )
        except Order.DoesNotExist:
            logger.warning(
                "payment_verify_order_not_found rz_order_id=%s", rz_order_id,
            )
            return JsonResponse({'error': 'ORDER_NOT_FOUND'}, status=404)

        # Already confirmed — return immediately (idempotent)
        if order.status != Order.Status.UNPAID:
            logger.info(
                "payment_verify_already_confirmed rz_order_id=%s order_status=%s",
                rz_order_id, order.status,
            )
            return JsonResponse({
                'ok': True,
                'order_id': str(order.id),
                'order_status': order.status,
            })

        try:
            payment_config = get_restaurant_payment_config(
                order.restaurant,
                require_usable=False,
                required_fields=('razorpay_key_id', 'razorpay_key_secret'),
                require_active=False,
            )
        except PaymentConfigurationError as e:
            logger.warning(
                "payment_verify_config_unavailable rz_order_id=%s error=%s",
                rz_order_id, e,
            )
            return JsonResponse({'error': 'PAYMENT_CONFIG_ERROR', 'message': str(e)}, status=503)

        client = razorpay.Client(
            auth=(payment_config.razorpay_key_id, payment_config.get_razorpay_key_secret())
        )

        # ── Step 1: Verify checkout signature ──
        # This proves the checkout flow completed (HMAC of order_id + payment_id
        # using key_secret). Necessary but not sufficient for financial truth.
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': rz_order_id,
                'razorpay_payment_id': rz_payment_id,
                'razorpay_signature': rz_signature,
            })
        except razorpay.errors.SignatureVerificationError:
            logger.warning(
                "payment_verify_signature_invalid rz_order_id=%s rz_payment_id=%s",
                rz_order_id, rz_payment_id,
            )
            return JsonResponse({'error': 'INVALID_SIGNATURE'}, status=400)

        logger.info(
            "payment_verify_signature_valid rz_order_id=%s rz_payment_id=%s",
            rz_order_id, rz_payment_id,
        )

        # ── Step 2: Backend payment.fetch() — verify actual capture status ──
        # This is the critical hardening step. The checkout signature only proves
        # the checkout flow completed, not that money was actually captured.
        # We fetch the payment directly from Razorpay to confirm capture.
        rz_payment_status = None
        rz_payment_amount = None
        try:
            rz_payment = client.payment.fetch(rz_payment_id)
            rz_payment_status = rz_payment.get('status')
            rz_payment_amount = rz_payment.get('amount')  # in paise

            logger.info(
                "payment_verify_fetch_result rz_order_id=%s rz_payment_id=%s "
                "rz_status=%s rz_amount=%s",
                rz_order_id, rz_payment_id, rz_payment_status, rz_payment_amount,
            )

            if rz_payment_status not in ('captured', 'authorized'):
                # Payment was not captured — do NOT confirm the order.
                # The webhook or reconciliation cron will handle it.
                logger.warning(
                    "payment_verify_not_captured rz_order_id=%s rz_payment_id=%s "
                    "rz_status=%s — deferring to webhook",
                    rz_order_id, rz_payment_id, rz_payment_status,
                )
                return JsonResponse({
                    'ok': False,
                    'error': 'PAYMENT_NOT_CAPTURED',
                    'message': 'Payment is being processed. It will be confirmed shortly.',
                    'rz_status': rz_payment_status,
                }, status=202)

            # Verify amount matches (paise vs rupees)
            expected_paise = int(order.total * 100)
            if rz_payment_amount is not None and int(rz_payment_amount) != expected_paise:
                logger.error(
                    "payment_verify_amount_mismatch rz_order_id=%s "
                    "expected=%s actual=%s",
                    rz_order_id, expected_paise, rz_payment_amount,
                )
                return JsonResponse({
                    'error': 'AMOUNT_MISMATCH',
                    'message': 'Payment amount does not match order total.',
                }, status=400)

        except razorpay.errors.BadRequestError:
            # Payment ID doesn't exist at Razorpay — reject
            logger.error(
                "payment_verify_fetch_bad_request rz_order_id=%s rz_payment_id=%s",
                rz_order_id, rz_payment_id,
            )
            return JsonResponse({
                'error': 'PAYMENT_NOT_FOUND',
                'message': 'Payment could not be verified with Razorpay.',
            }, status=400)
        except Exception:
            # Network/timeout error fetching from Razorpay.
            # Provider truth is required before confirming the order. The
            # webhook or reconciliation cron will complete this later.
            logger.warning(
                "payment_verify_fetch_failed rz_order_id=%s rz_payment_id=%s "
                "— proceeding with checkout signature verification only",
                rz_order_id, rz_payment_id,
                exc_info=True,
            )
            return JsonResponse({
                'ok': False,
                'error': 'PAYMENT_VERIFICATION_UNAVAILABLE',
                'message': 'Payment verification is temporarily unavailable. The payment will be confirmed automatically once the provider status is available.',
            }, status=202)

        # ── Step 3: Confirm the payment ──
        # Find or create a PaymentTransaction for this order so that
        # mark_paid() has a transaction to update. The webhook may also
        # create one, but get_or_create is idempotent.
        try:
            payment, _created = PaymentTransaction.objects.get_or_create(
                restaurant=order.restaurant,
                order=order,
                provider=PaymentProvider.RAZORPAY,
                provider_order_id=rz_order_id,
                defaults={
                    'state': PaymentState.INITIATED,
                    'amount': order.total,
                    'currency': 'INR',
                    'expires_at': timezone.now() + timezone.timedelta(minutes=15),
                },
            )

            event = ProviderWebhookEvent(
                kind='payment_paid',
                provider_order_id=rz_order_id,
                provider_payment_id=rz_payment_id,
                amount=order.total,
                raw={
                    'source': 'frontend_verify',
                    'rz_payment_status': rz_payment_status,
                    'rz_payment_amount': rz_payment_amount,
                },
            )
            PaymentMutationService().mark_paid(payment, event)
            order.refresh_from_db()

            logger.info(
                "payment_verify_confirmed rz_order_id=%s rz_payment_id=%s "
                "payment_id=%s source=frontend_verify",
                rz_order_id, rz_payment_id, payment.id,
            )

        except Exception:
            logger.exception(
                "payment_verify_mark_paid_failed rz_order_id=%s rz_payment_id=%s",
                rz_order_id, rz_payment_id,
            )
            return JsonResponse({
                'error': 'PAYMENT_PROCESSING_ERROR',
                'message': 'Payment received but processing failed. It will be confirmed shortly via webhook.',
            }, status=500)

        return JsonResponse({
            'ok': True,
            'order_id': str(order.id),
            'order_status': order.status,
        })



@method_decorator(rate_limit('razorpay_webhook', limit=300, window=60), name='dispatch')
@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(View):
    """
    POST /payments/razorpay/webhook/
    Legacy endpoint — delegates to the unified WebhookIngestionService.
    Kept for backward compatibility with Razorpay dashboard webhook URL config.
    """

    def post(self, request):
        from ordering.payments.jobs import ProcessPaymentWebhookJob
        from ordering.payments.services import WebhookIngestionService

        try:
            webhook_log = WebhookIngestionService().receive(
                provider='razorpay',
                raw_body=request.body,
                headers=request.headers,
            )
            if webhook_log:
                try:
                    ProcessPaymentWebhookJob.dispatch(webhook_log.id)
                except Exception:
                    logger.exception(
                        "Razorpay webhook persisted but dispatch failed for %s",
                        webhook_log.id,
                    )
            return HttpResponse(status=200)
        except Exception:
            logger.exception("Razorpay webhook: unified ingestion failed")
            return HttpResponse(status=400)
