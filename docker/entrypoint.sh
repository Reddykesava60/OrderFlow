#!/bin/bash
set -e

echo "══════════════════════════════════════════════════════════════"
echo " DineFlow — Container Startup"
echo "══════════════════════════════════════════════════════════════"

# ── Wait for database ────────────────────────────────────────────────────────
if [ -n "$DATABASE_URL" ]; then
    echo "[entrypoint] Waiting for database..."
    python -c "
import time, sys
from urllib.parse import urlparse
import socket

url = urlparse('$DATABASE_URL')
host = url.hostname
port = url.port or 5432
max_retries = 30

for i in range(max_retries):
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        print(f'[entrypoint] Database is reachable at {host}:{port}')
        sys.exit(0)
    except (socket.error, socket.timeout):
        print(f'[entrypoint] Waiting for database ({i+1}/{max_retries})...')
        time.sleep(2)

print('[entrypoint] ERROR: Database not reachable after retries')
sys.exit(1)
"
fi

# ── Role-specific startup logs ───────────────────────────────────────────────
if [[ "$*" == *"daphne"* ]]; then
    echo "[entrypoint] Role: WEB/WEBSOCKET (daphne)"
elif [[ "$*" == *"celery"* ]]; then
    echo "[entrypoint] Role: QUEUE/SCHEDULER (celery)"
fi

echo "══════════════════════════════════════════════════════════════"
echo "[entrypoint] Executing: $@"
echo "══════════════════════════════════════════════════════════════"

exec "$@"
