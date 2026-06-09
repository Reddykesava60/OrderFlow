from uuid import UUID
from django.db import transaction
from django.db.models import Sum
from .models import MenuItem, AddOn, InventoryLedger

class InsufficientStockError(Exception):
    pass

class ItemNotFoundError(Exception):
    pass

class CatalogService:
    @staticmethod
    def get_menu_item(menu_item_id: UUID, restaurant_id: UUID) -> MenuItem:
        try:
            return MenuItem.objects.get(id=menu_item_id, restaurant_id=restaurant_id, is_available=True)
        except MenuItem.DoesNotExist:
            raise ItemNotFoundError(f"Menu item {menu_item_id} not found or unavailable")

    @staticmethod
    def get_addon(addon_id: UUID, restaurant_id: UUID) -> AddOn:
        try:
            return AddOn.objects.get(id=addon_id, restaurant_id=restaurant_id, is_active=True)
        except AddOn.DoesNotExist:
            raise ItemNotFoundError(f"Addon {addon_id} not found or inactive")

    @staticmethod
    def reserve_stock(menu_item_id: UUID, quantity: int, reference_id: UUID):
        """
        Reserves stock by appending a reservation to the ledger.
        In a real scenario, this must lock the aggregate to prevent overselling.
        """
        # Lock to compute current stock safely
        # Note: A strict modular monolith would lock at the row level. For greenfield,
        # we can lock the MenuItem to serialize ledger inserts for this item.
        item = MenuItem.objects.select_for_update().get(id=menu_item_id)
        
        current_stock = InventoryLedger.objects.filter(menu_item=item).aggregate(
            total=Sum('quantity_change')
        )['total'] or 0

        if current_stock < quantity:
            raise InsufficientStockError(f"Insufficient stock for {item.name}. Available: {current_stock}")

        InventoryLedger.objects.create(
            restaurant_id=item.restaurant_id,
            menu_item=item,
            transaction_type=InventoryLedger.TransactionType.RESERVATION,
            quantity_change=-quantity,
            reference_id=reference_id
        )

    @staticmethod
    def release_stock(menu_item_id: UUID, quantity: int, reference_id: UUID):
        item = MenuItem.objects.get(id=menu_item_id)
        InventoryLedger.objects.create(
            restaurant_id=item.restaurant_id,
            menu_item=item,
            transaction_type=InventoryLedger.TransactionType.RELEASE,
            quantity_change=quantity,
            reference_id=reference_id
        )
