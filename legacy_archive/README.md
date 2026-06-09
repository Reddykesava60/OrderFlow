# Order-Flow Platform

Order-Flow is a multi-tenant restaurant ordering and Kitchen Display System (KDS) platform built on Django. It covers guest QR ordering, owner menu operations, staff kitchen queues, cash/UPI payment workflows, and payment reconciliation.

![Order-Flow Architecture Overview](https://img.shields.io/badge/Architecture-Modular_Monolith-blue)
![Django Version](https://img.shields.io/badge/Django-5.2-0C4B33?logo=django)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-336791?logo=postgresql)

## Production Posture

Order-Flow is structured like an operational SaaS codebase:

- Split Django settings for development, tests, and production.
- Live and ready health endpoints for deployment probes.
- Tenant-scoped restaurant, staff, customer, order, and payment models.
- Idempotency guards for order/payment creation.
- Role-based owner and staff access control.
- Payment webhook verification, replay protection, retries, expiry jobs, and reconciliation commands.
- Docker, Railway, Supabase, Redis, and Celery deployment paths.
- Security headers, secure cookies, HSTS, CSP controls, upload limits, and password policies.

The internal Django project package is still named `dineflow` to avoid a risky import-path migration. Product-facing names, docs, templates, admin chrome, and payment notes use `Order-Flow`.

## Core Capabilities

- Multi-tenant restaurant management.
- QR menu ordering with item, add-on, stock, and image support.
- Real-time KDS through Django Channels and Redis-backed channel layers in production.
- Cash, UPI, Razorpay, and provider-agnostic payment orchestration.
- Customer accounts, ledgers, balances, and platform fee records.
- Owner dashboard for daily revenue, inventory movement, staff, customers, and reconciliation.

## Quick Start

```bash
git clone <repository_url>
cd Order-Flow
cp .env.example .env
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://localhost:8000`.

For Docker:

```bash
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

For production with Nginx and Redis:

```bash
docker compose --profile production up --build -d
```

## Required Configuration

At minimum, production needs:

- `DJANGO_SETTINGS_MODULE=dineflow.settings.prod`
- `APP_NAME=Order-Flow`
- `SECRET_KEY`
- `DATABASE_URL`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `REDIS_URL`
- Supabase/S3 media storage credentials
- Per-restaurant payment provider credentials configured in the owner dashboard

Use `.env.example` as the source template.

## Test And Check

```bash
python manage.py test
python manage.py check --deploy --settings=dineflow.settings.prod
```

`check --deploy` requires production-like environment values, including a strong `SECRET_KEY`, valid hosts, and database settings.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [System Design](docs/SYSTEM_DESIGN.md)
- [Database Design](docs/DATABASE_DESIGN.md)
- [API Reference](docs/API_REFERENCE.md)
- [Security Review](docs/SECURITY_REVIEW.md)
- [Performance Review](docs/PERFORMANCE_REVIEW.md)
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md)
- [Runbook](docs/RUNBOOK.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Engineering Standards

- Keep tenant boundaries explicit on every data access path.
- Prefer database transactions for payment, stock, and ledger mutations.
- Treat webhooks as untrusted input until signature and replay checks pass.
- Keep user-facing branding driven by settings, not hardcoded strings.
- Do not rename the `dineflow` Python package without a dedicated migration plan.

Copyright 2026 Order-Flow Platform.
