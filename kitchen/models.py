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
    event_type          = models.CharField(max_length=30, choices=EventType.choices)
    amount              = models.DecimalField(max_digits=10, decimal_places=2)
    staff_user          = models.ForeignKey('core.User', on_delete=models.SET_NULL, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True)
    razorpay_refund_id  = models.CharField(max_length=100, blank=True)
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
