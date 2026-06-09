from django.db import models
from shared.models import DomainModel

class ItemType(DomainModel):
    restaurant_id = models.UUIDField()
    name = models.CharField(max_length=100)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'catalog_item_type'
        ordering = ['sort_order', 'name']

class MenuItem(DomainModel):
    restaurant_id = models.UUIDField()
    item_type = models.ForeignKey(ItemType, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image_url = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=12, decimal_places=4)
    parcel_surcharge = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    is_veg = models.BooleanField(default=True)
    is_available = models.BooleanField(default=True)
    auto_hidden_due_to_stock = models.BooleanField(default=False)
    spice_configurable = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = 'catalog_menu_item'
        ordering = ['sort_order', 'name']

class AddOn(DomainModel):
    restaurant_id = models.UUIDField()
    name = models.CharField(max_length=200)
    image_url = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=4)
    max_qty = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'catalog_addon'

class MenuItemAddOn(DomainModel):
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='addons')
    addon = models.ForeignKey(AddOn, on_delete=models.PROTECT)

    class Meta:
        db_table = 'catalog_menu_item_addon'
        constraints = [
            models.UniqueConstraint(fields=['menu_item', 'addon'], name='unique_catalog_menu_item_addon')
        ]

class InventoryLedger(DomainModel):
    """
    Append-only inventory sourcing to replace the simple integer stock.
    """
    class TransactionType(models.TextChoices):
        INITIAL = 'INITIAL', 'Initial Stock'
        RESERVATION = 'RESERVATION', 'Stock Reserved'
        RELEASE = 'RELEASE', 'Reservation Released'
        CONSUMPTION = 'CONSUMPTION', 'Stock Consumed (Paid)'
        MANUAL_ADJUSTMENT = 'MANUAL_ADJUSTMENT', 'Manual Adjustment'

    restaurant_id = models.UUIDField()
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, null=True, blank=True)
    addon = models.ForeignKey(AddOn, on_delete=models.CASCADE, null=True, blank=True)
    
    transaction_type = models.CharField(max_length=50, choices=TransactionType.choices)
    quantity_change = models.IntegerField(help_text="Positive for additions, negative for consumption/reservations")
    reference_id = models.UUIDField(null=True, blank=True, help_text="e.g. Order ID or Reservation ID")

    class Meta:
        db_table = 'catalog_inventory_ledger'
