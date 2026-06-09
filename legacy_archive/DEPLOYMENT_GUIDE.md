# Order-Flow Deployment Guide

Last updated: 2026-05-14

This document covers the full deployment lifecycle for Order-Flow, from local development through staging to production using Docker containers.

---

## 1. Deployment Architecture

```mermaid
graph TD
    subgraph Developer Machine
        Dev["Local Dev Server<br/>docker compose up"]
    end
    
    subgraph CI/CD Pipeline
        GH[GitHub Push] --> CI["CI Runner<br/>Lint + Test + Build"]
        CI --> StgDeploy{Staging?}
        CI --> ProdDeploy{Production?}
    end
    
    subgraph Staging Environment
        StgDeploy --> StgApp["Staging Stack<br/>docker compose up"]
        StgApp --> StgDB["(Staging PostgreSQL)"]
    end
    
    subgraph Production Environment
        ProdDeploy --> Nginx["Nginx Reverse Proxy<br/>Rate Limiting + Static Files"]
        Nginx --> ProdASGI["Daphne ASGI<br/>HTTP + WebSocket"]
        ProdASGI --> ProdDB["(Supabase PostgreSQL<br/>via PgBouncer)"]
        ProdASGI --> ProdRedis["(Redis<br/>Channel Layer + Cache)"]
        ProdASGI --> RZP[Razorpay API]
        ProdASGI --> SupaStorage["Supabase Storage<br/>S3-Compatible"]
        Cron["Cron Container<br/>Scheduled Tasks"] --> ProdDB
        Worker["Payment Worker<br/>Webhook + Reconciliation"] --> ProdRedis
        Worker --> ProdDB
    end

    Dev --> GH
```

---

## 2. Environment Configuration

Order-Flow uses a split-settings architecture located in `dineflow/settings/`:

| File | Purpose | Key Differences |
|------|---------|----------------|
| `base.py` | Shared configuration for all environments | Database URL, Installed Apps, Middleware, Logging, `STORAGES` dict |
| `dev.py` | Local development | `DEBUG=True`, relaxed `ALLOWED_HOSTS`, `InMemoryChannelLayer`, local memory cache |
| `prod.py` | Production | `DEBUG=False`, HSTS, secure cookies, SSL redirect, Redis cache + channels, `SECURE_PROXY_SSL_HEADER` |

### 2.1 Required Environment Variables

```text
# Core
DJANGO_SETTINGS_MODULE=dineflow.settings.prod
SECRET_KEY=<generate-with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
PAYMENT_ENCRYPTION_KEY=<generate-a-separate-strong-secret>
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Database
DATABASE_URL=postgres://user:pass@host:port/dbname
DB_SSLMODE=require

# Redis
REDIS_URL=redis://redis:6379/0

# Payment (optional — per-restaurant keys stored in DB)
RAZORPAY_KEY_ID=rzp_live_XXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXX
RAZORPAY_WEBHOOK_SECRET=XXXXXXXXXX

# Storage (optional)
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIs...
```

`PAYMENT_ENCRYPTION_KEY` protects stored payment credentials. If it is not set,
the app falls back to `SECRET_KEY` so existing encrypted credentials continue to
work. Set it before rotating `SECRET_KEY`; old values encrypted with
`SECRET_KEY` remain readable during migration, while new writes use
`PAYMENT_ENCRYPTION_KEY`.

See `.env.example` for the full documented template with comments.

### 2.2 Settings Selection

The active settings module is determined by `DJANGO_SETTINGS_MODULE`:
```bash
# Development (default for wsgi.py and asgi.py)
export DJANGO_SETTINGS_MODULE=dineflow.settings.dev

# Production (set in docker-compose.yml and Dockerfile)
export DJANGO_SETTINGS_MODULE=dineflow.settings.prod
```

---

## 3. Docker Deployment (Recommended)

### 3.1 Development Mode

```bash
# Clone and configure
git clone <repository_url>
cd Order-Flow
cp .env.example .env    # Edit with your credentials

# Build and start (docker-compose.override.yml auto-loads for dev)
docker compose up --build -d

# Create admin user
docker compose exec web python manage.py createsuperuser

# Access at http://localhost:8000
```

Development mode (`docker-compose.override.yml`):
- Source code mounted as volume for hot reload
- Daphne accessible directly on port 8000
- Nginx disabled
- `DEBUG=True` set

### 3.2 Production Deployment

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Docker as Docker Build
    participant Nginx as Nginx Proxy
    participant App as Daphne ASGI
    participant DB as PostgreSQL
    participant Redis as Redis

    Dev->>Docker: docker compose build
    Docker->>Docker: Stage 1: Install deps, collectstatic
    Docker->>Docker: Stage 2: Copy to minimal runtime
    Dev->>Docker: docker compose up -d
    Docker->>App: Start entrypoint.sh
    App->>DB: Wait for connectivity
    App->>DB: python manage.py migrate --noinput
    App->>App: python manage.py collectstatic --noinput
    App->>App: Start Daphne on :8000
    Nginx->>App: Proxy HTTP + WebSocket traffic
    App->>Redis: Channel Layer + Cache
    App-->>Dev: Deployment complete ✅
