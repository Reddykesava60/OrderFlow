# Workflows and State Machines

## Order Lifecycle

The primary state machine revolves around the `Order` aggregate in the `sales` domain.

### 1. `UNPAID`
- **Trigger**: The default state upon successful execution of `PlaceOrderUseCase`.
- **Side Effects**: Stock reservations are actively placed in the `InventoryLedger`. A Celery task (`expire_unpaid_order`) is dispatched to cancel the order if payment is not completed within `cash_payment_timeout_minutes` (default 10m).

### 2. `PENDING`
- **Trigger**: Payment confirmation, which now uses a highly resilient dual-path architecture:
  1. **Fast-path operational confirmation**: The frontend checkout calls `/payments/razorpay/verify/` which verifies the checkout signature AND performs a server-side `payment.fetch()` to ensure the payment was captured. This provides immediate, low-latency confirmation necessary for kitchen (KDS) responsiveness.
  2. **Authoritative async reconciliation**: Webhooks (e.g. `payment.captured`) act as the ultimate source of truth and safety net, providing cryptographically verified server-to-server confirmation in case the fast-path is interrupted (e.g., user closes the browser too early). Both paths are idempotent and safely map to `PaymentMutationService.mark_paid()`.
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
