#!/bin/sh
set -e
(set -o pipefail) 2>/dev/null && set -o pipefail

# Snapshot the database before migrations touch it. Opt out with
# BACKUP_BEFORE_MIGRATE=false; skipped when /backups is not mounted/writable
# or the database is not Postgres.
if [ "${BACKUP_BEFORE_MIGRATE:-true}" = "true" ] \
    && [ -d /backups ] && [ -w /backups ] \
    && command -v pg_dump >/dev/null 2>&1; then
    case "$DATABASE_URL" in
        postgres*)
            dump="/backups/pre-migrate-$(date +%F-%H%M).sql.gz"
            echo "Backing up database to $dump..."
            pg_dump "$DATABASE_URL" | gzip > "$dump.partial"
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
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 \
        --proxy-headers --forwarded-allow-ips='*'
fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
