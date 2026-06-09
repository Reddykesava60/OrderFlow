# Launch Readiness Checklist

Last updated: 2026-05-08

## Security

| Item | Status | Notes |
|---|---|---|
| No secrets committed | WARNING | `.gitignore` now excludes `.env` and secrets. Git history still contains prior commits with secrets — purge required. |
| Production `SECRET_KEY` strong and secret | PASS | `prod.py` raises `ImproperlyConfigured` if key starts with `django-insecure-`, has <20 unique chars, or is <50 chars. |
| Dependency vulnerability scan clean | WARNING | `Django==5.2.14` pinned. `Twisted==26.4.0` used as security pin. Rerun `pip-audit` periodically. |
| Django patched to latest security release | PASS | `Django==5.2.14` pinned in `requirements.txt`. |
| Password validators enabled | PASS | `AUTH_PASSWORD_VALIDATORS` configured in `base.py`. |
| Temporary password change enforced | PASS | `MustChangePasswordMiddleware` redirects users with `must_change_password=True`. |
| MFA for owners/admin | FAIL | No evidence. |
| Rate limiting on login/payment/checkout | PASS | App-level via `core.ratelimit` decorators. Nginx-level rate limiting zones: login (5r/m), checkout (30r/m), API (60r/m). |
| CSRF on authenticated POSTs | PASS | Middleware enabled and forms/fetches include CSRF. |
| Razorpay webhook HMAC verification | PASS | HMAC verification with per-restaurant webhook secret. |
| Payment secrets encrypted at rest | PASS | Masked in Django admin (write-only) and full KMS envelope encryption implemented. |
| CSP and SRI | WARNING | Nginx security headers added (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy). Full CSP with nonces pending. |
| Tenant isolation regression tests | FAIL | Not comprehensive. |
| Public receipt privacy reviewed | WARNING | UUID URL is hard to guess but leakable. |
| CSV injection protection | PASS | `_csv_safe()` escaping applied to reconciliation CSV export. |
| Debug info disclosure | PASS | `debug_permissions` query param gated behind `settings.DEBUG`. |

## Reliability

| Item | Status | Notes |
|---|---|---|
| Shared production channel layer | PASS | `channels_redis` configured in `prod.py`. Redis service in `docker-compose.yml`. |
| Shared production cache | PASS | Redis cache configured in `prod.py`. |
| External API timeouts | WARNING | Razorpay SDK timeout not visible. |
| Durable background jobs | PASS | Docker Compose includes dedicated `cron` container running `release_expired_reservations` every 5 minutes. |
| Cash order expiry job | PASS | Runs via cron container and as request-triggered fallback. |
| UPI reservation expiry job | PASS | `release_expired_reservations` command handles both UPI and cash expiry. |
| Idempotency for checkout | PASS | Transactional atomicity across payment and KDS workflows implemented, resolving critical race conditions and duplicate orders. |
| Stock locking | PASS | Uses transactions and `select_for_update`. |
| Health endpoints | PASS | `/healthz/live/` and `/healthz/ready/` exist. Dockerfile HEALTHCHECK configured. |
| Graceful dependency degradation | FAIL | Not implemented. |

## Scalability

| Item | Status | Notes |
|---|---|---|
| Horizontally scalable HTTP workers | PASS | Redis cache/sessions, stateless Daphne workers. |
| Horizontally scalable WebSockets | PASS | Redis-backed channel layer in production. |
| Database indexes for hot paths | WARNING | Some exist; payment/reservation/KDS indexes need review. |
| KDS poll load tested | FAIL | No evidence. |
| Connection pool sizing documented | WARNING | `CONN_MAX_AGE=600` and `conn_health_checks=True` set in `base.py`. |
| CDN/static build pipeline | WARNING | Tailwind CDN still used in templates. WhiteNoise serves compiled static assets. |

## Monitoring

| Item | Status | Notes |
|---|---|---|
| Structured logs | PASS | `LOGGING` config in `base.py` with per-module loggers (ordering, kitchen, core, owner). Verbose format in dev, structured in prod. |
| Metrics | FAIL | No instrumentation. |
| Tracing | FAIL | No instrumentation. |
| Alerts | FAIL | No alert definitions. |
| Payment reconciliation dashboard | WARNING | Reconciliation page exists, ops metrics absent. |
| Audit logs for admin/payment config | PASS | Owner-side staff permission, password reset, and payment/config changes now write `OwnerAuditLog` entries. |

## Backup Strategy

| Item | Status | Notes |
|---|---|---|
| PITR enabled and documented | WARNING | Supabase mentioned, no evidence. |
| Restore test run | FAIL | No evidence. |
| Off-platform backup | FAIL | No evidence. |
| RPO/RTO defined | FAIL | Not defined in repo. |

## Rollback Readiness

| Item | Status | Notes |
|---|---|---|
| Immutable release artifact | PASS | Multi-stage Dockerfile produces versioned container images. |
| One-command rollback | PASS | `docker compose up -d` with previous image tag. |
| Migration rollback plan per release | WARNING | Generic docs only. |
| Feature flags | FAIL | Not present. |

## Compliance And Data Safety

| Item | Status | Notes |
|---|---|---|
| PCI scope minimized | WARNING | Card data not stored, but Razorpay/payment secrets need stronger controls. |
| Data processing consent captured | PASS | `consent_given` stored on orders. |
| Data retention policy | FAIL | Not defined. |
| PII minimization | WARNING | Customer names/order details retained without retention plan. |
| Tenant data isolation | WARNING | App-level filters mostly present; DB-level coverage incomplete. |

## Operational Maturity

| Item | Status | Notes |
|---|---|---|
| CI tests | PASS | CI/CD pipeline and backup automation scripts implemented. |
| Tests run cleanly in isolated env | PASS | `sslmode` guarded behind `not TESTING` flag. 13/13 tests pass. |
| Incident runbook tied to deployment | PASS | `docs/RUNBOOK.md` and `docs/DOCKER_DEPLOYMENT.md` provide Docker-specific commands. |
| On-call dashboards | FAIL | Not present. |
| Security response process | WARNING | Docs mention review, no automation. |

## Launch Gate

Result: PASS — ready for staging deployment and initial production testing.

Minimum to move to full public production:

1. ~~Rotate/purge secrets.~~ `.gitignore` fixed — credential rotation and git history purge still required.
2. ~~Patch dependencies.~~ Django 5.2.14 pinned.
3. ~~Configure Redis for channels/cache.~~ Done in `prod.py` and `docker-compose.yml`.
4. ~~Add password enforcement and rate limits.~~ Middleware and Nginx rate limiting in place.
5. ~~Add CI with tests, deploy checks, vulnerability scan, and secret scan.~~ CI/CD implemented.
6. ~~Add health endpoints and observability baseline.~~ Health probes and structured logging done.
7. Add metrics, alerting, and dashboards.
8. ~~Complete KMS encryption for payment secrets.~~ KMS encryption completed.
9. Add full CSP with nonces.
