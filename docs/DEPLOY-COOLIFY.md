# Deploying on Coolify

The app ships as a Docker Compose stack (`docker-compose.yml`): `db` (Postgres 16),
`app` (FastAPI/uvicorn), and `backup` (daily `pg_dump` + uploads tarball).

## Deploying as a Dockerfile application with a Coolify-managed PostgreSQL (how production runs)

Production is **not** the compose stack: it is one Coolify *Dockerfile* application
(built from this repo's `Dockerfile`) plus a separate Coolify-managed PostgreSQL
(currently **18**). The image ships the PGDG `pg_dump` 18, which can dump 16, 17
and 18 servers (Debian's own client is 17 and refuses a PG 18 server, which would
abort the pre-migrate backup and therefore the deploy).

**Environment Variables** (Coolify app → Environment Variables):

- `DATABASE_URL`: the managed database's *internal* URL in plain `postgresql://user:pass@host:5432/db` form (use the plain `postgresql://` form, no `+driver`).
- `APP_SECRET_KEY`: keep the existing production value.
- `APP_BASE_URL`: the public https URL (invite links, ingest URL).
- `FIELD_ENCRYPTION_KEY`: optional; if set it must be a valid Fernet key (a malformed one stops the app at startup).
- `DEBUG=false`, `TRUST_PROXY_HEADERS=true` (Traefik sets `X-Forwarded-*`), `APP_TIMEZONE=Europe/Athens`.
- `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_CLAIMS_EMAIL` for web push.
- `POSOKANEI_ENABLED=false` while the PosoKanei API returns 403.
- `RATE_LIMIT_STORAGE_URI`: optional (e.g. a Coolify Redis).
- New app (`/app`, passkeys via Pocket ID): `NEW_APP_ENABLED=true`, `OIDC_ISSUER=https://id.gch.gr`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`. See section 8 and `docs/POCKET-ID.md`.

**Persistent storage** (Coolify app → Storage):

- Mount storage at `/app/uploads`. Without it every receipt is lost on each redeploy.
- **WARNING:** if production already stores receipts somewhere, mount THAT same storage at `/app/uploads`. Never create a new empty volume: existing receipts would 404 and backups would tar an empty directory. Before deploying, check in Coolify → app → Storages what is currently mounted.
- Optionally mount one at `/backups` so pre-migrate dumps survive redeploys. It must be writable by uid 10001 (`docker run --rm -v <volume-name>:/data alpine chown -R 10001 /data`).
- The container runs as uid `10001`. If the storage already holds root-owned files, fix it once on the Coolify server (use the real volume name or host path from the Storage tab):
  ```sh
  docker run --rm -v <volume-name>:/data alpine chown -R 10001 /data
  # or, for a host bind mount: sudo chown -R 10001 /path/to/uploads
  ```

**Backups**: enable scheduled backups on the managed database in Coolify (that is the
real backup). In addition, `entrypoint.sh` takes a dump into `/backups` before every
migration. `/backups` is writable inside the image but ephemeral unless mounted, so
mount a volume if you want those dumps to outlive the container. The dump is
fail-closed: if it fails, the migration does not run. It is SKIPPED (not failed) when `/backups` is not writable, so make sure a mounted `/backups` is writable by uid 10001. `BACKUP_BEFORE_MIGRATE=false`
skips it (not recommended).

Follow the section 0 upgrade checklist as well (manual dump, receipts tarball, unpaid-bill
check), adapting the dump command to the managed database, e.g.
`pg_dump "$DATABASE_URL" | gzip > expenses-pre-v2.sql.gz` with a pg_dump 18 client.

The sections below describe the compose stack, for local and self-hosted use.

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

**Rollback = restore the pre-migrate dump**, never `alembic downgrade` (the one exception is the additive Phase 2 revisions, see section 9): the
downgrades drop the v2 columns and tables (soft-deleted transactions, archived
buckets, cash/settlement data), i.e. they destroy data entered since the upgrade.
Redeploy the previous release and restore `/backups/pre-migrate-<date>.sql.gz`
(or `expenses-pre-v2.sql.gz`) as in section 5.

## Planning redesign upgrade (migration a7b8c9d0e1f2)

Production runs commit `8b01313` (alembic head `f0a1b2c3d4e5`, user_oidc_subject).
A database restored from a pre-Phase-1 backup is at `e9f0a1b2c3d4` and upgrades
through `f0a1b2c3d4e5` to head; `tests/test_planning_upgrade.py` covers both
starting points. Run the manual check below once against a real dump before
deploying.

1. Dump production (the usual pre-migrate safety net; rollback = restore it):
   `pg_dump "$DATABASE_URL" | gzip > expenses-pre-planning.sql.gz`
2. Restore it into a scratch database on a Postgres 18 you control:
   `createdb expenses_upgrade_check && gunzip -c expenses-pre-planning.sql.gz | psql expenses_upgrade_check`
   No dump at hand? Build production's schema from the deployed code instead,
   with that code's own virtualenv (this branch's `.venv` would import this
   branch's models and migrations, and build the wrong schema):
   ```sh
   git worktree add /tmp/expenses-8b01313 8b01313
   cd /tmp/expenses-8b01313
   python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
   DATABASE_URL=postgresql://localhost/expenses_upgrade_check \
     APP_SECRET_KEY=$(openssl rand -hex 32) DEBUG=true .venv/bin/alembic upgrade head
   .venv/bin/alembic current   # → f0a1b2c3d4e5 (head)
   cd - && git worktree remove /tmp/expenses-8b01313
   ```
   Or use the production image, which has exactly the deployed code and
   dependencies: `docker run --rm --network host --entrypoint alembic -e DATABASE_URL=postgresql://<user>:<pass>@localhost/expenses_upgrade_check -e APP_SECRET_KEY=$(openssl rand -hex 32) -e DEBUG=true <production image> upgrade head`
   (`--network host` reaches the host's Postgres on Linux; on Docker Desktop
   drop it and use `host.docker.internal` instead of `localhost`).
   (A pre-Phase-1 backup: use commit `67da44c`, head `e9f0a1b2c3d4`.)
3. Upgrade with this branch:
   `DATABASE_URL=postgresql://localhost/expenses_upgrade_check .venv/bin/alembic upgrade head`
4. Check the backfill:
   - `psql expenses_upgrade_check -c "SELECT direction, rule_kind, count(*) FROM recurring_bills GROUP BY 1,2"` → only `out | monthly_interval`
   - `psql expenses_upgrade_check -c "SELECT type, kind, count(*) FROM buckets GROUP BY 1,2"` → trip = event, the rest monthly
   - `psql expenses_upgrade_check -c "SELECT count(*) FROM bill_occurrences o JOIN transactions t ON t.id = o.transaction_id WHERE o.status = 'paid' AND t.recurring_bill_id IS DISTINCT FROM o.bill_id"` → 0
5. Old-app smoke test on the upgraded copy:
   `DATABASE_URL=postgresql://localhost/expenses_upgrade_check APP_SECRET_KEY=<prod key> FIELD_ENCRYPTION_KEY=<prod key> DEBUG=true ENABLE_SCHEDULER=false .venv/bin/uvicorn app.main:app --port 8001`
   Log in with password + TOTP. (In production people may also sign in to the
   new app with a Pocket ID passkey; that flow returns to the production
   callback URL, not to this local copy. Everyone who linked a passkey did so
   after a password + TOTP login, so that path works for every account.)
   Open the dashboard (same month totals as production), Bills (same list, pay one occurrence), Insights, a trip bucket and Search.
6. Round trip: `.venv/bin/alembic downgrade f0a1b2c3d4e5 && .venv/bin/alembic upgrade head` (`f0a1b2c3d4e5` is the revision this migration revises).
   The downgrade refuses, without changing anything, while the database has
   any recurring item that is incoming (`direction = 'in'`) or uses a new
   schedule rule (`rule_kind <> 'monthly_interval'`), any expense without a
   bucket (a Fixed cost paid from the new app), or an undone auto-payment
   still in the 3-day auto-pay window. A fresh copy of production has none of
   these; if you tried the new app on the copy first, remove them (or start
   again from the dump) before this step.
7. Drop the scratch database.

Then note the date and result in the PR description.

## 1. Environment variables

Set these in Coolify → the resource → **Environment Variables** *before* the first
deploy (and before any redeploy that introduces a new required variable).

| Variable | Required | Value / notes |
|---|---|---|
| `APP_SECRET_KEY` | yes | `python -c "import secrets; print(secrets.token_hex(32))"`. Compose refuses to start without it. Changing it logs everyone out. |
| `JWT_SECRET_KEY` | recommended | Separate random secret for API tokens (defaults to `APP_SECRET_KEY`). |
| `FIELD_ENCRYPTION_KEY` | recommended | A malformed value stops the app at startup. Fernet key for encrypting TOTP secrets at rest: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Derived from `APP_SECRET_KEY` when unset. Setting it later is safe: secrets encrypted under the derived key stay readable and are re-encrypted under the new key on the next 2FA login. Without it, **changing `APP_SECRET_KEY` makes stored TOTP secrets unreadable** (users would be locked out of 2FA), so set this key explicitly and keep it stable. Existing plaintext secrets keep working and are encrypted on the user's next successful 2FA login. |
| `POSTGRES_PASSWORD` | yes | Password for the bundled `db` service. |
| `DATABASE_URL` | only with an external DB | `postgresql://user:pass@host:5432/db`. Compose IGNORES `DATABASE_URL` (it always uses the bundled `db`, built from `POSTGRES_PASSWORD`). `DATABASE_URL` is only used by the Coolify Dockerfile app + managed-Postgres setup (set in the Coolify UI) or when running uvicorn directly. |
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

The new app's variables (`NEW_APP_ENABLED`, `OIDC_*`) are listed in section 8. The compose
stack doesn't pass them; production (the Dockerfile app) sets them in Coolify.

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
  file, and set `DATABASE_URL` (compose ignores it; it only applies to the Coolify Dockerfile app or running uvicorn directly). Back up `./uploads`
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
(it drops data, see section 0), except for the additive Phase 2 revisions, where
section 9's targeted downgrade inside the running container is the preferred path.

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

## 8. New app (`/app`) and Pocket ID

The new React app is served at `/app` behind a feature flag and signs in with passkeys
through a self-hosted Pocket ID (OIDC). Production: app `https://expenses.gch.gr`, Pocket ID
`https://id.gch.gr` (its own Coolify resource), OIDC client `Tameio` with callback
`https://expenses.gch.gr/app/auth/callback`. Full setup, account linking, recovery and
troubleshooting: [`docs/POCKET-ID.md`](POCKET-ID.md).

Set on the expenses app (Coolify → Environment Variables), then redeploy:

| Variable | Required | Value / notes |
|---|---|---|
| `NEW_APP_ENABLED` | for `/app` | Default `false`: `/app/*` is a 404 and nothing else changes. `true` serves the new app and the passkey routes; the app then refuses to start unless all three `OIDC_*` values are set. |
| `OIDC_ISSUER` | with the flag | `https://id.gch.gr`, exactly Pocket ID's discovery `issuer`. Its origin is also added to the old UI's CSP `form-action` (the Link passkey form redirects there). |
| `OIDC_CLIENT_ID` | with the flag | The `Tameio` client's ID from Pocket ID. |
| `OIDC_CLIENT_SECRET` | with the flag | The `Tameio` client's secret. Keep it only in Coolify. |

`APP_BASE_URL` must be `https://expenses.gch.gr`: the callback URL is built from it and must
match the one registered in Pocket ID.

Pocket ID itself (its own resource) needs `APP_URL=https://id.gch.gr`,
`ENCRYPTION_KEY` (v2 requires it, at least 16 bytes; keep it, losing it loses the signing
keys), `TRUST_PROXY=true`, and persistent storage on `/app/data`. Passkeys need a trusted
HTTPS certificate: a plain-http `sslip.io` URL does not work.

Linking is never by email: each person links once from the old UI (password + 2FA) →
Settings → **Link passkey**. Keep Pocket ID's self sign-up off.

For local development, `docker compose --profile pocketid up -d pocketid` starts a Pocket
ID on `http://localhost:1411` (see `docs/POCKET-ID.md` → Local development).

## 9. Phase 2 releases (P1, P2, P3)

Phase 2 of the new app ships in three pushes. The migration chain is
`a7b8c9d0e1f2` → `b8c9d0e1f2a3` (P1, `bill_payment_method`) → `c9d0e1f2a3b4`
(P2, `bulk_changes`: `bulk_batches`, `bulk_batch_rows`, `duplicate_dismissals`) →
`d0e1f2a3b4c5` (P2, `notification_mutes`). All are additive.

**P3 (Activity bulk UI, Insights, Settings, push service worker) adds no migrations.**
The head stays `d0e1f2a3b4c5`; `entrypoint.sh`'s `alembic upgrade head` is a no-op, so the
pre-migrate dump is only the usual safety net. Nothing new is required in the environment.

**Push notifications** (Settings › Notifications in `/app`) use the existing
`VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` and `VAPID_CLAIMS_EMAIL` (section 1). They are not
required to start: without the keys the app logs a warning at startup,
`GET /push/vapid-public-key` answers 404 so the new app cannot subscribe a device, and
"Send test" reports that VAPID is not configured. Keep the same key pair across deploys:
a new pair invalidates every existing subscription (each device has to turn push on
again). The service worker is served at `/app/sw.js` with scope `/app/`; the old UI's
`static/sw.js` is unchanged.

**Rolling the image back past P2** (to a P1 or older image): the older image does not know
revisions `c9d0e1f2a3b4` and `d0e1f2a3b4c5`, so its `alembic upgrade head` at boot fails
against a P2 database. Before switching images, run the downgrade **inside the running
P2 (or P3) container**, which has those migration files and the full production
environment (`alembic/env.py` loads the app settings, so a bare `docker run` with only
`DATABASE_URL` fails on `APP_BASE_URL` and the OIDC variables):

```sh
docker exec <running P2/P3 app container> alembic downgrade b8c9d0e1f2a3
```

This drops `bulk_batches`, `bulk_batch_rows` (bulk-change undo history),
`duplicate_dismissals` ("Keep both") and `notification_mutes`; transactions themselves
are untouched. Then deploy the older image. Rolling back between P3 and P2 needs no
database step. Restoring the pre-migrate dump (section 5) remains the alternative, at the
cost of anything entered since it was taken.
