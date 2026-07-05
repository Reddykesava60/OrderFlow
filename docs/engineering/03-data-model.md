# Data Model

This covers the database tables that matter for understanding how the
system behaves — not an exhaustive field-by-field dump (read the actual
`models.py` files for that). Every table uses a `UUIDField` primary key
unless noted otherwise.

## Tenancy & identity (`core`)

| Model | What it represents |
|---|---|
| `Restaurant` | The tenant boundary. Almost every other table links back to one. Has a `slug` (used in customer-facing URLs) and an optional per-restaurant `commission_rate` override. |
| `RestaurantConfig` | Per-restaurant toggles: is the restaurant currently open, is cash/UPI enabled, has the data processing agreement been accepted, is the KDS preparation stage enabled (`kds_prep_enabled`), and an optional per-restaurant `cash_payment_timeout_minutes_override`. |
| `RestaurantPaymentConfig` | The **legacy**, Razorpay-only per-restaurant payment credential record. Still actively used — see [Payments & Webhooks](./06-payments-and-webhooks.md). |
| `PlatformSettings` | A singleton row (`singleton_key=1`, enforced in `save()`) holding platform-wide defaults: cash payment timeout, and the default platform fee mode/rate. |
| `User` | Custom user model (`AUTH_USER_MODEL = 'core.User'`). Has a `role` (`OWNER` or `STAFF`), a `restaurant` FK, and granular permission flags (`allow_cash_collection`, `allow_view_all_orders`, `allow_order_completion`). |
| `Customer` | A restaurant's own customer record, used for the optional "pay later" / tab feature. Authenticated with a hashed PIN, not a password. |

## Catalog (`core`)

| Model | What it represents |
|---|---|
| `ItemType` | A menu category, scoped per restaurant. Can be linked to `MenuItem`s directly from the Category edit view. |
| `MenuItem` | A sellable dish. `stock = NULL` means unlimited; a non-null value is decremented on confirmed orders. `is_available` can be turned off manually or automatically (`auto_hidden_due_to_stock`) when stock hits zero. |
| `AddOn` | An optional extra (e.g., "extra cheese"), also independently stocked. |
| `MenuItemAddOn` | The many-to-many link between a `MenuItem` and the `AddOn`s it offers. Its mere existence (with an active add-on) is what marks an item as "has add-ons" in the UI. Can be managed from either the Menu Item or Add-on edit views. |
| `StaffFilter` | A named subset of menu items, used to scope what a given staff member's KDS view shows. |

## Orders (`ordering`)

| Model | What it represents |
|---|---|
| `Order` | The aggregate root of a sale. Carries `status` (the order state machine — see [Order & Payment Lifecycle](./04-order-and-payment-lifecycle.md)), `payment_method` (`CASH`, `UPI`, or `POST_PAYMENT`), and an `idempotency_key` used to make checkout submission safe to retry. `total` is always server-computed — the client's submitted price is never trusted. |
| `OrderItem` / `OrderItemAddOn` | Line items, each storing a **snapshot** of the item's name and price at the moment of purchase. This is deliberate: if a restaurant changes a menu price tomorrow, today's receipts must not retroactively change. |
| `RestaurantOrderCounter` | One row per restaurant, locked with `SELECT FOR UPDATE` to hand out sequential, human-readable order numbers that reset daily (in IST). |
| `StockReservation` | A short-lived hold on a `MenuItem`/`AddOn` quantity, created at checkout and either confirmed (on payment) or released (on cancellation/expiry). Defaults to a 15-minute expiry. |

## Payments (`ordering`)

