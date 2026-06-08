# Architectural Decision Records (ADR)

This document captures the critical engineering decisions made during the design and development of Order-Flow. By recording the context and consequences of these choices, we prevent future engineers from repeatedly debating settled architecture.

---

## ADR 001: Use a Modular Monolith over Microservices

**Context**: As the Order-Flow platform expands, there is a natural temptation to split services (e.g., Auth, Ordering, KDS) into independently deployable microservices.

**Decision**: We will maintain a Modular Monolith architecture within Django.

**Consequences**:
* **Positive**: Operational simplicity. We avoid the overhead of managing distributed transactions, network latency between services, and complex CI/CD orchestration. Data integrity is guaranteed via native PostgreSQL foreign keys.
* **Negative**: The codebase can become tightly coupled if developers aren't disciplined. We must enforce strict boundaries between Django apps (e.g., `kitchen` cannot write to `ordering` models directly).
* **Future Path**: If a specific module (like KDS polling) requires dramatically different scaling profiles than the rest of the app, we can run identical Docker containers but route specific URL patterns to different clusters (e.g., an ASGI cluster dedicated purely to `/ws/kds/`).

---

## ADR 002: WebSocket-Triggered Polling for KDS

**Context**: The Kitchen Display System (KDS) requires real-time updates. Standard HTTP polling (every 3 seconds) hammers the database. Pure WebSockets (sending entire JSON payloads over the socket) introduces massive complexity regarding state reconstruction, missed messages, and dropped connections.

**Decision**: We use "WebSocket-Triggered Polling". WebSockets are used *only* as a lightweight signaling mechanism (`{"action": "refresh"}`). The client receives the ping, waits `0-500ms` (jitter), and executes an HTTP `fetch()` to get the full state.

**Consequences**:
* **Positive**: The Django Channels layer handles minimal data, making it incredibly cheap to run and infinitely scalable via Redis. The frontend state is "self-healing" because every fetch returns the absolute source of truth.
* **Negative**: Introduces a fractional delay (the ping + the HTTP roundtrip). This is an acceptable tradeoff for KDS operations.

---

## ADR 003: Item Pricing Snapshots

**Context**: An `Order` contains multiple `OrderItem` rows linked to a `MenuItem`. Over time, a restaurant will update the price of a `MenuItem`.

**Decision**: We strictly snapshot `menu_item_name` and `unit_price` directly onto the `OrderItem` row at the exact moment of checkout. We NEVER calculate historical order totals by traversing the Foreign Key back to the `MenuItem`.

**Consequences**:
* **Positive**: Absolute financial integrity. If a restaurant raises the price of a Burger from $10 to $12 tomorrow, all historical orders from today will correctly reflect the $10 price without requiring complex historical pricing tables.
* **Negative**: Data duplication. The database size grows slightly faster, but storage is cheap, whereas financial corruption is unacceptable.

---

## ADR 004: Alpine.js + Django Templates over React/Vue

**Context**: Modern SaaS platforms default to React/Vue SPAs. However, SPAs require separate API backends, complex build pipelines (Vite/Webpack), and client-side routing.

**Decision**: Order-Flow uses classic Django Server-Side Rendering (SSR) for all static/admin pages, and uses Alpine.js + JSON APIs specifically for the KDS reactive dashboard.

**Consequences**:
* **Positive**: Developer velocity is significantly higher. There is no context-switching between a Node.js frontend and a Python backend. FCP (First Contentful Paint) is much faster for the Owner dashboard.
* **Negative**: The KDS UI logic (Alpine.js) is embedded directly in HTML attributes, which can become messy if the component grows too large. Developers must be vigilant about extracting complex logic into `<script>` functions.

---

## ADR 005: Docker Compose with Daphne as Unified ASGI Server

**Date**: 2026-05-08

**Context**: Order-Flow needs both HTTP and WebSocket support. The traditional approach uses separate Gunicorn (WSGI) and Daphne (ASGI) workers behind a reverse proxy. This adds operational complexity and requires careful URL routing between two process groups.

**Decision**: Use Daphne as the single ASGI entry point for both HTTP and WebSocket traffic, running behind an Nginx reverse proxy in Docker Compose.

**Consequences**:
* **Positive**: Simplified deployment — one Django process type handles all traffic. Nginx handles static files, rate limiting, and SSL termination. Docker Compose orchestrates web, redis, nginx, and cron as a complete stack.
* **Negative**: Daphne's HTTP performance is slightly lower than Gunicorn for pure HTTP workloads. This is acceptable for Order-Flow's scale. Gunicorn is available in requirements.txt as a fallback.
* **Future Path**: If HTTP throughput becomes a bottleneck, split into Gunicorn (HTTP) + Daphne (WebSocket) behind Nginx path-based routing. The `nginx/nginx.conf` already separates `/ws/` routes.

---

## ADR 006: Structured Logging with Per-Module Loggers

**Date**: 2026-05-08

**Context**: Order-Flow had no logging configuration. All log output was unstructured Django defaults, making production debugging and log aggregation impossible.

**Decision**: Configure a comprehensive `LOGGING` dict in `base.py` with per-module loggers (`ordering`, `kitchen`, `core`, `owner`), verbose timestamp formatting, and production-appropriate log levels.

**Consequences**:
* **Positive**: Each module's log output can be filtered independently. Structured format enables log aggregation (ELK, Datadog, CloudWatch). Production `prod.py` can override to JSON format when a log shipper is deployed.
* **Negative**: Slightly more verbose output in development. Mitigated by setting `django` logger to WARNING level.

