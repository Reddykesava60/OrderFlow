# Dineflow

Dineflow is a multi-tenant restaurant operating system: customers order and
pay from their phone via a QR code, kitchens see tickets in real time, and
every payment is tracked through an immutable financial ledger.

**Start here → [`docs/README.md`](./docs/README.md)** — documentation is
organized by audience (non-technical overview, engineering, operations),
not dumped into one file.

## At a glance

- **Backend**: Django 5.2
- **Database**: PostgreSQL in production (Supabase-hosted), SQLite for
  local development
- **Real-time**: Django Channels + Redis (Kitchen Display System
  WebSockets)
- **Background jobs**: Celery + Redis
- **Payments**: Razorpay, with a multi-provider abstraction in place
- **File storage**: Supabase Storage (S3-compatible)

## Quick local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set SECRET_KEY and DATABASE_URL at minimum
python manage.py migrate
python manage.py runserver
```

See
[`docs/engineering/11-local-development-setup.md`](./docs/engineering/11-local-development-setup.md)
for the full setup (including Celery, Redis, and Docker Compose options),
and
[`docs/operations/01-deployment-guide.md`](./docs/operations/01-deployment-guide.md)
for deploying this to production.

## Where the four Django apps fit

| App | Owns |
|---|---|
| `core` | Tenants (`Restaurant`), users, the menu catalog, and the platform-wide financial records |
| `ordering` | Checkout, inventory locking, the order state machine, and the full payment/webhook pipeline |
| `kitchen` | The Kitchen Display System — REST + WebSocket |
| `owner` | Restaurant manager dashboards |

See [`docs/engineering/01-architecture-overview.md`](./docs/engineering/01-architecture-overview.md)
for why the boundaries are drawn where they are, and
[`docs/engineering/02-codebase-map.md`](./docs/engineering/02-codebase-map.md)
for the full directory-by-directory breakdown.
