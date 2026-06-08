# Order-Flow Security Review & Threat Model

Last updated: 2026-05-08

Order-Flow processes financial transactions and stores business-critical operational data. Security is integrated at the framework, middleware, application, and proxy layers. This document outlines the threat models and their mitigations.

## 1. Authentication & Authorization (AuthN/AuthZ)

### 1.1 Session Management
* **Mechanism**: Server-side sessions via `django.contrib.sessions`. We do not use stateless JWTs because they cannot be immediately revoked if an owner terminates a staff member.
* **Timeout Policies**: 
  - `SESSION_COOKIE_AGE = 28800` (8 hours). Prevents abandoned terminals from remaining logged in indefinitely.
  - `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`. Closing the iPad/Browser forcibly clears the session.

### 1.2 Role-Based Access Control (RBAC)
Instead of a complex permission matrix, Order-Flow uses strict, boolean-based RBAC enforced via View Mixins.
- **Owner**: Inherently possesses all permissions for their specific `restaurant_id`.
- **Staff**: Must have specific flags enabled (`allow_cash_collection`, `allow_view_all_orders`).
- **Enforcement**: Never check permissions manually inside a view. Always inherit from `core.mixins` (e.g., `ActiveStaffMixin`).

## 2. Input Validation & Injection Prevention

### 2.1 Cross-Site Scripting (XSS)
* **Stored XSS Mitigation**: All string fields that accept user input (e.g., `MenuItem.name`, `RestaurantConfig.reopen_message`) are passed through `bleach.clean(value, tags=[], strip=True)` inside the model's `save()` method. This aggressively strips all HTML/JS payloads before they hit the database.
* **Reflected XSS Mitigation**: Django's template engine auto-escapes all variables by default. We strictly prohibit the use of the `|safe` template filter on user-generated content.

### 2.2 SQL Injection (SQLi)
* **Mitigation**: We exclusively use the Django ORM. Raw SQL is strictly forbidden across the entire codebase.

## 3. Financial Transaction Security

### 3.1 Checkout Race Conditions & Double Billing
* **Threat**: A user's network stutters, and they mash the "Submit Payment" button 5 times.
* **Mitigation**: `ordering.models.Order` implements a database-level `UNIQUE` constraint on `idempotency_key`. Subsequent duplicate requests instantly fail at the database level, guaranteeing a customer is never double-charged.

### 3.2 Malicious Webhook Spoofing
* **Threat**: An attacker sends a `POST` request to `/payments/webhook/razorpay/` pretending a payment succeeded.
* **Mitigation**: The webhook ingestion layer resolves the restaurant's payment config, validates the provider signature with HMAC-SHA256, deduplicates provider event IDs and payload hashes, and rejects stale callbacks when a provider timestamp is available. If the signature doesn't match, the request returns 400 Bad Request.

## 4. Multi-Tenant Data Leakage

* **Threat**: A staff member of Restaurant A views orders from Restaurant B.
* **Mitigation**: Logical Isolation. Every core query must explicitly include `restaurant=request.user.restaurant`.
  - Public payment polling and retry endpoints require either a same-restaurant session or a signed payment access token.
  - KDS sockets are restricted to the authenticated user's restaurant and origin-validated in ASGI.

## 5. Security Headers

### 5.1 Django Settings (`prod.py`)

| Setting | Purpose |
| :--- | :--- |
| `SECURE_SSL_REDIRECT = True` | Forces HTTPS for all requests. |
| `SECURE_HSTS_SECONDS = 31536000` | 1 year HTTP Strict Transport Security. |
| `SECURE_HSTS_PRELOAD = config(default=False)` | Allows HSTS preload list submission. Set `True` only after verifying domain on the preload list. |
| `SESSION_COOKIE_SECURE = True` | Cookies transmitted only over HTTPS. |
| `CSRF_COOKIE_SECURE = True` | CSRF token transmitted only over HTTPS. |
| `SECURE_PROXY_SSL_HEADER` | Trusts Nginx `X-Forwarded-Proto` header. |
| `X_FRAME_OPTIONS = 'DENY'` | Prevents Clickjacking. |
| `SECURE_CONTENT_TYPE_NOSNIFF = True` | Prevents MIME-sniffing. |

### 5.2 Nginx Reverse Proxy Headers

| Header | Value | Purpose |
| :--- | :--- | :--- |
| `X-Frame-Options` | `DENY` | Prevents embedding in iframes. |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type guessing. |
| `X-XSS-Protection` | `1; mode=block` | Enables browser XSS filter. |
| `Referrer-Policy` | `same-origin` | Prevents referrer leaks to external domains. |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Disables device APIs. |

## 6. Rate Limiting

Rate limiting is enforced at two layers:

### 6.1 Nginx Proxy Layer (`nginx/nginx.conf`)

| Zone | Rate | Burst | Endpoints |
| :--- | :--- | :--- | :--- |
| `login` | 5 req/min | 3 | `/owner/login/` |
| `checkout` | 30 req/min | 5 | `/r/<slug>/checkout/` |
| `api` | 60 req/min | 10 | `/api/*`, `/payments/*` |
| `general` | 30 req/sec | 20 | All other routes |

### 6.2 Application Layer (`core.ratelimit`)

Django view-level rate limiting via `@rate_limit` decorator using IP-based Redis/cache keys.

## 7. Request Body Limits

- **Nginx**: `client_max_body_size 10M` rejects oversized requests at the proxy.
- **Django**: Server-side cart validation limits line count to 30 and quantity to 99.

## 8. CSV Injection Protection

Reconciliation CSV exports escape cell values that could be interpreted as spreadsheet formulas. The `_csv_safe()` function prefixes values starting with `=`, `+`, `-`, `@`, `\t`, `\r`, `\n` with a single quote.

## 9. Admin Secret Masking

Payment secrets (`razorpay_key_secret`, `razorpay_webhook_secret`) are masked in the Django admin panel. Only the first and last 4 characters are displayed. Values can be updated but never read back in full through the admin interface.

## 10. Debug Information Disclosure

The `debug_permissions` query parameter on `KDSPollView` is gated behind `settings.DEBUG`. In production, this parameter is completely ignored, preventing exposure of username, role, and permission flags.
