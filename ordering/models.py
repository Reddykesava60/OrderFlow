# ordering/models.py
import uuid
from decimal import Decimal
from django.db import models
from django.utils import timezone
from core.models import Restaurant, MenuItem, AddOn


class WorkStatus(models.TextChoices):
    PENDING   = 'PENDING', 'Pending'
    PREPARING = 'PREPARING', 'Preparing'
    COMPLETED = 'COMPLETED', 'Completed'


class RestaurantOrderCounter(models.Model):
    """SELECT FOR UPDATE on this row assigns the next order number atomically."""
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant  = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name='order_counter')
    last_number = models.IntegerField(default=0)
    last_reset  = models.DateField(null=True, blank=True)


class Order(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Cash'
        UPI  = 'UPI',  'UPI'
        POST_PAYMENT = 'POST_PAYMENT', 'Post Payment'

    class Status(models.TextChoices):
        UNPAID      = 'UNPAID',       'Unpaid'
        PENDING     = 'PENDING',      'Pending'
        PREP_STARTED = 'PREP_STARTED','Prep Started'
        COMPLETED   = 'COMPLETED',    'Completed'
        CANCELLED   = 'CANCELLED',    'Cancelled'

    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant          = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='orders')
    order_number        = models.IntegerField()
    customer_name       = models.CharField(max_length=200)
    table_number        = models.CharField(max_length=20, blank=True)
    payment_method      = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status              = models.CharField(max_length=15, choices=Status.choices, default=Status.UNPAID)
    total               = models.DecimalField(max_digits=10, decimal_places=2)  # server-computed, never from client
    customer            = models.ForeignKey('core.Customer', on_delete=models.PROTECT, null=True, blank=True, related_name='orders')
    idempotency_key     = models.UUIDField(null=True, blank=True, unique=True)
    consent_given       = models.BooleanField(default=False)
    razorpay_order_id   = models.CharField(max_length=100, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    paid_at             = models.DateTimeField(null=True, blank=True)
    prep_started_at     = models.DateTimeField(null=True, blank=True)
    completed_at        = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['restaurant', 'status']),
            models.Index(fields=['restaurant', 'created_at']),
            models.Index(fields=['restaurant', 'status', 'created_at'], name='ord_rest_status_created_idx'),
            models.Index(fields=['restaurant', 'payment_method', 'status', 'created_at'], name='ord_rest_pay_status_idx'),
        ]

    @property
    def order_ref_snapshot(self):
        """Human-readable reference that survives nightly order purge."""
        return f"#{self.order_number} {self.created_at.date()} {self.restaurant.slug}"

    def __str__(self):
        return f"Order #{self.order_number} — {self.restaurant.name}"


class OrderItem(models.Model):
    class DiningOption(models.TextChoices):
        DINE_IN = 'DINE_IN', 'Dine In'
        PARCEL  = 'PARCEL',  'Parcel'

    class SpiceLevel(models.TextChoices):
        MILD   = 'MILD',   'Mild'
        MEDIUM = 'MEDIUM', 'Medium'
        HOT    = 'HOT',    'Hot'

    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order            = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item        = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    # ── Snapshots (captured at checkout — never change) ──────────────────────
    menu_item_name   = models.CharField(max_length=200)
    unit_price       = models.DecimalField(max_digits=10, decimal_places=2)
    parcel_surcharge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    # ─────────────────────────────────────────────────────────────────────────
    quantity         = models.PositiveIntegerField()
    dining_option    = models.CharField(max_length=10, choices=DiningOption.choices)
    spice_level      = models.CharField(max_length=10, choices=SpiceLevel.choices, blank=True)
    prep_status      = models.CharField(max_length=12, choices=WorkStatus.choices, default=WorkStatus.PENDING)
    prep_started_at  = models.DateTimeField(null=True, blank=True)
    prep_started_by  = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='started_order_items'
    )
    completed_at     = models.DateTimeField(null=True, blank=True)
    completed_by     = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_order_items'
    )

    def line_total(self):
        surcharge = self.parcel_surcharge if self.dining_option == self.DiningOption.PARCEL else Decimal('0.00')
        return (self.unit_price + surcharge) * self.quantity


class OrderItemAddOn(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name='addons')
    addon      = models.ForeignKey(AddOn, on_delete=models.SET_NULL, null=True, blank=True)
    # Snapshots
    addon_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity   = models.PositiveIntegerField()
    prep_status = models.CharField(max_length=12, choices=WorkStatus.choices, default=WorkStatus.PENDING)
    prep_started_at = models.DateTimeField(null=True, blank=True)
    prep_started_by = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='started_order_item_addons'
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        'core.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_order_item_addons'
    )

    def line_total(self):
        return self.unit_price * self.quantity


