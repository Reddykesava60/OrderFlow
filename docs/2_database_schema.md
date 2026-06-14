# Database Schema Design

The application implements a normalized schema optimized for data integrity and Django ORM compatibility.

## Core Advancements
1. **UUIDv4 Primary Keys**: All tables use `UUIDField` as their primary keys to ensure universally unique keys and prevent ID enumeration.
2. **Financial Precision**: Monetary fields (prices, amounts, ledgers, surcharges) utilize `DecimalField(max_digits=10, decimal_places=2)`.
3. **Immutability and Audit Trails**:
   - **`PaymentEvent`**: An append-only audit log capturing every state transition of the payment lifecycle, including exact metadata and correlation IDs.
   - **`LedgerEntry`**: The Restaurant's financial balance is determined by the summation of `CREDIT` and `DEBIT` entries, tracking every revenue event and platform fee extraction immutably.
4. **Stock Reservation**: `StockReservation` handles concurrent checkout locks to prevent overselling, rolling back if payments fail.

## Key Table Structures

### Ordering App (`ordering_`)
- **`ordering_order`**: Core aggregate root for checkout. Tracks `total_amount`, `payment_method`, and `status`. Stores `idempotency_key` explicitly.
- **`ordering_orderitem` / `ordering_orderitemaddon`**: Stores a static snapshot of the item's name and price at the exact time of order to prevent historical data mutation if a menu item changes.
- **`ordering_stockreservation`**: Temporary holds on `MenuItem` and `AddOn` stock during checkout processing.
- **`ordering_paymenttransaction`**: Tracks the external provider's lifecycle. Stores `provider_order_id`, `state`, and references `tenant_config_id`.
- **`ordering_webhooklog`**: An immutable audit log of every webhook received by the platform, capturing the raw JSON payload and signature validity.
- **`ordering_ledgerentry`**: The double-entry accounting backbone.
- **`ordering_settlement`**: Tracks batched payouts to the restaurants.

### Core App (`core_`)
- **`core_menuitem`**: Stores definition, metadata, base price, and `stock` count.
- **`core_addon`**: Global addons linking to menu items.
- **`core_restaurant`**: Multi-tenant isolation boundary for orders and catalog.

### Kitchen App (`kitchen_`)
- **`kitchen_paymentevent`**: The timeline of a `PaymentTransaction` logging `RAZORPAY_INITIATED`, `WEBHOOK_PROCESSING_STARTED`, `WEBHOOK_PROCESSING_COMPLETED`, and exceptions.
