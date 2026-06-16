# Workflows and State Machines

## Order Lifecycle

The primary state machine revolves around the `Order` aggregate in the `ordering` app.

### 1. `UNPAID`
- **Trigger**: The default state upon successful execution of `place_cash_order` or `place_upi_order` in `ordering/services.py`.
- **Side Effects**: Temporary `StockReservation` records are created to hold inventory. A Celery task (`expire_unpaid_order_task`) is dispatched to cancel the order if payment is not completed within a configured timeout.

### 2. `PENDING`
- **Trigger**: Payment confirmation, which relies on a resilient multi-path architecture:
  1. **Authoritative async reconciliation**: Webhooks (e.g. `payment.captured`) act as the ultimate source of truth, providing cryptographically verified server-to-server confirmation.
  2. **PaymentMutationService**: Events are routed through `apply_provider_event()` to either `mark_paid()` or `mark_failed()`. This handles idempotency and exact amount validations.
- **Side Effects**: 
  - Revenue and Platform Fee entries are created in the Double-Entry Ledger.
  - `StockReservation` is confirmed, permanently deducting from `MenuItem.stock`.
  - The ticket appears dynamically on the Kitchen Display System (KDS).

### 3. `PREP_STARTED`
- **Trigger**: Kitchen staff interact with the KDS, acknowledging the ticket.
- **Side Effects**: Timestamp recorded. KDS WebSocket broadcasts update the UI.

### 4. `COMPLETED`
- **Trigger**: Kitchen staff marks the ticket as ready.
- **Side Effects**: Final delivery to the customer. KDS WebSocket broadcasts update the UI.

### 5. `CANCELLED`
- **Trigger**: The Celery expiration task triggers, a failed webhook (`payment.failed`) is processed, or a manual cancellation via the dashboard.
- **Side Effects**: Reserved stock is released back to `MenuItem.stock`. If paid, a refund sequence is initiated and the Ledger records `DEBIT_REFUND` and `CREDIT_REFUND_REVERSAL`.

## Payment Observability and Webhook Lifecycle

Every transition in the payment lifecycle is immutably tracked via `PaymentEvent` in the `kitchen` app. This provides a clear audit trail for diagnosing stalled or failed payments.

3. **Dedicated Webhook Processing Lifecycle**
The end-to-end webhook processing pipeline flows deterministically:
**Webhook Received** → **WebhookLog(Status=RECEIVED)** → **Task Enqueued** → **`WEBHOOK_PROCESSING_STARTED`** → **Payment Mutation** → **`RAZORPAY_CONFIRMED` / `PAYMENT_FAILED`** → **WebhookLog(Status=PROCESSED)** → **`WEBHOOK_PROCESSING_COMPLETED`**

1. **`RAZORPAY_INITIATED` / `DIGITAL_PAYMENT_INITIATED`**: Logged synchronously when the client creates the initial order intent.
2. **Webhook Receipt**: The `WebhookLog` model acts as an immutable ledger of incoming gateway events. Its fields have specific operational semantics:
   - `status`: Enum tracking the webhook state (`RECEIVED`, `PROCESSED`, `FAILED`, `DLQ`).
   - `signature_valid`: A boolean indicating if the webhook passed cryptographic verification. Unverified webhooks are ignored by the Celery processor.
   - `provider_event_id`: Used to track and deduplicate the specific event ID sent by the gateway (e.g., preventing double-processing of the exact same Razorpay event).
   - `failed_reason`: Stores the exception traceback if terminal processing failed due to a business logic violation.
   - `retry_count` and `next_retry_at`: Controls the exponential backoff logic for background tasks to retry processing up to a maximum number of times before permanently landing in the Dead Letter Queue (DLQ).
4. **`RAZORPAY_CONFIRMED` / `PAYMENT_FAILED`**: Logged when the database transaction successfully commits the state change.
5. **`WEBHOOK_PROCESSING_COMPLETED`**: Logged at the very end of processing, after KDS broadcasts have finished.
6. **Exception Events**: 
   - `PAYMENT_TRANSACTION_NOT_FOUND`: Logged if the incoming webhook references an unknown order.
   - `WEBHOOK_PROCESSING_EXCEPTION`: Logged for general traceback failures (e.g. invalid JSON, missing keys).
   - `PAYMENT_STATE_TRANSITION_FAILED`: Logged when validation or business rules reject the transition (e.g. incorrect amounts).

## Payment State Transitions

The `PaymentTransaction` state machine enforces strict financial consistency:
- **`INITIATED` → `PAID`**: The standard success path when a webhook confirms the transaction.
- **`INITIATED` → `FAILED`**: The standard failure path when a webhook or polling detects a timeout or insufficient funds.
- **`FAILED` → `PAID` (Late Capture Recovery)**: Allowed exclusively for UPI late captures (see below).
- **Invalid Transitions**: Any attempt to transition `PAID → FAILED` or `PAID → INITIATED` raises a `ValueError` to prevent financial corruption.

## Late-Captures and Out-of-Order Webhooks

### Known Razorpay Behavior
In the UPI ecosystem, network timeouts between the user's bank app and the NPCI network frequently cause immediate failures. In these scenarios, Razorpay fires a `payment.failed` webhook. However, the banking network may ultimately clear the transaction 30 seconds to several minutes later. When this happens, Razorpay fires `payment.captured` and `order.paid` webhooks out of order, *after* the failure.

### FAILED -> PAID Recovery
To prevent financial loss for the user (who was charged) and the restaurant (who never received the order), the `PaymentTransaction` state machine explicitly permits the `FAILED -> PAID` transition. 

When a late-capture webhook arrives:
1. The `PaymentTransaction` transitions from `FAILED` to `PAID`.
2. A deterministic recovery flow runs: It checks if `MenuItem` and `AddOn` stock is still available.
3. If stock is available, it is deducted, the `Order` reopens to `PENDING`, and KDS is notified.
4. If stock is unavailable (sold out), the `Order` remains `CANCELLED` and operations must manually refund the late capture.

## Idempotency Workflow
1. Client generates a unique UUID `Idempotency-Key` locally.
2. Client sends a POST to create an order.
3. If a network timeout occurs but the server succeeded, the client retries the exact same payload with the identical `Idempotency-Key`.
4. The service intercepts the key, queries `Order.objects.filter(idempotency_key=...)`. 
5. If found, the server immediately returns the existing order details, bypassing inventory reservation and database mutations.
