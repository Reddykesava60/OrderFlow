from django.db import models
from shared.models import DomainModel

class OrderCounter(DomainModel):
    restaurant_id = models.UUIDField()
    last_number = models.IntegerField(default=0)
    last_reset = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'sales_order_counter'

class Order(DomainModel):
    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UPI = 'UPI', 'UPI'
        POST_PAYMENT = 'POST_PAYMENT', 'Post Payment'

    class Status(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PENDING = 'PENDING', 'Pending'
        PREP_STARTED = 'PREP_STARTED', 'Prep Started'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    restaurant_id = models.UUIDField()
    customer_id = models.UUIDField(null=True, blank=True)
    
    order_number = models.IntegerField()
    customer_name = models.CharField(max_length=200)
    table_number = models.CharField(max_length=20, blank=True)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.UNPAID)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=4)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)
    
    paid_at = models.DateTimeField(null=True, blank=True)
    prep_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'sales_order'

class OrderItem(DomainModel):
    class DiningOption(models.TextChoices):
        DINE_IN = 'DINE_IN', 'Dine In'
        PARCEL = 'PARCEL', 'Parcel'

    class SpiceLevel(models.TextChoices):
        MILD = 'MILD', 'Mild'
        MEDIUM = 'MEDIUM', 'Medium'
        HOT = 'HOT', 'Hot'

    class PrepStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PREPARING = 'PREPARING', 'Preparing'
        COMPLETED = 'COMPLETED', 'Completed'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item_id = models.UUIDField(null=True, blank=True)
    
    # Snapshots
    menu_item_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=12, decimal_places=4)
    parcel_surcharge = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    
    quantity = models.PositiveIntegerField()
    dining_option = models.CharField(max_length=10, choices=DiningOption.choices)
    spice_level = models.CharField(max_length=10, choices=SpiceLevel.choices, blank=True)
    
    prep_status = models.CharField(max_length=12, choices=PrepStatus.choices, default=PrepStatus.PENDING)

    class Meta:
        db_table = 'sales_order_item'

class OrderItemAddOn(DomainModel):
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='addons')
    addon_id = models.UUIDField(null=True, blank=True)
    
    addon_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=12, decimal_places=4)
    quantity = models.PositiveIntegerField()
    
    prep_status = models.CharField(max_length=12, choices=OrderItem.PrepStatus.choices, default=OrderItem.PrepStatus.PENDING)

    class Meta:
        db_table = 'sales_order_item_addon'
