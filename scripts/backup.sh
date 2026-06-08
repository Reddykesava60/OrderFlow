#!/usr/bin/env bash
set -euo pipefail

# DineFlow database backup.
# Runs pg_dump from the web container against DATABASE_URL, so the same script
# works for Compose Postgres and managed Postgres/Supabase.

BACKUP_DIR="${BACKUP_DIR:-/var/backups/dineflow/db}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-web}"
DATE="$(date +%Y-%m-%d_%H-%M-%S)"
BACKUP_FILE="$BACKUP_DIR/db_backup_$DATE.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] Writing $BACKUP_FILE"
docker compose exec -T "$COMPOSE_SERVICE" sh -c 'pg_dump "$DATABASE_URL"' | gzip > "$BACKUP_FILE"

if gzip -t "$BACKUP_FILE"; then
  echo "[backup] Verified gzip archive."
else
  echo "[backup] Backup verification failed." >&2
  exit 1
fi

find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[backup] Complete."