class StockReservation(models.Model):
    """
    Holds stock between Razorpay checkout creation and webhook confirmation.
    If webhook never arrives, the 30-min cron releases this and cancels the order.
    """
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order        = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='stock_reservations')
    menu_item    = models.ForeignKey(MenuItem, on_delete=models.SET_NULL, null=True, blank=True)
    addon        = models.ForeignKey(AddOn,     on_delete=models.SET_NULL, null=True, blank=True)
    quantity     = models.PositiveIntegerField()
    reserved_at  = models.DateTimeField(auto_now_add=True)
    expires_at   = models.DateTimeField()
    is_confirmed = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.pk and not self.expires_at:  # only on create
            self.expires_at = timezone.now() + timezone.timedelta(minutes=15)
        super().save(*args, **kwargs)

    class Meta:
        indexes = [
            models.Index(fields=['is_confirmed', 'expires_at'], name='stock_confirm_exp_idx'),
            models.Index(fields=['order', 'is_confirmed'], name='stock_order_confirm_idx'),
        ]


class PaymentProvider(models.TextChoices):
    RAZORPAY = 'razorpay', 'Razorpay'
    PHONEPE  = 'phonepe',  'PhonePe'
    CASHFREE = 'cashfree', 'Cashfree'
    PAYTM    = 'paytm',    'Paytm'


class PaymentState(models.TextChoices):
    PENDING    = 'pending',    'Pending'
    INITIATED  = 'initiated',  'Initiated'
    PROCESSING = 'processing', 'Processing'
    PAID       = 'paid',       'Paid'
    FAILED     = 'failed',     'Failed'
    REFUNDED   = 'refunded',   'Refunded'
    EXPIRED    = 'expired',    'Expired'


class GatewayAccountSource(models.TextChoices):
    PLATFORM   = 'PLATFORM',   'Platform'
    RESTAURANT = 'RESTAURANT', 'Restaurant'


PAYMENT_STATE_TRANSITIONS = {
    PaymentState.PENDING: {PaymentState.INITIATED, PaymentState.EXPIRED},
    PaymentState.INITIATED: {PaymentState.PROCESSING, PaymentState.PAID, PaymentState.FAILED, PaymentState.EXPIRED},
    PaymentState.PROCESSING: {PaymentState.PAID, PaymentState.FAILED, PaymentState.EXPIRED},
    PaymentState.PAID: set(),
    PaymentState.FAILED: {PaymentState.PAID},  # Allowed for late-capture recovery
    PaymentState.REFUNDED: set(),
    PaymentState.EXPIRED: {PaymentState.PAID},  # Allowed for late-capture recovery after expiration
}


class TenantPaymentConfig(models.Model):
    class Mode(models.TextChoices):
        TEST = 'test', 'Test'
        LIVE = 'live', 'Live'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='tenant_payment_configs')
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TEST)
    account_name = models.CharField(max_length=120, blank=True)
    encrypted_credentials = models.TextField(blank=True)
    encrypted_webhook_secret = models.TextField(blank=True)
    settlement_account_ref = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=False)
    priority = models.PositiveSmallIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenant_payment_configs'
        ordering = ['restaurant', 'priority', 'provider']
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'provider', 'mode'), name='unique_tenant_payment_config_provider_mode')
        ]
        indexes = [
            models.Index(fields=['restaurant', 'provider', 'is_active'], name='tenant_paym_restaur_888921_idx'),
            models.Index(fields=['restaurant', 'priority'], name='tenant_paym_restaur_4d65e3_idx'),
        ]

    def get_credentials(self):
        """Decrypt and return the credentials dict. Returns {} if empty or decrypt fails."""
        from ordering.payments.crypto import decrypt_json
        return decrypt_json(self.encrypted_credentials)

    def set_credentials(self, credentials_dict):
        """Encrypt and store the credentials dict."""
        from ordering.payments.crypto import encrypt_json
        self.encrypted_credentials = encrypt_json(credentials_dict)

    def get_webhook_secret(self):
        """Decrypt and return the webhook secret string. Returns '' if empty."""
        from ordering.payments.crypto import decrypt_text
        return decrypt_text(self.encrypted_webhook_secret)

    def set_webhook_secret(self, secret):
        """Encrypt and store the webhook secret."""
        from ordering.payments.crypto import encrypt_text
        self.encrypted_webhook_secret = encrypt_text(secret)


class PaymentTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='payment_transactions')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payment_transactions')
    tenant_config = models.ForeignKey(TenantPaymentConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_transactions')
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    state = models.CharField(max_length=20, choices=PaymentState.choices, default=PaymentState.PENDING)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    provider_order_id = models.CharField(max_length=160, blank=True)
    provider_payment_id = models.CharField(max_length=160, blank=True)
    provider_qr_id = models.CharField(max_length=160, blank=True)
    idempotency_key = models.UUIDField(unique=True, null=True, blank=True)
    intent_uri = models.TextField(blank=True)
    qr_image_url = models.TextField(blank=True)
    qr_payload = models.TextField(blank=True)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    gateway_account_source = models.CharField(
        max_length=20, choices=GatewayAccountSource.choices, default=GatewayAccountSource.PLATFORM,
        help_text='Whether credentials came from PLATFORM env vars or RESTAURANT-specific config.',
    )
    gateway_account_identifier = models.CharField(
        max_length=160, blank=True,
        help_text='Identifier for the gateway account used (e.g. masked key_id or account name).',
    )
    metadata = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    expires_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'order'], name='payment_tra_restaur_423b4a_idx'),
            models.Index(fields=['restaurant', 'state'], name='payment_tra_restaur_418ff5_idx'),
            models.Index(fields=['provider', 'provider_order_id'], name='payment_tra_provide_77d59d_idx'),
            models.Index(fields=['provider', 'provider_payment_id'], name='payment_tra_provide_1f8091_idx'),
            models.Index(fields=['expires_at'], name='payment_tra_expires_dd87d6_idx'),
        ]




class WebhookLog(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSED = 'PROCESSED', 'Processed'
        DEAD_LETTERED = 'DEAD_LETTERED', 'Dead Lettered'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_logs')
    payment_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='webhook_logs')
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_event_id = models.CharField(max_length=160, blank=True)
    idempotency_key = models.CharField(max_length=160, blank=True)
    signature_valid = models.BooleanField(default=False)
    payload_hash = models.CharField(max_length=64)
    raw_payload = models.TextField()
    headers = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    failed_reason = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'webhook_logs'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=('restaurant', 'provider', 'payload_hash'), name='unique_webhook_payload_per_restaurant')
        ]
        indexes = [
            models.Index(fields=['provider', 'idempotency_key'], name='webhook_log_provide_e7b376_idx'),
            models.Index(fields=['provider', 'provider_event_id'], name='webhook_log_provide_c45a37_idx'),
            models.Index(fields=['processed_at'], name='webhook_log_process_ada51a_idx'),
            models.Index(fields=['status'], name='webhook_log_status_idx'),
        ]


class PaymentReconciliationLog(models.Model):
    class Result(models.TextChoices):
        MATCHED = 'matched', 'Matched'
        UPDATED = 'updated', 'Updated'
        MISMATCH = 'mismatch', 'Mismatch'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_reconciliation_logs')
    payment_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciliation_logs')
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    result = models.CharField(max_length=20, choices=Result.choices)
    local_state = models.CharField(max_length=20, blank=True)
    provider_state = models.CharField(max_length=40, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_reconciliation_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'provider', 'created_at'], name='payment_rec_restaur_a7b39d_idx'),
            models.Index(fields=['payment_transaction', 'created_at'], name='payment_rec_payment_7a369a_idx'),
            models.Index(fields=['result', 'created_at'], name='payment_rec_result_03cd4b_idx'),
        ]


class PaymentAttempt(models.Model):
    class Method(models.TextChoices):
        QR = 'qr', 'Dynamic QR'
        UPI_INTENT = 'upi_intent', 'UPI Intent'
        HOSTED = 'hosted', 'Hosted Checkout'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.CASCADE, related_name='attempts')
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='payment_attempts')
    attempt_no = models.PositiveIntegerField()
    method = models.CharField(max_length=20, choices=Method.choices)
    app = models.CharField(max_length=30, blank=True)
    provider_attempt_id = models.CharField(max_length=160, blank=True)
    state = models.CharField(max_length=20, choices=PaymentState.choices, default=PaymentState.INITIATED)
    request_payload_hash = models.CharField(max_length=64, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_attempts'
        ordering = ['payment_transaction', 'attempt_no']
        constraints = [
            models.UniqueConstraint(fields=('payment_transaction', 'attempt_no'), name='unique_payment_attempt_no')
        ]
        indexes = [
            models.Index(fields=['restaurant', 'state'], name='payment_att_restaur_2d4f63_idx'),
            models.Index(fields=['provider_attempt_id'], name='payment_att_provide_14e8a1_idx'),
        ]


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        ORDER = 'ORDER', 'Order'
        PAYMENT = 'PAYMENT', 'Payment'
        ADJUSTMENT = 'ADJUSTMENT', 'Adjustment'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='ledger_entries')
    customer = models.ForeignKey('core.Customer', on_delete=models.PROTECT, related_name='ledger_entries')
    entry_type = models.CharField(max_length=20, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # positive = debt to restaurant, negative = payment
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_entries')
    description = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'customer']),
            models.Index(fields=['restaurant', 'customer', 'created_at']),
        ]

    def __str__(self):
        return f"{self.entry_type} {self.amount} for {self.customer.name}"


