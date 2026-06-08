# Order-Flow Dependency Audit & Third-Party Boundaries

Last updated: 2026-05-08

Order-Flow strictly limits its dependency footprint to minimize supply chain attack vectors and reduce maintenance overhead. This document details all third-party libraries, services, and their designated boundaries within the system.

## 1. Python Backend Dependencies (`requirements.txt`)

All Python packages must be pinned to specific versions to guarantee reproducible builds across environments.

### Core Framework & Infrastructure
* **`Django==5.2.14`**: The core web framework. Handles ASGI/WSGI routing, ORM, Auth, and template rendering. Pinned to latest security release.
* **`channels==4.3.2` & `daphne==4.2.1`**: Provides the ASGI layer and WebSocket capabilities. Used for KDS real-time events.
* **`channels_redis==4.2.1`**: Redis-backed channel layer for production. Enables WebSocket message distribution across multiple Daphne workers.
* **`psycopg2-binary==2.9.11`**: The PostgreSQL database adapter. Required for Django's database backend.
* **`dj-database-url==3.1.2`**: Helper utility to parse `DATABASE_URL` environment variables into Django settings dictionaries.
* **`whitenoise==6.12.0`**: Serves static files. In production, Nginx serves static files directly, but WhiteNoise is kept as fallback.
* **`gunicorn==23.0.0`**: Production WSGI server. Available as fallback for HTTP-only deployments (Daphne is primary).
* **`redis==6.2.0`**: Python Redis client. Used for cache backend and channel layer connections.
* **`Twisted==26.4.0`**: ASGI server dependency. Pinned for CVE-2026-42304 security fix.

### Security & Validation
* **`bleach==6.3.0`**: Used in `core/models.py` to cryptographically scrub HTML/JS payloads from text fields, mitigating Stored XSS attacks.
* **`python-decouple==3.8`**: Manages environment variables and secret extraction in `settings.py`.

### External Integrations
* **`razorpay==2.0.1`**: Official Razorpay SDK. Used in `ordering/services.py` for checkout creation and webhook signature validation.
* **`supabase==2.28.3`**: Used primarily for connecting to Supabase Storage Buckets to handle image/media uploads. Database connections bypass this SDK and connect directly via `psycopg2`.

### Utilities
* **`qrcode==8.2` & `pillow==12.2.0`**: Used to generate and render QR codes for restaurant tables.
* **`requests==2.33.1`**: Used for executing outbound HTTP calls (if any exist beyond SDKs).

---

## 2. Frontend Dependencies

Order-Flow avoids Node.js, Webpack, and NPM completely. All frontend dependencies are loaded via CDNs, drastically simplifying the build pipeline.

### Alpine.js
* **Source**: `cdn.jsdelivr.net/npm/alpinejs@3.14.9`
* **Boundary**: Used strictly inside the Kitchen Display System (`kitchen/templates/kitchen/kds.html`). It handles DOM manipulation, state management, and the `fetch()` polling interval. It does *not* exist in the Owner dashboard or public customer-facing checkout flows.

### TailwindCSS
* **Source**: `cdn.tailwindcss.com`
* **Boundary**: Used universally across all HTML templates for responsive styling. 
* **Note**: Currently uses the browser-based CDN script in both Development and Production environments for simplicity.

---

## 3. Infrastructure & Hosted Services

### Supabase
* **Database**: PostgreSQL 15+. Connections are routed through PgBouncer (connection pooler) provided natively by Supabase.
* **Storage**: Amazon S3-compatible buckets used for restaurant logos, menu item images, and QR codes.

### Redis
* **Role**: In-memory data structure store serving two purposes:
  1. **Channel Layer**: Backing layer for Django Channels (`channels_redis`). Handles pub/sub broadcasting of WebSocket messages across Daphne workers.
  2. **Cache Backend**: Production cache for KDS poll data, reducing database load. Configured in `prod.py` with 5-minute TTL.
* **Docker**: Redis 7 Alpine image with `maxmemory 256mb` and `allkeys-lru` eviction policy.

### Razorpay
* **Role**: Payment Gateway. Operates entirely out-of-scope of Order-Flow's PCI compliance boundaries. Order-Flow only stores Razorpay `order_id` and `payment_id` references; no card data ever touches Order-Flow servers.

---

## 4. Supply Chain Security Guidelines

1. **No new packages** may be added to `requirements.txt` without Security Team approval.
2. If a package is only required for local testing (e.g., `pytest`), it must be placed in a separate `requirements-dev.txt` file and never deployed to production.
3. CDNs must use SRI (Subresource Integrity) hashes in production templates to prevent malicious script injection if the CDN is compromised.
