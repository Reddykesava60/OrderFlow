import logging
from django.db import transaction, models as db_models
from core.models import MenuItem, AddOn
from ordering.models import StockReservation
from django.utils import timezone

logger = logging.getLogger(__name__)

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

def _lock_and_decrement_stock(priced_lines):
    """
    Lock the specific items/addons and decrement their stock.
    Must be called inside transaction.atomic().
    """
    from ordering.exceptions import CartError
    
    item_ids_with_stock = [
        line['menu_item'].id for line in priced_lines 
        if line['menu_item'].stock is not None
    ]
    addon_ids_with_stock = [
        addon_line['addon'].id for line in priced_lines 
        for addon_line in line['addons'] if addon_line['addon'].stock is not None
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
                content_object=item,
                quantity=line['quantity'],
                expires_at=expires_at
            ))
        for addon_line in line['addons']:
            addon = addon_line['addon']
            if addon.stock is not None:
                reservations.append(StockReservation(
                    order=order,
                    content_object=addon,
                    quantity=addon_line['quantity'],
                    expires_at=expires_at
                ))
    if reservations:
        StockReservation.objects.bulk_create(reservations)
