# Greenfield Database Schema Design

The Greenfield schema drops all legacy mappings and implements highly normalized structures, optimizing for performance and data integrity.

## Core Advancements
1. **UUIDv7 Primary Keys**: All tables (except identity `User`, which falls back to UUIDv4 for standard Django auth compatibility) use `UUIDField` as their primary keys. This ensures keys are universally unique, time-sortable, and friendly for distributed generation without indexing overhead.
2. **Financial Precision**: All monetary fields (prices, amounts, ledgers, surcharges) utilize `DECIMAL(12, 4)`. This guards against floating-point errors.
3. **Event Sourcing (Append-Only)**: The system moves away from mutating state variables for critical systems:
   - **`InventoryLedger`**: Stock is no longer a simple `integer` on the `MenuItem`. It is an append-only table of `INITIAL`, `RESERVATION`, `CONSUMPTION`, and `RELEASE` transactions. The current stock is the mathematical `Sum` of these transactions.
   - **`LedgerEntry`**: The Restaurant's financial balance is determined by the summation of `CREDIT` and `DEBIT` entries, tracking every revenue event and platform fee extraction immutably.

## Key Table Structures

### Sales Domain
- **`sales_order`**: Core aggregate root for checkout. Tracks `total_amount`, `payment_method`, and `status`. Stores `idempotency_key` explicitly.
- **`sales_order_item` / `sales_order_item_addon`**: Stores a static snapshot of the item's name and price at the exact time of order to prevent historical data mutation if a menu item changes.

### Payments Domain
- **`payments_transaction`**: Tracks the external provider's lifecycle. `provider_order_id` and `state`.
- **`payments_webhook_log`**: An immutable audit log of every webhook received by the platform, capturing the raw JSON payload and signature validity to aid debugging and compliance.

### Finance Domain
- **`finance_ledger_entry`**: The double-entry accounting backbone. 
- **`finance_settlement`**: Tracks batched payouts to the restaurants.

### Catalog Domain
- **`catalog_menu_item`**: Stores definition, metadata, and base price. Links to `catalog_item_type`.
- **`catalog_addon`**: Global addons linking to menu items via the junction table `catalog_menu_item_addon`.
