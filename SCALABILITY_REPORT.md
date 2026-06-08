# Scalability Report

Last updated: 2026-05-08

Audit status: CONDITIONAL for horizontal scale

## Current Scaling Model

The application is a Django modular monolith. It is containerized using Docker and is capable of horizontal scaling:

- WebSockets use Redis-backed channel layer.
- Cache uses Redis by default in production.
- Sessions are database-backed.
- Scheduled tasks run via a dedicated cron container.
- Payment and storage calls remain synchronous.
- KDS clients poll frequently, but payloads are cached via Redis.

## Horizontal Scaling Readiness

| Area | Status | Reason |
|---|---|---|
| HTTP statelessness | Warning | Mostly stateless except DB sessions. |
| WebSocket fanout | Pass | `channels_redis` distributes messages across Daphne workers. |
| Cache coherence | Pass | Shared Redis cache in production. |
| Database pooling | Warning | `conn_max_age=600` helps, but worker counts and Supabase pooler limits need tuning. |
| Background jobs | Pass | Docker `cron` container runs scheduled tasks. |
| Static assets | Warning | WhiteNoise serves static assets via Nginx. CDN/build pipeline missing. |
| Media | Warning | Supabase public storage works, but service role key handling is unsafe. |

## Tenant Scaling

Tenant isolation is logical and implemented mainly in views/services. This is acceptable for early SaaS but risky at scale because one missed filter becomes a data breach. Add database RLS or tenant-aware manager patterns for all tenant-owned models.

## Order Flow Scaling

### Order Number Counter

`RestaurantOrderCounter` serializes order number generation per restaurant. This is correct for sequential numbers but creates a hot row during rush traffic.

Scale mitigation:

- Track lock wait metrics.
- Keep checkout transactions small.
- Consider per-restaurant/day counter rows.
- Consider non-sequential display IDs if throughput requirements increase.

### Stock Reservation

Stock locking is mostly sound for finite inventory. Risk remains around abandoned UPI reservations because no durable scheduler was found.

Scale mitigation:

- Add periodic cleanup job for expired reservations.
- Add index on reservation expiry and confirmation state.
- Alert on stale reservation count.

## KDS Scaling

KDS is the largest scaling risk. Each active screen polls every few seconds and can request nested order payloads. In-memory cache means this work repeats per worker. In-memory channel layer means update signals are unreliable across workers.

Required scale architecture:

- ~~Redis channel layer.~~ **Resolved**: `channels_redis` configured.
- ~~Redis cache.~~ **Resolved**: Redis configured with 5-minute TTL.
- KDS version endpoint or `If-None-Match`.
- Payload split by tab or differential updates.
- Backpressure if clients reconnect/poll too aggressively.
- Metrics: active sockets, poll rate, cache hit rate, payload size, DB query count.

## External Integration Scaling

### Razorpay

Payment creation and verification are synchronous. No retry budget, timeout, or circuit breaker is visible.

Required:

- Explicit timeouts.
- Idempotent retry policy.
- Degraded mode when Razorpay is unhealthy.
- Queue or reconciliation job for webhook/verify mismatches.

### Supabase Storage

Image uploads perform CPU work via Pillow and then upload to Supabase in request path.

Required:

- Keep current 5 MB limit.
- Add per-owner upload rate limits.
- Move large/slow transformations to background workers if upload volume grows.

## Multi-Region Readiness

Not ready.

Reasons:

- Database is single-region.
- Sessions are DB-backed.
- Order counter and stock locking require strong consistency.
- WebSocket channel layer must be region-aware.

Recommendation: Stay single-region until operational maturity improves. Use backups and warm standby before active-active design.

## Scale Failure Points Under Heavy Traffic

1. KDS DB read amplification.
2. ~~Redis absence causing stale or inconsistent real-time state.~~ **Resolved**: Redis added.
3. Supabase/Postgres connection exhaustion.
4. Hot row contention on order counters and popular stock rows.
5. Payment gateway latency consuming worker threads/processes.
6. Large request bodies hitting Django before validation. (Mitigated by Nginx `client_max_body_size 10M`)
7. ~~No rate limiting allowing low-cost abuse.~~ **Resolved**: Nginx and app-level rate limiting applied.

## Required Pre-Launch Capacity Gates

- Run load tests with multiple WSGI/ASGI workers.
- Verify KDS updates propagate across workers.
- Verify no negative stock under concurrent checkout.
- Verify checkout p95 under expected peak load.
- Define max restaurant count, KDS screens, and checkout RPS for launch.
- Add autoscaling policy only after shared cache/channel layer is working.
