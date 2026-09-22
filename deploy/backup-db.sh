#!/usr/bin/env bash
# Dump the production database to backups/round1-<timestamp>.sql.gz and keep
# the newest 14. Installed on a daily cron by setup-gcp-vm.sh; run it by hand
# right before the event starts and after results are published.
#
# Restore (stops the app while restoring):
#   docker compose -f docker-compose.prod.yml stop api worker
#   gunzip -c backups/round1-<timestamp>.sql.gz | \
#     docker compose -f docker-compose.prod.yml exec -T postgres psql -U round1 -d round1
#   docker compose -f docker-compose.prod.yml start api worker
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p backups
STAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT="backups/round1-${STAMP}.sql.gz"
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U round1 -d round1 --clean --if-exists | gzip -9 > "$OUT"
echo "$(date -u +%FT%TZ) backup written: $OUT ($(du -h "$OUT" | cut -f1))"
# prune: keep the 14 newest
ls -1t backups/round1-*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
