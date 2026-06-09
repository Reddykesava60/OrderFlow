from django.db import models
from shared.models import DomainModel

class Settlement(DomainModel):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        REVERSED = 'REVERSED', 'Reversed'

    restaurant_id = models.UUIDField()
    amount = models.DecimalField(max_digits=12, decimal_places=4)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    settled_by_user_id = models.UUIDField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'finance_settlement'

class LedgerEntry(DomainModel):
    """
    Append-only double-entry ledger for the platform-restaurant relationship.
    """
    class EntryType(models.TextChoices):
        CREDIT_ORDER = 'CREDIT_ORDER', 'Order Revenue'
        DEBIT_PLATFORM_FEE = 'DEBIT_PLATFORM_FEE', 'Platform Fee'
        DEBIT_CASH_COLLECTED = 'DEBIT_CASH_COLLECTED', 'Cash Collected by Restaurant'
        DEBIT_POST_PAYMENT = 'DEBIT_POST_PAYMENT', 'Post Payment Collected by Restaurant'
        DEBIT_REFUND = 'DEBIT_REFUND', 'Refund Deducted'
        CREDIT_REFUND_REVERSAL = 'CREDIT_REFUND_REVERSAL', 'Refund Reversal'
        MANUAL_ADJUSTMENT = 'MANUAL_ADJUSTMENT', 'Manual Adjustment'
        SETTLEMENT_PAID = 'SETTLEMENT_PAID', 'Settlement Paid Out'

    restaurant_id = models.UUIDField()
    order_id = models.UUIDField(null=True, blank=True)
    payment_transaction_id = models.UUIDField(null=True, blank=True)
    settlement = models.ForeignKey(Settlement, on_delete=models.SET_NULL, null=True, blank=True)
    
    entry_type = models.CharField(max_length=50, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=4, help_text="Positive for credits (revenue), negative for debits (fees/payouts)")
    balance_after = models.DecimalField(max_digits=12, decimal_places=4)
    
    reference = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_by_user_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = 'finance_ledger_entry'
        indexes = [
            models.Index(fields=['restaurant_id', 'created_at']),
        ]
