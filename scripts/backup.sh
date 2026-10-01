#!/bin/sh
# Daily backup: gzipped pg_dump of $DATABASE_URL plus a tarball of uploads.
# Files older than BACKUP_KEEP_DAYS (default 30) are pruned.
set -eu
# Fail the pipeline when pg_dump fails, not only when gzip does.
(set -o pipefail) 2>/dev/null && set -o pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
UPLOADS_PARENT=${UPLOADS_PARENT:-/app}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-30}

: "${DATABASE_URL:?DATABASE_URL must be set}"
mkdir -p "$BACKUP_DIR"

stamp=$(date +%F-%H%M)
db_file="$BACKUP_DIR/db-$stamp.sql.gz"
# Write to a temp name first so a failed dump never looks like a good backup.
pg_dump "$DATABASE_URL" | gzip > "$db_file.partial"
mv "$db_file.partial" "$db_file"
echo "backup: wrote $db_file"

if [ -d "$UPLOADS_PARENT/uploads" ]; then
    tar czf "$BACKUP_DIR/uploads-$(date +%F).tgz" -C "$UPLOADS_PARENT" uploads
    echo "backup: wrote uploads-$(date +%F).tgz"
fi

find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.sql.gz' -o -name 'uploads-*.tgz' -o -name 'pre-migrate-*.sql.gz' \) \
    -mtime +"$KEEP_DAYS" -delete
