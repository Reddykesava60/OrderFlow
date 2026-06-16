# Financial Ledger

The backbone of the restaurant operating system's financial integrity is the Immutable Ledger located in `core/models.py`.

## Core Principles
The system operates on strict bookkeeping rules to guarantee that no money is ever "lost" or unaccounted for, and that platform fees are deterministically calculated.

1. **Immutability**: `LedgerEntry` records are append-only. They are never UPDATED or DELETED.
2. **Deterministic Balances**: Every `LedgerEntry` calculates and stores the `balance_after`. The system prevents tampering by ensuring the math flows chronologically.
3. **Denormalization**: To prevent expensive `SUM()` queries across millions of rows, the `MerchantLedgerBalance` table maintains the exact current real-time balance of the restaurant.

## Standard Order Flow

When an order is successfully captured and verified via webhook, the system calls `RestaurantLedgerService().record_payment()` inside the same atomic database transaction as the order status update.

Example `LedgerEntry` logic for a ₹500 order:
- A new `LedgerEntry` is appended for ₹500 (Type: `CREDIT`).
- The `MerchantLedgerBalance` is atomically incremented by ₹500.
- The `LedgerEntry.balance_after` stores the exact balance after this transaction was applied.

Because the ledger enforces strict boundary logic inside `transaction.atomic()`, any partial captures, mismatched amounts, or double-processing will instantly trigger a database rollback, ensuring financial state remains pristine.

## Monthly Statements

Instead of building a real-time banking transfer settlement engine, the system utilizes a `MonthlyPlatformFeeStatement` model. A background cron job (`sync_monthly_statements_task`) runs to automatically aggregate all `LedgerEntry` records for the month and calculate the final platform fee owed by the restaurant. The platform owner can then review these statements and issue physical or standard wire transfers outside of the application.
