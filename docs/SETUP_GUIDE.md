# Order-Flow Setup Guide (Dev, Staging, Production)

## 1. Development
1. Copy `.env.example` to `.env` and configure local values.
2. Start stack: `docker compose up --build -d`.
3. Create superuser: `docker compose exec web python manage.py createsuperuser`.
4. Validate health: `/healthz/live/` and `/healthz/ready/`.

## 2. Staging
1. Use `dineflow.settings.prod` with staging hostnames.
2. Use isolated staging DB + Redis.
3. Apply migrations and collect static assets before traffic switch.
4. Enable worker + cron services for payment jobs.
5. Run smoke checks: checkout, webhook, KDS refresh, owner reports.

## 3. Production
1. Set secure env vars through secret manager, not committed files.
2. Enable HTTPS, HSTS, secure cookies, and CSRF trusted origins.
3. Start services: web, nginx, redis, worker, cron.
4. Confirm channel layer uses Redis backend.
5. Confirm payment webhook endpoints are reachable from provider.
6. Run reconciliation and expiry jobs on schedule.

## 4. Required Runtime Services
- Nginx reverse proxy
- Daphne ASGI server
- PostgreSQL (Supabase or managed)
- Redis for cache/channel layer/queue
- Worker process for webhook + reconciliation
- Cron process for expiry and catch-up jobs

## 5. Release Gate Checklist
- Database migrations applied successfully.
- `python manage.py check --deploy` passes.
- Payment status/retry rejects unsigned access.
- Duplicate webhook replay is idempotent.
- KDS sockets authenticate and remain tenant-scoped.
