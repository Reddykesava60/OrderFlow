
from core.models import MenuItem, AddOn
from ordering.models import StockReservation, LedgerEntry
from ordering.exceptions import CartError
from ordering.ledger.services import RestaurantLedgerService

from core.ledger import LedgerService

import time
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, models as db_models
from django.utils import timezone

from core.models import PlatformFeeRecord, Restaurant
from ordering.models import Order, OrderItem, OrderItemAddOn, RestaurantOrderCounter, WorkStatus
from kitchen.models import PaymentEvent
from kitchen.services import trigger_kds_refresh
from ordering.signals import order_paid, order_cancelled


logger = logging.getLogger(__name__)
TWO_PLACES = Decimal('0.01')


def _compute_platform_fee(order_total, restaurant=None):
    """
    Compute platform fee according to restaurant settings policy.
    Returns (fee_amount, fee_rate_snapshot).
    """
    if not restaurant:
        return (Decimal('0.00'), Decimal('0.00'))

    mode = restaurant.fee_mode
    percent = restaurant.fee_percent
    fixed = restaurant.fee_fixed_amount

    if mode == Restaurant.FeeMode.FIXED:
        fee_amount = Decimal(fixed).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if order_total > Decimal('0.00'):
            fee_rate_snapshot = (fee_amount * Decimal('100') / order_total).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            fee_rate_snapshot = Decimal('0.00')
        return (fee_amount, fee_rate_snapshot)
    
    if mode == Restaurant.FeeMode.HYBRID:
        fixed_part = Decimal(fixed)
        percent_rate = Decimal(percent)
        fee_amount = ((order_total * percent_rate / Decimal('100')) + fixed_part).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        if order_total > Decimal('0.00'):
            fee_rate_snapshot = (fee_amount * Decimal('100') / order_total).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        else:
            fee_rate_snapshot = Decimal('0.00')
        return (fee_amount, fee_rate_snapshot)
        
    # PERCENTAGE mode (default)
    fee_rate = Decimal(percent)
    fee_amount = (order_total * fee_rate / Decimal('100')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return (fee_amount, fee_rate)

def _next_order_number(restaurant):
    """
    Assign sequential order number per restaurant per day.
    Uses SELECT FOR UPDATE — must be called inside transaction.atomic().
    Resets to 1 each calendar day (IST).
    """
    today = timezone.localdate()
    counter, _ = RestaurantOrderCounter.objects.select_for_update().get_or_create(restaurant=restaurant, defaults={'last_number': 0, 'last_reset': today})
    if counter.last_reset != today:
        counter.last_number = 0
        counter.last_reset = today
    counter.last_number += 1
    counter.save(update_fields=['last_number', 'last_reset'])
    return counter.last_number

def get_cash_payment_timeout_minutes(restaurant):
    return restaurant.config.cash_payment_timeout_minutes

def _expire_unpaid_cash_order_locked(order):
    """
    Expire a locked unpaid cash order and restore finite stock.
    Caller must hold a select_for_update() lock on the order row.
    """
    order_items = list(OrderItem.objects.select_related('menu_item').filter(order=order))
    order_addons = list(OrderItemAddOn.objects.select_related('addon').filter(order_item__order=order))
    for item in order_items:
        if item.menu_item_id and item.menu_item and item.menu_item.stock is not None:
            MenuItem.objects.filter(pk=item.menu_item_id).update(
                stock=db_models.F('stock') + item.quantity
            )

    from ordering.signals import inventory_released
    inventory_released.send(sender=Order, order=order)
    for addon in order_addons:
        if addon.addon_id and addon.addon and (addon.addon.stock is not None):
            AddOn.objects.filter(pk=addon.addon_id).update(stock=db_models.F('stock') + addon.quantity)
    order.status = Order.Status.CANCELLED
    order.save(update_fields=['status'])
    PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=order.restaurant, event_type=PaymentEvent.EventType.PAYMENT_TIMEOUT, amount=order.total)

def expire_overdue_unpaid_cash_orders(restaurant=None):
    """
    Expire all unpaid cash orders older than the platform timeout.
    Optionally scope to a single restaurant.
    Returns number of orders expired.
    """
    overdue_orders_query = Order.objects.filter(payment_method=Order.PaymentMethod.CASH, status=Order.Status.UNPAID).select_related('restaurant', 'restaurant__config').order_by('created_at')
    if restaurant is not None:
        overdue_orders_query = overdue_orders_query.filter(restaurant=restaurant)
        
    expired_count = 0
    now = timezone.now()
    for order in overdue_orders_query:
        timeout = get_cash_payment_timeout_minutes(order.restaurant)
        if order.created_at < now - timezone.timedelta(minutes=timeout):
            try:
                if expire_unpaid_cash_order(order):
                    expired_count += 1
            except Exception:
                logger.exception('Error expiring overdue cash order %s', order.pk)
    return expired_count

