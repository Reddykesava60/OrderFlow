# Codebase Map

A guide to where things live, written so you can answer "where would I add
X?" without grepping the whole repo first.

## Top-level layout

```
dineflow/          Django project shell: settings, URL root, ASGI/WSGI entry points, Celery app
core/               Tenants, users, catalog, platform settings, the financial ledger
ordering/           Checkout, inventory, order state, payments, webhooks
kitchen/            Kitchen Display System (KDS): REST + WebSocket
owner/              Restaurant manager dashboards
infrastructure/     Currently empty — reserved for cross-cutting infra code
supabase/           Supabase Edge Functions and one-off SQL run directly against the database
nginx/              Reverse proxy config for the VPS/Docker Compose deployment path
docker/             Container entrypoint script
scripts/            Operational shell scripts (backup, deploy, server hardening)
templates/          Global templates not owned by a specific app (404 page, landing page)
docs/               You are here
```

## `dineflow/` — the project shell

| File | Purpose |
|---|---|
| `settings/base.py` | Settings shared by every environment |
| `settings/dev.py` | Local development overrides (SQLite, relaxed security) |
| `settings/prod.py` | Production overrides (Postgres SSL, Celery broker config, security headers enforced, fails fast if Razorpay is half-configured) |
| `settings/test.py` | Test-runner overrides |
| `urls.py` | The root URL table — see the routing table below |
| `celery.py` | Celery app instance, task logging hooks |
| `asgi.py` / `wsgi.py` | Entry points for the ASGI (WebSocket-capable) and WSGI servers |

## `core/` — identity, tenants, catalog, ledger

| File | Purpose |
|---|---|
| `models.py` | `Restaurant`, `RestaurantConfig`, `RestaurantPaymentConfig`, `PlatformSettings`, `User`, `Customer`, `MenuItem`, `AddOn`, `MenuItemAddOn`, `PlatformFeeRecord`, `OwnerAuditLog`, `MonthlyPlatformFeeStatement`, and the ledger models (`MerchantLedgerBalance`, `JournalEntry`, `JournalLine`, `SettlementBatch`, `SettlementRecord`) |
| `ledger.py` | `LedgerService` — the double-entry bookkeeping engine. See [Financial Ledger](./05-financial-ledger.md) |
| `mixins.py` | Reusable view mixins (e.g., permission checks for staff actions) |
| `middleware.py` | Security headers, forced password-change redirect |
| `hashers.py` | Custom password hasher used for customer PINs |
| `ratelimit.py` | Rate-limiting decorator used on sensitive endpoints |
| `storage.py` | Supabase Storage integration for images |
| `services.py` | Small cross-cutting helpers that don't belong to a specific domain |
| `views_admin.py`, `views_ops.py` | The `/admin/kds-metrics/` and `/admin/ops/` internal dashboards |
| `management/commands/sync_monthly_statements.py` | CLI entry point for the same job Celery Beat runs hourly |

## `ordering/` — the busiest app, split into sub-packages

| Sub-package | Owns |
|---|---|
| `checkout/services.py` | Cart validation, server-side pricing, resolving which payment config applies, creating `Order` rows for cash/UPI/post-payment |
| `inventory/services.py` | Locking and decrementing `MenuItem`/`AddOn` stock, `StockReservation` creation and release |
| `orders/services.py` | Order-side transitions — confirming cash payments, expiring overdue unpaid orders, computing the per-order platform fee, syncing order status from payment status |
| `payments/` | Everything about talking to payment gateways — see the breakdown below |
| `ledger/services.py` | A lighter-weight, order-scoped ledger helper that sits alongside `core.ledger` |

`models.py` at the `ordering/` root holds `Order`, `OrderItem`,
`OrderItemAddOn`, `StockReservation`, `RestaurantOrderCounter`, plus the
payment-related models (`PaymentTransaction`, `TenantPaymentConfig`,
`WebhookLog`) and the `PaymentState` enum + transition table.

