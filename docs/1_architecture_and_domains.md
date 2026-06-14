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
| **core** | Identity (Users), Tenants (Restaurants), Catalog (MenuItems, AddOns), Platform Settings | Independent |
| **ordering** | Sales (Orders, Line Items, Stock Reservations), Payments (Transactions, Webhooks), Finance (Ledger Entries, Settlements) | Core (Pricing/Stock, Tenants) |
| **kitchen** | Real-time KDS APIs, WebSocket endpoints, Payment Observability (`PaymentEvent`) | Ordering (Order status), Core (Tenants) |
| **owner** | Dashboard and reporting views for restaurant operators | Core, Ordering |

## The Service Layer
Controllers and views are kept intentionally thin. They map HTTP requests to services located in `services.py` modules within each app.
These services (e.g., `PaymentMutationService`, `WebhookIngestionService`) encapsulate business rules, orchestration, and database transactions.

## Extensibility
Background processing is handled by Celery workers, and WebSocket traffic is managed by Django Channels with a Redis channel layer. This allows scaling specific application slices by routing WebSocket traffic (e.g., `/api/kitchen`) to specialized ASGI nodes, while Celery workers handle background payment reconciliation.
