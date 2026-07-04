# Security

This page is a tour of the defensive measures actually implemented in the
codebase, organized by the kind of risk each one addresses, including a
deliberately honest note on where a security feature looks stronger on
paper than it is in practice.

## Authentication

- **Staff and owners** authenticate with Django's session framework
  against the custom `User` model (`AUTH_USER_MODEL = 'core.User'`).
  Usernames are unique **per restaurant**, case-insensitively (a database
  constraint, not just application-level validation), so two different
  restaurants can each have a `manager` account without collision.
- **Owners and Admins can enable TOTP-based MFA** (`django-otp` +
  `otp_totp.TOTPDevice`) — a standard authenticator-app second factor.
  It is set up via `/owner/mfa/setup/` (or `/admin/mfa/setup/` for platform admins) 
  and required on subsequent logins once confirmed. The authentication 
  happens in a dedicated 2-step verification flow after standard username/password login.
  Both `OwnerRequiredMixin` and `AdminMfaMiddleware` gate on
  `user.mfa_enabled` before checking `is_verified()`, so users with MFA
  disabled bypass the verification redirect entirely.
- **Customers** (for the post-payment/tab feature) authenticate with a
  restaurant-scoped serial number + PIN, not a password. PINs are hashed
  with a dedicated hasher (`core.hashers.CustomerPINHasher`, PBKDF2 with
  260,000 iterations) precisely because PINs are short and low-entropy —
  using a deliberately expensive hash compensates for that.
