# Financial Double-Entry Ledger

The backbone of the restaurant operating system's financial integrity is the Immutable Double-Entry Ledger located in `core/ledger.py`.

## Core Principles
The system operates on strict double-entry bookkeeping rules to guarantee that no money is ever "lost" or unaccounted for, and that platform fees are deterministically calculated.

1. **Immutability**: `JournalEntry` and `JournalLine` records are append-only. They are never UPDATED or DELETED.
2. **Zero-Sum Guarantees**: A `JournalEntry` is only valid if the sum of all its associated `JournalLine` amounts equals exactly `0.00`. This is enforced at the database transaction layer.
3. **Idempotency**: The `LedgerService` requires an `idempotency_key` (usually the `Order` ID or `PaymentTransaction` ID) to ensure that duplicate webhooks cannot result in duplicate credits.

## Accounts
The ledger interacts across specific account types defined in `MerchantLedgerBalance`:
- **`REVENUE`**: Money earned by the restaurant from order sales. (Credits increase balance).
- **`FEE`**: Money owed to the platform for operational costs. (Debits increase balance).
- **`PAYOUT`**: Money transferred from the platform to the restaurant's bank account during settlements.
- **`REFUND`**: Money returned to the customer.

## Standard Order Flow

When a `place_cash_order` or `place_upi_order` is successfully captured, the `order_paid` Domain Event Signal fires. This triggers `LedgerService.record_payment_capture()`.

Example `JournalEntry` for a ₹500 order with a 5% platform fee (₹25):
- Line 1: `CREDIT` ₹500 to `REVENUE` (Restaurant earned ₹500)
- Line 2: `DEBIT` ₹25 to `FEE` (Restaurant owes Platform ₹25)
- Line 3: `DEBIT` ₹475 to `PAYOUT` (Restaurant will receive ₹475)

*Sum: (+500) + (-25) + (-475) = 0.00*

Because the ledger enforces strict boundary logic, any partial captures, mismatched amounts, or double-processing will inherently violate the zero-sum rule and trigger an immediate database rollback.

## Platform Fee Accrual

Alongside the `JournalEntry`, the ledger synchronously creates a `PlatformFeeRecord` which serves as a highly denormalized aggregate specifically optimized for the platform's internal finance team. This prevents the need to calculate platform earnings by scanning millions of `JournalLine` entries on the fly. 

## Settlements

Periodically, a `SettlementBatch` aggregates the un-settled `PAYOUT` ledger lines and issues an API call to the banking provider to deposit funds into the Restaurant's bank account. Once successful, a new `JournalEntry` marks the payout as completed, neutralizing the `PAYOUT` balance.
