# Monitoring and Observability Guide

## Metrics to Track
- Payment checkout attempts by provider, restaurant, and state.
- Webhook ingress count, signature failures, replay rejects, and processing latency.
- Payment state transitions: pending, initiated, processing, paid, failed, expired.
- Stock-reservation expirations and unpaid cash expirations.
- WebSocket connection count by restaurant and reconnect rate.
- Queue depth and job runtime for webhook processing and reconciliation.

## Suggested Alerts
- Spike in webhook signature failures.
- Spike in duplicate webhook event IDs.
- Increase in payment retries without eventual success.
- Payment reconciliation backlog older than the expected SLA.
- WebSocket send failures or sustained reconnect storms.
- Any sudden increase in blocked customers attempting post-payment checkout.

## Logs
- Log structured events with `restaurant_id`, `order_id`, `payment_id`, `provider`, and `event_id`.
- Log payment failures with a non-sensitive error code and a minimal reason.
- Log manual customer balance updates and PIN resets as audit events.
- Do not log raw webhook payloads in production unless redacted.

## Dashboards
- Checkout funnel: initiated -> confirmed -> completed.
- Provider reliability: success rate and failure rate.
- Tenant health: active orders, overdue cash orders, pending payments.
- Real-time health: WebSocket fan-out success and client refresh latency.

## Reconciliation Cadence
- Run payment reconciliation on a fixed schedule.
- Review mismatches daily until the provider settlement process is stable.
- Investigate any payment that remains in an active state past its expiry window.