def sync_order_status(order):
    """
    Recompute the order's summary status from item/add-on work states.
    The order must already be paid before this is called.

    Uses 2 aggregate queries instead of 4 individual EXISTS calls.
    """
    if order.status in (Order.Status.UNPAID, Order.Status.CANCELLED):
        return order
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        # ── 2 queries instead of 4: fetch distinct statuses per table ──
        item_statuses = set(
            OrderItem.objects
            .filter(order=order, prep_status__in=[WorkStatus.PENDING, WorkStatus.PREPARING])
            .values_list('prep_status', flat=True)
            .distinct()
        )
        addon_statuses = set(
            OrderItemAddOn.objects
            .filter(order_item__order=order, prep_status__in=[WorkStatus.PENDING, WorkStatus.PREPARING])
            .values_list('prep_status', flat=True)
            .distinct()
        )
        all_statuses = item_statuses | addon_statuses
        pending_exists = WorkStatus.PENDING in all_statuses
        preparing_exists = WorkStatus.PREPARING in all_statuses

        now = timezone.now()
        update_fields = []
        if not pending_exists and (not preparing_exists):
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

    from ordering.signals import order_paid
    order_paid.send(sender=Order, order=order, fee_amount=fee_amount)

    return fee_amount

def confirm_cash_payment(order, staff_user):
    """
    Counter staff taps 'Collect Cash & Confirm'.
    UNPAID → PENDING + PaymentEvent(CASH_COLLECTED) + PlatformFeeRecord — all atomic.
    Returns (order, fee_amount).
    """
    timeout_minutes = get_cash_payment_timeout_minutes(order.restaurant)
    timeout_cutoff = timezone.now() - timezone.timedelta(minutes=timeout_minutes)
    if order.created_at < timeout_cutoff:
        expire_unpaid_cash_order(order)
        raise CartError('PAYMENT_TIMEOUT', 'This cash order has expired.')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.UNPAID:
            raise CartError('ALREADY_PAID', 'This order has already been paid.')
        order.status = Order.Status.PENDING
        order.paid_at = timezone.now()
        order.save(update_fields=['status', 'paid_at'])
        PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=order.restaurant, event_type=PaymentEvent.EventType.CASH_COLLECTED, amount=order.total, staff_user=staff_user)
        fee_amount = _create_fee_record(order, order.restaurant)
        from ordering.ledger.services import RestaurantLedgerService
        RestaurantLedgerService().record_cash_payment(restaurant=order.restaurant, order=order, gross_amount=order.total, platform_fee=fee_amount)
    return (order, fee_amount)

def record_customer_payment(customer, amount, payment_method='Cash', description='', owner_user=None):
    """
    Record a manual payment from a customer.
    Decreases balance and creates LedgerEntry.
    """
    from ordering.models import LedgerEntry
    if amount <= Decimal('0.00'):
        raise ValueError('Payment amount must be positive.')
    with transaction.atomic():
        locked_customer = type(customer).objects.select_for_update().get(pk=customer.pk)
        locked_customer.balance -= amount
        locked_customer.save(update_fields=['balance'])
        entry = LedgerEntry.objects.create(restaurant=locked_customer.restaurant, customer=locked_customer, entry_type=LedgerEntry.EntryType.PAYMENT, amount=-amount, balance_after=locked_customer.balance, description=description or f'Payment ({payment_method})')
        customer.balance = locked_customer.balance
        if owner_user:
            from core.models import OwnerAuditLog
            OwnerAuditLog.objects.create(restaurant=locked_customer.restaurant, user=owner_user, customer=customer, action=OwnerAuditLog.ActionType.MANUAL_PAYMENT, details={'amount': str(amount), 'payment_method': payment_method, 'description': description})
        return entry

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
    logger.warning('DEPRECATED confirm_upi_payment called for order=%s rz_payment_id=%s — migrate caller to PaymentMutationService.mark_paid()', order.id, razorpay_payment_id)
    with transaction.atomic():
        order = Order.objects.select_for_update().select_related('restaurant').get(pk=order.pk)
        if order.status != Order.Status.UNPAID:
            return order
        StockReservation.objects.select_for_update().filter(order=order, is_confirmed=False).update(is_confirmed=True)
        now = timezone.now()
        order.status = Order.Status.PENDING
        order.paid_at = now
        order.razorpay_payment_id = razorpay_payment_id
        order.save(update_fields=['status', 'paid_at', 'razorpay_payment_id'])
        PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=order.restaurant, event_type=PaymentEvent.EventType.RAZORPAY_CONFIRMED, amount=order.total, razorpay_payment_id=razorpay_payment_id)
        fee_amount = _create_fee_record(order, order.restaurant)
        if not order.ledger_records.filter(entry_type='CREDIT_ORDER').exists():
            from ordering.ledger.services import RestaurantLedgerService
            RestaurantLedgerService().record_payment(restaurant=order.restaurant, order=order, payment_transaction=None, gross_amount=order.total, platform_fee=fee_amount)
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
            return
        reservations = list(StockReservation.objects.select_for_update().filter(order=order, is_confirmed=False))
        for res in reservations:
            if res.menu_item and res.menu_item.stock is not None:
                MenuItem.objects.filter(pk=res.menu_item_id).update(stock=db_models.F('stock') + res.quantity)
            if res.addon and res.addon.stock is not None:
                AddOn.objects.filter(pk=res.addon_id).update(stock=db_models.F('stock') + res.quantity)
            res.is_confirmed = True
            res.save(update_fields=['is_confirmed'])

        from ordering.signals import inventory_released
        inventory_released.send(sender=Order, order=order)
        order.status = Order.Status.CANCELLED
        order.save(update_fields=['status'])
        PaymentEvent.objects.create(order=order, order_ref=order.order_ref_snapshot, restaurant=order.restaurant, event_type=event_type, amount=order.total)

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