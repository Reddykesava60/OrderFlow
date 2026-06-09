from django.db import models
from shared.models import DomainModel

class CustomerCounter(DomainModel):
    restaurant_id = models.UUIDField()
    last_number = models.IntegerField(default=0)

    class Meta:
        db_table = 'customers_counter'

class Customer(DomainModel):
    restaurant_id = models.UUIDField()
    serial_number = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    pin_hash = models.CharField(max_length=128)
    must_change_pin = models.BooleanField(default=True)
    balance = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    is_post_payment_enabled = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)

    class Meta:
        db_table = 'customers_customer'
        constraints = [
            models.UniqueConstraint(fields=['restaurant_id', 'serial_number'], name='unique_customer_serial')
        ]
