# Edge-Case Handling Guide

## Payment Creation
- Treat checkout creation as an atomic transaction.
- Lock the order row before creating a payment transaction.
- Re-check for an active payment transaction after the lock is acquired.
- Reuse the existing active payment when a retry arrives during an in-flight checkout.

## Webhook Processing
- Accept each webhook event once per provider event ID.
- Also dedupe on payload hash for providers that resend the same body.
- Reject stale webhooks when a provider sends a timestamp header.
- Keep webhook handlers idempotent so retries do not double-confirm an order.

## Post-Payment Customers
- Reject blocked customers before stock is reserved.
- Reject disabled post-payment customers before any order rows are written.
- Lock the customer row before checking or updating balance.
- Enforce credit limits against the locked, current balance.
- Create the ledger entry in the same transaction as the balance update.

## Refunds
- Refunds are handled outside the application in the provider dashboard for the current business model.
- The application preserves historical refund-related fields for compatibility, but does not execute refunds or process refund webhooks.
- Do not mutate RestaurantLedger or RestaurantBalance for refund callbacks.

## Stock and KDS
- Stock is decremented under lock and restored only from the matching reservation.
- Failed or expired payments must release the held stock in the same transaction.
- KDS refresh events should be broadcast only after the database commit succeeds.
- If a client drops its WebSocket connection, the next reconnect must re-poll state.

## Customer Experience
- Surface clear errors for invalid PIN, blocked customer, credit limit, and payment timeout.
- Keep retry flows explicit: expired payment, fresh payment, or cash fallback.
- Never silently create a new payment when the current one is still active.
