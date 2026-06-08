# Operations Runbook

Last updated: 2026-05-08  
Status: Production-ready for Docker-based deployment.

## Service Inventory

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| Django/Daphne ASGI | `dineflow-web` | 8000 (internal) | HTTP + WebSocket serving |
| Nginx reverse proxy | `dineflow-nginx` | 80 (external) | SSL termination, static files, rate limiting, WebSocket proxy |
| Redis | `dineflow-redis` | 6379 (internal) | Cache + Channel Layers |
| Cron scheduler | `dineflow-cron` | — | Scheduled reservation/order cleanup |
| PostgreSQL | External (Supabase) | 5432 | Primary database |
| Supabase Storage | External | — | Menu images and QR codes |
| Razorpay | External | — | UPI checkout and webhook source |

## Launch Preconditions

Do not launch until:

- [x] `.gitignore` updated with comprehensive rules.
- [ ] Secrets have been rotated and removed from git history.
- [x] Django upgraded to at least 5.2.14.
- [x] Redis-backed channel layer and cache configured in `prod.py`.
- [x] Docker deployment artifacts created (Dockerfile, Compose, Nginx, entrypoint).
- [x] Health endpoints exist (`/healthz/live/`, `/healthz/ready/`).
- [x] Structured logging configured.
- [x] Rate limiting configured (Nginx + app-level).
- [ ] CI runs tests, deploy checks, secret scanning, and dependency audit.
- [ ] Alerting and dashboards are live.

## Deployment Commands

### Start Production Stack
```bash
# Build and start all services
docker compose up --build -d

# Start with Nginx (production profile)
docker compose --profile production up --build -d

# View all service status
docker compose ps
```

### Stop / Restart
```bash
docker compose down              # Stop all
docker compose restart web       # Restart web only
docker compose restart nginx     # Restart Nginx only
```

### View Logs
```bash
docker compose logs -f web       # Application logs
docker compose logs -f nginx     # Nginx access/error logs
docker compose logs -f cron      # Scheduled task logs
docker compose logs -f redis     # Redis logs
```

### Database Operations
```bash
# Run migrations
docker compose exec web python manage.py migrate --noinput

# Create superuser
docker compose exec web python manage.py createsuperuser

# Django shell
docker compose exec web python manage.py shell

# Collect static files
docker compose exec web python manage.py collectstatic --noinput

# Run Django deploy check
docker compose exec web python manage.py check --deploy
```

### Manual Maintenance Tasks
```bash
# Release expired reservations (normally runs via cron container)
docker compose exec web python manage.py release_expired_reservations

# Run tests
docker compose exec web python manage.py test ordering kitchen --verbosity=2
```

## Health Checks

| Endpoint | Method | Expected | Purpose |
|----------|--------|----------|---------|
| `/healthz/live/` | GET | 200 | Process is running |
| `/healthz/ready/` | GET | 200 | Database, cache, migrations ready |
| WebSocket `/ws/kds/` | WS | Connection accepted | ASGI + Channels working |

```bash
# Quick health check
curl -f http://localhost/healthz/live/
curl -f http://localhost/healthz/ready/

# Redis health
docker compose exec redis redis-cli ping

# Database connectivity
docker compose exec web python -c "
import django; django.setup()
from django.db import connections
c = connections['default']
c.ensure_connection()
print('Database OK')
"
```

Readiness checks should fail if:

- Database connection fails.
- Redis connection fails.
- Required secrets are missing.
- Migrations are unapplied.
- `DEBUG=True` in production.

## Monitoring

Required service-level indicators:

- HTTP request rate, latency p50/p95/p99, and 5xx rate.
- Checkout success/failure rate by payment method.
- Razorpay order creation latency and errors.
- Webhook event count, invalid HMAC count, duplicate event count.
- KDS poll rate, poll latency, cache hit ratio, payload size.
- Active WebSocket connections by restaurant.
- Database connection count, slow query count, lock wait time.
- Stock reservation stale count.
- Cash unpaid order stale count.
- Login failures and staff permission changes.

