# API Contracts

The APIs are built using standard Django views returning JSON responses, utilizing session authentication for internal tools and token/signature-based authentication for external webhooks.

## Global Headers
- `Idempotency-Key` [UUID] *(Required on payment and order POST requests)*

---

## Ordering API

### POST `/r/{restaurant_slug}/checkout/`
Places a new order in the system, validates stock, and calculates pricing. This is a traditional Django form submission endpoint that returns a redirect to the payment or success page.

### GET `/payments/status/{payment_id}/`
Polls the current status of a payment transaction.

**Response (`200 OK`)**:
```json
{
  "id": "uuid",
  "state": "paid",
  "amount": "260.00",
  "order_id": "uuid"
}
```

---

## Payments Webhook API

### POST `/payments/webhook/{provider}/`
Receives asymmetric webhook events from external providers (e.g., `razorpay`). 
Requires provider-specific signature headers (e.g., `X-Razorpay-Signature`).

**Processing Flow**:
1. Request is received and signature is verified.
2. The raw payload is saved to `WebhookLog`.
3. A Celery task (`process_payment_webhook_task`) is dispatched to process the webhook asynchronously.
4. The endpoint immediately returns `200 OK` to prevent gateway retries.

**Response**:
`200 OK` (Always returns 200 to prevent gateway retries).
