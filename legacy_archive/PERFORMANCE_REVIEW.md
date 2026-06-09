# Order-Flow Performance & Scalability Review

This document audits the performance profile of the Order-Flow application, highlighting optimizations already implemented and identifying areas for future scale.

## 1. Database Query Optimization

The primary bottleneck in any Django application is the Database. Order-Flow has been aggressively optimized to minimize query latency.

### 1.1 Eliminating N+1 Queries
The Kitchen Display System (`KDSPollView`) must serialize complex, deeply nested relational data (`Order` -> `OrderItem` -> `OrderItemAddOn`). A naive ORM implementation would trigger an N+1 query explosion (hundreds of queries per request).

**Optimization**:
We utilize Django's `Prefetch` objects to fetch the entire tree in exactly 3 queries, regardless of how many active orders exist.
```python
item_prefetch = Prefetch(
    "items",
    queryset=(
        OrderItem.objects
        .select_related("menu_item", "menu_item__item_type")
        .prefetch_related(
            Prefetch("addons", queryset=OrderItemAddOn.objects.select_related("addon"))
        )
    ),
)
```

### 1.2 Targeted Indexing
Because Order-Flow isolates data by `restaurant_id`, querying active orders requires filtering by both `restaurant_id` and `status`. We utilize PostgreSQL composite indexes to ensure these queries evaluate in `O(log n)` time.

## 2. Real-Time KDS Polling Optimization

### 2.1 The "Thundering Herd" Problem
**Scenario**: A restaurant has 6 KDS tablets. A new order arrives. The server sends a WebSocket ping to the tablets. All 6 tablets instantly fire an HTTP `fetch()` to `/api/kds/poll/` at the exact same millisecond.
**Mitigation**:
1. **Client-Side Jitter**: The Alpine.js frontend applies a `Math.random() * 500` millisecond delay before executing the fetch. This spreads the 6 requests out over half a second.
2. **Version-Based Caching**: The `KDSPollView` JSON payload is cached in memory. The cache key includes the restaurant ID, a version number, and the specific user's permission flags. The first tablet's request builds the JSON and caches it. The remaining 5 tablets fetch the payload directly from memory without hitting the database.

### 2.2 Cache Invalidation
The cache is never allowed to go stale. The instant an order is mutated (e.g., payment succeeds, chef marks item as complete), the `trigger_kds_refresh(restaurant_id)` service increments the `kds_version_{restaurant_id}` key in Redis/Cache. This immediately deprecates all existing cached payloads for that restaurant, guaranteeing 100% data accuracy.

## 3. Frontend Performance

Order-Flow specifically avoids heavy JavaScript bundles (like React/Angular) to guarantee fast load times on low-end restaurant tablets.

*   **CSS**: TailwindCSS is loaded via the browser CDN (`cdn.tailwindcss.com`). This trades a small page-load overhead for zero build-step complexity.
*   **JavaScript**: Alpine.js is delivered via a global CDN. The entire KDS logic is less than 400 lines of combined HTML/JS.
*   **Result**: FCP (First Contentful Paint) and TTI (Time to Interactive) are near-instantaneous.

## 4. Areas for Future Scaling

While current optimizations easily support thousands of concurrent restaurants, hyper-growth will require the following:

1. **Database Read Replicas**: The `/api/kds/poll/` endpoint is heavily read-intensive. We should configure Django's database router to send these `SELECT` queries to a PostgreSQL read replica.
2. **CDN for Static/Media**: Currently, images are served directly from Supabase Storage. Slapping a CDN (like Cloudflare) in front of the Supabase bucket will significantly improve image loading speeds and reduce egress costs.
3. **PGBouncer Integration**: As WSGI/ASGI workers scale horizontally, the number of raw connections to PostgreSQL will increase. PgBouncer must be configured at the infrastructure level to pool connections effectively.
