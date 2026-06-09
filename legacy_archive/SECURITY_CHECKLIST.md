# Security Checklist

## Identity and Access
- [ ] Staff and owner accounts are always scoped to a single restaurant.
- [ ] Superusers cannot access restaurant staff screens unless explicitly intended.
- [ ] PINs are stored with `make_password()` and verified with `check_password()`.
- [ ] Customer PIN changes are audited.
- [x] Owner actions that modify money, customers, or permissions are written to `OwnerAuditLog`.

## Tenant Isolation
- [ ] Every order, customer, payment transaction, and ledger entry is filtered by `restaurant`.
- [ ] Cross-tenant lookups never use raw UUIDs without tenant checks.
- [ ] Payment polling and retry endpoints require either a valid signed token or an authenticated same-restaurant session.
- [ ] WebSocket consumers only join the authenticated user’s restaurant channel.
- [ ] WebSocket origin checks are enforced by `AllowedHostsOriginValidator`.

## Payments
- [ ] Razorpay credentials are stored per restaurant and not shared globally for tenant traffic.
- [ ] Webhook signatures are verified before processing.
- [ ] Webhook replay is blocked using payload dedupe, provider event IDs, and freshness checks where supported.
- [ ] Public payment status/retry URLs are signed and short-lived.
- [ ] Duplicate checkout creation is prevented inside the payment transaction lock.
- [ ] Refunds are handled manually outside the app and do not mutate payment or ledger state.

## Data Handling
- [ ] CSRF protection remains enabled for browser-based POST flows.
- [ ] HTML output is escaped by templates; any rich text is sanitized server-side.
- [ ] SQL is executed through the ORM or parameterized queries only.
- [ ] Secrets are read from environment variables and never logged.
- [ ] Sensitive credentials are encrypted at rest where tenant-managed.

## Logging
- [ ] Log every payment state transition, webhook failure, and manual customer balance change.
- [ ] Avoid logging raw secrets, full card data, or full customer PINs.
- [ ] Correlate logs by `order_id`, `payment_id`, `restaurant_id`, and webhook event ID.
