# ============================================================================
# Order-Flow - Multi-stage Production Dockerfile
# ============================================================================
# Build:  docker build -t order-flow:latest .
# Run:    docker compose up -d
# ============================================================================

# ── Stage 1: Builder ────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install system dependencies required for psycopg2 and Pillow
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libjpeg62-turbo-dev \
        libwebp-dev \
        zlib1g-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual env for clean copy
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Collect static files (uses a dummy SECRET_KEY — real key is injected at runtime)
RUN SECRET_KEY=build-only-dummy-key \
    DATABASE_URL=sqlite:///tmp/build.db \
    DJANGO_SETTINGS_MODULE=dineflow.settings.dev \
    python manage.py collectstatic --noinput

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Labels
LABEL maintainer="Order-Flow Team" \
      org.opencontainers.image.title="Order-Flow" \
      org.opencontainers.image.description="Restaurant ordering & kitchen display platform"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=dineflow.settings.prod

# Install only runtime system dependencies (no compiler)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        postgresql-client \
        libjpeg62-turbo \
        libwebp7 \
        fonts-dejavu-core \
        curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 dineflow && \
    useradd --uid 1000 --gid dineflow --shell /bin/bash --create-home dineflow

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source and collected static files
WORKDIR /app
COPY --from=builder /build/ /app/
COPY --from=builder /build/staticfiles/ /app/staticfiles/

# Copy entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create media directory
RUN mkdir -p /app/media && chown -R dineflow:dineflow /app

# Switch to non-root user
USER dineflow

# Expose dynamic port for Railway
EXPOSE ${PORT:-8000}

# Health check (we will override this per-container in docker-compose)
HEALTHCHECK NONE

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "-c", "daphne --bind 0.0.0.0 --port ${PORT:-8000} --access-log - --proxy-headers dineflow.asgi:application"]
