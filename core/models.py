# core/models.py
import uuid
from decimal import Decimal
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.db.models.signals import post_save
from django.dispatch import receiver
import bleach


def _clean(value):
    """Strip any HTML/JS from user-supplied text fields (SEC-09)."""
    return bleach.clean(value, tags=[], strip=True) if value else value


# ── Restaurant ───────────────────────────────────────────────────────────────

class Restaurant(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name       = models.CharField(max_length=200)
    slug       = models.SlugField(max_length=60, unique=True)
    logo       = models.TextField(blank=True)  # Supabase Storage public URL
    menu_qr_code_url = models.TextField(blank=True)  # Supabase Storage public URL
    is_active  = models.BooleanField(default=True)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Per-restaurant commission override (%). NULL = use PlatformSettings default.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def has_active_razorpay(self):
        """True if this restaurant can accept Razorpay payments — via own config OR platform credentials."""
        try:
            config = self.payment_config
        except RestaurantPaymentConfig.DoesNotExist:
            config = None
        if config and config.is_usable:
            return True
        # Fallback: platform-level credentials
        from django.conf import settings as app_settings
        return bool(app_settings.RAZORPAY_KEY_ID and app_settings.RAZORPAY_KEY_SECRET)

    def __str__(self):
        return self.name


class RestaurantConfig(models.Model):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant      = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name='config')
    is_open         = models.BooleanField(default=True)
    reopen_message  = models.CharField(max_length=300, blank=True)
    cash_enabled    = models.BooleanField(default=True)
    upi_enabled     = models.BooleanField(default=True)
    kds_prep_enabled = models.BooleanField(
        default=True,
        help_text='When off, tapping Start in the KDS marks items complete immediately — no separate preparing step.',
    )
    dpa_accepted_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.reopen_message = _clean(self.reopen_message)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Config: {self.restaurant.name}"


class RestaurantPaymentConfig(models.Model):
    class ConfigStatus(models.TextChoices):
        ACTIVE              = 'ACTIVE',              'Active'
        DISABLED            = 'DISABLED',            'Disabled'
        MIGRATED_TO_PLATFORM = 'MIGRATED_TO_PLATFORM', 'Migrated to Platform'

    id                      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant              = models.OneToOneField(
        Restaurant, on_delete=models.CASCADE, related_name='payment_config'
    )
    account_name            = models.CharField(max_length=120, blank=True)
    razorpay_key_id         = models.CharField(max_length=100, blank=True)
    razorpay_key_secret     = models.TextField(blank=True)
    razorpay_webhook_secret = models.TextField(blank=True)
    is_active               = models.BooleanField(default=False)
    config_status           = models.CharField(
        max_length=25, choices=ConfigStatus.choices, default=ConfigStatus.ACTIVE,
        help_text='Operational status. MIGRATED_TO_PLATFORM means this config is superseded by platform credentials.',
    )
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    @staticmethod
    def _plain_secret(value):
        if not value:
            return ''
        from ordering.payments.crypto import decrypt_text
        return decrypt_text(value) or value

    @classmethod
    def _stored_secret(cls, value):
        value = value or ''
        if not value:
            return ''
        from ordering.payments.crypto import decrypt_text, encrypt_text
        return value if decrypt_text(value) else encrypt_text(value)

    def get_razorpay_key_secret(self):
        return self._plain_secret(self.razorpay_key_secret)

    def set_razorpay_key_secret(self, secret):
        self.razorpay_key_secret = secret or ''

    def get_razorpay_webhook_secret(self):
        return self._plain_secret(self.razorpay_webhook_secret)

    def set_razorpay_webhook_secret(self, secret):
        self.razorpay_webhook_secret = secret or ''

    def save(self, *args, **kwargs):
        raw_key_secret = self.razorpay_key_secret
        raw_webhook_secret = self.razorpay_webhook_secret
        self.razorpay_key_secret = self._stored_secret(raw_key_secret)
        self.razorpay_webhook_secret = self._stored_secret(raw_webhook_secret)
        try:
            super().save(*args, **kwargs)
        finally:
            self.razorpay_key_secret = raw_key_secret
            self.razorpay_webhook_secret = raw_webhook_secret

    @property
    def is_usable(self):
        return bool(
            self.is_active
            and self.razorpay_key_id
            and self.get_razorpay_key_secret()
            and self.get_razorpay_webhook_secret()
        )

    @property
    def masked_key_id(self):
        if not self.razorpay_key_id:
            return ''
        return f"{self.razorpay_key_id[:8]}..."

    def __str__(self):
        label = self.account_name or self.restaurant.name
        status = 'active' if self.is_usable else 'inactive'
        return f"{label} Razorpay ({status})"


