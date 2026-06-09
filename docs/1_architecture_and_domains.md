# Core Architecture & Domain Contexts

## Architectural Pattern: Domain-Driven Modular Monolith
The Greenfield application adopts a strict Modular Monolith architecture. While running within a single Django process, the application is divided into highly cohesive, loosely coupled Bounded Contexts (domains). 

### Key Principles
1. **Vertical Slicing**: Each domain owns its models, use cases (services), schemas, and API routers.
2. **Soft Inter-Domain References**: Domains do not use explicit database Foreign Keys to reference entities in other domains. Instead, they use `models.UUIDField()` soft references (e.g., `restaurant_id`). This guarantees that domains can be extracted into separate microservices in the future without tearing apart the database schema.
3. **Synchronous Internal Event Bus**: Side effects are completely decoupled using `shared/event_bus.py`. Instead of the `sales` domain importing `finance` to generate ledger entries, it publishes an `OrderPaidEvent`. The `finance` domain subscribes to this event and handles it.

## Bounded Contexts
| Domain | Responsibility | Interacts With |
|--------|----------------|----------------|
| **identity** | Users, Authentication, Roles | Independent |
| **operations**| Restaurant configuration, Tenants | Identity (owner role) |
| **catalog** | Menu items, categories, Addons, Inventory Ledger | Operations (tenant ID) |
| **customers** | CRM, Customer balances, Counters | Operations (tenant ID) |
| **sales** | Checkout, Cart Validation, Orders, Line items | Catalog (pricing/stock), Payments (intent) |
| **payments** | Gateway integrations (Razorpay), Webhooks | Operations (config), Sales (order state) |
| **finance** | Double-Entry Ledger, Platform Fees, Settlements | Sales (Order revenue) |
| **kitchen** | KDS, WebSockets, Prep States | Sales (ticket status) |

## The Service Layer (Use Cases)
Controllers and views (Django Ninja endpoints) are intentionally thin. They map HTTP requests to DTOs and invoke Use Cases.
The Use Cases (e.g., `PlaceOrderUseCase`, `PaymentUseCases`) encapsulate all business rules, orchestration, and database transactions.

## Extensibility
The modular setup ensures that when specific domains require scaling (for instance, the Kitchen WebSocket servers), that specific application slice can be deployed on specialized compute nodes by configuring the HTTP load balancer to route `/api/kitchen` traffic to those nodes.
