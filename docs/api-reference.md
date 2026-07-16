# API Reference

## Authentication
Internal staff and owner endpoints rely on Django Session Authentication (`sessionid`).
Payment webhooks rely on HMAC Signature verification.

---

## KDS API (Kitchen Display System)

### `GET /api/kds/poll/`
Fetches the full state of active orders for the current restaurant. Used for initial hydration and reconnection.

**Response:**
```json
{
  "orders": [
    {
      "id": "uuid",
      "order_number": 123,
      "type": "DINE_IN",
      "status": "PENDING",
      "items": [
        {
          "id": "uuid",
          "name": "Burger",
          "quantity": 1,
          "status": "PENDING"
        }
      ]
    }
  ]
}
```

### `POST /api/order/<uuid>/start-prep/`
Moves an order from `PENDING` to `PREP_STARTED`.

### `POST /api/item/<uuid>/complete/`
Marks a specific order line item as completed. If all items in an order are completed, the order auto-transitions to `COMPLETED`.

---

## Payment API

### `POST /payments/webhook/<provider>/`
Ingress for all payment provider webhooks.
- **Headers:** Requires provider-specific signature headers (e.g., `X-Razorpay-Signature`).
- **Security:** Idempotent, validates HMAC, payload timestamp replay window, and queues to Celery.

### `GET /payments/status/<uuid:payment_id>/?token=<token>`
Polled by the customer checkout frontend to check if a digital payment succeeded.

---

## WebSockets (Channels)

**Endpoint:** `wss://<domain>/ws/kds/`

**Payloads Received by Client:**

`kds.refresh`
Instruction to client to re-fetch full state via `/api/kds/poll/`.
```json
{
  "type": "kds.refresh",
  "order_id": "uuid",
  "action": "refresh"
}
```

`payment.update`
Live update for payment status changes on the checkout screen.
```json
{
  "type": "payment.update",
  "payment_id": "uuid",
  "state": "PAID"
}
```