class PlatformSettings(models.Model):
    class FeeMode(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Percentage'
        FIXED = 'FIXED', 'Fixed per order'

    singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    cash_payment_timeout_minutes = models.PositiveIntegerField(
        default=10,
        help_text='Minutes before an unpaid cash order expires automatically.',
    )
    platform_fee_mode = models.CharField(
        max_length=20,
        choices=FeeMode.choices,
        default=FeeMode.PERCENTAGE,
        help_text='Choose whether platform fee is calculated as a percentage or fixed amount per order.',
    )
    platform_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('3.00'),
        help_text='Used when fee mode is Percentage.',
    )
    platform_fee_fixed_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text='Used when fee mode is Fixed per order.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform Settings'
        verbose_name_plural = 'Platform Settings'

    def save(self, *args, **kwargs):
        self.singleton_key = 1
        if self.cash_payment_timeout_minutes < 1:
            self.cash_payment_timeout_minutes = 1
        if self.platform_fee_percent < 0:
            self.platform_fee_percent = Decimal('0.00')
        if self.platform_fee_fixed_amount < 0:
            self.platform_fee_fixed_amount = Decimal('0.00')
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        settings_obj, _ = cls.objects.get_or_create(
            singleton_key=1,
            defaults={
                'cash_payment_timeout_minutes': 10,
                'platform_fee_mode': cls.FeeMode.PERCENTAGE,
                'platform_fee_percent': Decimal('3.00'),
                'platform_fee_fixed_amount': Decimal('0.00'),
            },
        )
        return settings_obj

    def __str__(self):
        return (
            f"Cash timeout: {self.cash_payment_timeout_minutes} min | "
            f"Fee mode: {self.platform_fee_mode}"
        )


@receiver(post_save, sender=Restaurant)
def create_restaurant_config(sender, instance, created, **kwargs):
    """Auto-create RestaurantConfig whenever a Restaurant is created (Django Admin or code)."""
    if created:
        if not hasattr(instance, 'config'):
            RestaurantConfig.objects.get_or_create(restaurant=instance)
        if not hasattr(instance, 'payment_config'):
            RestaurantPaymentConfig.objects.get_or_create(restaurant=instance)


# ── User ─────────────────────────────────────────────────────────────────────

class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        STAFF = 'STAFF', 'Staff'

    role                  = models.CharField(max_length=10, choices=Role.choices, default=Role.STAFF)
    restaurant            = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE,
        null=True, blank=True, related_name='users'
    )
    allow_cash_collection  = models.BooleanField(default=False)
    allow_view_all_orders  = models.BooleanField(default=False)
    allow_order_completion = models.BooleanField(default=False)
    must_change_password   = models.BooleanField(default=False)
    mfa_enabled            = models.BooleanField(default=True, help_text="Require Two-Factor Authentication for this user.")
    photo                  = models.TextField(blank=True)  # Supabase Storage URL (prefer signed URL if private later)


    class Meta:
        constraints = [
            # Case-insensitive unique username per restaurant (SEC-04)
            models.UniqueConstraint(
                Lower('username'), 'restaurant',
                name='unique_username_lower_per_restaurant'
            )
        ]

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    def __str__(self):
        return f"{self.username} ({self.restaurant})"


