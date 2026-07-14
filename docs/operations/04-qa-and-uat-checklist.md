# QA & UAT Checklist

The happy path (browse menu → pay → food arrives) is the least interesting
thing to test in this system — it's also the easiest to get right by
accident. This checklist focuses on the edge cases that actually decide
whether real money and real inventory stay correct under real-world
conditions. Run this against a live (or live-like) environment using
Razorpay **Test Mode**, not just locally — some of these scenarios depend
on real webhook delivery timing that's hard to fully simulate locally.

## 1. Multi-tenant isolation (the most important category)

The worst possible bug in a multi-tenant system is Restaurant A seeing
Restaurant B's anything.

- [x] **Cross-tenant ordering**: open Restaurant A's menu, then manually
  change the URL slug to Restaurant B's. Confirm the cart resets/rejects
  rather than letting you check out Restaurant A's items against
  Restaurant B.
- [x] **Dashboard isolation**: log in as Restaurant A's owner, then try to
  navigate directly to a Restaurant B record by ID/URL. Confirm you get
  blocked, not a partial or full view of their data.
- [x] **KDS isolation**: open Restaurant A's kitchen display, place an
  order on Restaurant B's menu, and confirm it never appears on
  Restaurant A's screen.



## 2. Concurrency and stock locking

- [x] Set a menu item's stock to exactly `1`. Attempt to check out that
  item from two different devices at effectively the same instant.
  **Expected**: exactly one succeeds; the other is rejected with a clear
  out-of-stock error *before* being sent to the payment gateway, not
  after being charged.



## 3. Webhook and payment resilience

- [x] **The "dead phone" test**: start a UPI checkout, complete the test
  payment successfully in Razorpay's flow, and **immediately** close the
  browser tab before being redirected back. **Expected**: the order still
  gets confirmed and appears in the kitchen — driven entirely by the
  server-to-server webhook, with no dependency on the customer's browser
  surviving the transaction.
- [x] **Idempotent redelivery**: from the Razorpay dashboard, manually
  resend a successful webhook event several times in a row. **Expected**:
  only the first delivery has any effect; subsequent ones are recognized
  as duplicates and are no-ops (no double-counted revenue, no duplicate
  ledger entries).
- [ ] **Late capture recovery**: this is harder to trigger on demand since
  it depends on real banking network timing, but if you observe one in
  Test Mode (or can simulate the webhook sequence manually), confirm the
  order recovers correctly per
  [Order & Payment Lifecycle](../engineering/04-order-and-payment-lifecycle.md)
  rather than staying incorrectly cancelled.



## 4. Order lifecycle (kitchen side)

- [x] **KDS reconnect**: disconnect the kitchen device's network, place an
  order from a customer device, then reconnect the kitchen device.
  **Expected**: it automatically re-fetches the complete current state and
  the order appears — nothing is permanently missed by a temporary
  disconnect.
- [x] **Cancellation releases stock**: cancel an order from the kitchen
  side and confirm the held stock returns to the menu immediately
  (visible as the item becoming orderable again if it had hit zero).



## 5. Expiration behavior

- [x] **Abandoned UPI checkout**: start checkout, reach the Razorpay
  screen, then simply abandon it without paying. **Expected**: after the
  payment's expiry window (15 minutes by default —
  see `expire_pending_payments_task` in
  [Background Jobs](../engineering/08-background-jobs.md)), the
  transaction expires and any reserved stock is released.
- [x] **Abandoned cash order**: create a cash order and never confirm
  payment at the counter. **Timeout Expiration**
  Wait past the designated cash timeout duration (defaults to 10 minutes — configurable via `RestaurantConfig.cash_payment_timeout_minutes` on the backend). The order auto-cancels and stock is restored.
  Don't assume this matches the UPI window — they're independently
  configured.



## 6. Financial reconciliation

Because the books are double-entry (see
[Financial Ledger](../engineering/05-financial-ledger.md)), they should
always tie out exactly.

- [ ] At the end of a test session, check the `RestaurantLedger` entries
  for the restaurant you tested with (via Django Admin or the
  Reconciliation screen) and confirm the running balance matches what you
  expect from the orders you actually placed.
- [ ] Confirm `PlatformFeeRecord.fee_amount` for each test order matches
  the platform fee rate that was actually configured *at the time* —
  remember the rate is snapshotted per-order, so changing the default rate
  mid-test should not retroactively change earlier orders' fee amounts.
- [ ] If you test a refund, confirm the reversing entries appear (don't
  expect the original entry to be edited or deleted — see
  [Financial Ledger](../engineering/05-financial-ledger.md#refunds-the-reversing-entry-pattern-applied-consistently)).



## How to actually run this

Don't run the payment-related scenarios against a purely local
environment with `PAYMENT_JOBS_INLINE=True` and no real webhook delivery
— several of these tests (the "dead phone" test, idempotent redelivery,
late captures) specifically exercise real network and timing behavior
between your server and Razorpay. Run them against your actual deployed
environment with Razorpay **Test Mode** keys, using Razorpay's test
cards/UPI simulators. Once every item above is checked, switch the
environment's Razorpay keys from test to live and open up to real
customers.

## Next

Once QA passes, you're ready to operate this for real — keep
[Incident Playbook](./03-incident-playbook.md) close for the first few
weeks of live traffic.