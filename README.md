# Tameio — household money tracker

A self-hosted app for a household's money: everyday spending, recurring bills and income, budgets, cash, a pantry with a shopping list, and monthly statements. It runs on your own server and installs on a phone as a PWA.

There are two front ends on one server:

- **The new app**, a React PWA at `/app`. This is the one in daily use and the one this README is about.
- **The legacy pages** (server-rendered, at `/`). They still handle first-run setup, two-factor enrolment and a few admin screens.

## What it does

- **Add** an expense or income in a few taps, from the phone or with the keyboard on desktop. Offline entries are queued and sent later.
- **Plan**: recurring bills and income, what is coming up, the month's picture, budgets, cash wallets and a private stash, and a pantry with barcode scanning.
- **Insights**: where the money went, trends, each bill's history with optional usage (kWh, m³), and a statement for every past month.
- **Home**: what needs attention (overdue bills, cash not logged, a bill that changed, a month ready to review).
- **Automations**: an Apple Pay Shortcut can log card payments; push notifications for bills and reviews.

---

## Run it locally

You need **Python 3.11+** and **Node 22+**. The steps below were run as written on macOS.

```bash
# 1. Get the code
git clone <your-repo> expenses && cd expenses

# 2. Python environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Build the new app once (the server serves web/dist at /app)
cd web && npm ci && npm run build && cd ..

# 4. Start the server with local settings
DEBUG=true NEW_APP_ENABLED=true \
APP_SECRET_KEY=local-dev-secret-change-me-0123456789 \
DATABASE_URL=sqlite:///./local.db \
uvicorn app.main:app --reload --port 8000
```

`DEBUG=true` allows plain http and a placeholder secret. `NEW_APP_ENABLED=true` turns on `/app`; without it `/app` answers 404. The database is one file, `local.db`, created and migrated on first start. Delete it to start over.

### First sign-in

1. Open <http://localhost:8000>. With an empty database it sends you to the **setup** page: name the household and create your user.
2. You are then asked to **enrol two-factor**: scan the QR code with any authenticator app and type the 6-digit code. This step is required; the app's API refuses a session that has not finished it.
3. Open <http://localhost:8000/app/>. You are signed in: the new app uses the same session cookie.

Production signs in with a passkey through Pocket ID ("Sign in with Face ID"). Locally that button only works if you also set the three `OIDC_*` variables ([`docs/POCKET-ID.md`](docs/POCKET-ID.md)); the password and authenticator route above needs nothing extra.

### Explore it

A new household is empty, so the screens fill in as you add things. A quick tour that touches every area, about 10 minutes:

1. **Add an expense:** press **＋** (or `N` on desktop), type an amount and a place, pick a budget, save. Add three or four, with different categories.
2. **Add a recurring bill:** Plan › **Items** › New. Give one a fixed amount (rent) and leave one without (electricity), and set its "Track usage" to kWh.
3. **Pay a bill:** Plan › Upcoming › tap the bill › Paid. For the variable one, set the amount and the usage first.
4. **Set a budget:** Plan › Budgets.
5. **Cash:** Plan › Cash › Take, then add a cash expense, and watch "not yet logged" change.
6. **Pantry:** Plan › Pantry › ＋. Type a barcode from something in your kitchen (for example `5201054017906`), add it, and use − / + on the row. Product names come from Open Food Facts, so this step needs internet.
7. **Insights:** the dashboard, then **Bills** for the history of the bill you paid.
8. **Desktop:** widen the window past 1024 px: the tabs become a sidebar, Activity becomes a table, and Add opens as a side panel.
9. **Phone:** open the same address from a phone on your network (start uvicorn with `--host 0.0.0.0`). Installing it as a PWA and using the camera need https, so those two only work on a real deployment.

Things that stay quiet locally, by design: push notifications (no VAPID keys), the daily jobs' notifications until a day passes, statements (they appear for past months, so a brand-new database has none), and store prices (the price service does not answer outside its own site).

