from django.db import models
from shared.models import DomainModel

class Restaurant(DomainModel):
    """
    Core Tenant Model.
    """
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=60, unique=True)
    logo_url = models.TextField(blank=True)
    menu_qr_code_url = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    # Financial config specific to operations
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Per-restaurant commission override (%).'
    )

    class Meta:
        db_table = 'operations_restaurant'

    def __str__(self):
        return self.name

class RestaurantConfig(DomainModel):
    restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name='config')
    is_open = models.BooleanField(default=True)
    reopen_message = models.CharField(max_length=300, blank=True)
    cash_enabled = models.BooleanField(default=True)
    upi_enabled = models.BooleanField(default=True)
    dpa_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'operations_restaurant_config'

class PlatformSettings(DomainModel):
    class FeeMode(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Percentage'
        FIXED = 'FIXED', 'Fixed per order'

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    cash_payment_timeout_minutes = models.PositiveIntegerField(default=10)
    platform_fee_mode = models.CharField(
        max_length=20, choices=FeeMode.choices, default=FeeMode.PERCENTAGE
    )
    platform_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=3.00)
    platform_fee_fixed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'operations_platform_settings'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(singleton_key=1)
        return obj
