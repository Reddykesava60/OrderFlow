
from kitchen.models import PaymentEvent
from kitchen.services import trigger_kds_refresh
from ordering.models import PaymentTransaction, PaymentProvider, PaymentState, LedgerEntry
from core.models import Customer
from core.services import verify_customer_pin
from ordering.ledger.services import RestaurantLedgerService
from ordering.orders.services import _next_order_number

import time
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
import razorpay
from django.db import IntegrityError, transaction, models as db_models
from django.conf import settings
from django.utils import timezone
import bleach

from core.models import MenuItem, AddOn, MenuItemAddOn, PlatformFeeRecord
from ordering.models import Order, OrderItem, OrderItemAddOn, RestaurantOrderCounter, StockReservation, WorkStatus
from ordering.exceptions import CartError, PaymentConfigurationError
from ordering.inventory.services import _lock_and_decrement_stock, _create_stock_reservations

logger = logging.getLogger(__name__)
TWO_PLACES = Decimal('0.01')


def _clean(value):
    return bleach.clean(value or '', tags=[], strip=True).strip()

def _payment_config_field(config, field):
    if field == 'razorpay_key_secret':
        return config.get_razorpay_key_secret()
    if field == 'razorpay_webhook_secret':
        return config.get_razorpay_webhook_secret()
    return getattr(config, field)

def get_restaurant_payment_config(restaurant, require_usable=True, required_fields=None, require_active=True, *, allow_test_keys=False):
    from ordering.payments.resolver import resolve_payment_config
    try:
        resolved = resolve_payment_config(restaurant)
        class _LegacyResolvedProxy:
            def __init__(self, res):
                self.razorpay_key_id = res.credentials.get('key_id', '')
                self._key_secret = res.credentials.get('key_secret', '')
                self._webhook_secret = res.webhook_secret
            def get_razorpay_key_secret(self): return self._key_secret
            def get_razorpay_webhook_secret(self): return self._webhook_secret
        return _LegacyResolvedProxy(resolved)
    except Exception as e:
        if type(e).__name__ == 'PaymentConfigurationError':
            raise PaymentConfigurationError(str(e))
        raise

class _PlatformPaymentConfigProxy:
    """
    In-memory proxy that mimics a payment configuration using platform env vars.
    Allows legacy code paths (CheckoutView, RazorpayVerifyView) to work unchanged.
    """

    def __init__(self):
        self.razorpay_key_id = settings.RAZORPAY_KEY_ID
        self._key_secret = settings.RAZORPAY_KEY_SECRET
        self._webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        self.is_active = bool(self.razorpay_key_id and self._key_secret)
        self.account_name = 'Platform'
        self.config_status = 'ACTIVE'
        self._source = 'PLATFORM'

    def get_razorpay_key_secret(self):
        return self._key_secret

    def get_razorpay_webhook_secret(self):
        return self._webhook_secret

    @property
    def is_usable(self):
        return bool(self.is_active and self.razorpay_key_id and self._key_secret and self._webhook_secret)

    @property
    def masked_key_id(self):
        if not self.razorpay_key_id:
            return ''
        return f'{self.razorpay_key_id[:8]}...'

def _get_platform_payment_config(*, allow_test_keys=False):
    """Return a platform-level config proxy using environment variables."""
    proxy = _PlatformPaymentConfigProxy()
    if not proxy.razorpay_key_id or not proxy._key_secret:
        raise PaymentConfigurationError('No Razorpay configuration found for this restaurant and no platform credentials configured.')
    if not allow_test_keys and (not settings.DEBUG) and proxy.razorpay_key_id.startswith('rzp_test_'):
        raise PaymentConfigurationError('Test Razorpay credentials are not allowed in production.')
    return proxy

