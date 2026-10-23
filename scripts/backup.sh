#!/usr/bin/env sh
# Nightly Postgres backup. Cron: 30 3 * * * cd /opt/sift && ./scripts/backup.sh >> backups/backup.log 2>&1
set -eu
cd "$(dirname "$0")/.."
. ./.env
mkdir -p backups
file="backups/sift-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-sift}" -d "${POSTGRES_DB:-sift}" --no-owner | gzip > "$file"
echo "wrote $file"
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  rclone copy "$file" "$BACKUP_RCLONE_REMOTE" && echo "copied to $BACKUP_RCLONE_REMOTE"
fi
find backups -name 'sift-*.sql.gz' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
