# Deploying on Coolify

The app ships as a Docker Compose stack (`docker-compose.yml`): `db` (Postgres 16),
`app` (FastAPI/uvicorn), and `backup` (daily `pg_dump` + uploads tarball).

## 0. Upgrading an existing v1 deployment (first v2 deploy) — checklist

Do these **before** pressing Deploy:

1. **Back up the database by hand** (the automatic pre-migrate dump is a second
   safety net, not the only one):
   ```sh
   docker compose exec -T db pg_dump -U expenses_user expenses | gzip > expenses-pre-v2.sql.gz
   ```
2. **Tarball the receipts** on the host: `tar czf uploads-pre-v2.tgz uploads`
   (run in the directory that holds `docker-compose.yml`).
3. **Check unpaid bill occurrences** — the result must be `0`; otherwise those
   occurrences cannot be paid through the new pay flow (fix or report them first):
   ```sql
   SELECT count(*) FROM bill_occurrences WHERE status='unpaid' AND transaction_id IS NOT NULL;
   ```
4. **Environment** (section 1): keep the *existing* `APP_SECRET_KEY` value
   (changing it logs everyone out and, without `FIELD_ENCRYPTION_KEY`, breaks
   stored 2FA secrets); set `APP_BASE_URL` (compose refuses to start without it);
   set `FIELD_ENCRYPTION_KEY` to a key generated with the command in the table — a
   malformed key now stops the app at startup. Set `POSOKANEI_ENABLED=false` for
   now (the PosoKanei API currently answers 403).
5. **Ownership of ./uploads**: the container now runs as uid `10001`, so fix the
   host directory once: `sudo chown -R 10001 ./uploads` (see section 2).

After the deploy, **everyone has to log in again once** — web sessions and the
mobile app's refresh tokens from v1 are no longer accepted.

**Rollback = restore the pre-migrate dump**, never `alembic downgrade`: the
downgrades drop the v2 columns and tables (soft-deleted transactions, archived
buckets, cash/settlement data), i.e. they destroy data entered since the upgrade.
Redeploy the previous release and restore `/backups/pre-migrate-<date>.sql.gz`
(or `expenses-pre-v2.sql.gz`) as in section 5.

## 1. Environment variables

Set these in Coolify → the resource → **Environment Variables** *before* the first
deploy (and before any redeploy that introduces a new required variable).

| Variable | Required | Value / notes |
|---|---|---|
| `APP_SECRET_KEY` | yes | `python -c "import secrets; print(secrets.token_hex(32))"`. Compose refuses to start without it. Changing it logs everyone out. |
| `JWT_SECRET_KEY` | recommended | Separate random secret for API tokens (defaults to `APP_SECRET_KEY`). |
| `FIELD_ENCRYPTION_KEY` | recommended | A malformed value stops the app at startup. Fernet key for encrypting TOTP secrets at rest: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Derived from `APP_SECRET_KEY` when unset. Setting it later is safe: secrets encrypted under the derived key stay readable and are re-encrypted under the new key on the next 2FA login. Without it, **changing `APP_SECRET_KEY` makes stored TOTP secrets unreadable** (users would be locked out of 2FA), so set this key explicitly and keep it stable. Existing plaintext secrets keep working and are encrypted on the user's next successful 2FA login. |
| `POSTGRES_PASSWORD` | yes | Password for the bundled `db` service. |
| `DATABASE_URL` | only with an external DB | `postgresql://user:pass@host:5432/db`. When unset, the compose file builds it from `POSTGRES_PASSWORD` for the bundled `db`; when set it is passed to `app` and `backup`. |
| `DEBUG` | yes | `false` (compose sets it). |
| `TRUST_PROXY_HEADERS` | yes | `true` — Coolify's Traefik overwrites `X-Forwarded-For`. |
| `APP_TIMEZONE` | yes | `Europe/Athens` (compose default). Drives "today" for bills and reminders. |
| `APP_BASE_URL` | yes | `https://expenses.example.com` — used for invite links and the Shortcut ingest URL; compose refuses to start without it. |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_CLAIMS_EMAIL` | for push | Web-push keys. |
| `RATE_LIMIT_STORAGE_URI` | recommended | `redis://redis:6379` with the compose `redis` profile enabled (`docker compose --profile redis up`, or remove the `profiles:` line in Coolify). Without it, per-IP login limits apply per worker; the per-account lockout (10 failures → 15 min) is stored in the database and holds regardless. |
| `POSOKANEI_ENABLED` | optional | Default `true`: fetch supermarket prices for the stock list (unofficial API, see `docs/POSOKANEI.md`). `false` stops all outbound lookups; `/stock` still works. **Recommended `false` for now**: the API currently answers 403. |
| `POSOKANEI_BASE_URL` | optional | Default `https://api.posokanei.gov.gr`. |
| `ALLOW_REGISTRATION` | optional | Default `false`. |
| `CORS_ALLOWED_ORIGINS` | optional | Space-separated origins for API clients, e.g. `capacitor://localhost`. Empty = none. |
| `BACKUP_KEEP_DAYS` | optional | Days of backups to keep (default 30). |
| `BACKUP_BEFORE_MIGRATE` | optional | `true` (default) dumps the DB to `/backups/pre-migrate-*.sql.gz` before `alembic upgrade`. |

