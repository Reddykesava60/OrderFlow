# ordering/services.py
"""
All checkout business logic lives here.
Views and the Razorpay webhook both call into this module.
Nothing in this file touches the HTTP request object directly.
"""
import time
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP
import razorpay
from django.db import IntegrityError, transaction, models as db_models
from django.conf import settings
# pyrefly: ignore [missing-import]
from django.utils import timezone
import bleach

from core.models import (
    MenuItem, AddOn, MenuItemAddOn,
    PlatformFeeRecord, PlatformSettings, RestaurantPaymentConfig,
)
from .models import (
    Order, OrderItem, OrderItemAddOn,
    RestaurantOrderCounter, StockReservation, WorkStatus,
)
from kitchen.models import PaymentEvent
from kitchen.services import trigger_kds_refresh

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal('0.01')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(value):
    return bleach.clean(value or '', tags=[], strip=True).strip()


def _compute_platform_fee(order_total, restaurant=None):
    """
    Compute platform fee according to platform settings policy.
    Returns (fee_amount, fee_rate_snapshot).
    """
    if restaurant and restaurant.commission_rate is not None:
        fee_rate = Decimal(restaurant.commission_rate)
        fee_amount = (order_total * fee_rate / Decimal('100')).quantize(
            TWO_PLACES,
            rounding=ROUND_HALF_UP,
        )
        return fee_amount, fee_rate

    settings_obj = PlatformSettings.get_solo()

    if settings_obj.platform_fee_mode == PlatformSettings.FeeMode.FIXED:
        fee_amount = Decimal(settings_obj.platform_fee_fixed_amount).quantize(
            TWO_PLACES,
            rounding=ROUND_HALF_UP,
        )
        if order_total > Decimal('0.00'):
            fee_rate_snapshot = (fee_amount * Decimal('100') / order_total).quantize(
                TWO_PLACES,
                rounding=ROUND_HALF_UP,
            )
        else:
            fee_rate_snapshot = Decimal('0.00')
        return fee_amount, fee_rate_snapshot

    fee_rate = Decimal(settings_obj.platform_fee_percent)
    fee_amount = (order_total * fee_rate / Decimal('100')).quantize(
        TWO_PLACES,
        rounding=ROUND_HALF_UP,
    )
    return fee_amount, fee_rate


def _next_order_number(restaurant):
    """
    Assign sequential order number per restaurant per day.
    Uses SELECT FOR UPDATE — must be called inside transaction.atomic().
    Resets to 1 each calendar day (IST).
    """
    today = timezone.localdate()
    counter, _ = RestaurantOrderCounter.objects.select_for_update().get_or_create(
        restaurant=restaurant,
        defaults={'last_number': 0, 'last_reset': today},
    )
    if counter.last_reset != today:
        counter.last_number = 0
        counter.last_reset  = today
    counter.last_number += 1
    counter.save(update_fields=['last_number', 'last_reset'])
    return counter.last_number


# ── Cart validation ───────────────────────────────────────────────────────────

class CartError(Exception):
    """Raised for any validation failure during checkout."""
    def __init__(self, code, message, item_name=None):
        self.code       = code       # e.g. 'STOCK_ERROR', 'ITEM_UNAVAILABLE'
        self.message    = message
        self.item_name  = item_name
        super().__init__(message)


class PaymentConfigurationError(Exception):
    """Raised when a restaurant does not have a usable Razorpay configuration."""
    pass


def _payment_config_field(config, field):
    if field == 'razorpay_key_secret':
        return config.get_razorpay_key_secret()
    if field == 'razorpay_webhook_secret':
        return config.get_razorpay_webhook_secret()
    return getattr(config, field)


