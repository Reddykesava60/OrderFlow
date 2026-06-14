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

## Payment Observability Timeline

Every transition in the payment lifecycle is immutably tracked via `PaymentEvent` in the `kitchen` app. This provides a clear audit trail for diagnosing stalled or failed payments.

1. **`RAZORPAY_INITIATED` / `DIGITAL_PAYMENT_INITIATED`**: Logged when the intent is created.
2. **`WEBHOOK_PROCESSING_STARTED`**: Logged the moment a Celery worker picks up a received webhook log.
3. **`RAZORPAY_CONFIRMED` / `PAYMENT_FAILED`**: Logged when the database transaction successfully commits the state change.
4. **`WEBHOOK_PROCESSING_COMPLETED`**: Logged at the very end of processing, after KDS broadcasts have finished.
5. **Exception Events**: Events like `WEBHOOK_LOOKUP_FAILED` or `PAYMENT_STATE_TRANSITION_FAILED` are logged with detailed metadata if validation or routing fails.

## Idempotency Workflow
1. Client generates a unique UUID `Idempotency-Key` locally.
2. Client sends a POST to create an order.
3. If a network timeout occurs but the server succeeded, the client retries the exact same payload with the identical `Idempotency-Key`.
4. The service intercepts the key, queries `Order.objects.filter(idempotency_key=...)`. 
5. If found, the server immediately returns the existing order details, bypassing inventory reservation and database mutations.
