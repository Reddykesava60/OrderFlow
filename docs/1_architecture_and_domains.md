# Core Architecture & App Contexts

## Architectural Pattern: Modular Django Application
The application adopts a standard Django app structure (Model-Template-View) with decoupled boundary logic. While running within a single Django process, the application is divided into cohesive core apps.

### Key Principles
1. **Vertical Slicing**: Each app owns its models, services, templates, and URLs.
2. **Standard Django MTV**: The application uses traditional Django Views, Forms, and Templates for the UI, alongside JSON-returning endpoints for client-side interactions.
3. **Decoupled Side Effects**: Side effects such as real-time WebSocket KDS updates and background webhook processing are decoupled from the main request/response cycle using Django Channels and Celery tasks.

## Core Apps
| App | Responsibility | Interacts With |
|--------|----------------|----------------|
| **core** | Identity (Users), Tenants (Restaurants), Catalog (MenuItems, AddOns), Platform Settings, Simple Ledger (`LedgerEntry`) | Independent |
| **ordering** | Sales Checkout, Inventory Reservation, Order State Machine, Payment Webhook Dead Letter Queue (DLQ) | Core (via DB constraints & signals) |
| **kitchen** | Real-time KDS APIs, WebSocket endpoints, Payment Observability (`PaymentEvent`) | Ordering (Order status), Core (Tenants) |
| **owner** | Operations dashboards for restaurant managers, decomposed into `views` package (`dashboard`, `auth`, `menu`, `staff`, `settings`, `reports`) | Core, Ordering |

## The Service Layer & Domain Boundaries
Business logic is strictly decoupled from the views and extracted into discrete service boundaries.
In `ordering`, this takes the form of:
- `ordering/checkout/services.py`: Handles cart validation, pricing logic, and initial DB writes.
- `ordering/inventory/services.py`: Manages finite stock decrements and `StockReservation` locks.
- `ordering/orders/services.py`: Manages payment confirmations, status synchronization, and expiration handlers.
- `ordering/payments/services.py`: The single source of truth for handling Razorpay webhooks, idempotency, and exact-amount payment verification.

## Decoupling via Domain Events
To prevent circular dependencies and tight coupling, the system makes heavy use of **Django Signals as Domain Events** for side effects that don't need to be strictly atomic with the payment transaction:
- `order_paid` (Used to trigger secondary non-critical receipts or notifications)
- `order_cancelled`
- `inventory_released` (Used to automatically make items visible again on the menu when stock is returned)

*Note*: Critical financial operations (like `RestaurantLedgerService().record_payment()`) are called *directly* inside the same atomic database transaction as the order status update. This guarantees that an order cannot be marked as PAID without the ledger simultaneously recording the revenue.

## Extensibility
Background processing is handled by Celery workers, and WebSocket traffic is managed by Django Channels with a Redis channel layer. This allows scaling specific application slices by routing WebSocket traffic (e.g., `/api/kitchen`) to specialized ASGI nodes, while Celery workers handle background payment reconciliation and Dead Letter Queue retries.
