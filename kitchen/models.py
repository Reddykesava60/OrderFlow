# kitchen/models.py
import uuid
from django.db import models
from core.models import Restaurant


class PaymentEvent(models.Model):
    """
    Append-only financial audit log. NEVER deleted by any automated process.
    No UPDATE permitted. Refund-related fields are retained only for legacy compatibility.
    """
    class EventType(models.TextChoices):
        INITIATED                  = 'INITIATED',                  'Initiated'
        CASH_COLLECTED             = 'CASH_COLLECTED',             'Cash Collected'
        RAZORPAY_INITIATED         = 'RAZORPAY_INITIATED',         'Razorpay Initiated'
        RAZORPAY_CONFIRMED         = 'RAZORPAY_CONFIRMED',         'Razorpay Confirmed'
        DIGITAL_PAYMENT_INITIATED  = 'DIGITAL_PAYMENT_INITIATED',  'Digital Payment Initiated'
        DIGITAL_PAYMENT_CONFIRMED  = 'DIGITAL_PAYMENT_CONFIRMED',  'Digital Payment Confirmed'
        PAYMENT_FAILED             = 'PAYMENT_FAILED',             'Payment Failed'
        PAYMENT_TIMEOUT            = 'PAYMENT_TIMEOUT',            'Payment Timeout'
        REFUND_INITIATED           = 'REFUND_INITIATED',           'Refund Initiated'
        REFUND_PROCESSED           = 'REFUND_PROCESSED',           'Refund Processed'
        REFUND_FAILED              = 'REFUND_FAILED',              'Refund Failed'
        WEBHOOK_LOOKUP_FAILED      = 'WEBHOOK_LOOKUP_FAILED',      'Webhook Lookup Failed'
        WEBHOOK_PROCESSING_STARTED = 'WEBHOOK_PROCESSING_STARTED', 'Webhook Processing Started'
        WEBHOOK_PROCESSING_COMPLETED = 'WEBHOOK_PROCESSING_COMPLETED', 'Webhook Processing Completed'
        WEBHOOK_PROCESSING_EXCEPTION = 'WEBHOOK_PROCESSING_EXCEPTION', 'Webhook Processing Exception'
        PAYMENT_TRANSACTION_NOT_FOUND = 'PAYMENT_TRANSACTION_NOT_FOUND', 'Payment Transaction Not Found'
        PAYMENT_STATE_TRANSITION_FAILED = 'PAYMENT_STATE_TRANSITION_FAILED', 'Payment State Transition Failed'
        
        # Late-Capture Recovery Events
        LATE_CAPTURE_RECEIVED      = 'LATE_CAPTURE_RECEIVED',      'Late Capture Received'
        ORDER_RECOVERY_STARTED     = 'ORDER_RECOVERY_STARTED',     'Order Recovery Started'
        ORDER_RECOVERED            = 'ORDER_RECOVERED',            'Order Recovered'
        ORDER_RECOVERY_FAILED      = 'ORDER_RECOVERY_FAILED',      'Order Recovery Failed'
        PAYMENT_RECOVERY_REQUIRED  = 'PAYMENT_RECOVERY_REQUIRED',  'Payment Recovery Required'

    class EventStatus(models.TextChoices):
        INFO = 'INFO', 'Info'
        SUCCESS = 'SUCCESS', 'Success'
        WARNING = 'WARNING', 'Warning'
        FAILED = 'FAILED', 'Failed'

    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order               = models.ForeignKey(
        'ordering.Order', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payment_events'
    )
    order_ref           = models.CharField(max_length=80)  # snapshot survives order purge
    restaurant          = models.ForeignKey(
        Restaurant, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payment_events'
    )
    event_type          = models.CharField(max_length=40, choices=EventType.choices)
    amount              = models.DecimalField(max_digits=10, decimal_places=2)
    staff_user          = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_refund_id  = models.CharField(max_length=100, blank=True)
    
    transaction         = models.ForeignKey('ordering.PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_events')
    event_status        = models.CharField(max_length=20, choices=EventStatus.choices, default=EventStatus.INFO)
    metadata            = models.JSONField(default=dict, blank=True)
    
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['restaurant', 'event_type', 'created_at'], name='k_pe_rest_type_created_idx'),
            models.Index(fields=['order', 'event_type', 'razorpay_payment_id'], name='k_pe_order_type_pay_idx'),
            models.Index(fields=['razorpay_payment_id'], name='k_pe_razorpay_pay_idx'),
        ]

    def __str__(self):
        return f"{self.event_type} — {self.order_ref}"