def validate_and_price_cart(restaurant, cart_lines):
    """
    Validate every line in the cart without touching stock.
    Returns a list of validated, priced line dicts.

    cart_lines: list of dicts from the parsed POST body:
        [
          {
            "item_id": "uuid",
            "quantity": 2,
            "dining_option": "DINE_IN" | "PARCEL",
            "spice_level": "MILD" | "MEDIUM" | "HOT" | "",
            "addons": [{"addon_id": "uuid", "quantity": 1}, ...]
          },
          ...
        ]
    """
    if not cart_lines:
        raise CartError('EMPTY_CART', 'Your cart is empty.')
    if len(cart_lines) > 30:
        raise CartError('CART_TOO_LARGE', 'Maximum 30 distinct items per order.')
    normalized_lines = []
    item_ids = []
    addon_ids = []
    for line in cart_lines:
        if not isinstance(line, dict):
            raise CartError('INVALID_CART', 'Invalid cart line.')
        try:
            item_id = uuid.UUID(str(line.get('item_id', '')))
        except (TypeError, ValueError):
            raise CartError('INVALID_ITEM', 'Invalid item selected.')
        normalized_addons = []
        addons = line.get('addons', [])
        if not isinstance(addons, list):
            raise CartError('INVALID_CART', 'Invalid add-on selection.')
        for addon_line in addons:
            if not isinstance(addon_line, dict):
                raise CartError('INVALID_CART', 'Invalid add-on selection.')
            try:
                addon_id = uuid.UUID(str(addon_line.get('addon_id', '')))
            except (TypeError, ValueError):
                raise CartError('INVALID_ADDON', 'Invalid add-on selected.')
            normalized_addons.append({**addon_line, 'addon_id': addon_id})
            addon_ids.append(addon_id)
        normalized_lines.append({**line, 'item_id': item_id, 'addons': normalized_addons})
        item_ids.append(item_id)
    items_qs = MenuItem.objects.filter(id__in=item_ids, restaurant=restaurant).select_related('restaurant')
    items_map = {str(item.id): item for item in items_qs}
    addons_map = {}
    if addon_ids:
        addons_qs = AddOn.objects.filter(id__in=addon_ids, restaurant=restaurant, is_active=True)
        addons_map = {str(a.id): a for a in addons_qs}
    valid_links = set(MenuItemAddOn.objects.filter(menu_item_id__in=item_ids, addon_id__in=addon_ids).values_list('menu_item_id', 'addon_id')) if addon_ids else set()
    priced_lines = []
    for line in normalized_lines:
        item = items_map.get(str(line['item_id']))
        if not item:
            raise CartError('ITEM_NOT_FOUND', f'Item not found.', line.get('item_id'))
        if not item.is_available:
            raise CartError('ITEM_UNAVAILABLE', f"'{item.name}' is no longer available.", item.name)
        try:
            qty = int(line.get('quantity', 1))
        except (TypeError, ValueError):
            raise CartError('INVALID_QTY', f"Quantity for '{item.name}' must be 1-99.", item.name)
        if not 1 <= qty <= 99:
            raise CartError('INVALID_QTY', f"Quantity for '{item.name}' must be 1–99.", item.name)
        dining_option = line.get('dining_option', 'DINE_IN')
        if dining_option not in ('DINE_IN', 'PARCEL'):
            raise CartError('INVALID_DINING', 'Invalid dining option.', item.name)
        spice_level = line.get('spice_level', '')
        if item.spice_configurable and spice_level not in ('MILD', 'MEDIUM', 'HOT'):
            raise CartError('INVALID_SPICE', f"Choose a spice level for '{item.name}'.", item.name)
        if not item.spice_configurable:
            spice_level = ''
        surcharge = item.parcel_surcharge if dining_option == 'PARCEL' else Decimal('0.00')
        unit_price = item.base_price
        priced_addons = []
        for addon_line in line.get('addons', []):
            addon = addons_map.get(str(addon_line['addon_id']))
            if not addon:
                raise CartError('ADDON_UNAVAILABLE', f'An add-on is no longer available.', item.name)
            if (item.id, addon.id) not in valid_links:
                raise CartError('ADDON_NOT_LINKED', f"Add-on not available for '{item.name}'.", item.name)
            try:
                addon_qty = int(addon_line.get('quantity', 1))
            except (TypeError, ValueError):
                raise CartError('ADDON_QTY', f"Invalid add-on quantity for '{addon.name}'.", item.name)
            if not 1 <= addon_qty <= addon.max_qty:
                raise CartError('ADDON_QTY', f"Max {addon.max_qty} of '{addon.name}' per item.", item.name)
            priced_addons.append({'addon': addon, 'addon_name': addon.name, 'unit_price': addon.price, 'quantity': addon_qty})
        priced_lines.append({'menu_item': item, 'menu_item_name': item.name, 'unit_price': unit_price, 'parcel_surcharge': surcharge, 'quantity': qty, 'dining_option': dining_option, 'spice_level': spice_level, 'addons': priced_addons})
    return priced_lines

