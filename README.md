# Dineflow — Real-Time Multi-Tenant Food & Beverage Operating Platform

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-Pub%2FSub-DC382D?style=flat&logo=redis&logoColor=white)](https://redis.io/)
[![WebSockets](https://img.shields.io/badge/WebSockets-Django_Channels-092E20?style=flat)](https://channels.readthedocs.io/)
[![Razorpay](https://img.shields.io/badge/Payments-Razorpay_UPI-0C2340?style=flat&logo=razorpay&logoColor=white)](https://razorpay.com/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-38B2AC?style=flat&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)

> **A production-ready, multi-tenant digital ordering, real-time Kitchen Display System (KDS), and financial accounting platform built for cafes and multi-outlet food & beverage brands.**

---

## ⚡ Executive Summary

Dineflow is an end-to-end cafe & restaurant operations platform engineered to solve real-world F&B challenges: eliminating paper tickets, preventing overselling during rush hours, guaranteeing payment settlement accuracy, and routing orders seamlessly across **Dine-In (QR Table Ordering)**, **Takeaway (Counter Parcel)**, and **Direct Delivery**.

Built with a high-concurrency architecture using **Django 5.2 (ASGI/Daphne)**, **PostgreSQL row-level locking (`SELECT FOR UPDATE`)**, **Redis Pub/Sub WebSockets**, and **Razorpay webhook ingestion**, the system handles peak rush volumes while maintaining zero inventory drift and bank-grade auditability.

---

## 🚀 Live Demo & Links

- **Live Application**: [https://your-demo-url.com](https://your-demo-url.com)
- **Browse Source Code**: (https://github.com/Reddykesava60/OrderFlow)
- **Demo Credentials**:
  - **Platform Admin**: `admin@platform.com` / `admin123`
  - **Store Manager (Owner)**: `owner@cafe.com` / `owner123`
  - **Kitchen / Barista Staff**: `barista@cafe.com` / `staff123`
  - **Customer QR Menu**: Scan table QR or visit `/r/blue-tokai-demo/`

---

## 🏗️ Architecture & System Design

```mermaid
flowchart TD
    subgraph ClientLayer ["Client & PWA Layer"]
        Customer["Customer Smartphone<br/>(QR Menu / Cart / UPI / Tracking)"]
        KDS["Kitchen / Barista Tablet<br/>(Alpine.js + Live WebSockets)"]
        Owner["Store Manager Dashboard<br/>(Live Sales / Stock / Reconciliation)"]
    end

    subgraph Gateway ["Reverse Proxy & Web Server"]
        Daphne["Daphne ASGI Server<br/>(HTTP + WebSockets)"]
    end

    subgraph DjangoApps ["Dineflow Core Engine"]
        Core["core<br/>Tenancy, Auth, Menu Catalog"]
        Ordering["ordering<br/>Pricing, Stock Locking, State Machines"]
        KitchenApp["kitchen<br/>KDS Queue, Payment Events"]
        Ledger["finance & ledger<br/>Double-Entry Bookkeeping"]
    end

    subgraph AsyncAndData ["Data & Messaging Layer"]
        PG[(PostgreSQL Database<br/>Row-Level Locks)]
        Redis[(Redis<br/>Channel Layer & Celery Broker)]
        CeleryWorker["Celery Workers<br/>Async Webhooks & Reconciliation"]
        RazorpayGateway["Razorpay Gateway<br/>(UPI Intent / Dynamic QR)"]
    end

    Customer -->|HTTP POST Checkout| Daphne
    KDS <-->|Persistent WebSocket /ws/kds/| Daphne
    Owner -->|HTTP Management| Daphne

    Daphne --> DjangoApps
    Ordering -->|Pessimistic Locking| PG
    Ordering -->|Broadcast Event| Redis
    Redis -->|Push Update < 1s| KDS
    Customer -.->|Approve UPI| RazorpayGateway
    RazorpayGateway -->|Signed Webhook| Ordering
    Ordering -->|Enqueue Task| CeleryWorker
    CeleryWorker -->|Record Transaction| Ledger
```

---

## 🌟 Key Engineering Features

### 1. Frictionless Customer Ordering (Zero App Download)
- **Instant Table QR Ordering**: Customers scan a table QR code and land on an ultra-lightweight mobile web app.
- **Multi-Channel Fulfillment**:
  - **Dine-In**: Bound to specific table numbers with live status tracking.
  - **Takeaway / Parcel**: Separate packing flags per item with counter pickup queues.
  - **Direct Delivery**: Collects recipient contact and destination address with real-time delivery status updates.
- **Customizable Menu Matrix**: Per-item modifier add-ons, quantity selectors, dietary tagging, and spice/customization levels.

### 2. Dual-State Machine Architecture (Orders vs. Payments)
To prevent split-brain issues where kitchen orders drift from payment states, the system isolates customer order fulfillment from financial transactions via two formal state machines:
- **`Order.Status` State Machine**: `UNPAID` ➔ `PENDING` ➔ `PREP_STARTED` ➔ `COMPLETED` (or `CANCELLED`). Order-level states are dynamically *derived* from item preparation statuses via `sync_order_status()`.
- **`PaymentTransaction.state` State Machine**: Strictly regulated transitions (`PENDING`, `INITIATED`, `PROCESSING`, `PAID`, `FAILED`, `EXPIRED`, `REFUNDED`) enforced by a transition matrix.

### 3. Concurrency-Safe Inventory & Stock Locking
- **Zero Race Conditions**: During rush hours, concurrent checkouts for finite stock items use **PostgreSQL pessimistic row locking (`SELECT FOR UPDATE`)** inside atomic database transactions (`transaction.atomic()`).
- **Short-Lived Stock Holds (`StockReservation`)**: Inventory is reserved for up to 15 minutes during UPI handoff. If the customer abandons the session, background tasks automatically release reserved units back into available stock.

### 4. Real-Time Kitchen Display System (KDS)
- **Sub-Second Ticket Routing**: Real-time order dispatch using **Django Channels WebSockets** backed by **Redis Pub/Sub**.
- **Resilient Push-Tells-You-To-Pull Design**: The WebSocket frame acts as an ultra-fast trigger (`kds.refresh`), prompting the client to fetch authoritative state over REST (`GET /api/kds/poll/`). If connection drops, Alpine.js handles automated reconnection, backoff, and visibility re-hydration.
- **Multi-Station Filtering**: Kitchen screens can filter tickets by prep station (e.g., Espresso Bar, Bakery, Hot Kitchen).
- **Dedicated Delivery & Cash-on-Delivery (COD) Queue**: Delivery orders feature live phone dials (`tel:`) and distinct visual triggers:
  - Prepaid orders show **"Mark Delivered"**.
  - COD orders show an amber-highlighted **"Collect Cash & Deliver"** action to ensure staff collect funds before closing the ticket.
  - Delivery cash orders are intelligently exempt from short counter auto-cancellation timers.

### 5. Bank-Grade Financial Ledger & Multi-Party Accounting
Every single financial fact is append-only, irreversible, and immutable:
- **Strict Double-Entry Bookkeeping**: `JournalEntry` and `JournalLine` balance across Asset (`ASSET_CASH_IN_TRANSIT`), Revenue (`REVENUE_PLATFORM_FEE`), and Liability (`LIABILITY_MERCHANT_BALANCE`) accounts—strictly rejecting any write that does not balance to `₹0.00`.
- **Three-Tier Operational Ledger**:
  1. `RestaurantLedger`: Real-time operational balance supporting gross credits, fee debits, and payout settlements.
  2. `PlatformFeeRecord`: Immutable snapshot of commission rates (percentage, fixed, or hybrid) per transaction.
  3. `Customer Ledger (Post-Payment Tab)`: Dedicated credit account ledger for corporate clients/regular guests secured with hashed PINs, credit limit validation, and itemized fee billing.

### 6. Robust Payment Integrations & Late-Capture Recovery
- **Razorpay Dual-Path Verification**: Combines instantaneous client verification for UI responsiveness with authoritative, cryptographically signed (`HMAC-SHA256`) server-to-server webhook ingestion.
- **UPI Late-Capture Recovery**: Built specifically for India's NPCI network behaviors. If a UPI transaction reports an initial client timeout but succeeds minutes later, the system gracefully recovers the order from `CANCELLED` back to `PENDING` if stock is available, or marks it for operator reconciliation if stock was exhausted.

---

## 🛠️ Tech Stack

| Domain | Technology / Library | Architectural Role |
|---|---|---|
| **Backend Framework** | **Python 3.13 / Django 5.2** | Monolithic modular service layer, ORM, Admin Engine |
| **Realtime Engine** | **Django Channels 4.2 / Daphne** | WebSockets for sub-second KDS order dispatch |
| **Relational Database**| **PostgreSQL 16** | Strict transactional integrity, row-level concurrency locking |
| **Caching & Messaging**| **Redis 7** | Channel layer backplane, session caching, Celery task broker |
| **Task Queue** | **Celery 5.4 + Celery Beat** | Asynchronous webhook processing, scheduled inventory sweeps |
| **Payment Gateway** | **Razorpay API + Webhooks** | UPI Intent, Dynamic QR, webhook signature validation |
| **Frontend UI** | **Tailwind CSS + Alpine.js** | Ultra-responsive, mobile-first, zero-framework-bloat frontend |
| **Deployment / CI** | **Docker, Gunicorn/Daphne, Nginx** | Production containerization & reverse proxy |

---

## 📂 Project Structure & App Boundaries

```text
├── core/                   # Tenancy, User Auth, Menu Catalog & Double-Entry Journal
│   ├── models.py           # Restaurant, RestaurantConfig, MenuItem, JournalEntry
│   ├── ledger.py           # Strict double-entry balance validation engine
│   └── admin.py            # Platform-level master controls & revenue telemetry
│
├── ordering/               # Checkout, Payments, Inventory & Order State Machine
│   ├── checkout/           # Pricing engine, atomic stock decrement & order placement
│   ├── inventory/          # Concurrency locks (SELECT FOR UPDATE) & StockReservations
│   ├── orders/             # Order state transitions, cash confirm, platform fees
│   ├── payments/           # Razorpay webhooks, signature verification, late recovery
│   └── ledger/             # Operational restaurant ledger & customer credit tabs
│
├── kitchen/                # Kitchen Display System (KDS) & Realtime Telemetry
│   ├── consumers.py        # Authenticated WebSocket consumer with rate-limiting
│   ├── views.py            # Optimized KDS polling endpoints & station aggregation
│   └── templates/kitchen/  # Responsive Alpine.js KDS interface
│
├── owner/                  # Store Manager Portal & Analytics
│   ├── views/              # Live sales analytics, inventory toggles, staff management
│   └── templates/owner/    # Responsive management dashboards & reconciliation views
│
└── docs/                   # Exhaustive Architecture & Engineering Documentation
    ├── engineering/        # In-depth specs: lifecycle, financial ledger, security
    └── operations/         # Production deployment & incident playbooks
```

---

## ⚙️ Local Development Setup

### Prerequisites
- Python 3.12+ or 3.13
- PostgreSQL & Redis (local or cloud instances)

### 1. Clone the repository
```bash
git clone https://github.com/your-username/dineflow.git
cd dineflow
```

### 2. Create and activate a virtual environment
```bash
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
```bash
cp .env.example .env
```
Fill in your credentials in `.env`:
```env
SECRET_KEY=your-secure-secret-key
DEBUG=True
DATABASE_URL=postgres://user:password@localhost:5432/dineflow_db
REDIS_URL=redis://127.0.0.1:6379/0
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_key_secret
```

### 5. Run migrations & seed data
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 6. Start the ASGI development server
```bash
python manage.py runserver --settings=dineflow.settings.dev
```

Open `http://127.0.0.1:8000/` in your browser.

---

## 🧪 Production Readiness & Security Highlights

- **Idempotent Requests**: Checkout and webhook endpoints use unique idempotency keys to prevent duplicate billing during client reconnects.
- **Strict Rate Limiting**: Redis-backed rate limiting on checkout endpoints, PIN verification, receipt lookups, and WebSocket frames (`4029` throttle termination).
- **Granular Role-Based Access Control (RBAC)**: Role separation (`OWNER` vs `STAFF`) with isolated permissions for cash collection and order completion.
- **Fail-Safe Realtime Degradation**: If Redis or WebSockets encounter network interruptions, the application automatically falls back to debounced REST polling without interrupting payment captures.
- **Comprehensive Audit Trail**: `PaymentEvent` and `OwnerAuditLog` maintain immutable records of every operational action.

---

