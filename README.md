# Expenses — Household Finance Tracker

A self-hosted PWA for tracking household expenses, shared bills, and budgets. No cloud, no subscription, runs anywhere Python runs.

## Features

- **Buckets** — organize spending into Day2Day, Trips, Bills, Savings, or custom buckets
- **Fast expense entry** — 4-step wizard optimized for mobile
- **Recurring bills** — fixed and variable, monthly or custom interval, with pay/skip tracking
- **Shared expenses** — split any transaction by amount or percentage per person, track who owes whom
- **Settle up** — household-wide balances netted across every settlement-enabled bucket, with a payment history
- **Multi-household** — switch between households from the nav (e.g. personal + parents)
- **Multi-currency** — EUR default, per-transaction currency for travel
- **PWA** — installable on iOS/Android, works offline for browsing

---

## Quick Start (local)

### Requirements
- Python 3.11+

### Steps

```bash
# 1. Clone
git clone <your-repo> && cd expenses

# 2. Create virtualenv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Install
pip install -r requirements.txt

# 4. Configure (optional — defaults work for dev)
cp .env.example .env
# Edit APP_SECRET_KEY if desired

# 5. Run
uvicorn app.main:app --reload
```

Open http://localhost:8000 — you'll be redirected to the setup wizard on first run.

---

## Docker

```bash
# Copy and edit env
cp .env.example .env
# Set APP_SECRET_KEY in .env

# Start
docker-compose up -d

# Open http://localhost:8000
```

Data is persisted in `./data/` (SQLite) and `./uploads/` (receipts).

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./expenses.db` | SQLAlchemy DB URL. Use `postgresql://...` for PostgreSQL in production |
| `APP_SECRET_KEY` | `change-me` | Secret for signing session cookies. **Change in production.** |
| `DEBUG` | `false` | Enable FastAPI debug mode |
| `APP_TIMEZONE` | `UTC` | Calendar timezone for scheduled work. Bill due dates are local calendar dates, so set this to your zone (e.g. `Europe/Athens`) or bills can be judged due a day late |
| `ENABLE_SCHEDULER` | `true` | Run the daily auto-pay / reminder job in this process. Each uvicorn worker starts its own scheduler; the job is idempotent, so this only avoids redundant work |
| `TRUST_PROXY_HEADERS` | `false` | Honour `X-Forwarded-For`. Enable **only** behind a proxy that overwrites it, otherwise clients can spoof their IP in logs and rate-limit buckets |
| `RATE_LIMIT_STORAGE_URI` | *(memory)* | e.g. `redis://host:6379`. Without it, login/2FA limits are counted per worker |
| `JWT_SECRET_KEY` | *(uses `APP_SECRET_KEY`)* | Separate signing key for mobile/API tokens |
| `CORS_ALLOWED_ORIGINS` | *(none)* | Space-separated allowed origins |
| `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` | *(none)* | Web-push keys; push is silently disabled without them |

See [`.env.example`](.env.example) for a commented template.

---

## Front-end build

Tailwind is compiled ahead of time; the built stylesheet is committed, so
deploys need no Node toolchain.

```bash
npm install          # once
npm run css          # rebuild static/css/app.css
npm run css:watch    # rebuild on change while developing
```

**Rebuild whenever you add or change Tailwind classes** in `templates/` or
`static/*.js`, and commit the result. `tailwind.config.js` scans both, because
some class names are constructed at runtime in JavaScript (the offline-queue
pill picks its colour by state) and would otherwise be purged.

`tests/test_frontend_wiring.py` guards the build: it fails if the CDN comes
back, if the stylesheet is missing or truncated, or if a class known to be
runtime-constructed has been purged.

---

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                       # full suite
pytest --cov=app             # with coverage
pytest tests/test_scheduler.py -v
```

Each test builds its own throwaway SQLite database, so the suite never touches
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

## What settle-up counts

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
| Auth | `itsdangerous` signed cookies + `passlib[bcrypt]` |
| Frontend | HTMX 1.9 + Alpine.js 3 + TailwindCSS (prebuilt, no CDN) |

---

## Project Structure

```
app/
  main.py           # FastAPI app, mounts, router includes
  config.py         # Settings via pydantic-settings
  database.py       # SQLAlchemy engine + session
  models.py         # All ORM models
  auth.py           # Password hashing, session cookie, auth deps
  seed.py           # Default categories seeder
  services.py       # Business logic: balances, summaries
  bills_service.py  # Bill occurrence generation
  templates.py      # Jinja2Templates + custom filters
  routes/
    auth.py         # Login, setup, invite join, household switch
    dashboard.py    # Main dashboard
    buckets.py      # Bucket CRUD
    transactions.py # Transaction CRUD + expense wizard
    bills.py        # Recurring bills + mark paid/skip
    settings.py     # Profile, household, invite, categories
templates/
  base.html         # Main layout (sidebar + mobile nav)
  auth/             # Login, setup, join invite
  dashboard.html
  buckets/          # list + detail
  transactions/     # new wizard + edit
  bills/            # list
  settings/         # index
  partials/         # HTMX swap fragments
static/
  manifest.json     # PWA manifest
  sw.js             # Service worker
  icons/            # icon-192.png, icon-512.png
uploads/            # Receipt images (gitignored)
```
