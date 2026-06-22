# Background Jobs

Celery does two kinds of work in Dineflow: jobs dispatched **on demand**
(a webhook just arrived, go process it) and jobs that run **on a
schedule** via Celery Beat (safety nets that catch anything the on-demand
path missed). Both matter, and the schedule below is the actual
production configuration, not an approximation.

## Why `ACKS_LATE` and `REJECT_ON_WORKER_LOST` exist

By default, Celery's worker tells Redis "got it, you can forget this
message" the moment it *starts* a task, not when it finishes. If the
worker process is killed mid-task — an out-of-memory kill, a container
restart during a deploy — that task simply vanishes. For most background
work that's an acceptable risk. For payment webhook processing, it is not.

Dineflow sets:

```python
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
```

`ACKS_LATE` delays acknowledgment until the task actually completes
successfully — so a crash mid-task leaves the message unacknowledged, and
Redis makes it visible to another worker again. `REJECT_ON_WORKER_LOST`
closes a related gap: if the *child process* running the task is killed
abruptly, the parent worker explicitly requeues the task instead of
treating it as silently lost. Together, these mean a worker dying at the
worst possible moment costs you a delayed retry, never a dropped payment
event.

`CELERY_WORKER_PREFETCH_MULTIPLIER = 1` is the other half of this: workers
fetch one task at a time rather than grabbing a batch upfront, which keeps
task distribution fair when some tasks (like a slow gateway reconciliation
call) take much longer than others.

## Queues

| Queue | Carries |
|---|---|
| `celery` (default) | General background jobs |
| `payments` | `process_payment_webhook_task` and `process_unprocessed_webhooks_task`, routed here explicitly via `CELERY_TASK_ROUTES` |

The dedicated `payments` queue means a backlog of unrelated background
work can never delay webhook processing — they're consumed independently.

## On-demand tasks (`ordering/payments/jobs.py`)

| Task | Triggered by | Retry behavior |
|---|---|---|
| `process_payment_webhook_task` | A webhook is received and stored | `max_retries=3`, 60s delay. Exhausting retries sets `WebhookLog.status = DEAD_LETTERED`. |
| `verify_payment_task` | The synchronous post-checkout verification path | `max_retries=3`, 60s delay |
| `reconcile_payment_task` | Manually, or from `expire_single_payment_task` | `max_retries=3`, 120s delay |
| `expire_single_payment_task` | `expire_pending_payments_task` finds a stale transaction | Reconciles with the gateway first (in case a webhook is just running late) before actually expiring — so a job that runs at the exact wrong moment can't expire something that's actually about to succeed |
| `retry_failed_payment_task` | Manual retry trigger (`PaymentRetryView` / admin action) | `max_retries=3`, 60s delay |

A useful detail: `_dispatch_or_run()` checks `settings.PAYMENT_JOBS_INLINE`
— if set, jobs run synchronously in the calling process instead of being
queued. This is on by default during tests (so test assertions don't have
to deal with async timing) and can be turned on temporarily in any
environment that doesn't have a working Celery broker, at the cost of
making the request that triggers it slower.

## Scheduled tasks (Celery Beat)

This is the actual `CELERY_BEAT_SCHEDULE` from `dineflow/settings/prod.py`
— if you've seen a different cadence written down elsewhere, this is the
one currently running:

| Task | Interval | Purpose |
|---|---|---|
| `release_expired_reservations_task` | 5 minutes | Releases `StockReservation`s past their expiry and cancels the orders holding them |
| `expire_pending_payments_task` | 5 minutes | Finds `PaymentTransaction`s past `expires_at` still stuck in a non-terminal state and dispatches `expire_single_payment_task` for each |
| `process_unprocessed_webhooks_task` | 1 minute | Re-scans for any verified `WebhookLog` that was stored but never successfully processed — the most important safety net in the system, since it catches anything `process_payment_webhook_task` couldn't finish |
| `stuck_webhook_detector_task` | 5 minutes | Flags webhooks that appear stuck rather than just slow, for operator visibility |
| `reconcile_recent_payments_task` | 15 minutes | Proactively asks Razorpay directly for the true state of recent non-terminal transactions |
| `sync_monthly_statements_task` | 1 hour | Keeps `MonthlyPlatformFeeStatement` rollups current |

## CLI equivalents — for when you need to act manually

Every important job also has a `manage.py` command, useful in an incident
or in an environment without Celery running:

| Command | Equivalent to | Notes |
|---|---|---|
| `manage.py release_expired_reservations` | `release_expired_reservations_task` | Documented to run every 30 minutes via cron as an additional fallback outside Celery Beat |
| `manage.py expire_pending_payments` | `expire_pending_payments_task` | |
| `manage.py reconcile_payments [--minutes N] [--limit N]` | `reconcile_recent_payments_task`, with adjustable window/limit | |
| `manage.py process_payment_webhooks [--limit N]` | `process_unprocessed_webhooks_task` | |
| `manage.py replay_webhook <webhook_id>` | Manually re-runs `process_log()` for one specific `WebhookLog`, by full UUID or a unique prefix | The tool you reach for once you've fixed whatever caused a webhook to dead-letter |
| `manage.py fix_webhook_zombies` | One-time data-repair tool | Backfills `WebhookLog.status` for rows written before the status enum existed (using `processed_at`/`failed_reason`/`retry_count`). You will most likely never need this unless migrating very old data. |

## Next

[API Reference](./09-api-reference.md) documents the HTTP surface that
these jobs sit behind.
