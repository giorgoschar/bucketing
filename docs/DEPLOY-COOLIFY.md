# Deploying on Coolify

The app ships as a Docker Compose stack (`docker-compose.yml`): `db` (Postgres 16),
`app` (FastAPI/uvicorn), and `backup` (daily `pg_dump` + uploads tarball).

## 1. Environment variables

Set these in Coolify → the resource → **Environment Variables** *before* the first
deploy (and before any redeploy that introduces a new required variable).

| Variable | Required | Value / notes |
|---|---|---|
| `APP_SECRET_KEY` | yes | `python -c "import secrets; print(secrets.token_hex(32))"`. Compose refuses to start without it. Changing it logs everyone out. |
| `JWT_SECRET_KEY` | recommended | Separate random secret for API tokens (defaults to `APP_SECRET_KEY`). |
| `FIELD_ENCRYPTION_KEY` | recommended | Fernet key for encrypting TOTP secrets at rest: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Derived from `APP_SECRET_KEY` when unset. |
| `POSTGRES_PASSWORD` | yes | Password for the bundled `db` service. |
| `DATABASE_URL` | only with an external DB | `postgresql://user:pass@host:5432/db`. The compose file builds it from `POSTGRES_PASSWORD` for the bundled `db`. |
| `DEBUG` | yes | `false` (compose sets it). |
| `TRUST_PROXY_HEADERS` | yes | `true` — Coolify's Traefik overwrites `X-Forwarded-For`. |
| `APP_TIMEZONE` | yes | `Europe/Athens` (compose default). Drives "today" for bills and reminders. |
| `APP_BASE_URL` | yes | `https://expenses.example.com` — used for invite links; required in production. |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_CLAIMS_EMAIL` | for push | Web-push keys. |
| `RATE_LIMIT_STORAGE_URI` | recommended | `redis://redis:6379` with the compose `redis` profile enabled (`docker compose --profile redis up`, or remove the `profiles:` line in Coolify). Without it, per-IP login limits apply per worker; the per-account lockout (10 failures → 15 min) is stored in the database and holds regardless. |
| `POSOKANEI_ENABLED` | optional | `true` to fetch supermarket prices for the stock list. |
| `BACKUP_KEEP_DAYS` | optional | Days of backups to keep (default 30). |
| `BACKUP_BEFORE_MIGRATE` | optional | `true` (default) dumps the DB to `/backups/pre-migrate-*.sql.gz` before `alembic upgrade`. |

## 2. Persistent storage

The compose file declares named volumes; Coolify keeps them across deploys:

| Volume | Mounted at | Contents |
|---|---|---|
| `postgres_data` | `/var/lib/postgresql/data` (db) | Database |
| `uploads_data` | `/app/uploads` (app, backup read-only) | Receipt files |
| `backups` | `/backups` (app, backup) | `db-*.sql.gz`, `uploads-*.tgz`, `pre-migrate-*.sql.gz` |

The container runs as uid `10001` (user `app`). Fresh volumes inherit that ownership
from the image. When upgrading a deployment whose uploads were written by the old root
container, fix ownership once:

```sh
docker compose run --rm --user root app chown -R 10001 /app/uploads /backups
```

Do not switch `uploads` back to a bind mount: Coolify's bind paths change between
deployments of some resource types.

## 3. Networking

Coolify ignores the `ports:` entry and routes traffic through Traefik labels. Set the
domain on the `app` service in Coolify and point it at port `8000`. Outside Coolify,
the app is published on `127.0.0.1:8000` only (override with `APP_BIND_ADDRESS`).

## 4. Backups

- **Bundled database (default):** the `backup` service runs `scripts/backup.sh` once
  a day, writing to the `backups` volume and pruning files older than
  `BACKUP_KEEP_DAYS`. Copy that volume off the server periodically (Coolify
  → Server → Backups, or `rsync` from the host path).
- **Coolify-managed Postgres resource:** enable Coolify's built-in scheduled backups
  (with S3) on the database resource, remove the `backup` service from the compose
  file, and set `DATABASE_URL` on `app`. Back up the `uploads_data` volume separately.
- **Before every migration:** `entrypoint.sh` writes `pre-migrate-<date>.sql.gz` when
  `/backups` is mounted.

Take a manual backup before redeploying a release that adds migrations:

```sh
docker compose exec backup /scripts/backup.sh
```

## 5. Restore

```sh
# Stop the app so nothing writes during the restore.
docker compose stop app

# Database: restore into an empty database.
docker compose exec -T db dropdb -U expenses_user expenses
docker compose exec -T db createdb -U expenses_user expenses
gunzip -c db-2026-10-01-0300.sql.gz | docker compose exec -T db psql -U expenses_user expenses

# Uploads
docker compose run --rm -v "$PWD":/restore backup \
  sh -c 'tar xzf /restore/uploads-2026-10-01.tgz -C /app'   # needs the volume mounted read-write

docker compose start app
```

For the uploads restore, temporarily drop `:ro` from the `uploads_data` mount on the
`backup` service, or extract on the host into the volume's path.

## 6. Secrets in the repository root

`private_key.pem`, `public_key.pem` and `.env` sit in the repo root for local
development. They are git-ignored; keep them out of the deployed image's build
context in production by setting the values as Coolify environment variables instead.
