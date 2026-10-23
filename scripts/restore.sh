#!/usr/bin/env sh
# Restore a backup into the running Postgres container. Usage: ./scripts/restore.sh backups/sift-XXXX.sql.gz
# Stops api and worker, recreates the database, loads the dump, starts them again.
set -eu
cd "$(dirname "$0")/.."
. ./.env
[ -f "${1:-}" ] || { echo "usage: $0 <backup.sql.gz>"; exit 1; }
docker compose stop api worker
docker compose exec -T postgres psql -U "${POSTGRES_USER:-sift}" -d postgres -c "DROP DATABASE IF EXISTS ${POSTGRES_DB:-sift};" -c "CREATE DATABASE ${POSTGRES_DB:-sift};"
gunzip -c "$1" | docker compose exec -T postgres psql -U "${POSTGRES_USER:-sift}" -d "${POSTGRES_DB:-sift}" -q
docker compose start api worker
echo "restored $1"
