from django.db import models
from shared.models import DomainModel

class PaymentProvider(models.TextChoices):
    RAZORPAY = 'razorpay', 'Razorpay'

class PaymentState(models.TextChoices):
    PENDING = 'pending', 'Pending'
    INITIATED = 'initiated', 'Initiated'
    PROCESSING = 'processing', 'Processing'
    PAID = 'paid', 'Paid'
    FAILED = 'failed', 'Failed'
    REFUNDED = 'refunded', 'Refunded'
    EXPIRED = 'expired', 'Expired'

class GatewayAccountSource(models.TextChoices):
    PLATFORM = 'PLATFORM', 'Platform'
    RESTAURANT = 'RESTAURANT', 'Restaurant'

class TenantPaymentConfig(DomainModel):
    class Mode(models.TextChoices):
        TEST = 'test', 'Test'
        LIVE = 'live', 'Live'

    restaurant_id = models.UUIDField()
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.TEST)
    
    account_name = models.CharField(max_length=120, blank=True)
    encrypted_credentials = models.TextField(blank=True)
    encrypted_webhook_secret = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        db_table = 'payments_tenant_config'

class PaymentTransaction(DomainModel):
    restaurant_id = models.UUIDField()
    order_id = models.UUIDField()
    tenant_config = models.ForeignKey(TenantPaymentConfig, on_delete=models.SET_NULL, null=True, blank=True)
    
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    state = models.CharField(max_length=20, choices=PaymentState.choices, default=PaymentState.PENDING)
    
    amount = models.DecimalField(max_digits=12, decimal_places=4)
    currency = models.CharField(max_length=3, default='INR')
    
    provider_order_id = models.CharField(max_length=160, blank=True)
    provider_payment_id = models.CharField(max_length=160, blank=True)
    
    idempotency_key = models.UUIDField(unique=True, null=True, blank=True)
    gateway_account_source = models.CharField(max_length=20, choices=GatewayAccountSource.choices, default=GatewayAccountSource.PLATFORM)
    
    paid_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payments_transaction'

class WebhookLog(DomainModel):
    restaurant_id = models.UUIDField(null=True, blank=True)
    payment_transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True)
    
    provider = models.CharField(max_length=30, choices=PaymentProvider.choices)
    provider_event_id = models.CharField(max_length=160, blank=True)
    
    signature_valid = models.BooleanField(default=False)
    payload_hash = models.CharField(max_length=64)
    raw_payload = models.TextField()
    
    processed_at = models.DateTimeField(null=True, blank=True)
    failed_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'payments_webhook_log'
