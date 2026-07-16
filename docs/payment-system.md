# Payment System Architecture

The payment subsystem in Order-Flow is designed for high reliability, idempotency, and strong consistency, ensuring that orders are never marked paid without verifiable funds, and inventory is never permanently leaked on failed payments.

## Core Payment Flow

1. **Checkout Initiation:** Customer selects a payment method and taps Pay.
2. **Stock Reservation:** Inventory is atomically decremented and held in `StockReservation`.
3. **Transaction Creation:** A `PaymentTransaction` is created in `PENDING` state via `PaymentOrchestratorService`.
4. **Gateway Intent:** A payment intent (e.g., Razorpay Order) is generated.
5. **Client Handoff:** The frontend receives the intent URL/QR and presents it to the customer.
6. **Confirmation:** The gateway fires a webhook (or client redirects back).
7. **Reconciliation:** The `PaymentMutationService` atomically marks the payment `PAID`, confirms stock reservations, updates `RestaurantLedger`, and fires KDS WebSocket updates.

## Webhook Ingestion Pipeline

To prevent race conditions and handle provider retries gracefully, webhooks are processed asynchronously:

1. **Ingress (`WebhookIngressView`)**: Validates HMAC signature and timestamp (replay protection).
2. **Persistence (`WebhookLog`)**: Saves the payload to DB. Uniqueness constraint on `(provider, provider_event_id)` acts as the first layer of idempotency.
3. **Queueing (`ProcessPaymentWebhookJob`)**: Dispatches the ID to a dedicated Celery `payments` queue.
4. **Processing (`WebhookIngestionService`)**: Loads the log, looks up the corresponding `PaymentTransaction`, and routes the event to `PaymentMutationService`.
5. **Mutation (`PaymentMutationService`)**: Uses `select_for_update()` to lock the transaction, apply the state change, update the order, and record ledger entries atomically.

## State Machine

`PaymentTransaction` adheres to a strict state machine (`PaymentStateMachine`):
- `PENDING` → `INITIATED` (Gateway intent created)
- `INITIATED` → `PROCESSING` (Webhook received, verification in progress)
- `INITIATED` | `PROCESSING` → `PAID` (Funds verified)
- `INITIATED` | `PROCESSING` → `FAILED` (Payment failed at gateway)
- `INITIATED` → `EXPIRED` (Time window elapsed without payment)

## Expiry & Stock Release

If a customer abandons a checkout, the inventory must be returned.
- A Celery Beat task (`expire_pending_payments_task`) runs every 5 minutes.
- It finds payments past their `expires_at` threshold.
- It first calls `PaymentReconciliationService` to proactively ask the gateway if the payment actually succeeded (handling cases where webhooks were dropped).
- If unpaid, it transitions the payment to `EXPIRED`, cancels the Order, and releases the `StockReservation` back to `MenuItem.stock`.
