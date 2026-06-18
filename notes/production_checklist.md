# Startup Production Launch Checklist

Since you are taking this application to real users, the codebase itself is now mathematically hardened, but the **infrastructure, security, and external integrations** must be equally resilient.

Here is your definitive checklist to complete before the public launch.

---

## 1. Django Security Settings
Before traffic hits the servers, your `settings.py` (specifically `settings/prod.py`) must be locked down:
- `[ ]` **`DEBUG = False`**: Never run with DEBUG in production. It leaks sensitive environment variables on error pages.
- `[ ]` **`SECRET_KEY`**: Generate a new, cryptographically secure string and inject it via environment variables. Never commit it to source control.
- `[ ]` **`PAYMENT_ENCRYPTION_KEY`**: Must be a distinct string from SECRET_KEY, securely generated. Used for encrypting sensitive payment credentials.
- `[ ]` **`ALLOWED_HOSTS`**: Explicitly list your production domain names (e.g., `['dineflow.app', 'www.dineflow.app']`).
- `[ ]` **Secure Cookies**: Ensure cookies cannot be intercepted over HTTP:
  ```python
  SESSION_COOKIE_SECURE = True
  CSRF_COOKIE_SECURE = True
  ```
- `[ ]` **CORS & CSRF**: Set `CSRF_TRUSTED_ORIGINS` to your exact HTTPS domains.

## 2. Infrastructure & Databases
SQLite is only for local development. Your data layer needs to be bulletproof.
- `[ ]` **Managed PostgreSQL**: Provision a managed Postgres database (e.g., AWS RDS, Supabase, Render) with **automated daily backups** and Point-In-Time-Recovery (PITR) enabled.
- `[ ]` **Managed Redis**: You need a highly-available Redis cluster. This is critical because it powers:
  - Django Channels (KDS WebSockets)
  - Celery Task Queues (Webhook processing)
  - Rate Limiting (`core.ratelimit`)
- `[ ]` **Media Storage**: Ensure your `Supabase` storage buckets are correctly configured for public read access for menu item images.
- `[ ]` **Web Servers**: Run the application behind a production-grade WSGI/ASGI server. Use `Gunicorn` with `Uvicorn` workers for ASGI WebSocket support.

## 3. Razorpay & Payments
Moving from Test Mode to Live Mode requires administrative steps.
- `[ ]` **Razorpay Live Activation**: Submit your KYC and business documents to Razorpay to get Live Mode API Keys.
- `[ ]` **Update Webhooks**: In the Razorpay Dashboard, point your webhooks to your production domain (e.g., `https://dineflow.app/payments/webhook/`) and generate a new production Webhook Secret.
- `[ ]` **Website Compliance**: Razorpay requires your website to have visible links to:
  - Terms and Conditions
  - Privacy Policy
  - Refund & Cancellation Policy
  - Contact Us page

## 4. Observability & Monitoring
When things break in production, you need to know *before* the restaurants complain.
- `[ ]` **Exception Tracking (Sentry)**: Integrate [Sentry](https://sentry.io/) to capture Python tracebacks and front-end JavaScript errors instantly.
- `[ ]` **Metrics Dashboard**: You already have `django-prometheus` installed. Connect a Prometheus scraper and a Grafana dashboard to monitor:
  - CPU/Memory usage of your Celery workers.
  - HTTP 500 error rates.
- `[ ]` **Alerting**: Set up Slack/Email alerts for critical business failures:
  - Trigger an alert if the **Dead Letter Queue (DLQ)** goes above 0.
  - Trigger an alert if Razorpay webhooks repeatedly return 4xx/5xx errors.

## 5. Operations & Scaling
- `[ ]` **Celery Worker Allocation**: Ensure you run at least two Celery worker processes to avoid a single point of failure for asynchronous tasks (like webhook processing and order expiration).
- `[ ]` **Cron Jobs (Celery Beat)**: Ensure Celery Beat is running in production so that the `process_unprocessed_webhooks_task` and `expire_unpaid_order_task` execute continuously.
- `[ ]` **Load Balancer**: Place your application behind a Load Balancer (or Cloudflare) to handle SSL termination (HTTPS) and basic DDoS protection.
