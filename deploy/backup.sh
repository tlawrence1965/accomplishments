#!/bin/bash
# Nightly backup: copy the SQLite database and uploads to a backup directory.
# Add to cron with: crontab -e
#   0 3 * * * /home/accomplishments/app/deploy/backup.sh >> /home/accomplishments/backup.log 2>&1

set -euo pipefail

APP_DIR="/home/accomplishments/app"
BACKUP_DIR="/home/accomplishments/backups"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"

# Use sqlite3's .backup command — safe even if the app is writing.
sqlite3 "$APP_DIR/accomplishments.db" ".backup '$BACKUP_DIR/db-$TIMESTAMP.db'"

# Tar up the uploads folder
tar -czf "$BACKUP_DIR/uploads-$TIMESTAMP.tar.gz" -C "$APP_DIR" uploads

# Prune anything older than KEEP_DAYS days
find "$BACKUP_DIR" -type f -mtime +$KEEP_DAYS -delete

echo "[$(date)] Backup complete: db-$TIMESTAMP.db, uploads-$TIMESTAMP.tar.gz"