# ── Customer ─────────────────────────────────────────────────────────────────

class RestaurantCustomerCounter(models.Model):
    """SELECT FOR UPDATE on this row assigns the next customer serial number atomically."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant  = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name='customer_counter')
    last_number = models.IntegerField(default=0)


class Customer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='customers')
    serial_number = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    pin = models.CharField(max_length=128)  # Hashed via make_password
    must_change_pin = models.BooleanField(default=True)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_post_payment_enabled = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['restaurant', 'serial_number'], name='unique_customer_serial_per_restaurant')
        ]
        indexes = [
            models.Index(fields=['restaurant', 'phone']),
            models.Index(fields=['restaurant', 'is_blocked', 'is_post_payment_enabled']),
        ]

    def save(self, *args, **kwargs):
        self.name = _clean(self.name)
        self.phone = _clean(self.phone)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"CUST-{self.serial_number} {self.name}"



# ── Menu ─────────────────────────────────────────────────────────────────────

class ItemType(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='item_types')
    name       = models.CharField(max_length=100)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(fields=['restaurant', 'name'], name='unique_itemtype_per_restaurant')
        ]

    def save(self, *args, **kwargs):
        self.name = _clean(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name



class StaffFilter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(
        'Restaurant',
        on_delete=models.CASCADE,
        related_name='staff_filters',
    )
    name = models.CharField(max_length=100)
    items = models.ManyToManyField('MenuItem', related_name='staff_filters', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'), 'restaurant',
                name='unique_stafffilter_lower_per_restaurant',
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = _clean(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant       = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='menu_items')
    item_type        = models.ForeignKey(ItemType, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')

    name             = models.CharField(max_length=200)
    description      = models.TextField(blank=True)
    image            = models.TextField(blank=True)  # Supabase Storage public URL
    base_price       = models.DecimalField(max_digits=10, decimal_places=2)
    parcel_surcharge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_veg           = models.BooleanField(default=True)
    is_available     = models.BooleanField(default=True)
    auto_hidden_due_to_stock = models.BooleanField(default=False)
    stock            = models.PositiveIntegerField(null=True, blank=True)  # NULL = unlimited
    spice_configurable = models.BooleanField(default=False)
    sort_order       = models.IntegerField(default=0)
    # NOTE: is_special is NOT a DB column — it's computed via annotation or property below

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['restaurant', 'is_available']),
            models.Index(fields=['restaurant', 'item_type']),
        ]

    def save(self, *args, **kwargs):
        self.name        = _clean(self.name)
        self.description = _clean(self.description)
        super().save(*args, **kwargs)

    @property
    def is_special(self):
        """
        Fallback for single-instance use only.
        In list views always use the ORM annotation for N+1 safety:
            MenuItem.objects.annotate(
                has_addons=Exists(MenuItemAddOn.objects.filter(
                    menu_item=OuterRef('pk'), addon__is_active=True
                ))
            )
        """
        return self.menuitemaddon_set.filter(addon__is_active=True).exists()

    def __str__(self):
        return self.name


class AddOn(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='addons')

    name       = models.CharField(max_length=200)
    image      = models.TextField(blank=True)  # Supabase Storage public URL
    price      = models.DecimalField(max_digits=10, decimal_places=2)
    max_qty    = models.PositiveIntegerField(default=5)
    stock      = models.PositiveIntegerField(null=True, blank=True)  # NULL = unlimited
    is_active  = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.name = _clean(self.name)
        if self.max_qty > 99:
            self.max_qty = 99
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class MenuItemAddOn(models.Model):
    """M2M link between MenuItem and AddOn. Existence of a row with is_active addon = is_special badge."""
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    addon     = models.ForeignKey(AddOn, on_delete=models.PROTECT)  # PROTECT: can't delete addon while linked

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['menu_item', 'addon'], name='unique_menuitem_addon')
        ]

    def __str__(self):
        return f"{self.menu_item.name} + {self.addon.name}"


class PlatformFeeRecord(models.Model):
    """
    Append-only. One record per confirmed payment.
    fee_rate_snapshot is immutable after insert.
    is_refunded is retained for legacy/manual compatibility; runtime refund
    processing is not active in the current business model.
    All other fields: READ ONLY in application code and Django Admin.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_is_refunded = self.is_refunded

    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order             = models.ForeignKey(
        'ordering.Order', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='fee_records'
    )
    order_ref         = models.CharField(max_length=80)   # snapshot — survives order purge
    restaurant        = models.ForeignKey(
        Restaurant, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='fee_records'
    )
    order_total       = models.DecimalField(max_digits=10, decimal_places=2)
    fee_amount        = models.DecimalField(max_digits=10, decimal_places=2)
    fee_rate_snapshot = models.DecimalField(max_digits=5, decimal_places=2)  # immutable
    is_refunded       = models.BooleanField(default=False)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'is_refunded', 'created_at'], name='pfr_rest_refund_created_idx'),
            models.Index(fields=['created_at'], name='pfr_created_idx'),
        ]

    def __str__(self):
        return f"Fee {self.fee_amount} for {self.order_ref}"