def compute_order_total(priced_lines):
    """Sum all line totals. Called AFTER validate_and_price_cart."""
    total = Decimal('0.00')
    for line in priced_lines:
        item_unit = line['unit_price'] + line['parcel_surcharge']
        total += item_unit * line['quantity']
        for addon in line['addons']:
            total += addon['unit_price'] * addon['quantity']
    return total.quantize(TWO_PLACES)

def _create_order_rows(restaurant, priced_lines, total, customer_name, table_number, payment_method, status, idempotency_key=None, customer=None):
    """Create Order + OrderItem + OrderItemAddOn rows. Must be inside transaction.atomic()."""
    order_number = _next_order_number(restaurant)
    order = Order.objects.create(restaurant=restaurant, order_number=order_number, customer_name=_clean(customer_name)[:60], table_number=_clean(table_number)[:20], payment_method=payment_method, status=status, total=total, customer=customer, consent_given=True, idempotency_key=idempotency_key)
    for line in priced_lines:
        order_item = OrderItem.objects.create(order=order, menu_item=line['menu_item'], menu_item_name=line['menu_item_name'], unit_price=line['unit_price'], parcel_surcharge=line['parcel_surcharge'], quantity=line['quantity'], dining_option=line['dining_option'], spice_level=line['spice_level'])
        addon_rows = [OrderItemAddOn(order_item=order_item, addon=a['addon'], addon_name=a['addon_name'], unit_price=a['unit_price'], quantity=a['quantity']) for a in line['addons']]
        if addon_rows:
            OrderItemAddOn.objects.bulk_create(addon_rows)
    return order

def place_cash_order(restaurant, cart_lines, customer_name, table_number, idempotency_key=None, staff_user=None):
    """
    Full cash checkout in one atomic transaction:
      validate → lock stock → create order (UNPAID) → PaymentEvent(INITIATED)
    Fee record is NOT created here — created when counter staff confirms cash.
    Returns the created Order.
    """
    priced_lines = validate_and_price_cart(restaurant, cart_lines)
    total = compute_order_total(priced_lines)
    try:
        with transaction.atomic():
            if idempotency_key:
                existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).select_for_update().first()
                if existing:
                    logger.warning('Duplicate cash checkout intercepted: idempotency_key=%s', idempotency_key)
                    return existing
            _lock_and_decrement_stock(priced_lines)
            order = _create_order_rows(restaurant, priced_lines, total, customer_name, table_number, payment_method=Order.PaymentMethod.CASH, status=Order.Status.UNPAID, idempotency_key=idempotency_key)
            PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=restaurant, event_type=PaymentEvent.EventType.INITIATED, amount=total)
            
            if staff_user and staff_user.is_authenticated and staff_user.restaurant_id == restaurant.id:
                if getattr(staff_user, 'allow_cash_collection', False) or getattr(staff_user, 'is_owner', False):
                    from ordering.orders.services import confirm_cash_payment
                    confirm_cash_payment(order, staff_user)
                    order.refresh_from_db()
    except IntegrityError:
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).first()
            if existing:
                logger.warning('Duplicate cash checkout caught by DB constraint: idempotency_key=%s', idempotency_key)
                return existing
        raise
    trigger_kds_refresh(restaurant.id)
    return order

def place_upi_order(restaurant, cart_lines, customer_name, table_number, idempotency_key=None):
    """
    UPI checkout — creates Order + StockReservations + PaymentEvent(RAZORPAY_INITIATED).
    Razorpay order creation happens in the view (needs HTTP context).
    Returns the created Order (status=UNPAID, razorpay_order_id still empty).
    """
    priced_lines = validate_and_price_cart(restaurant, cart_lines)
    total = compute_order_total(priced_lines)
    try:
        with transaction.atomic():
            if idempotency_key:
                existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).select_for_update().first()
                if existing:
                    logger.warning('Duplicate UPI checkout intercepted: idempotency_key=%s', idempotency_key)
                    return existing
            _lock_and_decrement_stock(priced_lines)
            order = _create_order_rows(restaurant, priced_lines, total, customer_name, table_number, payment_method=Order.PaymentMethod.UPI, status=Order.Status.UNPAID, idempotency_key=idempotency_key)
            _create_stock_reservations(order, priced_lines)
            PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=restaurant, event_type=PaymentEvent.EventType.RAZORPAY_INITIATED, amount=total)
    except IntegrityError:
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).first()
            if existing:
                logger.warning('Duplicate UPI checkout caught by DB constraint: idempotency_key=%s', idempotency_key)
                return existing
        raise
    trigger_kds_refresh(restaurant.id)
    return order

