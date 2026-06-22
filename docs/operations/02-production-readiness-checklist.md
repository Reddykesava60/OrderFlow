# Production Readiness Checklist

Work through this before onboarding your first real, paying restaurant.
Items marked **(enforced)** aren't just advice — `dineflow/settings/prod.py`
will refuse to start the application if they're wrong, so you'll find out
at deploy time rather than from a customer.

## 1. Secrets and configuration

- [ ] **`SECRET_KEY`** — a long, unique, randomly generated value.
  **(enforced)**: production rejects anything that looks like a default
  (`django-insecure-...`), is under 50 characters, or has fewer than 20
  distinct characters.
- [ ] **`PAYMENT_ENCRYPTION_KEY`** — a *separate* strong secret, used to
  encrypt stored gateway credentials. **(enforced)**: production refuses
  to start if this equals `SECRET_KEY`. Generate both with
  `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
- [ ] **`ALLOWED_HOSTS`** — your real domain(s). **(enforced)**:
  production strips out placeholder values (`*`, `localhost`, `127.0.0.1`,
  `0.0.0.0`) and refuses to start if nothing valid is left.
- [ ] **`CSRF_TRUSTED_ORIGINS`** — your real `https://` domain(s).
  **(enforced)**: any non-`https://` origin is silently stripped — make
  sure what's left is actually what you intended.
- [ ] Neither secret, nor any real credential, is committed to source
  control. `.env` is git-ignored; only `.env.example` (with placeholder
  values) belongs in the repo.

## 2. Database

- [ ] A managed Postgres instance (Supabase or otherwise) with automated
  backups and point-in-time recovery enabled. SQLite is for local
  development only — production requires Postgres.
- [ ] `DATABASE_URL` uses the **transaction pooler** connection string if
  you're on Supabase (typically port `6543`), not the direct connection
  (port `5432`). See
  [Incident Playbook](./03-incident-playbook.md#database-connection-exhaustion)
  for what happens if you get this wrong.
- [ ] `python manage.py migrate` has actually run against this database
  (Railway's `railway.json` does this automatically before the web
  service boots; on a manual VPS deploy, you need to run it yourself).

## 3. Redis

- [ ] A reachable Redis instance. **(enforced)**: production refuses to
  start without `REDIS_URL`, refuses a non-`redis://`/`rediss://` URL, and
  — if it looks like a self-hosted instance (`redis`/`localhost`/
  `127.0.0.1` as the host) — refuses to start without a password set.
- [ ] You understand that Redis backs **three** independent things:
  Celery's broker/result backend, the Django cache (used by the rate
  limiter and KDS cache-version bump), and the Channels layer (KDS
  WebSockets). Losing Redis degrades all three at once — see
  [Incident Playbook](./03-incident-playbook.md).

## 4. Razorpay

- [ ] Live Mode API keys obtained (KYC/business documents submitted and
  approved).
- [ ] **(enforced)**: if `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` are set,
  `RAZORPAY_WEBHOOK_SECRET` **must** also be set, or the app refuses to
  start — without it, webhook signatures can't be verified at all.
- [ ] **(enforced)**: a `RAZORPAY_KEY_ID` starting with `rzp_test_` causes
  production to refuse to start — this exists specifically to prevent
  sandbox credentials from accidentally taking live traffic.
- [ ] Webhooks configured in the Razorpay dashboard, pointing at
  `https://yourdomain.com/payments/webhook/razorpay/`, covering at least
  `order.paid`, `payment.captured`, and `payment.failed`.
- [ ] Your website has visible links to Terms & Conditions, a Privacy
  Policy, a Refund & Cancellation Policy, and a Contact page — Razorpay
  requires these for Live Mode activation.

## 5. Media storage

- [ ] Supabase Storage (or another S3-compatible bucket) configured with
  public read access for menu item images, restaurant logos, and QR
  codes. Without `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/
  `AWS_STORAGE_BUCKET_NAME`/`AWS_S3_ENDPOINT_URL` all set, production logs
  a warning and falls back to local filesystem storage — which is
  **ephemeral** on platforms like Railway, meaning uploaded images vanish
  on the next deploy.

## 6. Observability

- [ ] **Sentry** (`SENTRY_DSN`) — if set, error tracking for Django,
  Celery, and Redis is wired up automatically with `send_default_pii =
  False`. Strongly recommended; without it, the only way to discover a
  production exception is a user complaint or manually reading logs.
- [ ] `django-prometheus` is installed but its public endpoint has been
  removed for security reasons. Connect it internally if you want metrics beyond
  what Sentry gives you.
- [ ] Alerting set up for at least: any `WebhookLog` reaching
  `DEAD_LETTERED`, and any `PaymentTransaction` flagged
  `manual_recovery_required` in its metadata (see
  [Order & Payment Lifecycle](../engineering/04-order-and-payment-lifecycle.md)) —
  both represent money that needs a human, not a missed feature.

## 7. Process topology

- [ ] All three processes are running: **web** (Daphne/ASGI — required for
  WebSockets, not just plain WSGI), **worker** (at least one, two
  recommended so a single worker restarting doesn't stall the payments
  queue), and **beat** (exactly one — running it twice double-schedules
  every periodic task).
- [ ] If self-hosting: a load balancer or CDN (e.g. Cloudflare) in front
  for SSL termination and basic DDoS absorption, and Nginx (or equivalent)
  correctly proxying `/ws/` WebSocket traffic with `Upgrade` headers
  intact.

## 8. Security posture

Covered in depth in [Security](../engineering/10-security.md) — the short
version to verify before launch:
- [ ] `DEBUG = False` (the `prod` settings module sets this; don't
  override it).
- [ ] `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` are `True` (default
  in `prod.py` — only relevant if you've customized settings further).
- [ ] CSP is enforcing, not report-only
  (`CONTENT_SECURITY_POLICY_REPORT_ONLY=False`, the production default) —
  unless you're actively in the middle of tuning a policy change, in which
  case flip it to report-only temporarily, then back.
- [ ] At least the platform's own admin/owner accounts have MFA enabled.

## Next

Once this is checked off, work through
[QA & UAT Checklist](./04-qa-and-uat-checklist.md) before your first real
restaurant goes live, and keep
[Incident Playbook](./03-incident-playbook.md) bookmarked for when
something actually goes wrong.
