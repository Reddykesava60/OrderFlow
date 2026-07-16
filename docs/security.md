# Security Architecture

Order-Flow is built with defense-in-depth, prioritizing tenant isolation, financial integrity, and data protection.

## Authentication & Authorization

### Staff / Owner Panel
- **Session Authentication**: Django's robust `SessionMiddleware` is used for all internal dashboards.
- **MFA (Multi-Factor Auth)**: TOTP-based MFA is supported via `django-otp`. Owners can mandate MFA for staff via `mfa_enabled` on the `User` model.
- **Forced Password Changes**: A custom middleware (`ForcePasswordChangeMiddleware`) intercepts requests if a staff member's `must_change_password` flag is set, forcing them to update their credentials before accessing the KDS or admin panels.

### Tenant Isolation
- **URL-Agnostic Isolation**: Tenant ID is NEVER read from the URL for staff/owner routes. Instead, it is inextricably tied to the authenticated user's session (`request.user.restaurant`). This prevents IDOR (Insecure Direct Object Reference) vulnerabilities where a user could manipulate a URL parameter to view another restaurant's data.

## Payment & Financial Security

### Double-Entry Ledger
- **Financial Integrity**: All financial movements (customer balances, platform fee deductions, payouts) are recorded in append-only double-entry ledger tables (`RestaurantLedger`, `LedgerEntry`).
- **Atomicity**: Changes to balances and creation of ledger entries are strictly wrapped in `transaction.atomic()` with `select_for_update()` row-level locking.

### Encrypted Provider Credentials
- **Encryption at Rest**: Payment provider keys (e.g., Razorpay secrets for specific tenants) are encrypted in the database using symmetric AES encryption (Fernet) via `ordering.payments.crypto`.
- **Key Separation**: The encryption key (`PAYMENT_ENCRYPTION_KEY`) is strictly separated from the Django `SECRET_KEY`.

### Webhook Hardening
- **Signature Verification**: All webhooks validate the HMAC signature (e.g., `hmac.compare_digest`) before parsing payloads.
- **Replay Protection**: The `_is_webhook_timestamp_fresh` check prevents attackers from capturing a valid webhook payload and resending it hours later.
- **Deduping**: Webhooks are deduped by `payload_hash` to prevent double-crediting if the provider retries.

## Application Security (AppSec)

### Data Sanitization (XSS Mitigation)
- **Bleach Integration**: User-supplied text (names, phone numbers, item descriptions) is scrubbed of HTML/JS via Mozilla's `bleach` library in the model `save()` methods before hitting the database.
- **Content Security Policy (CSP)**: Enforced via `django-csp` in production to prevent execution of unauthorized inline scripts.

### Rate Limiting
- **Redis-Backed Limits**: Critical endpoints (Login, Checkout, API, Webhooks) are rate-limited at the Nginx layer and the Django application layer (`core.ratelimit`) to mitigate brute-force and DDoS attacks.
- **Fail-Open Policy**: If Redis is unreachable, the application-level rate limiter fails open to prioritize business continuity over strict limiting, while Nginx continues to provide a baseline defense.

### Network & Infrastructure
- **HSTS Preloading**: `Strict-Transport-Security` headers enforce HTTPS.
- **Non-Root Containers**: Docker images run as a restricted `dineflow` user, not root.
- **Hidden Metrics**: Prometheus `/metrics` endpoints are explicitly blocked from public access in Nginx.
