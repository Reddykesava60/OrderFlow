# API Contracts

The APIs are built using standard Django views returning JSON responses, utilizing session authentication for internal tools and token/signature-based authentication for external webhooks.

## Global Headers
- `Idempotency-Key` [UUID] *(Required on payment and order POST requests)*

---

## Ordering API (`ordering/urls.py`)

### `POST /r/<slug:restaurant_slug>/checkout/`
Places a new order in the system, validates stock, and calculates pricing. This is a traditional Django form submission endpoint that redirects to the payment verification page.

## Payments API (`ordering/urls_payments.py`)

### `GET /payments/status/<uuid:payment_id>/`
Polls the current status of a payment transaction.
**Response**: `{"id": "uuid", "state": "paid", "amount": "260.00", "order_id": "uuid"}`

### `POST /payments/razorpay/verify/`
Synchronous fast-path verification called by the frontend immediately after the Razorpay checkout modal closes.

### `POST /payments/webhook/<str:provider>/`
Receives asymmetric webhook events from external providers (e.g., `razorpay`). Requires provider-specific signature headers.
**Response**: `200 OK` (Always returns 200 to prevent gateway retries).

## Kitchen API (`kitchen/urls.py`)

### `GET /api/kds/<uuid:restaurant_id>/active-tickets/`
Fetches the full state of active tickets for a specific restaurant to hydrate the KDS upon initial load or reconnection.

### `POST /api/kds/<uuid:restaurant_id>/tickets/<uuid:order_id>/<str:action>/`
Transitions a ticket through its states (e.g., `acknowledge`, `complete`).
**Response**: `{"status": "success", "order_id": "uuid"}`
