# Dineflow: Production Restaurant Operating System

Dineflow is a robust, production-grade restaurant operating system built with Django. It manages multi-tenant restaurant configurations, ordering and checkout flows, inventory tracking, financial double-entry ledger bookkeeping, and real-time Kitchen Display Systems (KDS).

## Core Technologies
- **Backend**: Django 5.x
- **Database**: PostgreSQL (Production) / SQLite (Local Dev)
- **Real-Time**: Django Channels & Redis (for KDS WebSockets)
- **Background Tasks**: Celery & Redis
- **Payment Processing**: Razorpay

## Architectural Domains

The application is heavily modularized to maintain strict domain boundaries:

1. **`core` App**: 
   - Handles multi-tenant identity (`Restaurant`), Users, and global catalogs (`MenuItem`, `AddOn`).
   - Contains the **Double-Entry Financial Ledger** (`core/ledger.py`) acting as the ultimate source of truth for restaurant payouts and platform fees.
2. **`ordering` App**: 
   - **Checkout** (`ordering/checkout/services.py`): Cart validation, pricing, and initial order creation.
   - **Inventory** (`ordering/inventory/services.py`): Stock reservation locks, decrementing, and auto-availability toggles.
   - **Orders** (`ordering/orders/services.py`): Webhook validations, payment captures, state machine transitions, and expirations.
   - **Payments** (`ordering/payments/`): Webhook ingest, signature validation, and the Dead Letter Queue (DLQ).
3. **`owner` App**: 
   - Operations dashboards for restaurant managers, decomposed into `dashboard`, `auth`, `menu`, `staff`, `settings`, and `reports` views.
4. **`kitchen` App**:
   - Real-time Kitchen Display System (KDS) powered by Django Channels and React/Alpine.js.

## Immutable Data and Auditing
The system enforces strict immutability for critical paths:
- Financial records are tracked via append-only `JournalEntry` and `JournalLine` models.
- Payment lifecycles are tracked via `PaymentEvent`.
- Webhooks are stored completely in `WebhookLog` before processing, allowing deterministic replays of failed payloads.
- Staff actions (menu changes, refunds) are tracked in `OwnerAuditLog`.

## Local Setup

1. **Environment Setup**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configuration**:
   Copy `.env.example` to `.env` and fill in necessary Redis/Postgres/Razorpay keys.
3. **Database**:
   ```bash
   python manage.py migrate
   ```
4. **Run Server**:
   ```bash
   python manage.py runserver
   ```
5. **Run Workers** (requires Redis):
   ```bash
   celery -A dineflow worker -l info
   ```

For detailed internal documentation, see the `/docs/` directory.
