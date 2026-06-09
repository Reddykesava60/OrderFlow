# Risk Register

Last updated: 2026-05-08

| ID | Risk | Severity | Likelihood | Business impact | Evidence | Owner | Mitigation | Status |
|---|---|---:|---:|---|---|---|---|---|
| R-001 | Committed live-looking secrets expose DB/Supabase/Django trust boundary | Critical | High | Full data/service compromise | `.env` tracked, `.gitignore` was empty | Security/DevOps | `.gitignore` updated with comprehensive rules. Rotate, revoke, purge history, add secret scan. | Partial — `.gitignore` fixed; git history purge and secret rotation still required |
| R-002 | Vulnerable Django version exposed to public traffic | Critical | High | DoS, admin/authz exposure | `pip-audit` found many Django CVEs; current pinned version is `Django==5.2.14` | Backend | Upgraded to 5.2.14. Rerun audit periodically. | Resolved |
| R-003 | In-memory channel layer causes stale KDS across workers | High | High | Kitchen misses orders, customer dissatisfaction | `InMemoryChannelLayer` in dev settings; `channels_redis` in prod.py | Backend/SRE | Redis channel layer configured in `prod.py`. Dev uses in-memory by default. | Resolved |
| R-004 | Local cache causes inconsistent KDS state | High | High | Incorrect kitchen workflow, DB load | Redis cache configured in `prod.py`; dev falls back to local memory | Backend/SRE | Redis cache in production. `docker-compose.yml` includes Redis service. | Resolved |
| R-005 | Temporary staff passwords not forcibly rotated | High | Medium | Account compromise | `must_change_password` enforced via `MustChangePasswordMiddleware` | Backend/Security | Middleware redirects staff with `must_change_password=True` to change-password page. | Resolved |
| R-006 | No rate limits on public/payment/auth endpoints | High | High | Abuse, brute force, DB/API overload | App-level rate limiting via `core.ratelimit`; Nginx-level rate limiting zones configured | Security/SRE | Nginx rate limiting: login (5r/m), checkout (30r/m), API (60r/m). App-level `@rate_limit` decorators on KDS poll and login. | Resolved |
| R-007 | No reproducible deployment artifacts | High | High | Unsafe releases and rollbacks | `Dockerfile`, `docker-compose.yml`, `nginx/nginx.conf`, `docker/entrypoint.sh` created | DevOps | Multi-stage Dockerfile, 4-service Compose (web, redis, nginx, cron), entrypoint with DB wait/migrate/collectstatic. | Resolved |
| R-008 | Payment secrets stored cleartext in DB/admin | High | Medium | Merchant credential compromise | `RestaurantPaymentConfig` fields masked in Django admin; KMS envelope encryption implemented | Security/Backend | KMS Envelope encryption implemented. | Resolved |
| R-009 | Third-party scripts without CSP/SRI | High | Medium | Session/payment compromise via script injection | CDN Tailwind/Alpine/Razorpay templates | Frontend/Security | Nginx security headers added (X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy). Full CSP with nonces pending. | Partial — headers done; CSP nonces and local Tailwind compilation pending |
| R-010 | Request-triggered cleanup leaves stale orders/reservations | Medium | Medium | Inventory lock, wrong KDS/payment state | `release_expired_reservations` management command exists; Docker cron container runs it every 5 minutes | Backend/SRE | Docker Compose includes dedicated cron service. Also runs request-triggered as fallback. | Resolved |
| R-011 | Missing observability prevents fast incident response | High | Medium | Long outages, poor diagnosis | Structured `LOGGING` config added to `base.py` and `prod.py` with per-module loggers | SRE | Console logging with verbose formatter (dev) and structured format (prod). Metrics/tracing still pending. | Partial — logging done; metrics and dashboards pending |
| R-012 | Tests do not cover owner/core critical flows | Medium | High | Regressions in staff/payment config/menu | `core/tests.py` and `owner/tests.py` are placeholders. 13 tests exist for ordering/kitchen. | QA | Add unit/integration tests for owner and core modules. | Open |
| R-013 | Test suite not easily runnable with isolated SQLite | Medium | Medium | CI friction, unsafe DB use | `sslmode` now guarded behind `not TESTING` flag in `base.py` | Backend | Tests run cleanly — `TESTING` flag detected from `sys.argv`. | Resolved |
| R-014 | Supabase RLS baseline incomplete | High | Medium | Cross-tenant data exposure if app filter fails | SQL covers subset of tables | Security/Data | Full RLS or tenant manager needed. | Open |
| R-015 | Edge functions use service role and separate auth plane | Medium | Medium | RLS bypass from function bug | Supabase functions create service client | Security/Backend | Validate need, add audit/body/origin controls. | Open |
| R-016 | Public receipts rely on UUID secrecy | Medium | Low | Customer order data leak | Public receipt URL includes UUID | Backend/Security | Signed expiring receipt tokens recommended. | Open |
| R-017 | CSV formula injection | Medium | Low | Operator workstation risk | `_csv_safe()` function added to escape formula-leading cells in CSV exports | Backend/Security | CSV reconciliation export now escapes `=`, `+`, `-`, `@`, `\t`, `\r`, `\n` prefixes. | Resolved |
| R-018 | Razorpay SDK call in request path lacks explicit timeout | Medium | Medium | Worker exhaustion during gateway slowness | Eager operations removed, moved to rate-limited background tasks | Backend/SRE | Offloaded to background tasks via Celery with retries. | Resolved |
| R-019 | No MFA for owners/admin | Medium | Medium | Admin or owner compromise | No MFA integration | Security | Add MFA/SSO for privileged users. | Open |
| R-020 | Missing health/readiness endpoints | High | Medium | Bad deploys receive traffic | `/healthz/live/` and `/healthz/ready/` exist in `dineflow/urls.py`; Dockerfile HEALTHCHECK uses `/healthz/live/` | SRE | Health probes configured in Dockerfile and Nginx passthrough. | Resolved |

## Top Risks By Priority

1. R-001: Committed secrets — `.gitignore` fixed, but git history purge and credential rotation still required.
2. R-009: CSP/SRI — Nginx headers done, full CSP nonces and local asset compilation pending.
3. R-014: Database-level tenant isolation — RLS coverage incomplete.
4. R-012: Test coverage gaps — owner/core modules need tests.
