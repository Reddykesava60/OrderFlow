# API Reference

Dineflow is mostly server-rendered Django (views return HTML), with a
focused set of JSON endpoints for the parts of the UI that need
client-side interactivity: checkout, payment status, and the Kitchen
Display System. This page documents the JSON endpoints — for everything
else, the route table in
[Codebase Map](./02-codebase-map.md#url-routing-top-to-bottom) tells you
which view renders which page.

All routes below are mounted under the prefixes set in `dineflow/urls.py`.
Rate limits are enforced with `core.ratelimit.rate_limit` and are listed
where applied — exceeding one returns `429 Too Many Requests`.

## Customer-facing — public, no authentication (`/r/...`)

### `GET /r/<slug>/`
*Rate limit: 60 requests / 60s.*

Renders the restaurant's menu page (HTML), or a "currently closed" page if
the restaurant has paused ordering.

### `POST /r/<slug>/checkout/`
*Rate limit: 30 requests / 60s.*

Creates an order. Accepts a JSON body:

```json
{
  "payment_method": "CASH | UPI | POST_PAYMENT",
  "consent_given": true,
  "customer_name": "string (required unless POST_PAYMENT)",
  "table_number": "string, optional",
  "cart": [ { "...": "menu item / add-on / quantity / spice level" } ],
  "idempotency_key": "uuid, recommended",
  "customer_serial": "required only for POST_PAYMENT",
  "customer_pin": "required only for POST_PAYMENT"
}
```

Response shape depends on the payment method:

| Method | Response |
|---|---|
| `CASH` / `POST_PAYMENT` | `{"status": "ok", "order_id": "...", "order_number": N, "redirect": "/r/<slug>/receipt/<order_id>/"}` |
| `UPI` | `{"status": "razorpay_pending", "order_id": "...", "razorpay_order_id": "...", "razorpay_key_id": "...", "total_paise": N, "receipt_url": "..."}` — the front-end uses this to open the Razorpay checkout modal directly |

Notable error codes (all return a JSON `{"error": "CODE", "message": "..."}`
body): `RESTAURANT_CLOSED` (403), `CONSENT_REQUIRED` (422),
`INVALID_PAYMENT_METHOD` (422), `PAYMENT_METHOD_DISABLED` (403) — also
returned if UPI is requested but no payment gateway is actually configured
for that restaurant — `INVALID_CUSTOMER_CREDENTIALS` (422, with a `429` if
PIN attempts are rate-limited), a `CartError`-derived code with `status`
409 (e.g. an item went out of stock between adding to cart and checkout —
the response includes `item_name` so the UI can say exactly what changed),
and `RAZORPAY_ERROR` (502) if the gateway itself is unreachable when
creating the order.

### `GET /r/<slug>/receipt/<order_id>/`
Renders the order receipt/status page (HTML) — this is the page a customer
watches live as their order moves through the kitchen.

## Payments (`/payments/...`)

### `POST /payments/webhook/<provider>/`
*Rate limit: 300 requests / 60s (the legacy `/payments/razorpay/webhook/`
alias shares the same limit).*

The gateway-facing webhook ingress — see
[Payments & Webhooks](./06-payments-and-webhooks.md) for the full pipeline.
Returns `200 OK` once the event is durably stored and queued; returns
`400` (with the error message as the body) if signature verification or
parsing fails. CSRF-exempt, since the caller is Razorpay, not a browser
with a Dineflow session.

### `POST /payments/razorpay/verify/`
*Rate limit: 60 requests / 300s.*

Called by the customer's browser immediately after the Razorpay checkout
modal closes, as the fast-feedback path described in
[Order & Payment Lifecycle](./04-order-and-payment-lifecycle.md). Verifies
the signature Razorpay's client-side SDK provides and runs the same
`PaymentMutationService` path a webhook would. This is a UX optimization,
not a trust shortcut — the authoritative confirmation still comes from the
server-to-server webhook.

### `GET /payments/status/<payment_id>/`
Polls a payment's current state. Requires either an authenticated session
belonging to that payment's restaurant, **or** a valid per-payment access
token (`?token=...` or an `X-Payment-Access-Token` header) — see
[Payments & Webhooks](./06-payments-and-webhooks.md#customer-facing-endpoints-dont-use-session-auth).
Returns `403 FORBIDDEN` otherwise.

### `POST /payments/retry/<payment_id>/`
Same access control as above. Triggers `PaymentRetryService` to start a
fresh attempt for a payment that failed or expired.

## Kitchen Display System — staff session required (`/api/...`)

### `GET /api/kds/`
Renders the KDS shell page (HTML) — the page kitchen tablets stay open on.

### `GET /api/kds/poll/`
*Rate limit: 600 requests / 60s.*

The REST hydration endpoint described in
[Real-Time Kitchen Display](./07-realtime-kitchen-display.md). Returns the
complete current list of active tickets for the staff member's
restaurant, scoped by their `StaffFilter` if one applies. This is what the
WebSocket's `refresh` event tells the client to call — the WebSocket
message itself carries no order data.

### Ticket action endpoints
All `POST`, all require a staff/owner session with the relevant permission
flag set on the `User`, all trigger a KDS broadcast on success:

| Endpoint | Effect |
|---|---|
| `POST /api/order/<order_id>/start-prep/` | Marks every pending item/add-on on the order as `PREPARING` (or `COMPLETED` if `kds_prep_enabled` is false) |
| `POST /api/item/<item_id>/start-prep/` | Marks a single `OrderItem` as `PREPARING` (or `COMPLETED` if `kds_prep_enabled` is false) |
| `POST /api/addon/<addon_id>/start-prep/` | Marks a single `OrderItemAddOn` as `PREPARING` (or `COMPLETED` if `kds_prep_enabled` is false) |
| `POST /api/item/<item_id>/complete/` | Marks a single `OrderItem` as `COMPLETED` |
| `POST /api/addon/<addon_id>/complete/` | Marks a single `OrderItemAddOn` as `COMPLETED` |
| `POST /api/order/<order_id>/complete-all/` | Marks every item/add-on on the order `COMPLETED` (requires `allow_order_completion` **and** `allow_view_all_orders`, or owner role) |
| `POST /api/cash/<order_id>/collect/` | Confirms a cash order's payment (requires `allow_cash_collection`) |

### `GET /ws/kds/`
WebSocket endpoint (note: under `/ws/`, not `/api/`, wired through
`dineflow/asgi.py`). Pushes `{"action": "refresh", ...}` and
`{"action": "payment_update", ...}` events. See
[Real-Time Kitchen Display](./07-realtime-kitchen-display.md).

## Owner dashboard (`/owner/...`)

This is a server-rendered, session-authenticated area (login, dashboard,
menu/staff/customer/settings management, reconciliation) rather than a
JSON API. `owner_login` is rate-limited to 10 attempts / 300s,
`change_password` and `staff_reset_pw` to 5 / 900s each — see
[Security](./10-security.md) for why those specific limits exist. The full
route list is in
[Codebase Map](./02-codebase-map.md#url-routing-top-to-bottom).

## Internal dashboards

`/platform-admin/` (Django Admin), `/platform-admin/kds-metrics/`, and `/platform-admin/ops/` are
platform-operator-only HTML dashboards, not part of the customer- or
restaurant-facing API surface — see
[Production Readiness Checklist](../operations/02-production-readiness-checklist.md)
for what they're used for operationally.

## Next

[Security](./10-security.md) covers authentication, authorization, and the
defensive measures referenced throughout this page.
