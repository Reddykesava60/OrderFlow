# Financial Ledger

Dineflow's central design principle for money: **every financial fact is
written once, never edited, and corrections are made by adding a new fact
that reverses the old one.** This page covers the three financial
record-keeping systems that actually exist in the codebase today, why
there are three, and which one to trust for what.

## The honest summary

| System | Model(s) | App | What actually uses it |
|---|---|---|---|
| Restaurant ledger | `RestaurantLedger` | `ordering` | **The canonical source for restaurant balances.** Powers the Owner Dashboard, the Reconciliation screen, and Django Admin's balance display. |
| Double-entry journal | `JournalEntry` + `JournalLine` + `MerchantLedgerBalance` | `core` | Written in parallel, on every payment, via a signal. Visible in Django Admin. Not currently read by any restaurant-facing screen. |
| Platform fee record | `PlatformFeeRecord` + `MonthlyPlatformFeeStatement` | `core` | **The canonical source for what a restaurant owes the platform.** Drives the monthly fee statement. |

If you're investigating "why is this restaurant's balance wrong," start
with `RestaurantLedger`. If you're investigating "why doesn't the platform
fee statement match," start with `PlatformFeeRecord`. The double-entry
`JournalEntry` system runs alongside both, recording the same underlying
events in a stricter accounting shape, but isn't (yet) the thing any
operator-facing screen reads from. This is a known duplication, not a
hidden bug — it's documented here so nobody loses time rediscovering it.

## `RestaurantLedger` — the operational ledger

Defined in `ordering/models.py`, written by `RestaurantLedgerService` in
`ordering/ledger/services.py`. Every row is one entry with a type
(`CREDIT_ORDER`, `DEBIT_PLATFORM_FEE`, `DEBIT_CASH_COLLECTED`,
`DEBIT_POST_PAYMENT`, `DEBIT_REFUND`, `SETTLEMENT_PAID`, etc.) and stores
the resulting `balance_after` — so the running balance can always be read
straight off the latest row without summing the whole table.

Each `record_*` method **locks the restaurant row first**
(`select_for_update()`), then reads the last entry to compute the new
balance, then writes the new row(s). That lock is what makes concurrent
writes for the same restaurant safe — two payments confirming at the same
instant are serialized through that lock rather than racing each other.

What gets recorded depends on the payment method, because the actual flow
of cash is different:

| Payment method | Entries written |
|---|---|
| UPI | `CREDIT_ORDER` (gross) + `DEBIT_PLATFORM_FEE` (commission). Net effect: restaurant balance increases by `gross − fee`, because the platform is holding the gross amount and owes the net to the restaurant. |
| Cash | `CREDIT_ORDER` + `DEBIT_CASH_COLLECTED` (full gross, since the restaurant physically already has the cash) + `DEBIT_PLATFORM_FEE`. Net effect: balance decreases by the fee — the restaurant owes the platform the commission on cash they already collected. |
| Post-payment (customer tab) | Same shape as cash: `CREDIT_ORDER` + `DEBIT_POST_PAYMENT` + `DEBIT_PLATFORM_FEE`. |

## `JournalEntry` / `JournalLine` — the double-entry journal

Defined in `core/models.py`, written by `LedgerService` in `core/ledger.py`,
triggered via the `order_paid` Django signal (`ordering/receivers.py`).
This is intentionally stricter than `RestaurantLedger`: every
`JournalEntry` is made of `JournalLine`s tagged with a proper accounting
account type (`ASSET_CASH_IN_TRANSIT`, `REVENUE_PLATFORM_FEE`,
`LIABILITY_MERCHANT_BALANCE`, `EXPENSE_REFUND`), and `_create_journal_entry()`
**refuses to save anything where the lines don't sum to exactly zero**:

```python
total = sum(line['amount'] for line in lines)
if total != Decimal('0.00'):
    raise LedgerError(f"Unbalanced journal entry! Total: {total}")
```

That guarantee is the whole point of double-entry bookkeeping: it's
structurally impossible to record a payment capture without simultaneously
and correctly accounting for where every part of it went.

**Important nuance about the signal**: `order_paid.send(...)` is called
synchronously, from inside the same `transaction.atomic()` block as the
rest of order confirmation (see `_create_fee_record()` in
`ordering/orders/services.py`). Django signal receivers run inline in the
same call stack — they are not deferred or asynchronous — so in practice
this write *is* part of the same atomic transaction as the order's status
change, even though it's wired up via a signal rather than a direct call.
The architectural principle described in
[Architecture Overview](./01-architecture-overview.md) (avoid signals for
financially-critical writes) is about avoiding *unreliable* side-effect
wiring, not about a hard rule against signals when the call chain is
verified to be synchronous and atomic — this is the one deliberate
exception, and it's worth knowing it's there before you add another one.

`record_refund()` follows the same reversing-entry principle as everywhere
else in the system: it does not touch the original `JournalEntry`, it adds
a new one with the opposite signs.

## `PlatformFeeRecord` — what the platform is actually owed

The simplest and most heavily relied-upon record: one append-only row per
confirmed payment (`_create_fee_record()` in `ordering/orders/services.py`),
storing `order_total`, `fee_amount`, and `fee_rate_snapshot`. The rate
snapshot is the field that matters most operationally — it freezes the
commission rate that applied to that specific order, so if the platform's
default fee changes next month, every historical record still shows the
rate that was actually in effect when the sale happened.

A `post_save` signal on `PlatformFeeRecord` automatically rolls these up
into `MonthlyPlatformFeeStatement` — one row per restaurant per calendar
month, incrementing on creation and adjusting on a refund's
`is_refunded` flip from `False → True`. This statement is what `core`'s
monthly sync job (and the `sync_monthly_statements` management command)
keep current, and what an operator reviews to issue a payout outside the
system.

## Refunds: the reversing-entry pattern, applied consistently

Whichever ledger you're looking at, the rule is the same: a refund is
never an edit or a delete. It's a new record that cancels the original
out:

- `RestaurantLedger` gets `DEBIT_REFUND` / `CREDIT_REFUND_REVERSAL` entries.
- `JournalEntry`/`JournalLine` gets a new balanced entry with the signs
  flipped relative to the original capture.
- `PlatformFeeRecord.is_refunded` flips to `True`, which is what triggers
  the `MonthlyPlatformFeeStatement` adjustment and the `JournalEntry`
  refund write (see the `post_save` receiver in `core/models.py`).

The result: at any point, the complete history — the original charge *and*
the refund — remains in the data. Nothing is ever invisible after the
fact.

## Settlements (paying a restaurant out)

`Settlement` (in `ordering`) is the model the admin "record a payout"
action currently writes to, recording the amount, status, and an
operator-entered `reference_number`. `SettlementBatch`/`SettlementRecord`
(in `core`) is a newer, batch-oriented model for grouping multiple
restaurants' payouts together — present in the schema, but not yet wired
into a UI workflow at the time of writing.

## Next

[Payments & Webhooks](./06-payments-and-webhooks.md) covers the gateway
integration that ultimately triggers all of the above.
