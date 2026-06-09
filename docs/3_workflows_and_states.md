# Workflows and State Machines

## Order Lifecycle

The primary state machine revolves around the `Order` aggregate in the `sales` domain.

### 1. `UNPAID`
- **Trigger**: The default state upon successful execution of `PlaceOrderUseCase`.
- **Side Effects**: Stock reservations are actively placed in the `InventoryLedger`. A Celery task (`expire_unpaid_order`) is dispatched to cancel the order if payment is not completed within `cash_payment_timeout_minutes` (default 10m).

### 2. `PENDING`
- **Trigger**: The `OrderPaidEvent` is successfully handled (via the Payment Webhook firing `payment.captured`).
- **Side Effects**: 
  - Revenue and Platform Fee entries are created in the Double-Entry Ledger.
  - Stock is consumed.
  - The ticket appears dynamically on the Kitchen Display System (KDS).

### 3. `PREP_STARTED`
- **Trigger**: Kitchen staff interact with the KDS, acknowledging the ticket.
- **Side Effects**: Timestamp recorded. Client polling (if any) or WebSockets notify the customer UI that food is preparing.

### 4. `COMPLETED`
- **Trigger**: Kitchen staff marks the ticket as ready.
- **Side Effects**: Final delivery to the customer.

### 5. `CANCELLED`
- **Trigger**: The Celery expiration task triggers, or a manual cancellation via the dashboard.
- **Side Effects**: Reserved stock is released. If paid (e.g. manual cancel), a refund sequence is initiated and the Ledger records `DEBIT_REFUND` and `CREDIT_REFUND_REVERSAL`.

## Idempotency Workflow
1. Client generates a unique UUID `Idempotency-Key` locally.
2. Client sends a POST to `/api/sales/{id}/orders/`.
3. If a network timeout occurs but the server succeeded, the client retries the exact same payload with the identical `Idempotency-Key`.
4. The Use Case intercepts the key, queries `Order.objects.filter(idempotency_key=...)`. 
5. If found, the server immediately returns `201 OK` with the existing order details, completely bypassing inventory reservation and database mutations.
