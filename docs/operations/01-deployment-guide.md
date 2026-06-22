# Deployment Guide

Dineflow is built to deploy cleanly on a PaaS like Railway (it ships with a
`Procfile`, `Dockerfile`, and `railway.json`) or on your own
Docker Compose stack. Both paths are documented here. Either way, read
[Production Readiness Checklist](./02-production-readiness-checklist.md)
before flipping the switch to real customers and real money.

## Before you start: three required external accounts

| Service | What it's for |
|---|---|
| A hosting platform (Railway, or your own VPS) | Runs the app, database, and Redis |
| [Razorpay](https://razorpay.com/) | Payment processing |
| [Supabase](https://supabase.com/) | Postgres database hosting and/or S3-compatible storage for menu images, logos, and QR codes |

You don't have to use Supabase for *both* the database and storage — many
deployments use a different managed Postgres and only use Supabase for
storage, or vice versa. Either combination works as long as the
environment variables match what's actually provisioned.

## Path A — Railway

### 1. Provision infrastructure
1. Create a new Railway project.
2. Add a **Redis** service — required for WebSockets (KDS) and Celery.
3. Add your GitHub repo as a service.

If you're using Supabase for Postgres, you do **not** need to also
provision Postgres on Railway — just point `DATABASE_URL` at Supabase's
connection string.

### 2. Environment variables

Set these in the Railway service's **Variables** tab. Use
`.env.example` as the master checklist — every variable read by
`dineflow/settings/prod.py` is listed there with a comment. The ones most
worth calling out specifically:

```ini
DJANGO_SETTINGS_MODULE=dineflow.settings.prod
SECRET_KEY=<generate a strong, unique secret — at least 50 chars>
PAYMENT_ENCRYPTION_KEY=<a SEPARATE strong secret — production refuses to start if this equals SECRET_KEY>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Supabase pooler connection string — use the TRANSACTION pooler (port 6543), not 5432
DATABASE_URL=postgresql://postgres.[project]:password@aws-0-region.pooler.supabase.com:6543/postgres

RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
RAZORPAY_ENV=production

SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
AWS_ACCESS_KEY_ID=...          # Supabase Storage S3-compatible credentials
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=...
AWS_S3_ENDPOINT_URL=https://[project-ref].supabase.co/storage/v1/s3
```

Railway injects `REDIS_URL` automatically once you've added the Redis
service — you don't need to set it yourself.

Production will refuse to boot (raising `ImproperlyConfigured`, loudly,
rather than starting in a broken state) if: `SECRET_KEY` looks like a
default/weak value, `PAYMENT_ENCRYPTION_KEY` equals `SECRET_KEY`,
`ALLOWED_HOSTS` is empty or only contains placeholder values, `REDIS_URL`
is missing or unauthenticated, or Razorpay is partially configured (keys
present but no webhook secret, or a sandbox key in production). These
checks exist precisely so a misconfiguration is caught at deploy time, not
discovered later from a customer complaint.

### 3. Define the three services

Railway will detect the `Procfile` and let you split it into separate
services from the same repo:

| Service | Start command |
|---|---|
| Web (ASGI) | Leave blank — the `Dockerfile` already runs the correct Daphne command with the dynamic `$PORT` Railway provides |
| Worker | `celery -A dineflow worker -Q celery,payments -l info --concurrency=2` |
| Beat | `celery -A dineflow beat -l info` |

Generate a public domain for the **web** service only.

`railway.json` is already configured to run `python manage.py migrate`
before the web service boots, so schema changes deploy automatically.

### 4. Post-deployment steps

1. **Create a superuser** (via the Railway CLI or dashboard command
   palette): `python manage.py createsuperuser`, then log into
   `https://yourdomain.com/admin/`.
2. **Create your first restaurant** in Django Admin. The `slug` you
   choose becomes the menu URL (`slug='pizza-hut'` → `/r/pizza-hut/`).
   A `RestaurantConfig` and `RestaurantPaymentConfig` are created for it
   automatically.
3. **Connect Razorpay webhooks.** In the Razorpay Dashboard (Live mode):
   **Settings → Webhooks → Add New Webhook**, pointing at:

   ```
   https://yourdomain.com/payments/webhook/razorpay/
   ```

   Select at minimum `order.paid`, `payment.captured`, and
   `payment.failed`. Generate a secret and put it in
   `RAZORPAY_WEBHOOK_SECRET`. (Two legacy aliases —
   `/payments/razorpay/webhook/` and `/order/razorpay/webhook/` — also
   work, kept for backward compatibility with webhooks configured before
   the multi-provider endpoint existed; point new configurations at the
   provider-agnostic URL above.)

## Path B — Your own server (Docker Compose)

```bash
git clone <your repo>
cd dineflow
cp .env.example .env     # fill in every value — see Production Readiness Checklist
docker compose up -d --build
```

This brings up `web`, `worker`, `beat`, `db` (Postgres), `redis`, and
`nginx` as defined in `docker-compose.yml`. You are responsible for:

- Pointing a domain at the server and terminating SSL — either via the
  bundled `nginx` + `certbot` services, or your own reverse proxy in front
  of the `web` container's port 8000.
- Making sure WebSocket traffic (`/ws/`) is proxied correctly — Nginx
  needs the `Upgrade`/`Connection` headers passed through, which
  `nginx/nginx.conf` already does for you if you use the bundled config.
- Running the same post-deployment steps as Path A (superuser, first
  restaurant, Razorpay webhook configuration).

## Next

[Production Readiness Checklist](./02-production-readiness-checklist.md)
before you accept your first real customer payment.