| Model | What it represents |
|---|---|
| `TenantPaymentConfig` | The **current**, multi-provider payment credential model (`PaymentProvider`: `razorpay`, `phonepe`, `cashfree`, `paytm` — only Razorpay is actually wired up to a live integration today). Credentials are stored encrypted. |
| `PaymentTransaction` | The gateway-side record of a single payment attempt: `state` (the payment state machine), `provider_order_id`/`provider_payment_id`, the resolved `gateway_account_source` (was the platform's or the restaurant's own credentials used), and a `version` field used for optimistic-locking style transitions. |
| `WebhookLog` | Every incoming webhook, stored **before** it's interpreted. Tracks `status` (`PENDING`/`PROCESSED`/`DEAD_LETTERED`), whether the signature was valid, and a `payload_hash` used (together with restaurant + provider) to deduplicate identical redeliveries. |
| `PaymentReconciliationLog` | A record of each time the reconciliation job compared local state against the gateway's reported state, and what it found. |
| `PaymentAttempt` | Sub-records under a `PaymentTransaction` for systems that support multiple payment attempts per transaction (e.g., retrying a UPI intent). |

## Financial records — and an important duplication to know about

Dineflow currently runs **two parallel ledgers** that both record the same
underlying event (a payment being captured). This is documented honestly
here rather than papered over, because it's a real fact about the codebase
you'll run into:

| Model | App | Style | Actually powers |
|---|---|---|---|
| `RestaurantLedger` | `ordering` | Append-only, one row per debit/credit, each storing the running `balance_after` | The Owner Dashboard, the Reconciliation screen, and the restaurant balance shown in Django Admin |
| `JournalEntry` + `JournalLine` + `MerchantLedgerBalance` | `core` | Strict double-entry: every `JournalEntry` has `JournalLine`s across distinct account types (asset/revenue/liability/expense) that must sum to exactly zero | Kept in sync via the `order_paid` signal; registered in Django Admin; not yet the basis of any restaurant-facing screen |

In practice: if you're debugging "why does this restaurant's balance look
wrong," you want `RestaurantLedger` — that's the one every UI actually
reads from. `JournalEntry`/`JournalLine` is the more rigorously-structured
accounting model, written in parallel, but currently a secondary system.
See [Financial Ledger](./05-financial-ledger.md) for how each one is
written to, and why both exist.

| Model | What it represents |
|---|---|
| `PlatformFeeRecord` | The simplest financial record: one append-only row per confirmed payment, storing the order total, the fee amount, and an immutable snapshot of the fee rate that applied. This is what actually drives the platform's monthly invoice to each restaurant. |
| `MonthlyPlatformFeeStatement` | Auto-aggregated (via a signal on `PlatformFeeRecord`) rollup of orders/revenue/fees per restaurant per month. |
| `Settlement` / `SettlementBatch` / `SettlementRecord` | Records of an actual payout from the platform to a restaurant's bank account. `Settlement` (in `ordering`) is the one the admin settlement action currently writes to; `SettlementBatch`/`SettlementRecord` (in `core`) is the newer batch-oriented model. |

## Customer tab / credit ledger (`ordering`) — unrelated to the above

| Model | What it represents |
|---|---|
| `LedgerEntry` | Tracks a `Customer`'s running balance with the restaurant for the "pay later" feature — completely separate from the restaurant-vs-platform ledgers above. An `ORDER` entry increases what the customer owes; a `PAYMENT` entry decreases it. |

## Kitchen & observability (`kitchen`)

| Model | What it represents |
|---|---|
| `PaymentEvent` | An append-only diagnostic timeline — every meaningful event in a payment's life (`RAZORPAY_INITIATED`, `WEBHOOK_PROCESSING_STARTED`, `RAZORPAY_CONFIRMED`, `PAYMENT_TIMEOUT`, exceptions, etc.) gets a row here. This exists purely so a human can reconstruct what happened to a specific order without grepping logs. |

## Audit (`core`)

| Model | What it represents |
|---|---|
| `OwnerAuditLog` | Records sensitive staff/owner actions (creating a customer, resetting a PIN, recording a manual payment, editing staff permissions) with a JSON `details` payload for context. |

## Next

[Order & Payment Lifecycle](./04-order-and-payment-lifecycle.md) shows how
these tables actually change as an order moves from cart to kitchen.