def get_restaurant_payment_config(
    restaurant,
    require_usable=True,
    required_fields=None,
    require_active=True,
    *,
    allow_test_keys=False,
):
    try:
        config = restaurant.payment_config
    except RestaurantPaymentConfig.DoesNotExist:
        config = None

    if config is None:
        config = RestaurantPaymentConfig.objects.filter(restaurant=restaurant).first()

    # If config is migrated to platform or missing entirely, try platform credentials
    use_platform = False
    if not config:
        use_platform = True
    elif hasattr(config, 'config_status') and config.config_status == RestaurantPaymentConfig.ConfigStatus.MIGRATED_TO_PLATFORM:
        use_platform = True
    elif require_active and not config.is_active:
        use_platform = True

    if use_platform:
        return _get_platform_payment_config(allow_test_keys=allow_test_keys)

    if require_usable and required_fields is None:
        required_fields = (
            'razorpay_key_id',
            'razorpay_key_secret',
            'razorpay_webhook_secret',
        )

    if require_active and not config.is_active:
        raise PaymentConfigurationError("Razorpay is not active for this restaurant.")

    # Guardrail: prevent test keys from being used in production mode.
    # This protects against misconfiguration when onboarding new restaurants.
    if (not allow_test_keys) and (not settings.DEBUG) and (config.razorpay_key_id or '').startswith('rzp_test_'):
        raise PaymentConfigurationError("Test Razorpay credentials are not allowed in production.")

    if required_fields:
        missing = [field for field in required_fields if not _payment_config_field(config, field)]
        if missing:
            # Last chance: fall through to platform credentials
            return _get_platform_payment_config(allow_test_keys=allow_test_keys)

    return config


