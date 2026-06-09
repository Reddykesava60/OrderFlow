# Order-Flow Developer Onboarding Guide

Last updated: 2026-05-08

Welcome to the Order-Flow Engineering team! This guide outlines your first week, local environment setup, and the core concepts you need to grasp before submitting your first Pull Request.

## 1. Day One: Environment Setup

Order-Flow requires a standard Python/PostgreSQL stack.

### Prerequisites
1. **Python 3.10+**: Ensure `python --version` is at least 3.10.
2. **PostgreSQL 15+**: Run locally, or install the [Supabase CLI](https://supabase.com/docs/guides/cli) to spin up an identical local replication of our production DB.
3. **Redis**: Required for Django Channels (WebSockets).

### Bootstrapping (Docker — Recommended)
```bash
git clone git@github.com:Order-Flow/Order-Flow.git
cd Order-Flow

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL and SECRET_KEY

# Build and start
docker compose up --build -d

# Create your admin user
docker compose exec web python manage.py createsuperuser

# Access at http://localhost:8000
```

### Bootstrapping (Manual — Without Docker)
```bash
git clone git@github.com:Order-Flow/Order-Flow.git
cd Order-Flow

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, SECRET_KEY, etc.

# Database setup
python manage.py migrate
python manage.py createsuperuser

# Start dev server
python manage.py runserver
```

## 2. Day Two: Core Concepts to Learn

Before touching the codebase, you must understand these 3 paradigms:

1. **Modular Monolith Boundaries**: Code is split into `core`, `ordering`, `kitchen`, and `owner`. Read `docs/ARCHITECTURE.md`.
2. **WebSocket-Triggered Polling**: The KDS does *not* receive order data over WebSockets. It receives a ping and executes a `fetch()`. Read `docs/SYSTEM_DESIGN.md`.
3. **Idempotency**: Learn how `idempotency_key` and `select_for_update()` prevent race conditions. Read `docs/SECURITY_REVIEW.md`.

## 3. Day Three: The "Safe" vs "Danger" Zones

### 🟢 Safe Zones (Great for First Tickets)
- **`owner/templates/`**: Modifying HTML, adding Tailwind classes, or tweaking the owner dashboard layout.
- **`core/models.py`**: Adding simple new fields (e.g., a "description" field to `ItemType`), provided you write the corresponding migration.
- **`owner/views.py`**: Adding new reporting endpoints or CSV exports.

### 🔴 Danger Zones (Require Senior Sign-off)
- **`ordering/payments/services.py` and `ordering/views.py`**: If you break webhook ingestion or payment mutation, restaurants will stop getting paid.
- **`ordering/services.py`**: The state machines here (`confirm_cash_payment`) contain critical database locks. 
- **`kitchen/views.py`**: The `KDSPollView` payload is heavily optimized to avoid N+1 queries. Modifying the `Prefetch` tree here can accidentally take down the database.

## 4. Debugging Tips

* **Tailwind styles not applying**: TailwindCSS is loaded via the browser CDN (`cdn.tailwindcss.com`). No local build step or CLI watcher is needed. If styles look wrong, ensure you have an internet connection and check the browser's Network tab for CDN errors.
* **KDS isn't receiving WebSockets**: Ensure your local Redis server is actually running and `CHANNEL_LAYERS` in `settings/prod.py` points to it. In dev mode (`settings/dev.py`), the `InMemoryChannelLayer` is used — this works only in single-worker mode.
* **IntegrityError on Checkout**: You probably submitted an order with an `idempotency_key` that already exists in your local DB. Clear your local storage/cookies.

## 5. Your First PR Checklist
- [ ] Did you read `docs/CONTRIBUTING.md`?
- [ ] Did you test your changes logging in as both an `OWNER` and a `STAFF` member to ensure RBAC isn't broken?
- [ ] Did you run `python manage.py makemigrations` and commit the migration file if you changed a model?
- [ ] Did you request a review from the Code Owner of the modified module?
