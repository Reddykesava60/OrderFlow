# API Contracts

The Greenfield APIs are built using Django Ninja, providing highly performant JSON serialization and built-in OpenAPI schema generation.

## Global Headers
- `Idempotency-Key` [UUID] *(Required on all POST requests)*

---

## Sales API

### POST `/api/sales/{restaurant_id}/orders/`
Places a new order in the system, validates stock, and calculates pricing.

**Request Payload (`PlaceOrderIn`)**:
```json
{
  "customer_name": "string",
  "payment_method": "CASH | UPI",
  "table_number": "string",
  "idempotency_key": "uuid",
  "items": [
    {
      "menu_item_id": "uuid",
      "quantity": 1,
      "dining_option": "PARCEL | DINE_IN",
      "spice_level": "MILD",
      "addons": [
        {
          "addon_id": "uuid",
          "quantity": 1
        }
      ]
    }
  ]
}
```

**Response (`201 Created`)**:
```json
{
  "id": "uuid",
  "order_number": 1234,
  "status": "UNPAID",
  "total_amount": "260.0000",
  "idempotency_key": "uuid"
}
```

---

## Payments API

### POST `/api/payments/{restaurant_id}/initialize/`
Initializes an intent with the external gateway (e.g. Razorpay) based on the order details.

**Request Payload (`InitializePaymentIn`)**:
```json
{
  "order_id": "uuid",
  "amount": "260.0000",
  "currency": "INR",
  "idempotency_key": "uuid"
}
```

**Response (`200 OK`)**:
```json
{
  "transaction_id": "uuid",
  "provider_order_id": "order_abc123",
  "amount": "260.0000",
  "state": "INITIATED"
}
```

### POST `/api/payments/{restaurant_id}/webhook/{provider}/`
Receives asymmetric webhook events from external providers. Requires provider-specific signature headers (e.g. `X-Razorpay-Signature`).

**Response**:
`200 OK` (Always returns 200 to prevent gateway retries, with a body indicating `{"status": "ok"}` or `{"status": "ignored"}`).
