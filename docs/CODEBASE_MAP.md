# Order-Flow Codebase Map

Last updated: 2026-05-14

This document provides a high-level cartography of the Order-Flow repository. It is designed to help new engineers rapidly locate business logic, infrastructure bindings, and frontend assets.

## Directory Structure

```text
Order-Flow/
├── .env.example             # Template for local environment secrets
├── .gitignore               # Comprehensive ignore rules (secrets, bytecode, IDE, OS)
├── .dockerignore            # Docker build context exclusions
├── Dockerfile               # Multi-stage production container build
├── docker-compose.yml       # Production stack (web, redis, nginx, cron)
├── docker-compose.override.yml  # Development overrides (hot reload, direct port)
├── manage.py                # Django CLI entrypoint
├── requirements.txt         # Python package dependencies (organized by category)
│
├── dineflow/                # Project Root (Configuration)
│   ├── asgi.py              # ASGI entrypoint for HTTP + WebSockets (Channels)
│   ├── wsgi.py              # WSGI entrypoint for HTTP (fallback)
│   ├── urls.py              # Global URL router (includes /healthz/ endpoints)
│   └── settings/            # Settings module
│       ├── base.py          # Shared: DB, middleware, LOGGING, STORAGES, auth
│       ├── dev.py           # Development: DEBUG=True, InMemoryChannelLayer
│       └── prod.py          # Production: Redis cache/channels, HSTS, secure cookies
│
├── docker/                  # Container scripts
│   └── entrypoint.sh        # DB wait → migrate → collectstatic → Daphne
│
├── nginx/                   # Reverse proxy configuration
│   └── nginx.conf           # Rate limiting, WebSocket proxy, security headers
│
├── core/                    # [MODULE] Foundation & Base Entities
│   ├── models.py            # User, Restaurant, Config, PlatformSettings
│   ├── mixins.py            # RBAC and AuthZ view mixins
│   ├── admin.py             # Global superuser dashboard (payment secrets masked)
│   ├── ratelimit.py         # App-level rate limiting decorator
│   └── storage.py           # Supabase Storage integration
│
├── ordering/                # [MODULE] Cart, Checkout & Payments
│   ├── models.py            # Order, OrderItem, payment transactions, ledger entries
│   ├── services.py          # Checkout orchestration, balance logic, Razorpay flows
│   ├── payments/            # Provider-agnostic payment orchestration and webhook processing
│   ├── views.py             # Public checkout flow + legacy Razorpay webhook shim
│   └── management/commands/ # release_expired_reservations (cron job)
│
├── kitchen/                 # [MODULE] Kitchen Display System (KDS)
│   ├── consumers.py         # WebSocket connections (Django Channels)
│   ├── services.py          # Cache invalidation & WS triggers
│   ├── views.py             # High-performance JSON polling endpoints
│   └── templates/           # Alpine.js reactive frontend UI
│
├── owner/                   # [MODULE] Admin Dashboard
│   ├── views.py             # SSR views for reporting and management
│   ├── views_customers.py   # Customer management views
│   └── templates/           # Jinja-style HTML templates
│
├── supabase/                # Infrastructure-as-Code (IaC)
│   └── migrations/          # Raw SQL schema backups & functions
│
├── static/                  # Shared public assets
│   └── landing/             # Landing page assets
│
└── docs/                    # Enterprise Documentation
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT_GUIDE.md
    ├── DOCKER_DEPLOYMENT.md
    ├── SECURITY_REVIEW.md
    ├── RUNBOOK.md
    ├── ONBOARDING_GUIDE.md
    └── ...
```

## Critical Execution Paths

### 1. The Checkout Flow (`ordering/views.py`)
If you need to debug a customer order creation or payment failure, start at `checkout(request, slug)`. This view handles:
1. Validating the restaurant is accepting orders.
2. Checking inventory (`StockReservation`).
3. Calculating totals and platform fees.
4. Generating a Razorpay `order_id` and rendering the checkout template.

### 2. The Payment Webhook (`ordering/payments/services.py` + `ordering/views.py`)
This is the most critical financial code in the system. Razorpay sends an asynchronous `POST` request through the provider-specific webhook ingress.
- Look at `WebhookIngestionService.receive()` and `PaymentMutationService.apply_provider_event()`.
- The legacy Razorpay path in `ordering/views.py` now forwards to the unified ingestion pipeline.
- It deduplicates provider events, verifies signatures, locks payment rows, and writes the accounting records atomically.

### 3. The KDS Real-Time Update (`kitchen/views.py` & `kitchen/consumers.py`)
If orders are not appearing on the kitchen screen:
1. Trace `trigger_kds_refresh(restaurant_id)` in `kitchen/services.py`. This is called immediately after a webhook confirms payment.
2. This hits the Redis channel group.
3. The frontend (Alpine.js inside `kitchen/templates/kitchen/kds.html`) receives a `refresh` WS message.
4. The frontend fetches `/api/kds/poll/` which maps to `KDSPollView` in `kitchen/views.py`.

## Dead Code & Legacy Modules
*Currently, there are no deprecated modules.* All modules are actively maintained.

## Platform Abstractions
- **`core.mixins.py`**: This file contains the "Authorization Gateways". Before creating any new View, ensure it inherits from the appropriate Mixin (e.g., `ActiveStaffMixin`, `OwnerRequiredMixin`). Never manually check `request.user.is_owner` inside a `get()` method.
