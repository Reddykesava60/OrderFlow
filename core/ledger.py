import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import F
from core.models import (
    MerchantLedgerBalance,
    JournalEntry,
    JournalLine,
)

logger = logging.getLogger(__name__)

class LedgerError(Exception):
    pass

class LedgerService:
    """
    Service responsible for Double-Entry bookkeeping and balance updates.
    """

    @classmethod
    @transaction.atomic
    def _create_journal_entry(cls, restaurant, reference_id, entry_type, lines) -> JournalEntry:
        """
        Low-level method to create a balanced journal entry.
        lines: list of dicts [{'account_type': AccountType, 'amount': Decimal}, ...]
        """
        total = sum(line['amount'] for line in lines)
        if total != Decimal('0.00'):
            raise LedgerError(f"Unbalanced journal entry! Total: {total}")

        entry = JournalEntry.objects.create(
            restaurant=restaurant,
            reference_id=reference_id,
            entry_type=entry_type
        )

        for line in lines:
            JournalLine.objects.create(
                entry=entry,
                account_type=line['account_type'],
                amount=line['amount']
            )

        return entry

    @classmethod
    @transaction.atomic
    def _update_balance(cls, restaurant, amount: Decimal):
        """
        Updates the RestaurantBalance. 
        Selects for update to prevent race conditions.
        """
        balance, _ = MerchantLedgerBalance.objects.select_for_update().get_or_create(
            restaurant=restaurant
        )
        balance.available_balance = F('available_balance') + amount
        balance.save(update_fields=['available_balance', 'updated_at'])
        return balance

    @classmethod
    @transaction.atomic
    def record_payment_capture(cls, order, gross_amount: Decimal, fee_amount: Decimal, reference_id: str):
        """
        Records a successful payment capture.
        Debit Cash In Transit (Gross)
        Credit Platform Fee (Fee)
        Credit Merchant Balance (Net)
        """
        if not order:
            raise LedgerError("Order is required.")

        net_amount = gross_amount - fee_amount

        # Check idempotency
        if JournalEntry.objects.filter(reference_id=reference_id).exists():
            logger.info("Ledger entry already exists for %s", reference_id)
            return

        lines = [
            {
                'account_type': JournalLine.AccountType.ASSET_CASH_IN_TRANSIT,
                'amount': gross_amount  # Debit
            },
            {
                'account_type': JournalLine.AccountType.REVENUE_PLATFORM_FEE,
                'amount': -fee_amount   # Credit
            },
            {
                'account_type': JournalLine.AccountType.LIABILITY_MERCHANT_BALANCE,
                'amount': -net_amount   # Credit
            }
        ]

        cls._create_journal_entry(
            restaurant=order.restaurant,
            reference_id=reference_id,
            entry_type=JournalEntry.EntryType.PAYMENT_CAPTURED,
            lines=lines
        )

        # Update merchant balance
        cls._update_balance(order.restaurant, net_amount)

    @classmethod
    @transaction.atomic
    def record_refund(cls, order, amount: Decimal, fee_refunded: Decimal):
        """
        Records a refund.
        Debit Merchant Balance (Net Refund)
        Debit Platform Fee (Fee Refunded)
        Credit Cash In Transit (Gross Refund)
        """
        net_refund = amount - fee_refunded

        reference_id = f"REFUND_ORDER_{order.id}"
        # For simplicity, if we only allow full refunds or multiple refunds, we should use a unique reference.
        # But our system currently just tracks order refunds. Let's make it idempotent by counting entries or using unique ID.
        # Given we don't have a refund model, we append timestamp or just use order ID if it's full refund.
        # Assuming full refunds.
        if JournalEntry.objects.filter(reference_id=reference_id).exists():
            logger.info("Ledger entry already exists for %s", reference_id)
            return

        lines = [
            {
                'account_type': JournalLine.AccountType.EXPENSE_REFUND,
                'amount': amount  # Debit (or reducing Asset Cash In Transit, but let's just do it directly)
                # Actually, to balance:
            }
        ]
        # Wait, proper accounting for refund:
        # We need to reverse the original entry.
        # Debit: Liability Merchant Balance (Net Refund)
        # Debit: Revenue Platform Fee (Fee Refunded)
        # Credit: Asset Cash in Transit (Gross Refund)
        
        lines = [
            {
                'account_type': JournalLine.AccountType.LIABILITY_MERCHANT_BALANCE,
                'amount': net_refund  # Debit
            },
            {
                'account_type': JournalLine.AccountType.REVENUE_PLATFORM_FEE,
                'amount': fee_refunded  # Debit
            },
            {
                'account_type': JournalLine.AccountType.ASSET_CASH_IN_TRANSIT,
                'amount': -amount  # Credit
            }
        ]

        cls._create_journal_entry(
            restaurant=order.restaurant,
            reference_id=reference_id,
            entry_type=JournalEntry.EntryType.REFUND,
            lines=lines
        )

        # Update merchant balance (reduce it)
        cls._update_balance(order.restaurant, -net_refund)