# ── Owner Audit Logs ─────────────────────────────────────────────────────────

class OwnerAuditLog(models.Model):
    class ActionType(models.TextChoices):
        CREATE_CUSTOMER = 'CREATE_CUSTOMER', 'Create Customer'
        EDIT_CUSTOMER   = 'EDIT_CUSTOMER',   'Edit Customer'
        RESET_PIN       = 'RESET_PIN',       'Reset PIN'
        MANUAL_PAYMENT  = 'MANUAL_PAYMENT',  'Manual Payment'
        CREATE_STAFF    = 'CREATE_STAFF',    'Create Staff'
        EDIT_STAFF      = 'EDIT_STAFF',      'Edit Staff'
        DELETE_STAFF    = 'DELETE_STAFF',    'Delete Staff'
        RESET_STAFF_PASSWORD = 'RESET_STAFF_PASSWORD', 'Reset Staff Password'
        TOGGLE_STAFF_PERMISSION = 'TOGGLE_STAFF_PERMISSION', 'Toggle Staff Permission'
        UPDATE_RESTAURANT_CONFIG = 'UPDATE_RESTAURANT_CONFIG', 'Update Restaurant Config'
        UPDATE_PAYMENT_CONFIG = 'UPDATE_PAYMENT_CONFIG', 'Update Payment Config'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='owner_audit_logs')
    user = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    customer = models.ForeignKey('core.Customer', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50, choices=ActionType.choices)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'created_at']),
            models.Index(fields=['customer', 'created_at']),
        ]

    def __str__(self):
        return f"{self.action} by {self.user} on {self.customer}"


# ── Billing ──────────────────────────────────────────────────────────────────

