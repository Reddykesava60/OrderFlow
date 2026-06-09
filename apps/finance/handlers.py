from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from apps.payments.use_cases import OrderPaidEvent
from apps.sales.models import Order
from apps.operations.models import PlatformSettings, Restaurant
from .models import LedgerEntry

def handle_order_paid(event: OrderPaidEvent):
    """
    Creates double-entry ledger records for revenue and platform fees.
    """
    order = Order.objects.filter(id=event.order_id).first()
    if not order:
        return

    # To avoid duplicate entries if the webhook fires twice
    if LedgerEntry.objects.filter(order_id=order.id, entry_type=LedgerEntry.EntryType.CREDIT_ORDER).exists():
        return

    with transaction.atomic():
        restaurant = Restaurant.objects.filter(id=order.restaurant_id).first()
        if not restaurant:
            return
        
        settings = PlatformSettings.get_solo()
        
        # Calculate Platform Fee
        platform_fee = Decimal('0.0000')
        if settings.platform_fee_mode == PlatformSettings.FeeMode.PERCENTAGE:
            rate = restaurant.commission_rate if restaurant.commission_rate is not None else settings.platform_fee_percent
            platform_fee = order.total_amount * (rate / Decimal('100'))
        else:
            platform_fee = settings.platform_fee_fixed_amount

        # Calculate current balance safely (requires locking the restaurant or a dummy row in real systems, 
        # but here we aggregate the append-only ledger)
        current_balance = LedgerEntry.objects.filter(restaurant_id=order.restaurant_id).aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.0000')

        # 1. Credit Order Revenue
        balance_after_revenue = current_balance + order.total_amount
        LedgerEntry.objects.create(
            restaurant_id=order.restaurant_id,
            order_id=order.id,
            entry_type=LedgerEntry.EntryType.CREDIT_ORDER,
            amount=order.total_amount,
            balance_after=balance_after_revenue,
            reference=f"Order {order.order_number}"
        )

        # 2. Debit Platform Fee
        if platform_fee > 0:
            balance_after_fee = balance_after_revenue - platform_fee
            LedgerEntry.objects.create(
                restaurant_id=order.restaurant_id,
                order_id=order.id,
                entry_type=LedgerEntry.EntryType.DEBIT_PLATFORM_FEE,
                amount=-platform_fee,
                balance_after=balance_after_fee,
                reference=f"Platform Fee for Order {order.order_number}"
            )
