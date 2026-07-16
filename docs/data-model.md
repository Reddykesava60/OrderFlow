# Data Model Reference

Order-Flow uses a relational data model designed for strict referential integrity and safe financial transactions.

## Core Entities

### Restaurant (`core.models.Restaurant`)
The root tenant entity. Every transactional record links back to a Restaurant.
- **Fields:** `id`, `name`, `slug`, `logo`, `fee_mode`, `fee_percent`, `fee_fixed_amount`
- **Relations:** 1:1 `RestaurantConfig`

### User (`core.models.User`)
Staff and Owner accounts. Uses Django's `AbstractUser`.
- **Fields:** `role` (OWNER/STAFF), `allow_cash_collection`, `mfa_enabled`
- **Constraints:** Unique `username` (case-insensitive) per `restaurant`.

### Customer (`core.models.Customer`)
End-users placing orders.
- **Fields:** `serial_number`, `name`, `phone`, `balance`, `credit_limit`
- **Constraints:** Unique `serial_number` per `restaurant`.

## Catalog & Inventory

### MenuItem & AddOn (`core.models`)
Products available for order.
- **Fields:** `price`, `stock`, `is_available`, `auto_hidden_due_to_stock`
- **Behavior:** `stock` is decremented atomically during checkout. If stock reaches 0, `auto_hidden_due_to_stock` triggers.

## Order Lifecycle

### Order (`ordering.models.Order`)
The central transactional entity.
- **Fields:** `order_number`, `status` (UNPAID, PENDING, PREP_STARTED, COMPLETED, CANCELLED), `payment_method`, `total`, `tax_total`
- **Relations:** 1:N `OrderItem`, 1:N `PaymentTransaction`, 1:N `StockReservation`

### StockReservation (`ordering.models.StockReservation`)
Temporary lock on inventory while a payment is pending.
- **Fields:** `quantity`, `expires_at`, `is_confirmed`
- **Lifecycle:** Created at checkout. Confirmed (kept) if payment succeeds. Released (deleted) if payment fails or expires.

## Payment & Ledger (Financials)

### PaymentTransaction (`ordering.models.PaymentTransaction`)
Tracks intent and status with external gateways (Razorpay, etc).
- **Fields:** `provider`, `amount`, `state` (PENDING, PAID, FAILED, EXPIRED), `provider_payment_id`
- **Behavior:** Controlled by a strict `PaymentStateMachine`.

### WebhookLog (`ordering.models.WebhookLog`)
Idempotent ingestion table for payment provider callbacks.
- **Fields:** `provider_event_id`, `payload_hash`, `status`
- **Behavior:** Dedupes incoming webhooks by `provider_event_id` and payload hash to prevent double-processing.

### RestaurantLedger (`ordering.models.RestaurantLedger`)
Double-entry accounting for the platform-to-restaurant relationship.
- **Entry Types:** CREDIT_ORDER, DEBIT_PLATFORM_FEE, DEBIT_CASH_COLLECTED, SETTLEMENT_PAID
- **Behavior:** Every confirmed order generates a credit for the gross amount and a debit for the platform fee.

### LedgerEntry (`ordering.models.LedgerEntry`)
Double-entry accounting for the restaurant-to-customer relationship (Post Payments/Tabs).
- **Entry Types:** ORDER (debt added), PAYMENT (debt cleared)
- **Behavior:** Maintains a running `balance_after` for auditability.