## 2. Persistent storage

| Storage | Mounted at | Contents |
|---|---|---|
| `postgres_data` (named volume) | `/var/lib/postgresql/data` (db) | Database |
| `./uploads` (host bind mount, next to `docker-compose.yml`) | `/app/uploads` (app; backup read-only) | Receipt files |
| `backups` (named volume) | `/backups` (app, backup) | `db-*.sql.gz`, `uploads-*.tgz`, `pre-migrate-*.sql.gz` |

Receipts stay on the same `./uploads` bind mount v1 used, so existing files keep
working across the upgrade. Do not move them to a named volume: a fresh volume
would hide every existing receipt (they would 404) and the backups would tar an
empty directory.

The containers run as uid `10001` (user `app`). Files written by the old root
container are root-owned, so fix ownership once on the host before the first v2
deploy (and create the directory if it does not exist yet):

```sh
mkdir -p uploads && sudo chown -R 10001 uploads
```

(The `backups` named volume is created fresh and inherits uid 10001 from the image.)

## 3. Networking

Coolify ignores the `ports:` entry and routes traffic through Traefik labels. Set the
domain on the `app` service in Coolify and point it at port `8000`. Outside Coolify,
the app is published on `127.0.0.1:8000` only (override with `APP_BIND_ADDRESS`).

## 4. Backups

- **Bundled database (default):** the `backup` service (built from the app image,
  so its `pg_dump` matches the app's) runs `/app/scripts/backup.sh` once a day,
  writing to the `backups` volume and pruning files older than
  `BACKUP_KEEP_DAYS`. A failed run logs `BACKUP FAILED`, and the service turns
  **unhealthy** when the newest `db-*.sql.gz` is older than ~26 hours. Copy that
  volume off the server periodically (Coolify → Server → Backups, or `rsync`
  from the host path).
- **Coolify-managed Postgres resource:** enable Coolify's built-in scheduled backups
  (with S3) on the database resource, remove the `backup` service from the compose
  file, and set `DATABASE_URL` (passed to `app` when set). Back up `./uploads`
  separately.
- **Before every migration:** `entrypoint.sh` writes `pre-migrate-<date>.sql.gz` when
  `/backups` is mounted (`BACKUP_BEFORE_MIGRATE=true`, the default).

Take a manual backup before redeploying a release that adds migrations:

```sh
docker compose exec backup /app/scripts/backup.sh
```

## 5. Restore

This is also the **rollback** procedure after a failed upgrade: restore the
`pre-migrate-*.sql.gz` taken just before it. Do not use `alembic downgrade`
(it drops data, see section 0).

```sh
# Stop the app so nothing writes during the restore.
docker compose stop app

# Copy the dump out of the backups volume.
docker compose cp backup:/backups/db-2026-10-01-0300.sql.gz .

# Database: restore into an empty database.
docker compose exec -T db dropdb -U expenses_user expenses
docker compose exec -T db createdb -U expenses_user expenses
gunzip -c db-2026-10-01-0300.sql.gz | docker compose exec -T db psql -U expenses_user expenses

# Uploads: extract on the host into ./uploads (the archive contains uploads/).
docker compose cp backup:/backups/uploads-2026-10-01.tgz .
tar xzf uploads-2026-10-01.tgz -C . && sudo chown -R 10001 uploads

docker compose start app
```

## 6. Secrets in the repository root

`private_key.pem`, `public_key.pem` and `.env` sit in the repo root for local
development. They are git-ignored; keep them out of the deployed image's build
context in production by setting the values as Coolify environment variables instead.

**Action for the operator (not done automatically):** if these files currently
live in the repository root of a deployed checkout, move `private_key.pem`,
`public_key.pem` and `.env` somewhere outside the repo directory (for example
`~/secrets/expenses/`) and point the app at them via environment variables.
Nothing in the repo deletes them; they are only ignored by version control, and
anything in the build context can end up in an image layer.

## 7. Scheduler with multiple workers

The container runs `uvicorn --workers 2`. On PostgreSQL, each process tries
`pg_try_advisory_lock(727272)` at startup; only the winner runs the scheduler
(the lock is held on a dedicated connection and released if the process dies).
`ENABLE_SCHEDULER=true` can stay set everywhere.
