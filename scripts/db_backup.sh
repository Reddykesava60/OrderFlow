#!/bin/bash
# scripts/db_backup.sh
# 
# Usage: ./db_backup.sh
# 
# Requires standard PostgreSQL client tools (pg_dump) and AWS CLI if uploading to S3.
# Ensures the application has a backup strategy in place for disaster recovery.

set -e

BACKUP_DIR="/var/backups/orderflow"
DATE=$(date +%Y%m%d_%H%M%S)
FILE_NAME="orderflow_db_${DATE}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "Starting database backup: ${FILE_NAME}"

# Dump and compress
# DATABASE_URL should be available in the environment
pg_dump "$DATABASE_URL" | gzip > "${BACKUP_DIR}/${FILE_NAME}"

echo "Backup created at ${BACKUP_DIR}/${FILE_NAME}"

# Optional: Upload to S3 (Uncomment and configure if using Supabase S3)
# echo "Uploading to S3..."
# aws s3 cp "${BACKUP_DIR}/${FILE_NAME}" s3://${AWS_STORAGE_BUCKET_NAME}/backups/ --endpoint-url ${AWS_S3_ENDPOINT_URL}

# Keep only last 7 days of backups locally
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +7 -delete

echo "Backup complete."
