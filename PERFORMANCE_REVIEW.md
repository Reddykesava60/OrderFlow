# Performance Review

Audit status: CONDITIONAL for launch at scale
Last updated: 2026-05-08

## Backend Bottlenecks

### PERF-001: KDS Polling Can Become The Dominant Database Load

Severity: High  
Evidence: `kitchen/templates/kitchen/kds.html` states auto-updates every 5 seconds. `KDSPollView.get()` builds full kitchen, preparing, payment, all-orders, and staff-filter payloads.

Impact: A restaurant with 10 kitchen screens creates roughly 120 poll requests per minute before customer traffic. With many restaurants, this becomes constant database pressure.

Remediation:

- ~~Move cache to Redis.~~ **Resolved**: Redis cache configured in `prod.py`, Redis service in `docker-compose.yml`.
- ~~Cache per restaurant and permission profile.~~ **Resolved**: `KDSPollView` already caches by restaurant + permission profile with 5-minute TTL.
- Use WebSocket event versioning to poll only when version changes.
- Add `ETag` or `last_version` client contract.
- Add load tests for 10, 50, and 200 active KDS screens.

### PERF-002: Cache Is Process-Local By Default

Severity: High  
Status: **Resolved**  
Evidence: Redis cache configured in `dineflow/settings/prod.py`. `docker-compose.yml` includes Redis 7 service with health checks.

Impact: Multiple workers will have independent cache entries and versions. Some users will see stale data while others trigger unnecessary database rebuilds.

Remediation:

- Configure Redis cache in production.
- Treat cache version as a shared monotonic counter.
- Fail gracefully if cache is down.

### PERF-003: Real-Time WebSocket Layer Is In-Memory

Severity: High  
Status: **Resolved**  
Evidence: `dineflow/settings/prod.py` configures `channels_redis.core.RedisChannelLayer`. Dev settings use `InMemoryChannelLayer` intentionally.

Impact: ~~KDS refresh broadcasts do not cross worker or container boundaries.~~ Resolved — Redis-backed channel layer distributes messages across all Daphne workers.

Remediation:

- Add `channels_redis`.
- Configure Redis channel layer with capacity and expiry.
- Instrument WebSocket connect count and send failures.

### PERF-004: Hot Restaurant Checkout Lock Contention

Severity: Medium  
Evidence: `_next_order_number()` uses `RestaurantOrderCounter.objects.select_for_update().get_or_create()`.

Impact: This correctly guarantees order number sequence, but every checkout for a restaurant serializes on one row. During peak rush, checkout latency can climb.

Remediation:

- Measure p95/p99 lock wait time.
- Keep the transaction as small as possible.
- Consider per-day counter rows or database sequence-backed numbers if contention appears.

### PERF-005: Synchronous External Payment Calls In Request Path

Severity: Medium  
Status: **Resolved**  
Evidence: `create_razorpay_order(order)` runs Razorpay SDK calls during checkout.

Impact: Razorpay slowness directly holds a Django worker. The SDK path does not show explicit timeouts or retry budget.

Remediation:

- ~~Add explicit timeouts where supported by the SDK or wrap calls.~~
- ~~Capture latency metrics.~~
- ~~Add bounded retries only for safe idempotent operations.~~
- ~~Consider async job handoff if checkout volume grows.~~ **Resolved**: Offloaded to Celery background tasks with retry logic.

## Frontend Performance

### PERF-006: CDN Tailwind In Production

Severity: High  
Evidence: Public ordering, owner, login, and KDS templates load `https://cdn.tailwindcss.com`.

Impact: Tailwind browser compiler is not production-grade. It increases page startup cost and depends on third-party availability.

Remediation:

- **Status: Accepted Risk**
- The project currently continues to use the CDN for simplicity, acknowledging the performance tradeoff.

### PERF-007: Unpinned Alpine CDN

Severity: Medium  
Evidence: Templates load `alpinejs@3.x.x`.

Impact: Reproducibility and performance behavior can change unexpectedly.

Remediation:

- Pin exact version.
- Serve locally with cache headers.
- Add CSP/SRI.

### PERF-008: Session Storage Cart Is Fine, But Payload Needs Server Guardrails

Severity: Medium  
Evidence: Client stores cart in `sessionStorage`; server caps line count at 30 and quantity at 99.

Impact: Server still parses the whole body first. Oversized JSON can pressure memory before validation.

Remediation:

- Add request size limits at proxy and Django.
- Return 413 for oversized payloads.

## Database Performance

### Missing Or Weak Indexes

Recommended indexes:

- `ordering_stockreservation(order_id, is_confirmed, expires_at)` for stale reservation cleanup and cancellation.
- `kitchen_paymentevent(restaurant_id, created_at, event_type)` for dashboard/reconciliation aggregates.
- `core_platformfeerecord(restaurant_id, created_at, is_refunded)` for owner dashboard and fee reports.
- `ordering_order(restaurant_id, status, created_at)` to improve KDS daily status queries.
- `ordering_orderitem(order_id, prep_status)` and `ordering_orderitemaddon(order_item_id, prep_status)` for KDS filters.

### Query Shape

The KDS serialization code is reasonably careful with `select_related` and `prefetch_related`, but it builds large nested JSON payloads for every poll miss. The "all orders today" tab increases payload size and serialization CPU.

Remediation:

- Add query count tests for KDS poll.
- Add payload size metrics.
- Paginate or cap `all_orders`.
- Split KDS tabs into separate endpoints if data grows.

## Capacity Risks

Likely first bottlenecks:

1. KDS polling database load.
2. ~~Local cache/channel inconsistency under multiple workers.~~ **Resolved** — Redis cache and channels configured.
3. Checkout worker saturation during payment gateway slowness.
4. PostgreSQL connection exhaustion from combined Daphne workers.
5. Lock contention on restaurant order counters and hot stock rows.

## Load Test Plan

Minimum launch load test:

- 100 restaurants with 2 active KDS screens each.
- 20 hot restaurants with 10 screens each.
- 50 checkout requests per minute across hot restaurants.
- Razorpay latency injection at 500 ms, 2 s, and failure.
- Concurrent stock depletion for the same menu item.
- KDS poll p95 under 300 ms from cache and under 1 s on rebuild.

Pass criteria:

- No stale KDS state across two ASGI workers.
- No duplicate order numbers.
- No negative stock.
- No unbounded database connection growth.
- No 500s for malformed public checkout payloads.