To explore with real data instead, restore a copy of a production backup into a local PostgreSQL and point `DATABASE_URL` at it: see [Restore](docs/DEPLOY-COOLIFY.md#5-restore). Use a copy, never the live database.

### Work on the new app

For live reload while editing `web/`, run the Vite dev server next to the API:

```bash
# terminal 1: the API, as in step 4 above
# terminal 2:
cd web && npm run dev              # http://localhost:5173/app/
```

Vite proxies `/api`, `/app/auth`, `/login` and `/static` to port 8000. Sign in once at <http://localhost:5173/login>, then open <http://localhost:5173/app/>.

```bash
cd web
npm test                 # unit and component tests (Vitest)
npm run typecheck        # TypeScript, including the tests
npm run lint
npm run build            # production build + bundle and service-worker checks
npm run gen:api          # after changing the API: regenerate src/api/schema.d.ts
```

Design notes for each part of the app are in [`docs/superpowers/specs/`](docs/superpowers/specs/), and the roadmap and open follow-ups in [`docs/redesign/`](docs/redesign/).

---

## Docker

```bash
# Copy and edit env
cp .env.example .env
# Set in .env (compose refuses to start without both):
#   APP_SECRET_KEY  - python -c "import secrets; print(secrets.token_hex(32))"
#   APP_BASE_URL    - public URL, e.g. https://expenses.example.com
#                     (http://localhost:8000 for a local try-out, with DEBUG=true)

# Receipts live in ./uploads; the container runs as uid 10001
mkdir -p uploads && sudo chown -R 10001 uploads

# Start
docker compose up -d

# Open http://localhost:8000
```

The compose stack runs three services: `db` (PostgreSQL 16), `app` (uvicorn,
2 workers) and `backup` (daily `pg_dump` + uploads tarball).

Persistent data:

| Storage | Holds |
|---|---|
| `postgres_data` (named volume) | the PostgreSQL database |
| `./uploads` (host bind mount) | receipt images (`/app/uploads`) |
| `backups` (named volume) | daily dumps, plus a pre-migration dump on each deploy |

**Upgrading from v1?** Follow the checklist in
[`docs/DEPLOY-COOLIFY.md`](docs/DEPLOY-COOLIFY.md#0-upgrading-an-existing-v1-deployment-first-v2-deploy--checklist)
first: manual `pg_dump`, `tar czf uploads-pre-v2.tgz uploads`, keep your existing
`APP_SECRET_KEY`, set `APP_BASE_URL` and a valid `FIELD_ENCRYPTION_KEY`. Everyone
logs in again once after the upgrade. To roll back, restore the pre-migrate dump —
never `alembic downgrade`, which drops v2 data.

Migrations run automatically on start (`alembic upgrade head`). With two
workers, only the process that wins a PostgreSQL advisory lock runs the
background scheduler; on SQLite the single process always runs it.

### Backups

The `backup` service writes a daily database dump and an uploads tarball to the
`backups` volume (kept `BACKUP_KEEP_DAYS` days, default 30), and the app dumps
the database before every migration. Copy the volume off the host regularly.
Restore steps are in [`docs/DEPLOY-COOLIFY.md`](docs/DEPLOY-COOLIFY.md#5-restore).

### Deploying on Coolify

Production runs as a Coolify Dockerfile app + managed PostgreSQL: see [`docs/DEPLOY-COOLIFY.md`](docs/DEPLOY-COOLIFY.md#deploying-as-a-dockerfile-application-with-a-coolify-managed-postgresql-how-production-runs).

See [`docs/DEPLOY-COOLIFY.md`](docs/DEPLOY-COOLIFY.md) for the full guide,
including every production environment variable.

### Timestamps

`DateTime` columns store naive UTC (`app/clock.py: utcnow_naive`). Calendar
dates (bill due dates, "today") are evaluated in `APP_TIMEZONE`.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./expenses.db` | SQLAlchemy DB URL. Use `postgresql://...` for PostgreSQL in production |
| `APP_SECRET_KEY` | *(required)* | Secret for signing session cookies. Placeholder values (`change-me...`) are rejected when `DEBUG=false`. |
| `DEBUG` | `false` | Enable FastAPI debug mode |
| `NEW_APP_ENABLED` | `false` | Serve the new app at `/app`. When `DEBUG=false` it also needs the three `OIDC_*` variables ([`docs/POCKET-ID.md`](docs/POCKET-ID.md)) |
| `OPENFOODFACTS_ENABLED` | `true` | Fill in product names from Open Food Facts on a barcode lookup ([`docs/OPENFOODFACTS.md`](docs/OPENFOODFACTS.md)) |
| `APP_TIMEZONE` | `UTC` | Calendar timezone for scheduled work. Bill due dates are local calendar dates, so set this to your zone (e.g. `Europe/Athens`) or bills can be judged due a day late |
| `ENABLE_SCHEDULER` | `true` | Run the daily auto-pay / reminder job. On PostgreSQL only one worker holds the advisory lock and runs it; on SQLite the process always does |
| `POSOKANEI_ENABLED` | `true` | Look up supermarket prices on PosoKanei for `/stock` (unofficial API; see `docs/POSOKANEI.md`). `false` = no outbound requests, stock pages still work |
| `TRUST_PROXY_HEADERS` | `false` | Honour `X-Forwarded-For`. Enable **only** behind a proxy that overwrites it, otherwise clients can spoof their IP in logs and rate-limit buckets |
| `RATE_LIMIT_STORAGE_URI` | *(memory)* | e.g. `redis://host:6379`. Without it, login/2FA limits are counted per worker |
| `JWT_SECRET_KEY` | *(uses `APP_SECRET_KEY`)* | Separate signing key for mobile/API tokens |
| `CORS_ALLOWED_ORIGINS` | *(none)* | Space-separated allowed origins |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | *(none)* | Web-push keys; push is silently disabled without them |

This is the common subset. Production variables (`FIELD_ENCRYPTION_KEY`, `APP_BASE_URL`, `POSTGRES_PASSWORD`, backups, ...) are documented in [`docs/DEPLOY-COOLIFY.md`](docs/DEPLOY-COOLIFY.md); see also [`.env.example`](.env.example).

---

## Legacy pages: stylesheet build

This is for the server-rendered legacy pages only; the new app's build is under [Work on the new app](#work-on-the-new-app). Tailwind is compiled ahead of time and the built stylesheet is committed.

```bash
npm install          # once
npm run css          # rebuild static/css/app.css
npm run css:watch    # rebuild on change while developing
```

**Rebuild whenever you add or change Tailwind classes** in `templates/` or
`static/*.js`, and commit the result. `tailwind.config.js` scans both, because
some class names are constructed at runtime in JavaScript (the offline-queue
pill picks its colour by state) and would otherwise be purged.

`tests/test_frontend_wiring.py` guards the build: it fails if a CDN reference comes
back (assets are vendored), if the stylesheet is missing or truncated, or if a class known to be
runtime-constructed has been purged.

---

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                       # full suite
pytest --cov=app             # with coverage (CI enforces >= 80%)
pytest tests/test_scheduler.py -v
```

Each test builds its own throwaway SQLite database (or Postgres, with `TEST_DATABASE_URL`), so the suite never touches
your real data. Coverage focuses on the parts where a bug costs money or leaks
data:

| Suite | Covers |
|---|---|
| `test_scheduler.py` | Auto-pay idempotency under concurrent workers and repeated runs; notification de-duplication |
| `test_isolation.py` | Cross-household access control on every id accepted from a client |
| `test_auth.py` | Login, TOTP enrollment/re-enrollment, backup codes, session invalidation, CSRF |
| `test_bills.py` | Occurrence generation limits, double-pay protection, skip/pay guards |
| `test_transactions.py` | Amount/date/currency validation, CSV formula injection, leap-year export |
| `test_insights.py` | Date presets, filter consistency across widgets, chart scaling |
| `test_api.py` | JWT flow, token rotation, API validation and isolation |
| `test_migrations.py` | Migrations apply from scratch, single head, schema matches models, no data loss |
| `test_settlement_balance.py` | Per-member nets always sum to zero, whatever the split shape |
| `test_settlement_exclusions.py` | Expenses settle-up must skip, and the report that explains why |

---

## What settle-up counts (legacy pages)

Settle-up exists only in the legacy pages; the new app does not have it.

Balances are computed only from expenses that can actually create a debt, in
buckets with **Track settlement** on:

| Expense | Counted? |
|---|---|
| Split between members | Yes — each member takes their split |
| Split covering only part of the total | Yes — the payer absorbs the remainder |
| No splits | Yes — divided equally among the bucket's participants |
| **No payer recorded** | **No** — nobody fronted the money, so there is no debt |
| **Marked "exclude from settle-up"** | **No** — still counted as household spending |

The last two are listed on the settle-up page with their totals, so the gap
between what was spent and what is owed is never unexplained. An expense with
no payer used to have its shares charged to members while the money was
credited to nobody, which made both members appear to owe an outsider.

---

## Tech Stack

| Layer | Library |
|---|---|
| Web framework | FastAPI 0.115 |
| Templates | Jinja2 3.1 |
| ORM | SQLAlchemy 2.0 + Alembic |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Auth | `itsdangerous` signed cookies + `bcrypt`, PyJWT for API tokens |
| New app (`web/`) | React 19 + TypeScript + Vite, TanStack Query, Dexie (offline queue), a service worker (vite-plugin-pwa) |
| Legacy pages | Jinja2 + HTMX 1.9 + Alpine.js 3 + TailwindCSS (prebuilt; vendored under `static/`, no CDN at runtime) |

---

## Project Structure

```
app/
  main.py           # FastAPI app: middleware, security headers, router includes
  models.py         # All ORM models
  schemas.py        # Pydantic request/response models for the JSON API
  auth.py           # Password hashing, web session cookie, CSRF
  api_auth.py       # JWT access/refresh tokens, pat_ ingest tokens
  scheduler.py      # Background jobs (bill occurrences, reminders, price refresh)
  core/             # Infrastructure used by every layer
    config.py       #   Settings (pydantic-settings, reads .env)
    database.py     #   SQLAlchemy engine + session
    crypto.py       #   Field encryption (TOTP secrets)
    clock.py        #   Household timezone, today/now helpers
    ratelimit.py    #   slowapi limiter
    money.py        #   Decimal primitives, half-up rounding
    logging.py      #   Root log handler + LOG_LEVEL (app lines to stderr)
  services/         # Business logic; routes stay thin and call these
  integrations/     # Third-party API clients (PosoKanei prices)
  api/              # JSON API under /api/v1 (used by the new app and the Shortcut)
  routes/           # Server-rendered Jinja/HTMX pages (legacy UI, removed at cutover)
  templates.py      # Jinja2Templates + custom filters (legacy UI)
alembic/            # Database migrations
templates/, static/ # Legacy UI templates and assets
web/                # New React PWA (Vite), served at /app — see web/README.md
docs/               # Deploy guide, PosoKanei notes, redesign mocks
scripts/            # Ops scripts (backup, household purge)
tests/              # pytest suite (SQLite by default, Postgres via TEST_DATABASE_URL)
uploads/            # Receipt images (gitignored)
```
