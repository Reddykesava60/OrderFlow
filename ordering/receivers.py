from django.dispatch import receiver
from ordering.signals import order_paid, inventory_released
from core.ledger import LedgerService
from ordering.inventory.services import _restore_item_availability_after_stock_return

@receiver(order_paid)
def handle_order_paid(sender, order, fee_amount, **kwargs):
    # Fire the ledger record!
    LedgerService.record_payment_capture(
        order=order,
        gross_amount=order.total,
        fee_amount=fee_amount,
        reference_id=f"PAYMENT_ORDER_{order.id}"
    )

@receiver(inventory_released)
def handle_inventory_released(sender, order, **kwargs):
    # In `_expire_unpaid_cash_order_locked` or `cancel_upi_payment`
    # the caller restores the finite stock on MenuItem/AddOn.
    # The signal allows us to auto-restore visibility if needed!
    from ordering.models import OrderItem
    order_items = list(OrderItem.objects.select_related('menu_item').filter(order=order))
    for item in order_items:
        if item.menu_item_id and item.menu_item and item.menu_item.stock is not None:
            _restore_item_availability_after_stock_return(item.menu_item_id)
