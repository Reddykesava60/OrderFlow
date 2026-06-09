# Deployment Checklist

## Core Runtime
- [ ] Run Django behind Nginx with HTTPS termination.
- [ ] Set `DEBUG=False` in production.
- [ ] Provide a strong, uncommitted `SECRET_KEY`.
- [ ] Configure `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` for the production domain(s).
- [ ] Enable `SECURE_SSL_REDIRECT`, HSTS, secure cookies, and proxy SSL headers.

## Data and Secrets
- [ ] Store per-restaurant payment credentials in the database only after encryption.
- [ ] Keep provider secrets out of the browser and out of logs.
- [ ] Separate test and live Razorpay credentials.
- [ ] Rotate webhook secrets when a tenant is re-onboarded or compromised.

## WebSockets and Cache
- [ ] Use Redis-backed `CHANNEL_LAYERS` in production.
- [ ] Use Redis-backed cache for rate limits and payment locks.
- [ ] Ensure the ASGI stack applies origin validation for WebSocket traffic.
- [ ] Scale Daphne workers horizontally once Redis is configured.

## Background Workers
- [ ] Run Celery workers for payment webhook processing and reconciliation.
- [ ] Run a periodic job for expiring stale payment attempts and unpaid cash orders.
- [ ] Run a periodic reconciliation job against the provider API.
- [ ] Alert on queue backlog growth.

## Edge Proxy
- [ ] Proxy `/ws/` to ASGI and HTTP to Django/Nginx appropriately.
- [ ] Set request/body size limits at the edge.
- [ ] Add rate limiting on checkout, webhook, and login endpoints.
- [ ] Return a health endpoint that distinguishes live, ready, and dependency failures.

## Launch Gate
- [ ] Confirm tenant isolation with two sample restaurants.
- [ ] Confirm duplicate checkout and duplicate webhook tests pass.
- [ ] Confirm payment polling/retry URLs reject unsigned access.
- [ ] Confirm payment reconciliation works end-to-end in test mode before live cutover.