- **Customers checking their own payment status or retrying a payment**
  (no session at all, since they never log in) use a signed, per-payment,
  time-limited access token instead — see
  [Payments & Webhooks](./06-payments-and-webhooks.md#customer-facing-endpoints-dont-use-session-auth).

## Authorization

- `User.role` (`OWNER`/`STAFF`) plus three independent boolean flags
  (`allow_cash_collection`, `allow_view_all_orders`,
  `allow_order_completion`) give fine-grained control over what a staff
  account can do on the KDS — a restaurant can, for example, give someone
  cash-handling permission without giving them the ability to bulk-complete
  other staff's tickets.
- **Enforcement ordering**: `CashCollectionMixin`, `OrderCompletionMixin`,
  and `OwnerRequiredMixin` all enforce their permission checks **before**
  calling `super().dispatch()`, so the view body never executes and no
  database side-effects (ledger writes, status transitions, audit entries)
  can occur for an unauthorized request. Each mixin duplicates the base
  `ActiveStaffMixin` authentication guards (`is_authenticated`,
  `is_active`, superuser/no-restaurant check) to ensure safety even if
  called outside the normal MRO.
- `StaffFilter` further restricts *which menu items* a staff account's KDS
  view shows — useful for a restaurant that wants a bar station to only
  see drink orders, for example.
- `MustChangePasswordMiddleware` forces any account with
  `must_change_password=True` (set when an owner creates or resets a staff
  account) to set a new password before reaching any other authenticated
  page — closing the common "shared default password never gets changed"
  gap.

## Tenant isolation — and an honest caveat about Row-Level Security

Every tenant-scoped query in application code filters by the restaurant
tied to the request (the URL slug for customers, the logged-in user's
`restaurant_id` for staff). This application-level filtering is what
actually isolates one restaurant's data from another's.

Postgres Row-Level Security is also enabled on every table
(`core/migrations/0023_enable_rls_all_tables.py`), but it's worth being
precise about what that migration actually does: it exists to satisfy
Supabase's own security advisor, which flags any table reachable through
Supabase's auto-generated REST API (`PostgREST`) without RLS as a
vulnerability. Historically, it was assumed Django connects as a superuser which bypasses RLS, but if deployed with a non-superuser role, RLS will block Django from accessing its own tables. This is why the migration adds an explicit policy to `django_migrations` so Django can always read its migration history. However, for tenant data, RLS here is a guard against a *different* access path (the Supabase API surface, which this application doesn't use for tenant
data), not a second enforcement layer underneath the Django app. If you're
relying on "RLS will catch it" as a backstop for an application-level bug,
it won't — the only real backstop is correct query scoping in the view/
service layer.

## Encryption of stored secrets

Gateway credentials (`RestaurantPaymentConfig.razorpay_key_secret`,
`razorpay_webhook_secret`, and `TenantPaymentConfig.encrypted_credentials`)
are encrypted at rest using Fernet symmetric encryption
(`ordering/payments/crypto.py`), keyed off `PAYMENT_ENCRYPTION_KEY` — a
setting that's deliberately required to be **distinct from `SECRET_KEY`**
in production (`dineflow/settings/prod.py` raises
`ImproperlyConfigured` if it isn't set at all, falling back to
`SECRET_KEY` only outside production). Decryption tries the configured key
first and falls back to `SECRET_KEY` if that fails — this is what lets
`PAYMENT_ENCRYPTION_KEY` be introduced or rotated without breaking
decryption of secrets that were encrypted before the change.

## Input sanitization

User-supplied text fields that get rendered back (restaurant names, menu
item names/descriptions, category names, the "reopening soon" message,
customer names) are run through `bleach.clean()` with all HTML tags
stripped (`core/models.py`'s `_clean()` helper, called from each model's
`save()`). This is defense applied at the data layer, not just in
templates — it holds regardless of which view happens to write the field.

## Rate limiting

`core/ratelimit.py` implements a cache-backed (Redis in production)
sliding-window throttle, applied via `@rate_limit(name, limit=N,
window=seconds)` on the endpoints where abuse would matter most:

| Endpoint | Limit |
|---|---|
| `GET /r/<slug>/` (Menu) | 60 / 60s |
| `POST /r/<slug>/checkout/` | 30 / 60s |
| `POST /payments/razorpay/verify/` | 60 / 300s |
| `POST /payments/webhook/...` | 300 / 60s |
| `GET /api/kds/poll/` | 600 / 60s |
| Owner login | 10 / 300s |
| Change password / staff PIN reset | 5 / 900s |

Two details worth knowing: the limiter **fails open** — if the cache
itself is unreachable, the request is allowed through rather than blocking
legitimate traffic because of an infrastructure problem — and exceeding a
limit returns `429` with a `Retry-After` header set to the window length.
For API requests, the response is JSON. For browser requests, it renders
the `429.html` template.

*(Note: Standard HTTP errors like 400, 403, 404, and 500 are also handled globally via dedicated, branded HTML templates in the `templates/` directory when `DEBUG=False`.)*

Post-payment PIN attempts have their own separate, customer-specific
lockout logic in `ordering/views.py`, layered on top of the general
checkout rate limit.

## Transport and browser-level hardening

`SecurityHeadersMiddleware` sets `Content-Security-Policy` (or
`-Report-Only` while a policy is being tuned) and `Permissions-Policy` on
every response. Combined with settings in `dineflow/settings/base.py` and
`prod.py`: `X_FRAME_OPTIONS = 'DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF`,
HttpOnly + SameSite session cookies, an 8-hour session lifetime
(`SESSION_COOKIE_AGE = 28800`), and `SECURE_PROXY_SSL_HEADER` configured
for the Nginx/Railway reverse-proxy deployment path.

## Production-only fail-fast checks

`dineflow/settings/prod.py` deliberately refuses to start the application
in two specific misconfiguration scenarios, rather than degrading silently:

- Razorpay key ID/secret configured but no webhook secret — without it,
  webhook signature verification is impossible and the system would
  silently fall back to trusting only the unauthenticated frontend
  callback.
- A `rzp_test_` (sandbox) key ID detected in a production environment.

## Audit trail

`OwnerAuditLog` records sensitive owner/staff actions (creating or editing
a customer, resetting a PIN, recording a manual payment, staff account
changes) with a structured `details` JSON payload — useful both for
"who did this" investigations and for satisfying a restaurant's own
internal accountability needs.

**Known limitations**:

- **Django Admin bypass**: A platform superuser can change permission
  flags (`allow_cash_collection`, `allow_order_completion`, `role`)
  directly through Django Admin without going through the owner dashboard.
  These changes are recorded in Django's built-in `LogEntry` table, **not**
  in `OwnerAuditLog`, creating a blind spot in the owner-visible audit
  trail.
- **Order status actions are unauditable**: `Order`, `OrderItem`, and
  `OrderItemAddOn` have no actor/user field — there is currently no
  record of *who* started prep or completed an item. This is a known gap
  to address in a follow-up.
- **Ledger `created_by` is NULL for cash collections**:
  `RestaurantLedgerService.record_cash_payment()` does not thread the
  acting user through to `RestaurantLedger.created_by`. Auditing cash
  collections currently requires joining through `PaymentEvent` to
  recover the staff identity. This is a known gap to address in a
  follow-up.

## Next steps

[Local Development Setup](./11-local-development-setup.md) gets you a
running instance to explore all of the above hands-on.