def place_post_payment_order(restaurant, cart_lines, customer, plain_pin, table_number, idempotency_key=None):
    """
    Post-Payment checkout.
    Verifies PIN, checks credit limit, creates Order, deducts stock, records LedgerEntry, updates balance.
    All inside one strict transaction.atomic() to prevent race conditions.
    """
    from core.services import verify_customer_pin
    from ordering.models import LedgerEntry
    if customer.is_blocked:
        raise CartError('CUSTOMER_BLOCKED', 'This account is currently blocked.')
    if not customer.is_post_payment_enabled or not customer.admin_post_payment_enabled:
        raise CartError('POST_PAYMENT_DISABLED', 'Post-Payment is not enabled for this account.')
    t0 = time.time()
    pin_ok = verify_customer_pin(customer, plain_pin)
    dt_pin = time.time() - t0
    logger.info('Post-payment PIN verify took %.4fs', dt_pin)
    if not pin_ok:
        raise CartError('INVALID_PIN', 'The PIN you entered is incorrect.')
    priced_lines = validate_and_price_cart(restaurant, cart_lines)
    total = compute_order_total(priced_lines)
    try:
        t1 = time.time()
        with transaction.atomic():
            if idempotency_key:
                existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).select_for_update().first()
                if existing:
                    logger.warning('Duplicate post-payment checkout intercepted: idempotency_key=%s', idempotency_key)
                    return existing
            locked_customer = type(customer).objects.select_for_update().get(pk=customer.pk)
            if locked_customer.credit_limit is not None:
                if locked_customer.balance + total > locked_customer.credit_limit:
                    raise CartError('CREDIT_LIMIT_EXCEEDED', 'This order exceeds the available credit limit.')
            _lock_and_decrement_stock(priced_lines)
            order = _create_order_rows(restaurant, priced_lines, total, locked_customer.name, table_number, payment_method=Order.PaymentMethod.POST_PAYMENT, status=Order.Status.PENDING, idempotency_key=idempotency_key, customer=locked_customer)
            locked_customer.balance += total
            locked_customer.save(update_fields=['balance'])
            LedgerEntry.objects.create(restaurant=restaurant, customer=locked_customer, entry_type=LedgerEntry.EntryType.ORDER, amount=total, balance_after=locked_customer.balance, order=order, description=f'Order #{order.order_number}')
            PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=restaurant, event_type=PaymentEvent.EventType.INITIATED, amount=total)
            from ordering.ledger.services import RestaurantLedgerService
            RestaurantLedgerService().record_post_payment(restaurant=restaurant, order=order, gross_amount=total, platform_fee=Decimal('0.00'))
            customer.balance = locked_customer.balance
    except IntegrityError:
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).first()
            if existing:
                return existing
        raise
    dt_tx = time.time() - t1
    logger.info('Post-payment transaction took %.4fs', dt_tx)
    trigger_kds_refresh(restaurant.id)
    return order

def create_razorpay_order(order):
    """
    Create a Razorpay order for the given platform order.
    Uses get_restaurant_payment_config() which now falls through to
    platform credentials when no per-restaurant config exists.
    """
    payment_config = get_restaurant_payment_config(order.restaurant)
    client = razorpay.Client(auth=(payment_config.razorpay_key_id, payment_config.get_razorpay_key_secret()))
    razorpay_order = client.order.create({'amount': int(order.total * 100), 'currency': 'INR', 'receipt': str(order.id), 'notes': {'order_id': str(order.id), 'restaurant': order.restaurant.name}})
    order.razorpay_order_id = razorpay_order['id']
    order.save(update_fields=['razorpay_order_id'])
    from ordering.models import PaymentTransaction, PaymentProvider, PaymentState
    from django.utils import timezone
    PaymentTransaction.objects.get_or_create(restaurant=order.restaurant, order=order, provider=PaymentProvider.RAZORPAY, provider_order_id=razorpay_order['id'], defaults={'state': PaymentState.INITIATED, 'amount': order.total, 'currency': 'INR', 'expires_at': timezone.now() + timezone.timedelta(minutes=15)})
    return razorpay_order