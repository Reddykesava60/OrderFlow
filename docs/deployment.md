# Deployment Guide

Order-Flow is designed for containerized deployment on PaaS providers like Railway, Render, or a traditional Docker Swarm / VPS setup.

## Infrastructure Topology

A production deployment requires:
1. **Web Process**: Daphne ASGI server (handles HTTP and WebSockets).
2. **Worker Process**: Celery (handles background tasks).
3. **Beat Process**: Celery Beat (scheduler).
4. **PostgreSQL**: Primary relational database.
5. **Redis**: Cache, message broker (Celery), and Channel Layer (WebSockets).
6. **Object Storage**: Supabase Storage or AWS S3 (for menu images and QR codes).

## Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key (must be strong) | `django-insecure-...` |
| `PAYMENT_ENCRYPTION_KEY` | Fernet key for encrypting DB secrets | `...` |
| `DATABASE_URL` | PostgreSQL connection string | `postgres://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection string | `redis://:pass@host:6379/0` |
| `ALLOWED_HOSTS` | Comma-separated list of domains | `orderflow.app,api.orderflow.app` |
| `CSRF_TRUSTED_ORIGINS`| Comma-separated list of HTTPS origins | `https://orderflow.app` |
| `RAZORPAY_KEY_ID` | Platform Razorpay Key | `rzp_live_...` |
| `RAZORPAY_KEY_SECRET` | Platform Razorpay Secret | `...` |
| `RAZORPAY_WEBHOOK_SECRET`| Webhook secret configured in RZP dashboard | `...` |

## Railway Deployment

1. Provision a PostgreSQL and Redis database in your Railway project.
2. Link the Order-Flow GitHub repository.
3. Railway will auto-detect the `Dockerfile`.
4. Set the environment variables in the Railway Dashboard.
5. Create three services from the same repo with custom Start Commands:
   - **Web**: `daphne --bind 0.0.0.0 --port $PORT dineflow.asgi:application`
   - **Worker**: `celery -A dineflow worker -Q celery,payments -l info`
   - **Beat**: `celery -A dineflow beat -l info`
6. Map the Railway generated domain to the Web service.

## Traditional Docker Compose

A production-ready `docker-compose.yml` is provided in the repository root.

1. Create a `.env` file based on the required variables above.
2. Run `docker compose up --build -d`
3. The included Nginx container handles reverse proxying and static file serving.
4. If using the included Certbot container, ensure port 80 and 443 are open for ACME challenge and SSL termination.

## Static & Media Files

- **Static Files**: Collected via `python manage.py collectstatic` during the Docker build process and served by Nginx or WhiteNoise.
- **Media Files**: User uploads (logos, menu images) **must** use external object storage (Supabase/S3) in ephemeral PaaS environments (like Railway). Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_STORAGE_BUCKET_NAME` to enable `django-storages`.