```

```bash
# Build production image
docker compose build

# Start with Nginx (production profile)
docker compose --profile production up -d

# Verify health
curl http://localhost/healthz/live/
curl http://localhost/healthz/ready/

# View logs
docker compose logs -f web
```

### 3.3 Service Topology

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| `web` | `dineflow-web` | 8000 (internal) | Django/Daphne ASGI (HTTP + WebSocket) |
| `redis` | `dineflow-redis` | 6379 (internal) | Cache + Channel Layers |
| `nginx` | `dineflow-nginx` | 80 (external) | Reverse proxy, static files, rate limiting |
| `worker` | `dineflow-worker` | — | Celery worker — webhook processing and payment reconciliation |
| `beat` | `dineflow-beat` | — | Celery Beat — scheduled reservation cleanup and reconciliation |

### 3.4 Container Entrypoint

The `docker/entrypoint.sh` script runs on container startup:
1. Waits for database TCP connectivity (up to 30 retries).
2. Logs the container role (web/worker/beat).
3. Executes the provided command (e.g., Daphne, Celery).

*Note: Migrations are handled by `railway.json`'s `startCommand` on Railway, or must be run manually before starting services on VPS.*

### 3.5 Background Workers

Run at least one dedicated worker process for payment webhook ingestion, verification, mutation, and reconciliation. Queue-based processing keeps provider callbacks fast and prevents retry storms from blocking HTTP workers.

Recommended roles:
- `worker`: payment webhook processing and reconciliation jobs.
- `cron`: periodic expiry and catch-up tasks.
- `web`: HTTP and WebSocket traffic only.

---

## 4. Traditional (Non-Docker) Deployment

If Docker is not available:

1. **Pre-flight checks**
   ```bash
   python manage.py check --deploy
   python manage.py showmigrations | grep "\[ \]"
   ```

2. **Collect static assets**
   ```bash
   python manage.py collectstatic --noinput
   ```

3. **Apply database migrations**
   ```bash
   python manage.py migrate --noinput
   ```

4. **Start ASGI server (HTTP + WebSockets)**
   ```bash
   daphne -b 0.0.0.0 -p 8000 --proxy-headers dineflow.asgi:application
   ```

5. **Configure reverse proxy**
   Use the provided `nginx/nginx.conf` as a template. Route all traffic to Daphne on port 8000.

6. **Start background workers**
    Launch the payment worker and cron container before directing live traffic to the platform.

---

## 5. Production Security Hardening

The `prod.py` settings file enables these production-specific security features:

```python
DEBUG = False
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000        # 1 year HSTS
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False            # Set True only after HSTS preload list verification
SESSION_COOKIE_SECURE = True           # Cookies only over HTTPS
CSRF_COOKIE_SECURE = True              # CSRF token only over HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Trust Nginx forwarding
```

Nginx adds security headers:
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: same-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`

Nginx rate limiting:
- Login: 5 requests/minute
- Checkout: 30 requests/minute
- API: 60 requests/minute

---

## 6. Rollback Strategy

```mermaid
flowchart TD
    A[Deployment Fails] --> B{Migration ran?}
    B -- No --> C[Revert to previous Docker image tag]
    B -- Yes --> D{Migration reversible?}
    D -- Yes --> E["docker compose exec web python manage.py migrate app_name XXXX_previous"]
    D -- No --> F[Manual DB fix + Revert to previous image]
    E --> C
    F --> C
    C --> G["Verify: curl /healthz/ready/ ✅"]
```

### Rollback Procedure
1. **If no migration was applied**: `docker compose down && docker compose up -d` with previous image.
2. **If a migration was applied and is reversible**: `docker compose exec web python manage.py migrate <app_name> <previous_migration_number>` then revert image.
3. **If a migration is irreversible**: Manual DBA intervention required. Always test on staging first.

---

## 7. Health Checks & Monitoring

After deployment, verify system health:

| Check | Command | Expected |
|-------|---------|----------|
| Liveness | `curl http://localhost/healthz/live/` | 200 OK |
| Readiness | `curl http://localhost/healthz/ready/` | 200 OK |
| WebSocket | Connect to `ws://localhost/ws/kds/` | Connection accepted |
| Redis | `docker compose exec redis redis-cli ping` | PONG |
| Database | `docker compose exec web python manage.py dbshell` → `SELECT 1;` | 1 |
| Static Files | `curl http://localhost/static/landing/hero.webp` | 200 OK |
| Logs | `docker compose logs -f web` | Structured output |
