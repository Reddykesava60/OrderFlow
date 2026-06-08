# Docker Deployment Guide

## Prerequisites

- **Docker Engine** 24+ and **Docker Compose** v2
- A PostgreSQL database (Supabase or self-hosted)
- A Redis instance (included in Docker Compose, or use managed Redis)
- Domain name with DNS configured (for production)

## Quick Start (Development)

```bash
# 1. Clone the repository
git clone <repository-url>
cd Order-Flow

# 2. Create environment file
cp .env.example .env
# Edit .env with your database and secret values

# 3. Build and start (development mode)
docker compose up --build -d

# 4. Create a superuser
docker compose exec web python manage.py createsuperuser

# 5. Access the application
open http://localhost:8000
```

In development mode, `docker-compose.override.yml` is automatically loaded:
- Source code is mounted as a volume (hot reload)
- Daphne is accessible directly on port 8000
- Nginx is disabled
- `DEBUG=True` is set

## Production Deployment

### 1. Environment Configuration

Create a production `.env` file:

```bash
# Core Django
DJANGO_SETTINGS_MODULE=dineflow.settings.prod
SECRET_KEY=<generate-with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Database
DATABASE_URL=postgresql://user:password@host:5432/dbname
DB_SSLMODE=require

# Redis
REDIS_URL=redis://redis:6379/0

# Razorpay (optional — per-restaurant config is stored in DB)
RAZORPAY_KEY_ID=rzp_live_xxxxx
RAZORPAY_KEY_SECRET=xxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxx

# Supabase Storage (optional)
SUPABASE_URL=https://project.supabase.co
SUPABASE_SERVICE_KEY=xxxxx
```

### 2. Build and Deploy

```bash
# Build production image
docker compose build

# Start all services (production uses Nginx on port 80)
docker compose --profile production up -d

# Check health
curl http://localhost/healthz/live/
curl http://localhost/healthz/ready/

# View logs
docker compose logs -f web
```

### 3. SSL/TLS Setup

For production SSL, modify `nginx/nginx.conf`:

```nginx
server {
    listen 443 ssl http2;
    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    # ... rest of config
}

server {
    listen 80;
    return 301 https://$host$request_uri;
}
```

Mount certificates in `docker-compose.yml`:
```yaml
nginx:
  volumes:
    - /path/to/ssl/certs:/etc/nginx/ssl:ro
```

Alternatively, use a reverse proxy like Caddy, Traefik, or a cloud load balancer for automatic SSL.

## Architecture

```
                    ┌──────────────┐
                    │   Internet   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │    Nginx     │ :80/:443
                    │  (reverse    │
                    │   proxy)     │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
      ┌───────▼──┐  ┌──────▼──┐  ┌─────▼───┐
      │  Static  │  │  HTTP   │  │   WS    │
      │  Files   │  │ Proxy   │  │  Proxy  │
      │ /static/ │  │ /*      │  │  /ws/   │
      └──────────┘  └────┬────┘  └────┬────┘
                         │            │
                    ┌────▼────────────▼────┐
                    │      Daphne         │ :8000
                    │   (ASGI Server)     │
                    │  HTTP + WebSocket   │
                    └─────────┬───────────┘
                              │
                 ┌────────────┼────────────┐
                 │                         │
          ┌──────▼──────┐          ┌───────▼──────┐
          │  PostgreSQL │          │    Redis     │
          │  (Supabase) │          │  Cache +     │
          │             │          │  Channels    │
          └─────────────┘          └──────────────┘
```

## Services

| Service | Purpose | Port |
|---------|---------|------|
| `web` | Django/Daphne ASGI server | 8000 (internal) |
| `redis` | Cache + Channel Layers | 6379 (internal) |
| `nginx` | Reverse proxy, static files | 80 (external) |
| `cron` | Scheduled tasks (reservation cleanup) | — |

## Common Operations

### Database Migrations
```bash
docker compose exec web python manage.py migrate
```

### Create Superuser
```bash
docker compose exec web python manage.py createsuperuser
```

### Collect Static Files
```bash
docker compose exec web python manage.py collectstatic --noinput
```

### Django Shell
```bash
docker compose exec web python manage.py shell
```

### View Logs
```bash
docker compose logs -f web          # Application logs
docker compose logs -f nginx        # Nginx access/error logs
docker compose logs -f cron         # Scheduled task logs
```

### Manual Reservation Cleanup
```bash
docker compose exec web python manage.py release_expired_reservations
```

### Database Backup
```bash
# Using pg_dump (adjust connection details)
docker compose exec web pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
```

## Scaling

### Horizontal Scaling
The application supports horizontal scaling through:
- **Redis-backed Channel Layers**: WebSocket messages are distributed across workers
- **Redis-backed Cache**: KDS poll data is shared across instances
- **Database sessions**: Session state is in PostgreSQL, not local memory

Scale the web service:
```bash
docker compose up -d --scale web=3
```

Update `nginx/nginx.conf` upstream to use multiple backends or use Docker's built-in DNS.

### Performance Tuning
- **Daphne workers**: Adjust `--ws-protocol` and connection limits
- **Redis**: Increase `maxmemory` for high-volume KDS deployments
- **Nginx**: Tune `worker_processes` and `worker_connections`
- **Database**: Monitor connection pool usage via `CONN_MAX_AGE`

## Troubleshooting

### Container won't start
```bash
docker compose logs web              # Check for startup errors
docker compose exec web python manage.py check --deploy  # Django deploy check
```

### Database connection issues
```bash
docker compose exec web python -c "
import django; django.setup()
from django.db import connections
c = connections['default']
c.ensure_connection()
print('Database OK')
"
```

### Redis connection issues
```bash
docker compose exec redis redis-cli ping
```

### Static files not loading
```bash
docker compose exec web python manage.py collectstatic --noinput
docker compose restart nginx
```
