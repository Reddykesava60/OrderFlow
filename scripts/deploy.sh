#!/bin/bash
# ============================================================================
# DineFlow — Automated Deployment Script
# ============================================================================
# Usage: ./deploy.sh
# ============================================================================

set -e

echo "══════════════════════════════════════════════════════════════"
echo " Starting DineFlow Deployment"
echo "══════════════════════════════════════════════════════════════"

# 1. Pull latest code
echo "[1/4] Pulling latest code from Git..."
git pull origin main

# 2. Build updated images
echo "[2/4] Building updated Docker images..."
docker compose build

# 3. Deploy sequentially to minimize downtime
echo "[3/4] Restarting services with new images..."

# Ensure core services are up
docker compose up -d db redis

# Update web layer (HTTP + ASGI)
docker compose up -d --no-deps --build web daphne

# Update background workers
docker compose up -d --no-deps --build worker beat

# Update proxy
docker compose up -d --no-deps --build nginx certbot

# 4. Clean up old images
echo "[4/4] Cleaning up unused Docker resources..."
docker image prune -f

echo "══════════════════════════════════════════════════════════════"
echo " Deployment completed successfully!"
echo "══════════════════════════════════════════════════════════════"