### `ordering/payments/` in detail

| File | Purpose |
|---|---|
| `services.py` | `PaymentOrchestratorService` (creates gateway orders), `PaymentVerificationService` (the synchronous fast-path check after checkout), `PaymentMutationService` (the single place that actually moves a `PaymentTransaction` through its state machine), `WebhookIngestionService` (validates + stores incoming webhooks), `PaymentReconciliationService` (polls the gateway for stuck transactions), `PaymentRetryService` |
| `resolver.py` | Decides which payment credentials apply to a given restaurant — see [Payments & Webhooks](./06-payments-and-webhooks.md) |
| `providers.py` | Gateway-specific API calls (currently Razorpay) |
| `state_machine.py` | `PaymentStateMachine` — enforces the `PAYMENT_STATE_TRANSITIONS` table from `models.py` |
| `jobs.py` | Every Celery task related to payments — see [Background Jobs](./08-background-jobs.md) |
| `contracts.py` | Shared dataclasses (`ResolvedPaymentConfig`) and exception types used across the payments code |
| `interfaces.py` | Abstract base for what a "provider" must implement |
| `crypto.py` | Encrypts/decrypts stored gateway secrets |
| `upi.py` | UPI-specific helpers |
| `views.py` | `WebhookIngressView`, `PaymentStatusView`, `PaymentRetryView` |

### `ordering/management/commands/`

CLI wrappers around the same logic Celery runs on a schedule — useful for
manually triggering a job, or running it in an environment without a
working Celery broker. `replay_webhook.py` and `fix_webhook_zombies.py` are
specifically there for incident response — see
[Incident Playbook](../operations/03-incident-playbook.md).

## `kitchen/` — the KDS

| File | Purpose |
|---|---|
| `models.py` | `PaymentEvent` — the append-only diagnostic timeline of a payment's lifecycle |
| `views.py` | `KDSView` (the shell page), `KDSPollView` (REST hydration endpoint), and the per-ticket action endpoints (start prep, complete, cash collect) |
| `consumers.py` | `KDSWebsocketConsumer` — the live push channel |
| `routing.py` | WebSocket URL routing, wired into `dineflow/asgi.py` |
| `services.py` | `trigger_kds_refresh()` and the payment-update broadcaster called by `ordering` after a state change commits |

## `owner/` — restaurant manager dashboards

| File | Purpose |
|---|---|
| `views/auth.py` | Login, logout, forced password change, MFA setup/verify |
| `views/dashboard.py` | Main dashboard, reconciliation screen |
| `views/menu.py` | Menu item / add-on / category CRUD |
| `views/staff.py` | Staff account management, permission toggles |
| `views/settings.py` | Restaurant config, QR code download |
| `views/reports.py` | Owner-facing order receipts |
| `views_customers.py` | Customer accounts (for the post-payment/tab feature) |

## URL routing, top to bottom

All routing fans out from `dineflow/urls.py`:

| Prefix | App | Audience |
|---|---|---|
| `/` | `dineflow` | Public landing page, health checks |
| `/admin/` | Django admin | Platform operators |
| `/admin/kds-metrics/`, `/admin/ops/` | `core` | Internal dashboards |
| `/r/` | `ordering` | Public, no login — the customer-facing menu and checkout |
| `/payments/` | `ordering` (payments sub-package) | Public — Razorpay webhook + payment status polling |
| `/api/` | `kitchen` | Session-authenticated kitchen staff |
| `/owner/` | `owner` | Session-authenticated restaurant managers |

## Tests

Each app keeps its tests in a `tests.py` at its root (`core/tests.py`,
`ordering/tests.py`, `kitchen/tests.py`, `owner/tests.py`). `ordering/tests.py`
is by far the largest, reflecting how much of the system's risk lives in
checkout, inventory, and payments.

## Next

[Data Model](./03-data-model.md) goes one level deeper into the actual
database tables.
