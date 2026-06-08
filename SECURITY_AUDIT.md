# Security Audit

Last updated: 2026-05-08  
Audit status: CONDITIONAL PASS

## Critical Findings

### SEC-001: Committed Secrets And Empty Ignore Rules

Severity: Critical  
Exploitability: High  
Status: **Partially Resolved**

Resolution applied:
- `.gitignore` updated with comprehensive rules covering `.env`, `.env.*`, `__pycache__/`, `*.pyc`, `.venv/`, `staticfiles/`, `media/`, IDE files, and OS files.
- `.env.example` updated with documented template.

Remaining:
- **Git history still contains previously committed `.env` with live credentials.** A history rewrite is required using `git filter-repo` or BFG Repo-Cleaner.
- **All exposed credentials must be rotated**: database password, Supabase service role key, Django `SECRET_KEY`, and any Razorpay keys.

### SEC-002: Vulnerable Dependency Set

Severity: Critical  
Exploitability: Medium to High  
Status: **Resolved**

Resolution applied:
- `Django==5.2.14` pinned in `requirements.txt`.
- `Twisted==26.4.0` used as security pin for CVE-2026-42304.
- `gunicorn==23.0.0` added.
- All dependencies pinned to exact versions and organized by category.

Remaining:
- Add `pip-audit` to CI pipeline for continuous scanning.

### SEC-003: Weak Production Secret Key Detected

Severity: Critical  
Exploitability: High if deployed  
Status: **Resolved**

Resolution applied:
- `prod.py` now raises `ImproperlyConfigured` at startup if `SECRET_KEY` starts with `django-insecure-`, has fewer than 20 unique characters, or is shorter than 50 characters.

## High Findings

### SEC-004: No Password Policy Or Forced Password Change

Severity: High  
Exploitability: Medium  
Status: **Resolved**

Resolution applied:
- `MustChangePasswordMiddleware` enforces password change for users with `must_change_password=True`.
- `AUTH_PASSWORD_VALIDATORS` configured in `base.py`.
- Change-password flow with `ChangePasswordView` at `/owner/change-password/`.

### SEC-005: Merchant Payment Secrets Stored In Cleartext

Severity: High  
Exploitability: Medium  
Status: **Partially Resolved**

Resolution applied:
- Django admin `RestaurantPaymentConfigInline` now masks `razorpay_key_secret` and `razorpay_webhook_secret` (shows first/last 4 chars only).
- Fields are write-only in admin: new values can be entered, but existing values are never displayed in full.

Remaining:
- KMS/envelope encryption for at-rest storage.
- Audit logging for credential reads/updates.

### SEC-006: Missing Rate Limiting

Severity: High  
Exploitability: High  
Status: **Resolved**

Resolution applied:
- **App-level**: `@rate_limit` decorator from `core.ratelimit` applied to `OwnerLoginView` (10/5min), `KDSPollView` (180/60s), and checkout endpoints.
- **Nginx-level**: Rate limiting zones configured:
  - `login`: 5 requests/minute (burst 3)
  - `checkout`: 30 requests/minute (burst 5)
  - `api`: 60 requests/minute (burst 10)
  - `general`: 30 requests/second (burst 20)
- Request body limit: `client_max_body_size 10M` in Nginx.

### SEC-007: No CSP, SRI, Or External Script Pinning

Severity: High  
Exploitability: Medium  
Status: **Partially Resolved**

Resolution applied:
- Nginx security headers added:
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `X-XSS-Protection: 1; mode=block`
  - `Referrer-Policy: same-origin`
  - `Permissions-Policy: camera=(), microphone=(), geolocation=()`

Remaining:
- Full `Content-Security-Policy` with nonces or hashes.
- Compile Tailwind CSS locally.
- Pin exact Alpine.js version and serve locally with SRI.

### SEC-008: App-Level Tenant Isolation Only

Severity: High  
Exploitability: Medium  
Status: **Open**

No change. Database-level tenant isolation (RLS for all tables) still recommended.

## Medium Findings

### SEC-009: Public Receipt URLs Rely Only On UUID Secrecy

Severity: Medium  
Exploitability: Low to Medium  
Status: **Open**

Nginx adds `Referrer-Policy: same-origin` to mitigate referrer leaks.

### SEC-010: Request Body Size And Payload Validation Are Incomplete

Severity: Medium  
Exploitability: Medium  
Status: **Resolved**

Resolution applied:
- Nginx `client_max_body_size 10M` enforces request body limits at the proxy layer.
- `client_body_timeout 30s` and `client_header_timeout 15s` prevent slow-read attacks.

### SEC-011: Edge Functions Use Service Role Without Defense In Depth

Severity: Medium  
Exploitability: Medium  
Status: **Open**

No change.

### SEC-012: CSV Injection Risk

Severity: Medium  
Exploitability: Low  
Status: **Resolved**

Resolution applied:
- `_csv_safe()` function added to `owner/views.py`.
- Reconciliation CSV export now escapes values starting with `=`, `+`, `-`, `@`, `\t`, `\r`, `\n`.

### SEC-013: Debug Information Disclosure (New)

Severity: Medium  
Exploitability: Low  
Status: **Resolved**

Resolution applied:
- `debug_permissions` query parameter in `KDSPollView` now gated behind `settings.DEBUG`.
- In production (`DEBUG=False`), the parameter is completely ignored.

## Hardening Recommendations

- [x] Add comprehensive `.gitignore`.
- [x] Mask payment secrets in Django admin.
- [x] Add Nginx security headers.
- [x] Add rate limiting (app + proxy).
- [x] Fix CSV injection.
- [x] Gate debug endpoints behind `DEBUG`.
- [ ] Add MFA for owners and Django admin.
- [ ] Set `SECURE_HSTS_PRELOAD=True` after domain readiness.
- [ ] Add full `Content-Security-Policy` with nonces.
- [ ] Disable or restrict Django admin by network, SSO, or VPN.
- [ ] Add account lockout and audit logging for staff/owner changes.
- [ ] Add security regression tests for IDOR, CSRF, authz, password reset, and tenant isolation.
- [ ] Compile Tailwind locally and pin Alpine.js with SRI.
