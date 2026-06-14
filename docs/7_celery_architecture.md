# Background Processing (Celery Architecture)

Dineflow relies on Celery for executing asynchronous background jobs and scheduled periodic tasks to ensure high availability and responsiveness in the API layer.

## Infrastructure Stack
- **Celery Worker**: The daemon that consumes and processes tasks.
- **Celery Beat**: The scheduler that enqueues periodic tasks (e.g. expiring unpaid orders, reprocessing webhooks).
- **Redis Broker**: Acts as the message queue. Hosted on Railway internal network (`redis.railway.internal`).

## Queues
We use targeted queues to ensure high priority tasks (like payment confirmations) are not blocked by heavy background reconciliation tasks:
1. **`celery` (Default Queue)**: Handles general background jobs (e.g., expiring old carts).
2. **`payments` Queue**: A dedicated, high-priority queue specifically for `process_payment_webhook_task`. This ensures webhooks are consumed instantly even if the default queue is backed up.

## Fault Tolerance & Reliability
Payment webhooks carry critical financial data. The architecture enforces strict reliability guarantees:

### `ACKS_LATE`
By default, Celery acknowledges messages *before* executing them. If a worker crashes mid-execution (OOM kill, container restart), the task is lost. 
We set `ACKS_LATE = True` globally. The worker will only acknowledge the message from Redis *after* the task successfully returns. If the worker crashes, the unacknowledged message becomes visible to other workers again and is re-processed.

### `REJECT_ON_WORKER_LOST`
When combined with `ACKS_LATE`, setting `task_reject_on_worker_lost = True` ensures that if a child worker process is abruptly terminated, the master process explicitly requeues the task rather than dead-lettering it.

## Scheduled Jobs (Beat)
- **`process_unprocessed_webhooks_task` (Every 1 minute)**: Scans `WebhookLog` for entries where `processed_at__isnull=True`. This acts as a safety net catching webhooks that were dropped during transit or failed due to transient infrastructure errors (e.g., Redis timeouts).
- **`reconcile_recent_payments_task` (Every 5 minutes)**: Proactively queries Razorpay for `PaymentTransaction` records stuck in `INITIATED`, pulling state manually if webhooks were missed entirely.
