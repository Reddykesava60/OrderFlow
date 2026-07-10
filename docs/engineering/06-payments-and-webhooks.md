# Payments & Webhooks

This is the integration boundary between Dineflow and the outside world's
money. Almost every defensive measure in this file exists because of a
real failure mode that payment integrations run into in production.

## Resolving which credentials to use

A given restaurant might pay through the platform's shared Razorpay
account, or through their own. `ordering/payments/resolver.py` is the
**single** place this decision is made — every other module that needs
gateway credentials goes through it rather than checking models directly.
The resolution order:

1. **`TenantPaymentConfig`** — the current, multi-provider model. If the
   restaurant has an active config here, it wins.
2. **`Platform-level credentials`** (`RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET`
   environment variables) — the fallback every restaurant uses by default.

## Creating a payment

`PaymentOrchestratorService` creates the `PaymentTransaction` row and the
corresponding order on Razorpay's side, using whatever the resolver hands
it. This is also where `gateway_account_source` and
`gateway_account_identifier` get stamped onto the transaction — useful
later for "which account actually processed this?" without re-deriving it.

## The webhook pipeline, step by step

`WebhookIngestionService` runs in two distinct phases, and understanding
why they're split matters:

### Phase 1 — `receive()`, runs synchronously in the request

This runs inline, in the web process, the instant Razorpay's HTTP request
arrives at `POST /payments/webhook/<provider>/`:

1. Parse the payload and figure out which `PaymentTransaction` it refers
   to.
2. **Replay protection**: reject the webhook outright if its timestamp is
   outside the allowed freshness window. For Razorpay, the timestamp is
   read from the parsed JSON payload's `created_at` field (a Unix
   timestamp); other providers may supply it via a header instead.
3. **Signature verification**: resolve the right webhook secret (via the
   resolver above) and cryptographically verify the payload actually came
   from the gateway and wasn't tampered with in transit.
4. **Deduplication**: if a webhook with the same provider event ID (or the
   same raw payload hash) for this restaurant has already been seen, the
   existing `WebhookLog` is returned and nothing new happens — Razorpay
   redelivering the same event, or an operator manually clicking "resend"
   in their dashboard, is always safe. For Razorpay, the event ID is
   sourced from the `X-Razorpay-Event-Id` HTTP header (not from the JSON
   payload body), matching Razorpay's actual delivery behavior.
5. Store the raw payload as a `WebhookLog` row, **before** any business
   logic runs.

If the signature is invalid, this phase raises and the endpoint returns
**HTTP 400** — it does *not* unconditionally return 200. Only a payload
that's actually been durably stored gets queued for processing; a request
that fails verification gets nothing dispatched at all, which is the
correct behavior since the request is genuinely invalid, not just
something to handle later.

### Phase 2 — `process_log()`, runs in a Celery worker

The web process's job ends the moment the webhook is stored — it enqueues
`process_payment_webhook_task` onto the dedicated `payments` queue and
returns. A worker then picks it up and calls
`PaymentMutationService.apply_provider_event()`, the same state-machine
gate described in
[Order & Payment Lifecycle](./04-order-and-payment-lifecycle.md).

This split exists so that **Razorpay's HTTP request never waits on
Dineflow's database transaction logic, stock checks, or KDS broadcast** —
it gets an answer back in milliseconds, which matters because gateways
have their own timeout and retry behavior that you don't want to fight.

## What happens when processing fails

`process_payment_webhook_task` is decorated with `max_retries=3,
default_retry_delay=60` — if processing raises, Celery retries it up to 3
more times, 60 seconds apart. If all retries are exhausted, the
`WebhookLog.status` is set to `DEAD_LETTERED` and the raw payload stays
exactly as received, ready for manual replay — see
[Background Jobs](./08-background-jobs.md) and the
[Incident Playbook](../operations/03-incident-playbook.md).

## Reconciliation: the safety net for missing webhooks

Webhooks can simply never arrive — a network blip on Razorpay's side, a
firewall hiccup, anything. Two scheduled jobs exist specifically to catch
this:

- `process_unprocessed_webhooks_task` re-scans for any `WebhookLog` that
  was stored but never successfully processed.
- `reconcile_recent_payments_task` proactively asks Razorpay directly
  "what's the real status of this transaction?" for any `PaymentTransaction`
  that's been stuck in a non-terminal state for too long, via
  `PaymentReconciliationService`, and writes what it found to
  `PaymentReconciliationLog`.

Between webhooks, the synchronous verify-on-return path, and this
reconciliation safety net, there are three independent ways a payment's
true status eventually reaches Dineflow — by design, so that no single
point of failure can permanently strand an order.

## Customer-facing endpoints don't use session auth

`PaymentStatusView` and `PaymentRetryView` are hit by a customer's own
browser, but a customer doesn't have a logged-in session (only staff/owner
accounts do). Instead, these endpoints accept a signed, time-limited
access token (`get_payment_access_token` / `verify_payment_access_token`)
scoped to that specific payment — a customer can poll or retry *their own*
payment, and nothing else.

## API surface

See [API Reference](./09-api-reference.md) for the exact routes and
request/response shapes.

## Next

[Real-Time Kitchen Display](./07-realtime-kitchen-display.md) covers what
happens the moment `PaymentMutationService` commits.
