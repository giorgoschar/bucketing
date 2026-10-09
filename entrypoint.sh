#!/bin/sh
set -e
(set -o pipefail) 2>/dev/null && set -o pipefail

# Snapshot the database before migrations touch it. Opt out with
# BACKUP_BEFORE_MIGRATE=false; skipped when $BACKUP_DIR (/backups) is not
# mounted/writable or the database is not Postgres.
BACKUP_DIR=${BACKUP_DIR:-/backups}
if [ "${BACKUP_BEFORE_MIGRATE:-true}" = "true" ] \
    && [ -d "$BACKUP_DIR" ] && [ -w "$BACKUP_DIR" ] \
    && command -v pg_dump >/dev/null 2>&1; then
    case "$DATABASE_URL" in
        postgres*)
            dump="$BACKUP_DIR/pre-migrate-$(date +%F-%H%M).sql.gz"
            echo "Backing up database to $dump..."
            # libpq rejects SQLAlchemy's "postgresql+driver://" scheme.
            pg_url=$(printf '%s' "$DATABASE_URL" | sed -E 's#^postgres(ql)?\+[^:]*://#postgresql://#')
            if ! pg_dump "$pg_url" | gzip > "$dump.partial"; then
                rm -f "$dump.partial"
                {
                    echo "ERROR: the pre-migration backup failed; refusing to migrate without a safety dump."
                    echo "  client: $(pg_dump --version 2>&1)"
                    echo "  A 'server version mismatch' means pg_dump is older than the database server:"
                    echo "  install a pg_dump whose major version is >= the server's."
                    echo "  Set BACKUP_BEFORE_MIGRATE=false to skip the dump (not recommended) or fix the client version."
                } >&2
                exit 1
            fi
            mv "$dump.partial" "$dump"
            ;;
    esac
fi

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
# Behind Coolify's Traefik, trust X-Forwarded-* so request.url and client IPs
# reflect the real client. Only when explicitly enabled.
if [ "${TRUST_PROXY_HEADERS:-false}" = "true" ]; then
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}" \
        --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}"
