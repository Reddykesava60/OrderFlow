# Incident Playbook

Scenario-driven runbook for the situations you're actually likely to hit
in production, written for the moment you're paged and need to act, not
study. Each scenario tells you what you'll see, why it's happening, and
exactly what to do (including "do nothing" when that's the correct
answer).

Start at `/platform-admin/ops/` (superuser only) for a live snapshot: today's gross
order volume, today's accrued platform fees, the count of webhooks stuck
retrying, the Dead Letter Queue size, and how many restaurants are
currently active/online/offline. Most of the scenarios below are visible
there first.

## A busy Friday night (web traffic spike)

**Symptoms**: The `web` service shows high CPU; pages load a bit slower.

**What's happening**: A lot of customers are browsing menus and building
carts at once — read-heavy, cheap-per-request traffic.

**Action**: Scale up CPU/memory (or replica count) on the **web** service
only. You do not need to scale the worker or the database for this —
reading a menu is inexpensive; it's payment confirmation that's the heavy
operation, and that's a separate process.

## A burst of successful payments at once

**Symptoms**: The `worker` service's memory/CPU spikes; the `web` service
stays calm.

**What's happening**: This is by design. `WebhookIngressView` accepts each
incoming webhook, verifies it, stores it, and returns in milliseconds —
the actual work (state machine transition, stock confirmation, ledger
writes, KDS broadcast) happens in the **worker**, on the dedicated
`payments` queue.

**Action**: Scale the **worker** service (more memory, or more replicas)
to clear the backlog faster. The web service doesn't need to be touched.

## A payment looks "stuck" / banking network lag

**Symptoms**: A customer paid via UPI, the page says "waiting for
confirmation," and it's been a couple of minutes.

**What's happening**: This is expected, normal UPI/NPCI network behavior,
not a bug. See
[Order & Payment Lifecycle](../engineering/04-order-and-payment-lifecycle.md)
for the full explanation of why a UPI confirmation can legitimately take a
few minutes, and why a `FAILED → PAID` recovery exists specifically for
this case.

**Action**: Generally, do nothing — `reconcile_recent_payments_task` (runs
every 15 minutes) and the late-capture recovery path will catch up
automatically. If you want to force an immediate check on one specific
payment rather than waiting for the next scheduled pass:

```bash
python manage.py reconcile_payments --minutes 30 --limit 50
```

## The Dead Letter Queue has entries

**Symptoms**: `/platform-admin/ops/` shows a non-zero DLQ size, or you queried
`WebhookLog.objects.filter(status='DEAD_LETTERED')` directly.

**What's happening**: A webhook's processing raised an exception three
times in a row (`process_payment_webhook_task`'s `max_retries=3`) and
gave up automatically. No data was lost — the full original payload is
sitting in the `WebhookLog` row, untouched.

**Action**:
1. Look at the relevant `WebhookLog.failed_reason` (it holds the full
   traceback from the last attempt) to understand what actually went
   wrong.
2. If it's a transient issue that's since cleared (a brief outage, a bug
   that's now fixed and deployed), replay it directly:
   ```bash
   python manage.py replay_webhook <webhook_id>
   ```
   (Accepts a unique ID prefix, not just the full UUID.)
3. If the underlying cause needs a code fix first, fix and deploy it, then
   replay.
4. If it turns out to be genuinely unprocessable (e.g. a malformed event
   from a misconfigured integration), that's a manual investigation —
   don't just leave it dead-lettered indefinitely without understanding
   why.

## A payment recovered but the items had sold out (`manual_recovery_required`)

**Symptoms**: A `PaymentTransaction` shows `state=PAID` but its `metadata`
contains `"manual_recovery_required": true` and
`"manual_recovery_reason": "late_capture_insufficient_inventory"`, with a
`late_capture_snapshot` showing exactly what was required vs. available.

**What's happening**: A late UPI capture arrived for an order that was
already cancelled, but by the time the system tried to recover it, the
items had genuinely sold out in the meantime. The customer was charged but
the kitchen can't fulfill the original items — the system deliberately
does **not** auto-resolve this, since it requires a judgment call.

**Action**: This is a real customer issue requiring a human decision —
typically either substituting available items and contacting the
customer, or issuing a refund through Razorpay directly. Check
`PaymentEvent` records for that order (`ORDER_RECOVERY_FAILED`,
`PAYMENT_RECOVERY_REQUIRED`) for the full timeline before deciding.

## Database connection exhaustion

**Symptoms**: `500` errors, logs showing `FATAL: sorry, too many clients
already`.

**What's happening**: Every Daphne thread and every Celery worker process
holds its own database connection. If `DATABASE_URL` points at Postgres
directly rather than through a connection pooler, you can exhaust the
database's connection limit under load.

**Action**: Confirm `DATABASE_URL` uses the Supabase **transaction
pooler** endpoint (commonly port `6543`), not the direct connection (port
`5432`). The pooler multiplexes many app-side connections onto a smaller
number of real database connections.

## Selling out fast (flash sale / limited stock item)

**Symptoms**: A handful of customers report "sold out" immediately after
trying to buy a very limited item.

**What's happening**: This is the system working as intended, not a bug.
`StockReservation` creation happens inside a locked, atomic transaction —
if 50 people try to buy the last 5 of something at once, exactly 5 succeed
and the other 45 are rejected with a clear "out of stock" response
*before* they're ever sent to the payment gateway.

**Action**: Nothing required. If you want to confirm no over-selling
actually happened, check that `MenuItem.stock` for the affected item never
went negative and that the number of `StockReservation` rows with
`is_confirmed=True` for that item doesn't exceed what was actually
available.

## Old/orphaned `WebhookLog` rows with no status

**Symptoms**: Rows that predate the current `status` field's introduction,
sitting in an inconsistent state.

**Action**: A one-time repair command exists specifically for this:

```bash
python manage.py fix_webhook_zombies
```

It backfills `status` based on `processed_at`, `failed_reason`, and
`retry_count`. You should not need this on a database that's always been
on a current schema version — it exists for migrating very old data.

## Next

If an incident reveals a gap in monitoring or a missing safeguard, fold
the fix back into
[Production Readiness Checklist](./02-production-readiness-checklist.md)
so the next deployment starts from a stronger baseline.