Logging configuration: structured `LOGGING` dict in `dineflow/settings/base.py` with per-module loggers for `ordering`, `kitchen`, `core`, and `owner`.

## Alerts

Page immediately:

- 5xx rate above 2 percent for 5 minutes.
- Checkout failure rate above 5 percent for 5 minutes.
- Razorpay webhook invalid HMAC spike.
- Database unavailable.
- Redis unavailable.
- KDS poll p95 above 2 seconds for 10 minutes.
- Stale UPI reservations above threshold.
- Secrets scan detects committed secret on default branch.

Ticket during business hours:

- Django dependency scan high/critical finding.
- HSTS/CSP missing in production scan.
- Cache hit rate below target.
- Slow query regression.
- Test suite failure on default branch.

## Incident Response

### Checkout Outage

Symptoms:

- Customers cannot place orders.
- 5xxs on `/r/<slug>/checkout/`.
- Razorpay order creation failures.

Immediate actions:

1. Check application error logs: `docker compose logs -f web | grep ERROR`.
2. Check database and Redis health (see Health Checks above).
3. Check Razorpay status and latency.
4. If only UPI fails, disable UPI for affected restaurant and keep cash enabled.
5. If stock integrity is at risk, pause restaurant ordering through `RestaurantConfig.is_open=False`.

### KDS Stale Data

Symptoms:

- Kitchen screens do not update after checkout.
- WebSocket disconnects or stale poll results.

Immediate actions:

1. Check Redis channel layer health: `docker compose exec redis redis-cli ping`.
2. Check ASGI worker health: `docker compose logs -f web | grep -i websocket`.
3. Check KDS poll endpoint: `curl http://localhost/api/kds/poll/`.
4. Force clients to refresh if needed.
5. Use owner dashboard or database to verify source-of-truth order status.

### Payment Webhook Failure

Symptoms:

- Customers paid but orders remain unpaid.
- Webhook logs show invalid signature or no delivery.

Immediate actions:

1. Verify Razorpay webhook deliveries in Razorpay Dashboard.
2. Verify per-restaurant webhook secret.
3. Check `PaymentEvent` for duplicate or missing events.
4. Reconcile by Razorpay order/payment ID.
5. Confirm order using a controlled admin command after verification.

## Backup And Restore

Required:

- Supabase point-in-time recovery enabled.
- Daily logical backup export retained outside Supabase.
- Quarterly restore test into staging.
- Document RPO and RTO.

Suggested targets:

- RPO: 15 minutes or better for production.
- RTO: 2 hours for full database restore.

## Scheduled Jobs

| Job | Schedule | Container | Command |
|-----|----------|-----------|---------|
| Expire stale UPI reservations + cash orders | Every 5 minutes | `dineflow-cron` | `python manage.py release_expired_reservations` |
| Cash order expiry (fallback) | On KDS poll / receipt view | `dineflow-web` | `expire_overdue_unpaid_cash_orders()` |

Future recommended jobs:

- Payment reconciliation against Razorpay.
- Dependency vulnerability scan (`pip-audit`).
- Secret scan.
- Backup verification.

## Deployment Procedure

1. Build immutable Docker image: `docker compose build`.
2. Run CI checks (when CI is configured).
3. Run `docker compose exec web python manage.py check --deploy`.
4. Run migrations: `docker compose exec web python manage.py migrate --noinput`.
5. Deploy to production using rolling or blue/green strategy.
6. Run readiness checks: `curl -f http://localhost/healthz/ready/`.
7. Monitor error rate and checkout success for 30 minutes.

## Rollback Procedure

1. Stop rollout.
2. Revert to previous Docker image tag: `docker compose up -d --no-build`.
3. If migration ran, follow migration-specific rollback plan.
4. Validate health endpoints.
5. Confirm checkout and KDS.
6. Open incident review if customer impact occurred.

## Security Operations

- Rotate secrets immediately after any repo exposure.
- Require MFA for admin/owner accounts (pending implementation).
- Review staff permission changes daily during launch.
- Keep audit logs for payment config changes.
- Run dependency audit on every build.
- Payment secrets are masked in Django admin — do not expose raw values.