class _PlatformPaymentConfigProxy:
    """
    In-memory proxy that mimics RestaurantPaymentConfig using platform env vars.
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
        return f"{self.razorpay_key_id[:8]}..."


def _get_platform_payment_config(*, allow_test_keys=False):
    """Return a platform-level config proxy using environment variables."""
    proxy = _PlatformPaymentConfigProxy()
    if not proxy.razorpay_key_id or not proxy._key_secret:
        raise PaymentConfigurationError(
            "No Razorpay configuration found for this restaurant and no platform credentials configured."
        )
    if (not allow_test_keys) and (not settings.DEBUG) and proxy.razorpay_key_id.startswith('rzp_test_'):
        raise PaymentConfigurationError("Test Razorpay credentials are not allowed in production.")
    return proxy


def get_cash_payment_timeout_minutes():
    return PlatformSettings.get_solo().cash_payment_timeout_minutes


def _auto_update_item_availability(item, *, allow_restore=False):
    update_fields = []

    if item.stock == 0:
        if item.is_available:
            item.is_available = False
            update_fields.append('is_available')
        if not item.auto_hidden_due_to_stock:
            item.auto_hidden_due_to_stock = True
            update_fields.append('auto_hidden_due_to_stock')
    elif allow_restore and item.stock is not None and item.stock > 0 and item.auto_hidden_due_to_stock:
        item.is_available = True
        item.auto_hidden_due_to_stock = False
        update_fields.extend(['is_available', 'auto_hidden_due_to_stock'])

    return update_fields


def _restore_item_availability_after_stock_return(item_id):
    item = MenuItem.objects.select_for_update().get(pk=item_id)
    update_fields = _auto_update_item_availability(item, allow_restore=True)
    if update_fields:
        item.save(update_fields=update_fields)


def _expire_unpaid_cash_order_locked(order):
    """
    Expire a locked unpaid cash order and restore finite stock.
    Caller must hold a select_for_update() lock on the order row.
    """
    order_items = list(
        OrderItem.objects.select_related('menu_item').filter(order=order)
    )
    order_addons = list(
        OrderItemAddOn.objects.select_related('addon').filter(order_item__order=order)
    )

    for item in order_items:
        if item.menu_item_id and item.menu_item and item.menu_item.stock is not None:
            MenuItem.objects.filter(pk=item.menu_item_id).update(
                stock=db_models.F('stock') + item.quantity
            )
            _restore_item_availability_after_stock_return(item.menu_item_id)

    for addon in order_addons:
        if addon.addon_id and addon.addon and addon.addon.stock is not None:
            AddOn.objects.filter(pk=addon.addon_id).update(
                stock=db_models.F('stock') + addon.quantity
            )

    order.status = Order.Status.CANCELLED
    order.save(update_fields=['status'])

    PaymentEvent.objects.create(
        order=order,
        order_ref=order.order_ref_snapshot,
        restaurant=order.restaurant,
        event_type=PaymentEvent.EventType.PAYMENT_TIMEOUT,
        amount=order.total,
    )


def expire_overdue_unpaid_cash_orders(restaurant=None):
    """
    Expire all unpaid cash orders older than the platform timeout.
    Optionally scope to a single restaurant.
    Returns number of orders expired.
    """
    timeout_minutes = get_cash_payment_timeout_minutes()
    cutoff = timezone.now() - timezone.timedelta(minutes=timeout_minutes)

    overdue_orders = (
        Order.objects
        .filter(
            payment_method=Order.PaymentMethod.CASH,
            status=Order.Status.UNPAID,
            created_at__lt=cutoff,
        )
        .select_related('restaurant')
        .order_by('created_at')
    )
    if restaurant is not None:
        overdue_orders = overdue_orders.filter(restaurant=restaurant)

    expired_count = 0
    for order in overdue_orders:
        try:
            if expire_unpaid_cash_order(order):
                expired_count += 1
        except Exception:
            logger.exception("Error expiring overdue cash order %s", order.pk)

    return expired_count


def sync_order_status(order):
    """
    Recompute the order's summary status from item/add-on work states.
    The order must already be paid before this is called.
    """
    if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED):
        return order

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        pending_exists = (
            OrderItem.objects.filter(order=order, prep_status=WorkStatus.PENDING).exists()
            or OrderItemAddOn.objects.filter(order_item__order=order, prep_status=WorkStatus.PENDING).exists()
        )
        preparing_exists = (
            OrderItem.objects.filter(order=order, prep_status=WorkStatus.PREPARING).exists()
            or OrderItemAddOn.objects.filter(order_item__order=order, prep_status=WorkStatus.PREPARING).exists()
        )

        now = timezone.now()
        update_fields = []

        if not pending_exists and not preparing_exists:
            if order.status != Order.Status.COMPLETED:
                order.status = Order.Status.COMPLETED
                update_fields.append('status')
            if not order.completed_at:
                order.completed_at = now
                update_fields.append('completed_at')
        elif preparing_exists:
            if order.status != Order.Status.PREP_STARTED:
                order.status = Order.Status.PREP_STARTED
                update_fields.append('status')
            if not order.prep_started_at:
                order.prep_started_at = now
                update_fields.append('prep_started_at')
            if order.completed_at is not None:
                order.completed_at = None
                update_fields.append('completed_at')
        else:
            if order.status != Order.Status.PENDING:
                order.status = Order.Status.PENDING
                update_fields.append('status')
            if order.completed_at is not None:
                order.completed_at = None
                update_fields.append('completed_at')

        if update_fields:
            order.save(update_fields=update_fields)

    return order


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

    # Bulk-fetch all MenuItems referenced in the cart (one query)
    items_qs = MenuItem.objects.filter(
        id__in=item_ids,
        restaurant=restaurant,
    ).select_related('restaurant')
    items_map = {str(item.id): item for item in items_qs}

    # Bulk-fetch all AddOns referenced in the cart (one query)
    addons_map = {}
    if addon_ids:
        addons_qs = AddOn.objects.filter(
            id__in=addon_ids,
            restaurant=restaurant,
            is_active=True,
        )
        addons_map = {str(a.id): a for a in addons_qs}

    # Validate links between items and add-ons (one query)
    valid_links = set(
        MenuItemAddOn.objects.filter(
            menu_item_id__in=item_ids,
            addon_id__in=addon_ids,
        ).values_list('menu_item_id', 'addon_id')
    ) if addon_ids else set()

    priced_lines = []

    for line in normalized_lines:
        item = items_map.get(str(line['item_id']))
        if not item:
            raise CartError('ITEM_NOT_FOUND', f"Item not found.", line.get('item_id'))

        if not item.is_available:
            raise CartError('ITEM_UNAVAILABLE', f"'{item.name}' is no longer available.", item.name)

        try:
            qty = int(line.get('quantity', 1))
        except (TypeError, ValueError):
            raise CartError('INVALID_QTY', f"Quantity for '{item.name}' must be 1-99.", item.name)
        if not (1 <= qty <= 99):
            raise CartError('INVALID_QTY', f"Quantity for '{item.name}' must be 1–99.", item.name)

        dining_option = line.get('dining_option', 'DINE_IN')
        if dining_option not in ('DINE_IN', 'PARCEL'):
            raise CartError('INVALID_DINING', 'Invalid dining option.', item.name)

        spice_level = line.get('spice_level', '')
        if item.spice_configurable and spice_level not in ('MILD', 'MEDIUM', 'HOT'):
            raise CartError('INVALID_SPICE', f"Choose a spice level for '{item.name}'.", item.name)
        if not item.spice_configurable:
            spice_level = ''

        # Unit price — server always reads from DB, never from client
        surcharge = item.parcel_surcharge if dining_option == 'PARCEL' else Decimal('0.00')
        unit_price = item.base_price

        priced_addons = []
        for addon_line in line.get('addons', []):
            addon = addons_map.get(str(addon_line['addon_id']))
            if not addon:
                raise CartError('ADDON_UNAVAILABLE', f"An add-on is no longer available.", item.name)

            # Verify the add-on is actually linked to this menu item
            if (item.id, addon.id) not in valid_links:
                raise CartError('ADDON_NOT_LINKED', f"Add-on not available for '{item.name}'.", item.name)

            try:
                addon_qty = int(addon_line.get('quantity', 1))
            except (TypeError, ValueError):
                raise CartError('ADDON_QTY', f"Invalid add-on quantity for '{addon.name}'.", item.name)
            if not (1 <= addon_qty <= addon.max_qty):
                raise CartError(
                    'ADDON_QTY',
                    f"Max {addon.max_qty} of '{addon.name}' per item.",
                    item.name
                )

            priced_addons.append({
                'addon':      addon,
                'addon_name': addon.name,
                'unit_price': addon.price,
                'quantity':   addon_qty,
            })

        priced_lines.append({
            'menu_item':      item,
            'menu_item_name': item.name,
            'unit_price':     unit_price,
            'parcel_surcharge': surcharge,
            'quantity':       qty,
            'dining_option':  dining_option,
            'spice_level':    spice_level,
            'addons':         priced_addons,
        })

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


# ── Stock locking ─────────────────────────────────────────────────────────────

def _lock_and_decrement_stock(priced_lines):
    """
    Must be called inside transaction.atomic().
    SELECT FOR UPDATE on every MenuItem/AddOn with finite stock,
    then re-validates stock >= requested inside the lock (SEC-02).
    Decrements immediately to hold the stock. Cash orders consume that stock
    right away; UPI orders attach StockReservation rows so the hold can be
    released on timeout or payment failure.
    """
    # Collect items/addons that have finite stock
    item_ids_with_stock = [
        line['menu_item'].id
        for line in priced_lines
        if line['menu_item'].stock is not None
    ]
    addon_ids_with_stock = [
        a['addon'].id
        for line in priced_lines
        for a in line['addons']
        if a['addon'].stock is not None
    ]

    # Lock rows
    locked_items = {}
    if item_ids_with_stock:
        for item in MenuItem.objects.select_for_update().filter(id__in=item_ids_with_stock):
            locked_items[item.id] = item

    locked_addons = {}
    if addon_ids_with_stock:
        for addon in AddOn.objects.select_for_update().filter(id__in=addon_ids_with_stock):
            locked_addons[addon.id] = addon

    # Validate and decrement inside the lock
    for line in priced_lines:
        item = locked_items.get(line['menu_item'].id)
        if item is not None:
            # Re-read stock INSIDE the lock
            if item.stock < line['quantity']:
                raise CartError('STOCK_ERROR', f"'{item.name}' is out of stock.", item.name)
            item.stock -= line['quantity']
            item_update_fields = ['stock']
            stock_visibility_updates = _auto_update_item_availability(item)
            for field in stock_visibility_updates:
                if field not in item_update_fields:
                    item_update_fields.append(field)
            item.save(update_fields=item_update_fields)

        for addon_line in line['addons']:
            addon = locked_addons.get(addon_line['addon'].id)
            if addon is not None:
                if addon.stock < addon_line['quantity']:
                    raise CartError('STOCK_ERROR', f"Add-on '{addon.name}' is out of stock.", addon.name)
                addon.stock -= addon_line['quantity']
                addon.save(update_fields=['stock'])


def _create_stock_reservations(order, priced_lines):
    """
    UPI flow: attach StockReservation rows to stock that has already been held
    by _lock_and_decrement_stock().
    Must be called inside transaction.atomic().
    """
    reservations = []
    expires_at = timezone.now() + timezone.timedelta(minutes=15)

    for line in priced_lines:
        item = line['menu_item']
        if item.stock is not None:
            reservations.append(StockReservation(
                order=order,
                menu_item=item,
                quantity=line['quantity'],
                expires_at=expires_at,
            ))
        for addon_line in line['addons']:
            addon = addon_line['addon']
            if addon.stock is not None:
                reservations.append(StockReservation(
                    order=order,
                    addon=addon,
                    quantity=addon_line['quantity'],
                    expires_at=expires_at,
                ))

    if reservations:
        StockReservation.objects.bulk_create(reservations)


# ── Order creation ────────────────────────────────────────────────────────────

def _create_order_rows(restaurant, priced_lines, total, customer_name,
                        table_number, payment_method, status, idempotency_key=None, customer=None):
    """Create Order + OrderItem + OrderItemAddOn rows. Must be inside transaction.atomic()."""
    order_number = _next_order_number(restaurant)

    order = Order.objects.create(
        restaurant      = restaurant,
        order_number    = order_number,
        customer_name   = _clean(customer_name)[:60],
        table_number    = _clean(table_number)[:20],
        payment_method  = payment_method,
        status          = status,
        total           = total,
        customer        = customer,
        consent_given   = True,
        idempotency_key = idempotency_key,
    )

    for line in priced_lines:
        order_item = OrderItem.objects.create(
            order            = order,
            menu_item        = line['menu_item'],
            menu_item_name   = line['menu_item_name'],
            unit_price       = line['unit_price'],
            parcel_surcharge = line['parcel_surcharge'],
            quantity         = line['quantity'],
            dining_option    = line['dining_option'],
            spice_level      = line['spice_level'],
        )
        addon_rows = [
            OrderItemAddOn(
                order_item         = order_item,
                addon              = a['addon'],
                addon_name         = a['addon_name'],
                unit_price         = a['unit_price'],
                quantity           = a['quantity'],
            )
            for a in line['addons']
        ]
        if addon_rows:
            OrderItemAddOn.objects.bulk_create(addon_rows)

    return order


def _create_fee_record(order, restaurant):
    """Create PlatformFeeRecord for a confirmed payment. Call inside transaction.atomic()."""
    fee_amount, fee_rate = _compute_platform_fee(order.total, restaurant=restaurant)

    PlatformFeeRecord.objects.create(
        order             = order,
        order_ref         = order.order_ref_snapshot,
        restaurant        = restaurant,
        order_total       = order.total,
        fee_amount        = fee_amount,
        fee_rate_snapshot = fee_rate,
    )
    return fee_amount


# ── Public checkout entrypoints ───────────────────────────────────────────────

def place_cash_order(restaurant, cart_lines, customer_name, table_number, idempotency_key=None):
    """
    Full cash checkout in one atomic transaction:
      validate → lock stock → create order (UNPAID) → PaymentEvent(INITIATED)
    Fee record is NOT created here — created when counter staff confirms cash.
    Returns the created Order.
    """
    priced_lines = validate_and_price_cart(restaurant, cart_lines)
    total        = compute_order_total(priced_lines)

    try:
        with transaction.atomic():
            # Idempotency check INSIDE the transaction to prevent TOCTOU race
            if idempotency_key:
                existing = Order.objects.filter(
                    idempotency_key=idempotency_key, restaurant=restaurant
                ).select_for_update().first()
                if existing:
                    logger.warning("Duplicate cash checkout intercepted: idempotency_key=%s", idempotency_key)
                    return existing

            _lock_and_decrement_stock(priced_lines)
            order = _create_order_rows(
                restaurant, priced_lines, total,
                customer_name, table_number,
                payment_method = Order.PaymentMethod.CASH,
                status         = Order.Status.UNPAID,
                idempotency_key = idempotency_key,
            )
            PaymentEvent.objects.create(
                order      = order,
                order_ref  = order.order_ref_snapshot,
                restaurant = restaurant,
                event_type = PaymentEvent.EventType.INITIATED,
                amount     = total,
            )
    except IntegrityError:
        # Final safety net: the DB unique constraint on idempotency_key caught a race
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).first()
            if existing:
                logger.warning("Duplicate cash checkout caught by DB constraint: idempotency_key=%s", idempotency_key)
                return existing
        raise

    trigger_kds_refresh(restaurant.id)
    return order


def confirm_cash_payment(order, staff_user):
    """
    Counter staff taps 'Collect Cash & Confirm'.
    UNPAID → PENDING + PaymentEvent(CASH_COLLECTED) + PlatformFeeRecord — all atomic.
    Returns (order, fee_amount).
    """
    timeout_minutes = get_cash_payment_timeout_minutes()
    timeout_cutoff = timezone.now() - timezone.timedelta(minutes=timeout_minutes)
    if order.created_at < timeout_cutoff:
        expire_unpaid_cash_order(order)
        raise CartError('PAYMENT_TIMEOUT', 'This cash order has expired.')

    with transaction.atomic():
        # Re-read with lock to prevent double-confirm
        order = Order.objects.select_for_update().get(pk=order.pk)

        if order.status != Order.Status.UNPAID:
            raise CartError('ALREADY_PAID', 'This order has already been paid.')

        order.status  = Order.Status.PENDING
        order.paid_at = timezone.now()
        order.save(update_fields=['status', 'paid_at'])

        PaymentEvent.objects.create(
            order      = order,
            order_ref  = order.order_ref_snapshot,
            restaurant = order.restaurant,
            event_type = PaymentEvent.EventType.CASH_COLLECTED,
            amount     = order.total,
            staff_user = staff_user,
        )

        fee_amount = _create_fee_record(order, order.restaurant)

        # New immutable ledger tracking for cash
        from ordering.ledger.services import RestaurantLedgerService
        RestaurantLedgerService().record_cash_payment(
            restaurant=order.restaurant,
            order=order,
            gross_amount=order.total,
            platform_fee=fee_amount,
        )

    return order, fee_amount


def place_upi_order(restaurant, cart_lines, customer_name, table_number, idempotency_key=None):
    """
    UPI checkout — creates Order + StockReservations + PaymentEvent(RAZORPAY_INITIATED).
    Razorpay order creation happens in the view (needs HTTP context).
    Returns the created Order (status=UNPAID, razorpay_order_id still empty).
    """
    priced_lines = validate_and_price_cart(restaurant, cart_lines)
    total        = compute_order_total(priced_lines)

    try:
        with transaction.atomic():
            # Idempotency check INSIDE the transaction to prevent TOCTOU race
            if idempotency_key:
                existing = Order.objects.filter(
                    idempotency_key=idempotency_key, restaurant=restaurant
                ).select_for_update().first()
                if existing:
                    logger.warning("Duplicate UPI checkout intercepted: idempotency_key=%s", idempotency_key)
                    return existing

            _lock_and_decrement_stock(priced_lines)
            order = _create_order_rows(
                restaurant, priced_lines, total,
                customer_name, table_number,
                payment_method = Order.PaymentMethod.UPI,
                status         = Order.Status.UNPAID,
                idempotency_key = idempotency_key,
            )
            _create_stock_reservations(order, priced_lines)
            PaymentEvent.objects.create(
                order      = order,
                order_ref  = order.order_ref_snapshot,
                restaurant = restaurant,
                event_type = PaymentEvent.EventType.RAZORPAY_INITIATED,
                amount     = total,
            )
    except IntegrityError:
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).first()
            if existing:
                logger.warning("Duplicate UPI checkout caught by DB constraint: idempotency_key=%s", idempotency_key)
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
    
    if not customer.is_post_payment_enabled:
        raise CartError('POST_PAYMENT_DISABLED', 'Post-Payment is not enabled for this account.')

    t0 = time.time()
    pin_ok = verify_customer_pin(customer, plain_pin)
    dt_pin = time.time() - t0
    logger.info("Post-payment PIN verify took %.4fs", dt_pin)

    if not pin_ok:
        raise CartError('INVALID_PIN', 'The PIN you entered is incorrect.')

    priced_lines = validate_and_price_cart(restaurant, cart_lines)
    total = compute_order_total(priced_lines)

    try:
        t1 = time.time()
        with transaction.atomic():
            # Idempotency check inside transaction
            if idempotency_key:
                existing = Order.objects.filter(
                    idempotency_key=idempotency_key, restaurant=restaurant
                ).select_for_update().first()
                if existing:
                    logger.warning("Duplicate post-payment checkout intercepted: idempotency_key=%s", idempotency_key)
                    return existing

            # Lock customer row to safely check and update balance
            locked_customer = type(customer).objects.select_for_update().get(pk=customer.pk)
            
            # Check credit limit
            if locked_customer.credit_limit is not None:
                if locked_customer.balance + total > locked_customer.credit_limit:
                    raise CartError('CREDIT_LIMIT_EXCEEDED', 'This order exceeds the available credit limit.')

            _lock_and_decrement_stock(priced_lines)

            order = _create_order_rows(
                restaurant, priced_lines, total,
                locked_customer.name, table_number,
                payment_method=Order.PaymentMethod.POST_PAYMENT,
                status=Order.Status.PENDING,  # Post Payment goes straight to PENDING
                idempotency_key=idempotency_key,
                customer=locked_customer,
            )

            # Update Balance (Positive balance = debt)
            locked_customer.balance += total
            locked_customer.save(update_fields=['balance'])

            # Record Ledger Entry
            LedgerEntry.objects.create(
                restaurant=restaurant,
                customer=locked_customer,
                entry_type=LedgerEntry.EntryType.ORDER,
                amount=total,
                balance_after=locked_customer.balance,
                order=order,
                description=f"Order #{order.order_number}",
            )

            # Optional: payment event for KDS stats (though post-payment doesn't strictly have cash collected)
            PaymentEvent.objects.create(
                order=order,
                order_ref=order.order_ref_snapshot,
                restaurant=restaurant,
                event_type=PaymentEvent.EventType.INITIATED, # Or a new type if desired
                amount=total,
            )

            # Record in immutable restaurant ledger
            from ordering.ledger.services import RestaurantLedgerService
            RestaurantLedgerService().record_post_payment(
                restaurant=restaurant,
                order=order,
                gross_amount=total,
                platform_fee=Decimal('0.00'),  # No fee currently for post-payment
            )
            
            # Re-assign back to original customer object to reflect new balance
            customer.balance = locked_customer.balance

    except IntegrityError:
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key, restaurant=restaurant).first()
            if existing:
                return existing
        raise

    dt_tx = time.time() - t1
    logger.info("Post-payment transaction took %.4fs", dt_tx)

    trigger_kds_refresh(restaurant.id)
    return order


def record_customer_payment(customer, amount, payment_method='Cash', description='', owner_user=None):
    """
    Record a manual payment from a customer.
    Decreases balance and creates LedgerEntry.
    """
    from ordering.models import LedgerEntry
    if amount <= Decimal('0.00'):
        raise ValueError("Payment amount must be positive.")

    with transaction.atomic():
        locked_customer = type(customer).objects.select_for_update().get(pk=customer.pk)
        
        locked_customer.balance -= amount
        locked_customer.save(update_fields=['balance'])
        
        entry = LedgerEntry.objects.create(
            restaurant=locked_customer.restaurant,
            customer=locked_customer,
            entry_type=LedgerEntry.EntryType.PAYMENT,
            amount=-amount,
            balance_after=locked_customer.balance,
            description=description or f"Payment ({payment_method})"
        )
        
        customer.balance = locked_customer.balance

        if owner_user:
            from core.models import OwnerAuditLog
            OwnerAuditLog.objects.create(
                restaurant=locked_customer.restaurant,
                user=owner_user,
                customer=customer,
                action=OwnerAuditLog.ActionType.MANUAL_PAYMENT,
                details={'amount': str(amount), 'payment_method': payment_method, 'description': description}
            )
        return entry


def create_razorpay_order(order):
    """
    Create a Razorpay order for the given platform order.
    Uses get_restaurant_payment_config() which now falls through to
    platform credentials when no per-restaurant config exists.
    """
    payment_config = get_restaurant_payment_config(order.restaurant)
    client = razorpay.Client(auth=(payment_config.razorpay_key_id, payment_config.get_razorpay_key_secret()))
    razorpay_order = client.order.create({
        'amount': int(order.total * 100),
        'currency': 'INR',
        'receipt': str(order.id),
        'notes': {
            'order_id': str(order.id),
            'restaurant': order.restaurant.name,
        }
    })
    order.razorpay_order_id = razorpay_order['id']
    order.save(update_fields=['razorpay_order_id'])
    return razorpay_order


def confirm_upi_payment(order, razorpay_payment_id):
    """
    Called by the Razorpay webhook on payment.captured.
    Confirms StockReservations, marks order PENDING, creates PlatformFeeRecord,
    and records canonical RestaurantLedger entries — all atomic.

    DEPRECATED: This is a legacy confirmation path. The canonical payment
    mutation path is PaymentMutationService.mark_paid() in
    ordering.payments.services. This function is kept for backward
    compatibility. If you see this deprecation warning in logs, the
    calling code should be migrated.
    """
    logger.warning(
        "DEPRECATED confirm_upi_payment called for order=%s rz_payment_id=%s — "
        "migrate caller to PaymentMutationService.mark_paid()",
        order.id, razorpay_payment_id,
    )
    with transaction.atomic():
        order = Order.objects.select_for_update().select_related('restaurant').get(pk=order.pk)

        if order.status != Order.Status.UNPAID:
            return order

        StockReservation.objects.select_for_update().filter(
            order=order, is_confirmed=False
        ).update(is_confirmed=True)

        now = timezone.now()
        order.status              = Order.Status.PENDING
        order.paid_at             = now
        order.razorpay_payment_id = razorpay_payment_id
        order.save(update_fields=['status', 'paid_at', 'razorpay_payment_id'])

        # Append-only audit
        PaymentEvent.objects.create(
            order               = order,
            order_ref           = order.order_ref_snapshot,
            restaurant          = order.restaurant,
            event_type          = PaymentEvent.EventType.RAZORPAY_CONFIRMED,
            amount              = order.total,
            razorpay_payment_id = razorpay_payment_id,
        )

        fee_amount = _create_fee_record(order, order.restaurant)

        if not order.ledger_records.filter(entry_type='CREDIT_ORDER').exists():
            from ordering.ledger.services import RestaurantLedgerService
            RestaurantLedgerService().record_payment(
                restaurant=order.restaurant,
                order=order,
                payment_transaction=None,
                gross_amount=order.total,
                platform_fee=fee_amount,
            )

    trigger_kds_refresh(order.restaurant.id)
    return order


def cancel_upi_payment(order, event_type):
    """
    Called by webhook on payment.failed, or by expiry cron.
    Releases StockReservations and cancels the order.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        if order.status not in (Order.Status.UNPAID,):
            return  # already handled

        reservations = list(
            StockReservation.objects.select_for_update().filter(
                order=order,
                is_confirmed=False,
            )
        )

        # Return stock for the held-but-unconfirmed reservations only.
        for res in reservations:
            if res.menu_item and res.menu_item.stock is not None:
                MenuItem.objects.filter(pk=res.menu_item_id).update(
                    stock=db_models.F('stock') + res.quantity
                )
                _restore_item_availability_after_stock_return(res.menu_item_id)
            if res.addon and res.addon.stock is not None:
                AddOn.objects.filter(pk=res.addon_id).update(
                    stock=db_models.F('stock') + res.quantity
                )
            res.is_confirmed = True
            res.save(update_fields=['is_confirmed'])

        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])

        PaymentEvent.objects.create(
            order      = order,
            order_ref  = order.order_ref_snapshot,
            restaurant = order.restaurant,
            event_type = event_type,
            amount     = order.total,
        )


def expire_unpaid_cash_order(order):
    """
    Cancel an unpaid cash order after the configured timeout and restore
    any finite stock that was held when the order was placed.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        if order.payment_method != Order.PaymentMethod.CASH:
            raise CartError('INVALID_PAYMENT_METHOD', 'Only cash orders can expire through this flow.')

        if order.status != Order.Status.UNPAID:
            return False

        _expire_unpaid_cash_order_locked(order)

    return True
