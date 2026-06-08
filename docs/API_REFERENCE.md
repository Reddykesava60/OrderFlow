# Order-Flow API & Integrations Reference

Order-Flow exposes highly optimized, internal JSON APIs to support the Kitchen Display System (KDS), alongside securely validated Webhook endpoints for external payment gateways.

All tenant-scoped browser flows use Django sessions and CSRF. Public payment status and retry URLs are signed per payment so a copied UUID is not sufficient to inspect or mutate another tenant's payment.

---

## 1. Internal APIs (KDS Polling & Action Endpoints)

These endpoints are strictly for internal use by the Alpine.js frontend. They require active session authentication and validate CSRF tokens on all state-mutating requests.

### 1.1 KDS Polling Endpoint
* **Endpoint**: `GET /api/kds/poll/`
* **Purpose**: Retrieves the real-time state of the kitchen queue.
* **Auth Requirements**: Session Cookie + `ActiveStaffMixin`

**Response Payload Structure:**
```json
{
  "server_time": "2026-05-06T12:00:00Z",
  "cash_timeout_minutes": 10,
  "permissions": {
    "can_complete": true,
    "can_collect": false,
    "can_view_all": true,
    "can_bulk_update": false
  },
  "kitchen": [
    {
      "id": "uuid",
      "order_number": 42,
      "customer": "John D.",
      "status": "PENDING",
      "work_units": [
        { "name": "Burger", "qty": 1, "status": "PENDING", "has_addons": true }
      ]
    }
  ],
  "preparing": [...],
  "payments": [...],
  "all_orders": [...]
}
```
*Note: The response payload is heavily cached in Redis per permission tier to prevent "thundering herd" database spikes.*

### 1.2 State Mutation Endpoints
All mutation endpoints require a `POST` request with the `X-CSRFToken` header.

* **Start Prep (Entire Order)**: `POST /api/order/<uuid>/start-prep/`
* **Start Prep (Single Item)**: `POST /api/item/<uuid>/start-prep/`
* **Complete Work (Single Item)**: `POST /api/item/<uuid>/complete/`
* **Complete All Work**: `POST /api/order/<uuid>/complete-all/`
* **Collect Cash**: `POST /api/cash/<uuid>/collect/`

**Standard Success Response:**
```json
{
  "ok": true,
  "item_id": "uuid",
  "order_status": "PREP_STARTED"
}
```

**Standard Error Response (403 / 409):**
```json
{
  "error": "INVALID_STATUS",
  "message": "This item is already in progress."
}
```

---

## 2. External Integrations (Razorpay)

Order-Flow relies on Razorpay for UPI and digital checkout processing.

### 2.1 Order Creation Flow
When a customer clicks checkout:
1. Order-Flow computes the cart total synchronously on the server.
2. Order-Flow issues a server-to-server API call to `api.razorpay.com/v1/orders`.
3. Razorpay returns an `order_id` (e.g., `order_EKwxAR...`).
4. Order-Flow renders the Razorpay Checkout UI to the client.

### 2.2 Payment Webhook (`/payments/webhook/<provider>/`)
Order-Flow exposes a public webhook ingress for each supported provider.

* **Endpoint**: `POST /payments/webhook/<provider>/`
* **Security Model**: The provider adapter verifies the provider-specific signature before the payload is accepted for processing.
* **Replay Controls**:
  1. Provider event IDs are deduplicated in `WebhookLog`.
  2. Payload hashes are deduplicated per restaurant and provider.
  3. Timestamped providers are rejected if the callback is stale.
* **Process**:
  1. The unified webhook ingress resolves the payment transaction from provider order/payment identifiers.
  2. The payment mutation runs inside a database transaction with row locking.
  3. Successful payments confirm the stock reservation, create `PaymentEvent` and `PlatformFeeRecord`, and broadcast a restaurant-scoped WebSocket refresh.

---

## 3. Real-Time WebSocket APIs

* **Endpoint**: `ws://<domain>/ws/kds/`
* **Protocol**: ASGI / Django Channels
* **Auth Requirements**: Upgraded HTTP Session (`request.user`)

The WebSocket is currently used **exclusively** for uni-directional server-to-client signaling. 

**Server ➔ Client Ping:**
```json
{"action": "refresh"}
```
Upon receiving this ping, the client applies a randomized `0-500ms` jitter and executes an HTTP `fetch` to `/api/kds/poll/` to retrieve the latest state.

**Server ➔ Client Payment Update:**
```json
{"action": "payment_update", "payment_id": "uuid", "state": "paid", "order_id": "uuid"}
```
This event is used for same-restaurant dashboards and KDS clients; the frontend should still re-fetch authoritative state from the API after receiving the push.