class MonthlyPlatformFeeStatement(models.Model):
    """
    Consolidated monthly platform fee records for each restaurant.
    Allows platform admin to track monthly performance and payment status.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='monthly_statements'
    )
    
    # Month represented by the first day of that month
    month_date = models.DateField(help_text="The first day of the month this statement covers.")
    
    total_orders_count = models.PositiveIntegerField(default=0)
    total_revenue      = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_fee_amount   = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-month_date', 'restaurant']
        constraints = [
            models.UniqueConstraint(
                fields=['restaurant', 'month_date'], 
                name='unique_monthly_statement_per_restaurant'
            )
        ]

    def __str__(self):
        return f"{self.restaurant.name} - {self.month_date.strftime('%B %Y')}"


# ── Signals ──────────────────────────────────────────────────────────────────

@receiver(post_save, sender=PlatformFeeRecord)
def update_monthly_statement_on_fee_save(sender, instance, created, **kwargs):
    """
    Automatically update or create the MonthlyPlatformFeeStatement when a PlatformFeeRecord is saved.
    Handles new records and explicit False -> True refund transitions.
    """
    from django.db.models import F

    month_start = instance.created_at.date().replace(day=1)
    statement, _ = MonthlyPlatformFeeStatement.objects.get_or_create(
        restaurant=instance.restaurant,
        month_date=month_start
    )

    if created:
        statement.total_orders_count = F('total_orders_count') + 1
        statement.total_revenue      = F('total_revenue') + instance.order_total
        statement.total_fee_amount   = F('total_fee_amount') + instance.fee_amount
        statement.save(update_fields=['total_orders_count', 'total_revenue', 'total_fee_amount'])
        instance._original_is_refunded = instance.is_refunded
    else:
        # Explicit False -> True transition tracking
        if not getattr(instance, '_original_is_refunded', False) and instance.is_refunded:
            statement.total_orders_count = F('total_orders_count') - 1
            statement.total_revenue      = F('total_revenue') - instance.order_total
            statement.total_fee_amount   = F('total_fee_amount') - instance.fee_amount
            statement.save(update_fields=['total_orders_count', 'total_revenue', 'total_fee_amount'])
            instance._original_is_refunded = True

            from core.ledger import LedgerService
            LedgerService.record_refund(
                order=instance.order,
                amount=instance.order_total,
                fee_refunded=instance.fee_amount
            )

# ── Ledger & Settlements ──────────────────────────────────────────────────────

class MerchantLedgerBalance(models.Model):
    restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name='balance')
    available_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    pending_settlement = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.restaurant.name} Balance: {self.available_balance}"

class JournalEntry(models.Model):
    class EntryType(models.TextChoices):
        PAYMENT_CAPTURED = 'PAYMENT_CAPTURED', 'Payment Captured'
        PLATFORM_FEE = 'PLATFORM_FEE', 'Platform Fee'
        REFUND = 'REFUND', 'Refund'
        SETTLEMENT = 'SETTLEMENT', 'Settlement'
        MANUAL_ADJUSTMENT = 'MANUAL_ADJUSTMENT', 'Manual Adjustment'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, null=True, blank=True, related_name='journal_entries')
    reference_id = models.CharField(max_length=255, help_text='External reference, e.g. Order ID or Settlement ID')
    entry_type = models.CharField(max_length=50, choices=EntryType.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'created_at']),
            models.Index(fields=['reference_id']),
        ]

    def __str__(self):
        return f"{self.entry_type} for {self.restaurant} - {self.reference_id}"

class JournalLine(models.Model):
    class AccountType(models.TextChoices):
        ASSET_CASH_IN_TRANSIT = 'ASSET_CASH_IN_TRANSIT', 'Asset: Cash in Transit'
        REVENUE_PLATFORM_FEE = 'REVENUE_PLATFORM_FEE', 'Revenue: Platform Fee'
        LIABILITY_MERCHANT_BALANCE = 'LIABILITY_MERCHANT_BALANCE', 'Liability: Merchant Balance'
        LIABILITY_SETTLEMENT_PAYABLE = 'LIABILITY_SETTLEMENT_PAYABLE', 'Liability: Settlement Payable'
        EXPENSE_REFUND = 'EXPENSE_REFUND', 'Expense: Refund'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    account_type = models.CharField(max_length=50, choices=AccountType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text='Positive for Debit, Negative for Credit')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account_type}: {self.amount}"

class SettlementBatch(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSED = 'PROCESSED', 'Processed'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Batch {self.id} - {self.status}"

class SettlementRecord(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PAID = 'PAID', 'Paid'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(SettlementBatch, on_delete=models.CASCADE, related_name='records')
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='core_settlements')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_transfer_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settlement {self.id} for {self.restaurant} - {self.amount}"