class RestaurantBalance(models.Model):
    """
    Tracks restaurant earnings per order.
    Created when a payment is confirmed. Mirrors PlatformFeeRecord from the restaurant's perspective.
    Settlement is tracked internally; actual bank transfers happen outside the system for now.
    """
    class SettlementStatus(models.TextChoices):
        PENDING  = 'pending',  'Pending'
        SETTLED  = 'settled',  'Settled'
        REFUNDED = 'refunded', 'Refunded'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='balance_entries')
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='balance_entries')
    payment_transaction = models.ForeignKey('PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='balance_entries')

    gross_amount = models.DecimalField(max_digits=10, decimal_places=2,
        help_text='Total order amount collected via gateway.')
    platform_commission = models.DecimalField(max_digits=10, decimal_places=2,
        help_text='Platform fee deducted from gross amount.')
    commission_rate_snapshot = models.DecimalField(max_digits=5, decimal_places=2,
        help_text='Commission rate (%) at the time of this entry — immutable after creation.')
    net_amount = models.DecimalField(max_digits=10, decimal_places=2,
        help_text='Amount owed to restaurant (gross − commission).')

    settlement_status = models.CharField(
        max_length=20, choices=SettlementStatus.choices, default=SettlementStatus.PENDING,
    )
    settlement_reference = models.CharField(max_length=200, blank=True,
        help_text='External reference for manual settlement (bank ref, UTR, etc.).')
    settlement_date = models.DateTimeField(null=True, blank=True)

    gateway_account_source = models.CharField(
        max_length=20, choices=GatewayAccountSource.choices, default=GatewayAccountSource.PLATFORM,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'restaurant_balances'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'settlement_status', 'created_at'],
                         name='rest_bal_settle_created_idx'),
            models.Index(fields=['restaurant', 'created_at'],
                         name='rest_bal_rest_created_idx'),
        ]

    def __str__(self):
        return f"{self.restaurant.name} — ₹{self.net_amount} ({self.settlement_status})"


class Settlement(models.Model):
    """
    Records an admin payout to a restaurant.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        REVERSED = 'REVERSED', 'Reversed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='settlements')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    settled_by = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.restaurant.name} - ₹{self.amount} ({self.status})"


class RestaurantLedger(models.Model):
    """
    Immutable, append-only double-entry ledger for the platform-restaurant relationship.
    Tracks the running balance owed to the restaurant by the platform.
    """
    class EntryType(models.TextChoices):
        CREDIT_ORDER = 'CREDIT_ORDER', 'Order Revenue'
        DEBIT_PLATFORM_FEE = 'DEBIT_PLATFORM_FEE', 'Platform Fee'
        DEBIT_CASH_COLLECTED = 'DEBIT_CASH_COLLECTED', 'Cash Collected by Restaurant'
        DEBIT_POST_PAYMENT = 'DEBIT_POST_PAYMENT', 'Post Payment Collected by Restaurant'
        DEBIT_REFUND = 'DEBIT_REFUND', 'Refund Deducted'
        CREDIT_REFUND_REVERSAL = 'CREDIT_REFUND_REVERSAL', 'Refund Reversal'
        MANUAL_ADJUSTMENT = 'MANUAL_ADJUSTMENT', 'Manual Adjustment'
        MIGRATION_CREDIT = 'MIGRATION_CREDIT', 'Migration Initial Balance'
        SETTLEMENT_PAID = 'SETTLEMENT_PAID', 'Settlement Paid Out'
        SETTLEMENT_REVERSAL = 'SETTLEMENT_REVERSAL', 'Settlement Reversal'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='ledger_records')
    order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_records')
    payment_transaction = models.ForeignKey('PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_records')
    settlement = models.ForeignKey(Settlement, on_delete=models.SET_NULL, null=True, blank=True, related_name='ledger_records')
    
    entry_type = models.CharField(max_length=50, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Positive for credits (revenue), negative for debits (fees/payouts)")
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_by = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'restaurant_ledger'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'created_at']),
        ]

    def __str__(self):
        return f"{self.entry_type} {self.amount} - Bal: {self.balance_after}"
