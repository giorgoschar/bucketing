# Phase 2d: Insights, Settings and the bill payment method Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give recurring bills their own payment method (backend, shipped first), add the Insights tab (one period, one lens, drill-downs) and the Settings hub with five subscreens to the Tameio React PWA, and wire web push into the `/app/` service worker.

**Architecture:** Backend work is additive FastAPI endpoints under `/api/v1` (rules CRUD, person share, category detail, `monthly_in_out`, 2FA, notification mutes) plus two Alembic migrations. The web app reads everything through 2a's `useCachedQuery` (offline-first, encrypted cache), never queues Settings writes (a `useOnlineAction` wrapper refuses them offline), draws charts as small SVG/CSS components with text equivalents, and switches `vite-plugin-pwa` to `injectManifest` so `web/src/sw.ts` can handle `push` and `notificationclick`.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / Alembic (SQLite and Postgres 18), pytest; React 19, React Router 7, TanStack Query 5, openapi-fetch, Dexie, Vite 8, vite-plugin-pwa 2 (Workbox 7), Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-07-phase-2d-insights-settings-design.md` (the authority). Also read: `docs/superpowers/specs/2026-10-07-phase-2a-plan-home-design.md` (kit and data layer), `docs/redesign/mocks/insights-settings.html`, `docs/redesign/mocks/components.css`, `docs/redesign/backlog.md` ("Default payment method on a bill").

## Global Constraints

- Migration chain is fixed: `b8c9d0e1f2a3` (payment method, `down_revision = "a7b8c9d0e1f2"`) → 2c `c9d0e1f2a3b4` → mutes `d0e1f2a3b4c5` (`down_revision = "c9d0e1f2a3b4"`). `test_single_head` guards it.
- `recurring_bills.payment_method`: `String(16)`, NOT NULL, server default `card`; plain varchar like `transactions.payment_method`, no `ALTER TYPE`.
- "Not sent" means "use the bill's": request defaults for pay, done and the old pay form change from `card` to none; an explicit method wins. Create or edit never rewrites recorded transactions.
- All new endpoints are under `/api/v1`, use `require_api_auth`, are scoped to the caller's household; a `user_id` outside the household is 404.
- Rules: patterns go through `normalise_pattern` (2 to 200 characters). POST is an upsert by folded pattern: 201 new, 200 existing (category re-pointed, `match_count` kept). 400 message: "Enter at least 2 characters and pick a category from this household."
- No chart library. Colours are the token series `--c1`..`--c6`. Every chart has a text equivalent. No hover tooltips. Cash not yet logged is hatched and also labelled "not logged".
- Period values are exactly `this_month` (default), `last_month`, `last_3m`, `last_6m`, `this_year`, `custom` (+ `from`, `to`). Lens `household` (default) or a member's `user_id`. Both live in the URL query, with a `localStorage` fallback wrapped in try/catch.
- Every Settings write is **online only, never queued**; buttons stay enabled; offline or network failure toasts "You're offline. This change needs a connection." and changes nothing. 429 toasts "Too many attempts. Try again in a minute." 400/403/404/409 toast the server `detail` and keep the sheet open with its input.
- Tokens, TOTP secrets and backup codes never touch the query cache, the encrypted store, storage or the URL; sheets that show them ignore backdrop taps; secrets are `user-select: all` and cleared on unmount.
- Limits: display name 1–100 characters; new password at least 12 characters (checked before sending); token name 1–60 characters; pattern at least 2 characters.
- Look: Vault tokens (`web/src/styles/tokens.css`), dark-first with light mode; Sora figures, Plus Jakarta Sans text, JetBrains Mono tables; tabular numerals; safe areas; 44 pt tap targets including chips, toggles and swatches; colour is never the only signal; nothing animates on load; sheets do not slide under `prefers-reduced-motion`; 360–430 px target, a centred 480 px column on wider screens.
- Accessibility: toggles are `role="switch"` with `aria-checked`; chips use `aria-pressed`; the lens is a labelled radio group; password fields carry `autocomplete="current-password"` / `"new-password"`; the code field `autocomplete="one-time-code"` with `inputmode="numeric"`.
- Service worker: scope `/app/`; navigate fallback `/app/index.html`; denylist `/^\/app\/auth\//` and `/^\/api\//`; no runtime caching; the Phase 1 update flow (prompt, `SKIP_WAITING` on a safe moment) keeps working. `static/sw.js` is untouched.
- Settle up does not appear anywhere. Export, household switching, ownership transfer, leaving, member 2FA reset, quiet hours, thresholds and Appearance stay on the old app.
- **Every UI task:** load skills `frontend-design`, `mobile-native`, `apple-design`, and `dataviz` (for charts) before writing UI code.
- Speed mode: each task runs only its own tests. The integration task runs everything.

## Commands

- Backend tests (one task): `.venv/bin/python -m pytest <files> -o addopts="" -p no:cacheprovider`
- Backend full suite: `.venv/bin/python -m pytest -n 8 -o addopts="" -p no:cacheprovider`
- Postgres run of the same files: prefix with `TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t` (drop `-n 8`; the database is shared).
- Format check: `.venv/bin/ruff format --check .` and `.venv/bin/ruff check .`
- Web (from `web/`): `npm test -- <file>`, `npm run typecheck`, `npm run build`, `npm run lint`, `npm run gen:api` (needs `npm ci` once per worktree and the repo `.venv`).

## Review Focus

1. **An item edited by a client that does not send `payment_method`** (2a's Item sheet before F5 lands, the old `/bills` JSON API) must keep its stored method, not fall back to `card`. Pinned by `test_put_without_payment_method_keeps_it` (Task M3).
2. **Disabling 2FA on a password session** leaves a cookie that every ordinary endpoint answers with 403 "TOTP enrollment required" (2FA is mandatory for password sign-in). The security endpoints must stay reachable and the Profile screen must lead straight into Set up. Pinned by `test_disable_keeps_the_caller_signed_in_for_setup` (Task B5) and "after Turn off the Set up sheet opens" (Task F3.2).
3. **Two members with the same first name** in the lens control must get distinguishable labels, and **a lens pointing at a member who left** (old URL, stale `localStorage`) must fall back to Household instead of showing an error. Pinned by `lensOptions` and `resolveLens` tests (Task F1.4).
4. **"Where it went" rows for Uncategorised and Cash not logged:** Uncategorised (`category_id: null`) opens `/insights/category/uncategorised`; the hatched cash row is not tappable and says "not logged". Pinned by the HBarList test (Task F1.2) and the Where-it-went test (Task F2.2).
5. **A custom range typed into the URL with From after To, or a malformed date,** must not reach the server as-is: it falls back to the stored or default period. Pinned by `parsePeriod` tests (Task F1.4).

---

## Interfaces from 2a (read before any web task)

These come from the 2a plan (`docs/superpowers/plans/2026-10-07-phase-2a-plan-home.md`, "Stream A exports"). 2d uses them as they are; **open the merged files on `main` before a web task** and follow any rename there.

```ts
// ui/  (one file each)
<Money amount={number|null} currency? signed? whole? estimated? tone?: 'auto'|'none' nullText? className? />
<Sheet open onClose title closeOnBackdrop?=true footer? initialFocus?>{children}</Sheet>   // backdrop: data-testid="sheet-backdrop"
<ListRow title subtitle? leading? trailing? badges? onClick? muted? ariaLabel? className? />
<Segmented<T> label options={readonly {value,label}[]} value onChange disabled? />          // role="group", buttons with aria-pressed
<ProgressBar value max label tone?: 'ok'|'warn'|'over' thin? />
<Badge tone?: 'neutral'|'pos'|'neg'|'warn'|'acc' icon?>{text}</Badge>
<OfflineBanner updatedAt={ms} />; <EmptyState title body? action? />
<QueryView result={CachedQuery<T>} noDataText showBanner?=true loadingLabel?>{(data: T) => node}</QueryView>
toast(message, opts?); useToast(): { show: typeof toast; dismiss() }
formatMoney(amount, { currency?, signed?, whole? }); formatShortDate(iso); formatTime(ms); addDays(iso, n)   // ui/format.ts
// data/
useCachedQuery<T>(key: QueryKey, fetcher: (signal: AbortSignal) => Promise<T>, opts?: { enabled?: boolean }): CachedQuery<T>
interface CachedQuery<T> { data: T | undefined; dataUpdatedAt: number; fromCache: boolean; isLoading: boolean
  isError: boolean; offline: boolean; stale: boolean; noData: boolean; refetch(): void }
keys (data/keys.ts): keys.plan.month(month), keys.plan.budgets(), keys.plan.pace(), keys.insights.all,
  keys.insights.categoriesVsUsual(month), keys.household(), keys.buckets(), keys.categories(), keys.categoryRules(); affects.*
  // The household id is NOT in the query keys; it is in the device-cache key (cacheKeyFor).
unwrap(p); class ApiError(status, detail); detailOf(error, status?): string          // data/http.ts
isOnline(); useOnline()                                                               // data/online.ts
useHousehold(); useBuckets(); useCategories(); memberName(m)                          // data/reads.ts (narrowed)
Household { id; name; default_currency; members: Member[] }; Member; Bucket; Category { id; name; icon; color }   // data/types.ts
usePlanMonth(month); useCategoriesVsUsual(month); useBudgets()                       // features/plan/hooks.ts
fakeApi(routes) (test/fakeApi.ts) — typed fake fetch; 2d tests may use it instead of a raw fetch spy
```

`useAction` (2a's queued writes) is **not** used by 2d Settings: their writes are never queued. 2d adds, in F1 tasks: `Chips`, `Toggle`, charts, `data/rawJson.ts`, `data/onlineAction.ts`, a 2d section in `data/keys.ts`, and the extra `Category` fields Settings needs (`is_default`, `system_key`, `locked`, `expense_count`, `rule_count`) in `data/types.ts` + `data/reads.ts`.

## Streams, dependencies and file ownership

| Stream | Tasks | Needs | Owns (only this stream edits these) |
|---|---|---|---|
| **M** | M1–M3 | nothing; **first thing in Phase 2, ships alone** | `alembic/versions/b8c9d0e1f2a3_*`, `app/models.py` (M part), `app/services/bills.py`, `app/scheduler.py`, `app/api/bills.py`, `app/api/recurring.py`, `app/api/planning_models.py`, `app/services/planning.py`, `app/validators.py`, `app/routes/bills.py`, `templates/bills/list.html`, `tests/test_bill_payment_method*.py`, `tests/test_planning_upgrade.py` |
| **B** | B1–B6 | nothing (rebase on `main` after M merges, before its last `gen:api`) | `app/api/category_rules.py`, `app/api/security.py`, `app/services/totp.py`, `app/api/insights.py`, `app/services/insights.py`, `app/api/settings.py`, `app/api_auth.py`, `app/routes/settings.py`, `app/web_app.py`, their tests |
| **N** | N1–N2 | **2c's B1 merged** (`c9d0e1f2a3b4` on `main`); M and B merged | `alembic/versions/d0e1f2a3b4c5_*`, `app/models.py` (N part), `app/services/notifications.py`, `app/services/notification_prefs.py`, `app/api/notification_prefs.py` |
| **F1** | F1.1–F1.7 | 2a stream A merged; F1.5–F1.7 also need B merged (typed endpoints) | `web/src/ui/Chips.tsx`, `Toggle.tsx`, `controls.css`, `BackHeader.tsx`, `ui/charts/*`, `data/keys.ts` (2d section), `data/rawJson.ts`, `data/onlineAction.ts`, the extra `Category` fields in 2a's `data/types.ts` + `data/reads.ts`, `features/insights/{period,lens,types,hooks,format}.ts`, `features/settings/{hooks,palette}.ts`, `pwa/pushClient.ts`, `router.tsx`, `screens/Insights.tsx`, the stub screens it creates |
| **F2** | F2.1–F2.4 | F1, B | `features/insights/*` except the F1 files above |
| **F3** | F3.1–F3.3 | F1, B | `features/settings/{Settings,Profile,Household}.tsx`, `features/settings/{profileHooks,householdHooks}.ts`, `features/settings/settings.css`, `shell/TopBar.tsx`, `session/notice.ts`, `session/SignIn.tsx` |
| **F4** | F4.1–F4.4 | F1, B; F4.4's alert toggles need N | `features/settings/{Categories,Automations,Notifications}.tsx`, `features/settings/{categoryHooks,tokenHooks,notificationHooks}.ts`, `src/sw.ts`, `pwa/appRoute.ts`, `pwa/pushPayload.ts`, `vite.config.ts`, `tsconfig.app.json`, `tsconfig.sw.json`, `tsconfig.json`, `package.json` |
| **F5** | F5.1–F5.2 | M merged, 2a streams C and D merged, F1.5 (for `useOnlineAction`) | 2a's `features/plan/items/ItemSheet.tsx`, `features/plan/EntrySheet.tsx`, `features/plan/Budgets.tsx` and their tests |
| **I** | I1 | everything | nothing new |

Shared-by-design (merge, never parallel): `app/api/__init__.py` gets one `include_router` line from B1, B5 and N2 (sequential: N runs after B). `web/src/api/openapi.json` and `web/src/api/schema.d.ts` are generated: each stream regenerates them as its last step after rebasing on `main`; on a merge conflict, take either side and rerun `npm run gen:api`.

**Merge order:** M (before 2c's migration) → B (B1 may merge alone, early, so 2b can regenerate its types) → F1 → F2 / F3 / F4 in any order → F5; N after 2c's B1 → I1.

---

## Stream M: payment method on a bill (ships first and alone)

### Task M1: Migration `b8c9d0e1f2a3` and the model column

**Stream:** M · **Depends on:** nothing

**Files:**
- Create: `alembic/versions/b8c9d0e1f2a3_bill_payment_method.py`
- Modify: `app/models.py` (add `default_payment_method()` after `ItemDirection`; add the column on `RecurringBill` after `rule_interval_weeks`)
- Test: `tests/test_planning_upgrade.py` (append), `tests/test_migrations.py` (unchanged, rerun)

**Interfaces:**
- Produces: `app.models.default_payment_method(direction: str | None) -> str` (`"transfer"` for `"in"`, else `"card"`); `RecurringBill.payment_method: str` (NOT NULL; ORM default by direction, server default `card`).

- [ ] **Step 1: Write the failing upgrade test**

Append to `tests/test_planning_upgrade.py`:

```python
# ---------------------------------------------------------------------------
# 2d M: recurring_bills.payment_method, backfilled from history
# ---------------------------------------------------------------------------

PLANNING_REVISION = "a7b8c9d0e1f2"
BILL_PM_REVISION = "b8c9d0e1f2a3"


def _paid_occurrence(conn, ids, bill_key, *, due, method, deleted=False):
    """A paid entry of ``bill_key`` with its expense. a7b8c9d0e1f2 links the two."""
    from datetime import datetime, time

    txn = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement, payment_method, deleted_at) VALUES (:i, :b, :h, 38.90, "
            "'EUR', 1, 'expense', :u, :d, false, false, :m, :x)"
        ),
        {
            "i": txn,
            "b": ids["daily"],
            "h": ids["hh"],
            "u": ids["user"],
            "d": due,
            "m": method,
            "x": datetime.combine(due, time()) if deleted else None,
        },
    )
    conn.execute(
        text(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status, transaction_id) "
            "VALUES (:i, :b, :d, 'paid', :t)"
        ),
        {"i": str(uuid.uuid4()), "b": ids[bill_key], "d": due, "t": txn},
    )


def _item(conn, ids, name, *, direction):
    """A recurring item written at a7b8c9d0e1f2 (direction exists from there on)."""
    item = str(uuid.uuid4())
    conn.execute(
        text(
            "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
            "frequency, interval_months, start_date, is_active, is_auto_pay, direction) "
            "VALUES (:i, :h, :b, :n, 100, 'EUR', 'monthly', 1, :s, true, false, :d)"
        ),
        {
            "i": item,
            "h": ids["hh"],
            "b": None if direction == "in" else ids["daily"],
            "n": name,
            "s": local_today() - timedelta(days=60),
            "d": direction,
        },
    )
    return item


def _linked(conn, ids, item, *, when, method, kind="expense", created_at=None):
    """A transaction linked to ``item`` the way the new app links it (recurring_bill_id)."""
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement, payment_method, recurring_bill_id, created_at) "
            "VALUES (:i, :b, :h, 100, 'EUR', 1, :k, :u, :d, false, false, :m, :r, :c)"
        ),
        {
            "i": str(uuid.uuid4()),
            "b": None if kind == "income" else ids["daily"],
            "h": ids["hh"],
            "k": kind,
            "u": ids["user"],
            "d": when,
            "m": method,
            "r": item,
            "c": created_at,
        },
    )


def _methods(db_url) -> dict:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            return dict(conn.execute(text("SELECT id, payment_method FROM recurring_bills")).all())
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [PROD_REVISION, PRE_PHASE1_REVISION])
def test_bill_payment_method_is_backfilled_from_history(tmp_path, revision):
    from datetime import datetime

    from sqlalchemy import inspect

    db_url = _db_url(tmp_path, "pm.db")
    assert _alembic(["upgrade", revision], db_url).returncode == 0
    today = local_today()
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
        # Cosmote: card 40 days ago (seeded), transfer 25 days ago, and a newer
        # cash payment that was deleted. The latest *active* one is the transfer.
        _paid_occurrence(conn, ids, "bill", due=today - timedelta(days=25), method="transfer")
        _paid_occurrence(
            conn, ids, "bill", due=today - timedelta(days=5), method="cash", deleted=True
        )
    engine.dispose()
    up = _alembic(["upgrade", PLANNING_REVISION], db_url)
    assert up.returncode == 0, up.stderr

    engine = create_engine(db_url)
    with engine.begin() as conn:
        # Income items exist from a7b8c9d0e1f2 on. One received "by card" by mistake
        # still becomes transfer: receive_occurrence always recorded transfer.
        ids["salary"] = _item(conn, ids, "Salary", direction="in")
        _linked(conn, ids, ids["salary"], when=today - timedelta(days=3), method="card",
                kind="income")
        # Two payments on one day: the one with a created_at is the newer (rows
        # without one predate the column), whichever way the dialect sorts NULLs.
        ids["rent"] = _item(conn, ids, "Rent", direction="out")
        same_day = today - timedelta(days=2)
        _linked(conn, ids, ids["rent"], when=same_day, method="other")
        _linked(conn, ids, ids["rent"], when=same_day, method="apple_pay",
                created_at=datetime(2026, 1, 1, 9, 0))
    engine.dispose()

    up = _alembic(["upgrade", BILL_PM_REVISION], db_url)
    assert up.returncode == 0, up.stderr
    expected = {
        ids["bill"]: "transfer",  # latest active linked payment
        ids["gym"]: "card",  # claim-only: no linked transaction
        ids["paused"]: "card",  # nothing paid
        ids["salary"]: "transfer",  # in items
        ids["rent"]: "apple_pay",  # created_at breaks the same-day tie
    }
    assert _methods(db_url) == expected

    # Round trip: down drops the column, up recomputes the same values.
    down = _alembic(["downgrade", PLANNING_REVISION], db_url)
    assert down.returncode == 0, down.stderr
    engine = create_engine(db_url)
    assert "payment_method" not in {
        c["name"] for c in inspect(engine).get_columns("recurring_bills")
    }
    engine.dispose()
    up = _alembic(["upgrade", BILL_PM_REVISION], db_url)
    assert up.returncode == 0, up.stderr
    assert _methods(db_url) == expected
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_planning_upgrade.py -k payment_method -o addopts="" -p no:cacheprovider`
Expected: FAIL — alembic exits non-zero with "Can't locate revision identified by 'b8c9d0e1f2a3'".

- [ ] **Step 3: Write the migration**

Create `alembic/versions/b8c9d0e1f2a3_bill_payment_method.py`:

```python
"""recurring_bills.payment_method: how a recurring item is paid by default

Without it every auto-paid and one-tap payment was recorded as "card"
(2d spec §7.0). Plain VARCHAR(16) like transactions.payment_method,
validated by app.models.PaymentMethod in Python, so adding a method never
needs ALTER TYPE.

Backfill, in this migration:
- in items get 'transfer' (what receive_occurrence always recorded);
- other items get the method of their most recent active linked
  transaction (recurring_bill_id), by transaction_date, then created_at
  (rows without one count as older), then id;
- items with none keep the 'card' default.

Additive: the old app ignores the column.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-07 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None

BACKFILL_IN = "UPDATE recurring_bills SET payment_method = 'transfer' WHERE direction = 'in'"
# (created_at IS NULL) sorts false before true on both dialects, so rows with a
# created_at come first whatever the dialect does with NULLs in DESC.
BACKFILL_OUT = (
    "UPDATE recurring_bills SET payment_method = ("
    "  SELECT t.payment_method FROM transactions t"
    "  WHERE t.recurring_bill_id = recurring_bills.id AND t.deleted_at IS NULL"
    "  ORDER BY t.transaction_date DESC, (t.created_at IS NULL), t.created_at DESC, t.id DESC"
    "  LIMIT 1"
    ") WHERE direction <> 'in' AND EXISTS ("
    "  SELECT 1 FROM transactions t"
    "  WHERE t.recurring_bill_id = recurring_bills.id AND t.deleted_at IS NULL"
    ")"
)


def upgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.add_column(
            sa.Column("payment_method", sa.String(16), nullable=False, server_default="card")
        )
    op.execute(BACKFILL_IN)
    op.execute(BACKFILL_OUT)


def downgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.drop_column("payment_method")
```

- [ ] **Step 4: Add the model column**

In `app/models.py`, after `class ItemDirection` add:

```python
def default_payment_method(direction: str | None) -> str:
    """How an item's payments are recorded when nobody picks a method (2d §7.0):
    transfer for income (what Mark received always recorded), card otherwise."""
    if direction == ItemDirection.in_.value:
        return PaymentMethod.transfer.value
    return PaymentMethod.card.value


def _item_payment_method_default(context) -> str:
    return default_payment_method(context.get_current_parameters().get("direction"))
```

In `class RecurringBill`, after `rule_interval_weeks`:

```python
    # How a payment of this item is recorded when the payer picks none: one-tap
    # Pay, auto-pay, Mark received (2d §7.0). Plain VARCHAR like PaymentMethod.
    payment_method = Column(
        String(16),
        default=_item_payment_method_default,
        server_default=PaymentMethod.card.value,
        nullable=False,
    )
```

(M2's `test_model_default_follows_direction` exercises this default. If it fails because `direction` is missing from `get_current_parameters()`, replace the context default with a `before_insert` mapper event on `RecurringBill` that sets `payment_method = default_payment_method(target.direction)` when it is `None`.)

- [ ] **Step 5: Run the migration tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_planning_upgrade.py tests/test_migrations.py -o addopts="" -p no:cacheprovider`
Expected: PASS (including `test_single_head`, `test_schema_matches_models`, `test_downgrade_then_upgrade_round_trips` and both `test_bill_payment_method_is_backfilled_from_history[...]`).

Then on Postgres: `TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t .venv/bin/python -m pytest tests/test_planning_upgrade.py tests/test_migrations.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/b8c9d0e1f2a3_bill_payment_method.py app/models.py tests/test_planning_upgrade.py
git commit -m "feat(bills): recurring_bills.payment_method with a history backfill (b8c9d0e1f2a3)"
```

### Task M2: Services and auto-pay use the item's method

**Stream:** M · **Depends on:** M1

**Files:**
- Modify: `app/services/bills.py` (`pay_occurrence`, `receive_occurrence`, `complete_entry`; `settle_occurrence` already forwards `**kwargs`)
- Modify: `app/scheduler.py` (`_auto_pay_due_bills`: the `pending` dict and the `settle_occurrence` call)
- Test: `tests/test_bill_payment_method.py` (create)

**Interfaces:**
- Consumes: `RecurringBill.payment_method`, `default_payment_method` (M1).
- Produces: `pay_occurrence(..., payment_method: str | None = None)`, `receive_occurrence(..., payment_method: str | None = None)`, `complete_entry(..., payment_method: str | None = None)`. `None` means "the item's".

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bill_payment_method.py`:

```python
"""2d §7.0: a recurring item's payment method is what Pay, Mark received and
auto-pay record when nobody picks one; an explicit method wins."""

from datetime import timedelta

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, RecurringBill, Transaction
from app.services.bills import complete_entry, pay_occurrence


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _income_item(db, hh, *, method=None):
    item = RecurringBill(
        household_id=hh.household_id,
        name="Salary",
        amount=1500,
        currency="EUR",
        start_date=local_today(),
        direction="in",
        rule_kind="monthly_interval",
    )
    if method:
        item.payment_method = method
    db.add(item)
    db.flush()
    occ = BillOccurrence(bill_id=item.id, due_date=local_today(), status=OccurrenceStatus.unpaid)
    db.add(occ)
    db.commit()
    return item, occ


def test_model_default_follows_direction(db, make_household, make_bill):
    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, occurrence=False)
    item, _ = _income_item(db, hh)
    assert (bill.payment_method, item.payment_method) == ("card", "transfer")


def test_pay_uses_the_bills_method_unless_one_is_sent(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    bill.payment_method = "transfer"
    db.commit()
    txn = pay_occurrence(db, occ, amount=45, paid_by=hh.user_id, paid_on=utcnow_naive())
    assert txn.payment_method == "transfer"

    occ2 = BillOccurrence(
        bill_id=bill.id, due_date=local_today() + timedelta(days=31), status=OccurrenceStatus.unpaid
    )
    db.add(occ2)
    db.flush()
    txn2 = pay_occurrence(
        db, occ2, amount=45, paid_by=hh.user_id, paid_on=utcnow_naive(), payment_method="cash"
    )
    assert txn2.payment_method == "cash"


def test_complete_entry_out_uses_the_items_method(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, None, auto_pay=False)  # a Fixed cost
    bill.payment_method = "apple_pay"
    db.commit()
    txn = complete_entry(db, occ, user_id=hh.user_id)
    assert txn.payment_method == "apple_pay"


def test_complete_entry_explicit_method_wins(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    bill.payment_method = "transfer"
    db.commit()
    txn = complete_entry(db, occ, user_id=hh.user_id, payment_method="card")
    assert txn.payment_method == "card"


def test_mark_received_records_the_items_method(db, make_household):
    hh = make_household()
    item, occ = _income_item(db, hh)
    assert complete_entry(db, occ, user_id=hh.user_id).payment_method == "transfer"

    other, occ2 = _income_item(db, hh, method="cash")
    occ2.due_date = local_today() + timedelta(days=1)
    db.commit()
    assert complete_entry(db, occ2, user_id=hh.user_id).payment_method == "cash"


def test_mark_received_explicit_method_wins(db, make_household):
    hh = make_household()
    _, occ = _income_item(db, hh)
    txn = complete_entry(db, occ, user_id=hh.user_id, payment_method="other")
    assert txn.payment_method == "other"


def test_auto_pay_records_the_bills_method(db, make_household, make_bill, run_job):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=50, due=local_today() - timedelta(1))
    bill.payment_method = "transfer"
    db.commit()
    run_job()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.paid
    assert db.get(Transaction, occ.transaction_id).payment_method == "transfer"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bill_payment_method.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — `test_pay_uses_the_bills_method...` gets `card`; `test_mark_received_records_the_items_method` gets `transfer` for the cash item; `complete_entry() got an unexpected keyword` is not raised (it exists) but `test_complete_entry_out_uses_the_items_method` gets `card`; auto-pay gets `card`. `test_model_default_follows_direction` passes already (M1).

- [ ] **Step 3: Implement**

In `app/services/bills.py`:

1. `pay_occurrence` signature: replace `payment_method: str = "card",` with `payment_method: str | None = None,`. Add to its docstring: "``payment_method`` None records the item's own method (2d §7.0)." In the `Transaction(...)` call replace `payment_method=payment_method,` with:

```python
        payment_method=payment_method or bill.payment_method or PaymentMethod.card.value,
```

2. `receive_occurrence` signature: add `payment_method: str | None = None,` after `fallback_user_id`. In its `Transaction(...)` replace `payment_method=PaymentMethod.transfer.value,` with:

```python
        payment_method=payment_method or bill.payment_method or PaymentMethod.transfer.value,
```

Docstring: "The method is ``payment_method``, else the item's (transfer unless changed)."

3. `complete_entry` signature: `payment_method: str | None = None,`. Pass it to both branches:

```python
    if bill.direction == ItemDirection.in_.value:
        txn = receive_occurrence(
            db,
            occ,
            amount=value,
            received_by=person,
            paid_on=paid_on,
            fallback_user_id=user_id,
            payment_method=payment_method,
        )
```

(the `pay_occurrence` call already passes `payment_method=payment_method`). Docstring: "``payment_method`` None uses the item's."

4. `settle_occurrence` is unchanged: it forwards `**kwargs` to `pay_occurrence`.

In `app/scheduler.py` `_auto_pay_due_bills`, add to the `pending.append({...})` dict:

```python
                "payment_method": bill.payment_method,
```

and to the `bills_service.settle_occurrence(...)` call:

```python
            payment_method=item["payment_method"],
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bill_payment_method.py tests/test_planning_auto_pay.py tests/test_payment_method.py tests/test_planning_lifecycle.py tests/test_planning_income.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/bills.py app/scheduler.py tests/test_bill_payment_method.py
git commit -m "feat(bills): Pay, Mark received and auto-pay record the item's payment method"
```

### Task M3: The API, the old pay form and the generated types

**Stream:** M · **Depends on:** M2

**Files:**
- Modify: `app/validators.py` (add `payment_method_or_400`)
- Modify: `app/api/recurring.py` (`RecurringItemIn`, `EntryDoneIn`, `_apply`, `_item_out`, `entry_done`)
- Modify: `app/api/bills.py` (`BillIn`, `PayOccurrenceIn`, `_bill_dict`, `create_bill`, `update_bill`, `pay_occurrence`)
- Modify: `app/api/planning_models.py` (`EntryOut.payment_method`, `RecurringItemOut.payment_method`)
- Modify: `app/services/planning.py` (`Entry.payment_method`, `_entry`)
- Modify: `app/routes/bills.py` (`mark_paid`: blank form field means the bill's)
- Modify: `templates/bills/list.html` (pay modal "Paid with" select: a first "Bill's default" option)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/schema.d.ts`
- Test: `tests/test_bill_payment_method_api.py` (create)

**Interfaces:**
- Consumes: M2's service signatures.
- Produces (wire): `RecurringItemIn.payment_method?: string | null`, `RecurringItemOut.payment_method: string`, `EntryOut.payment_method: string` (the item's method), `EntryDoneIn.payment_method?: string | null`, `/bills` dicts carry `payment_method`, `PayOccurrenceIn.payment_method?: string | null`. Invalid → 400 with `parse_payment_method`'s message. On create, absent → `transfer` for in items, `card` for out. **On update, absent → unchanged** (a direction change without a method resets it to the new direction's default).
- Produces (Python): `app.validators.payment_method_or_400(value) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bill_payment_method_api.py`:

```python
"""2d §7.0 over the wire: /recurring and /bills take, keep and return an item's
payment method; Pay and Done without one use it; the old pay form too."""

from datetime import timedelta

from app.core.clock import local_today
from app.models import BillOccurrence, RecurringBill, Transaction
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring"


def _out_item(**over):
    body = {
        "name": "Rent",
        "direction": "out",
        "amount": "800",
        "rule_kind": "monthly_interval",
        "interval_months": 1,
        "start_date": local_today().isoformat(),
    }
    body.update(over)
    return body


def _in_item(**over):
    return _out_item(name="Salary", direction="in", amount="1500", **over)


def _today_entry(client, headers, item_id):
    r = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": local_today().isoformat(), "to": (local_today() + timedelta(40)).isoformat()},
    )
    assert r.status_code == 200, r.text
    return next(e for e in r.json() if e["item_id"] == item_id)


def test_create_defaults_by_direction(client, api):  # noqa: F811
    headers, _ = api
    out = client.post(URL, headers=headers, json=_out_item()).json()
    inc = client.post(URL, headers=headers, json=_in_item()).json()
    assert (out["payment_method"], inc["payment_method"]) == ("card", "transfer")


def test_create_with_a_method_and_entries_carry_it(client, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_out_item(payment_method="transfer")).json()
    assert item["payment_method"] == "transfer"
    assert item["next_entry"]["payment_method"] == "transfer"
    assert _today_entry(client, headers, item["id"])["payment_method"] == "transfer"
    listed = {i["id"]: i for i in client.get(URL, headers=headers).json()}
    assert listed[item["id"]]["payment_method"] == "transfer"


def test_put_without_payment_method_keeps_it(client, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_out_item(payment_method="transfer")).json()
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_out_item(name="Rent flat"))
    assert r.status_code == 200, r.text
    assert r.json()["payment_method"] == "transfer"
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_out_item(payment_method="cash"))
    assert r.json()["payment_method"] == "cash"


def test_invalid_method_is_400_everywhere(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post(URL, headers=headers, json=_out_item(payment_method="bitcoin"))
    assert r.status_code == 400 and "Unknown payment method" in r.json()["detail"]
    item = client.post(URL, headers=headers, json=_out_item()).json()
    entry = _today_entry(client, headers, item["id"])
    r = client.post(
        f"{URL}/entries/{entry['id']}/done", headers=headers, json={"payment_method": "bitcoin"}
    )
    assert r.status_code == 400
    r = client.post(
        "/api/v1/bills",
        headers=headers,
        json={"name": "X", "amount": "5", "start_date": local_today().isoformat(),
              "payment_method": "nope"},
    )
    assert r.status_code == 400


def test_done_without_method_uses_the_items(client, db, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_out_item(payment_method="transfer")).json()
    entry = _today_entry(client, headers, item["id"])
    r = client.post(f"{URL}/entries/{entry['id']}/done", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert db.get(Transaction, r.json()["transaction_id"]).payment_method == "transfer"


def test_done_explicit_method_wins(client, db, api):  # noqa: F811
    headers, _ = api
    item = client.post(URL, headers=headers, json=_in_item()).json()
    entry = _today_entry(client, headers, item["id"])
    r = client.post(
        f"{URL}/entries/{entry['id']}/done", headers=headers, json={"payment_method": "cash"}
    )
    assert db.get(Transaction, r.json()["transaction_id"]).payment_method == "cash"


def test_bills_api_creates_updates_returns_and_pays_with_it(client, db, api):  # noqa: F811
    headers, hh = api
    body = {
        "name": "Cosmote",
        "amount": "38.90",
        "bucket_id": hh.bucket_id,
        "start_date": local_today().isoformat(),
        "payment_method": "transfer",
    }
    bill = client.post("/api/v1/bills", headers=headers, json=body).json()
    assert bill["payment_method"] == "transfer"
    body.pop("payment_method")
    r = client.put(f"/api/v1/bills/{bill['id']}", headers=headers, json=body)
    assert r.json()["payment_method"] == "transfer"  # absent: unchanged
    occ = db.query(BillOccurrence).filter_by(bill_id=bill["id"], due_date=local_today()).one()
    r = client.post(f"/api/v1/bills/occurrences/{occ.id}/pay", headers=headers, json={})
    assert r.status_code == 200, r.text
    assert db.get(Transaction, r.json()["transaction_id"]).payment_method == "transfer"


def test_bills_api_create_without_method_is_card(client, api):  # noqa: F811
    headers, hh = api
    bill = client.post(
        "/api/v1/bills",
        headers=headers,
        json={"name": "Gym", "amount": "25", "start_date": local_today().isoformat()},
    ).json()
    assert bill["payment_method"] == "card"


def test_old_pay_form_blank_method_uses_the_bills(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, authed.bucket_id, auto_pay=False)
    db.get(RecurringBill, bill.id).payment_method = "transfer"
    db.commit()
    r = client.post(
        f"/bills/{bill.id}/occurrences/{occ.id}/pay",
        headers=authed.headers,
        data={"amount": "", "paid_by": "", "payment_method": ""},
    )
    assert r.status_code == 302
    db.expire_all()
    txn_id = db.get(BillOccurrence, occ.id).transaction_id
    assert db.get(Transaction, txn_id).payment_method == "transfer"


def test_old_pay_form_offers_the_bills_default(client, authed, make_bill):
    make_bill(authed.household_id, authed.bucket_id, auto_pay=False)
    page = client.get("/bills").text
    assert '<option value="" selected>Bill\'s default</option>' in page
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bill_payment_method_api.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — `KeyError: 'payment_method'` on responses; invalid method gives 422 for done.

- [ ] **Step 3: Add the validator helper**

In `app/validators.py` (after `parse_amount`):

```python
def payment_method_or_400(value) -> str | None:
    """A sent payment method, normalised; None when not sent (blank or null),
    meaning "the item's own" (2d §7.0). An unknown method is a 400 with
    parse_payment_method's message. parse_payment_method itself keeps mapping
    blank to card: transactions rely on that."""
    from app.schemas import parse_payment_method

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return parse_payment_method(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
```

- [ ] **Step 4: Planning entry and response models**

In `app/services/planning.py`: import `default_payment_method` from `app.models`; add the last field of `Entry`:

```python
    payment_method: str  # the item's: what Pay / Mark received records by default
```

and in `_entry(...)`'s `Entry(...)` call:

```python
        payment_method=bill.payment_method or default_payment_method(bill.direction),
```

In `app/api/planning_models.py` add `payment_method: str` as the last field of `EntryOut`, and `payment_method: str` after `payer_mode` in `RecurringItemOut`.

- [ ] **Step 5: `/recurring`**

In `app/api/recurring.py`:
- import `payment_method_or_400` from `app.validators`, `default_payment_method` from `app.models`; drop the now-unused `PaymentMethod` and `parse_payment_method` imports if nothing else uses them.
- `RecurringItemIn`: add `payment_method: str | None = None  # None: create → by direction; update → unchanged`.
- `EntryDoneIn`: replace the field and its validator with `payment_method: str | None = None  # None: the item's`.
- In `_apply`, right after `income = direction == ItemDirection.in_.value`:

```python
    method = payment_method_or_400(body.payment_method)
    if method is not None:
        item.payment_method = method
    elif not item.id or direction != item.direction:
        # New item, or it changed direction: that direction's default.
        item.payment_method = default_payment_method(direction)
```

(it must run before `item.direction = direction`).
- `_item_out`: add `payment_method=item.payment_method,`.
- `entry_done`: pass `payment_method=payment_method_or_400(body.payment_method),`.

- [ ] **Step 6: `/bills`**

In `app/api/bills.py`:
- import `payment_method_or_400` from `app.validators`, `PaymentMethod` from `app.models`; drop `parse_payment_method` from the `app.schemas` import.
- `BillIn`: add `payment_method: str | None = None  # None: card on create, unchanged on update`.
- `PayOccurrenceIn`: replace the field and validator with `payment_method: str | None = None  # None: the bill's`.
- `_bill_dict`: add `"payment_method": b.payment_method,` after `"payer_mode"`.
- `create_bill`: first line after `user, hh_id = auth`: `method = payment_method_or_400(body.payment_method)`; in `RecurringBill(...)`: `payment_method=method or PaymentMethod.card.value,`.
- `update_bill`: after `_validate_bill_refs`: `method = payment_method_or_400(body.payment_method)`; after `bill.is_auto_pay = body.is_auto_pay`: 

```python
    if method is not None:
        bill.payment_method = method
```

- `pay_occurrence` route: before the `try`, `method = payment_method_or_400(body.payment_method)`; pass `payment_method=method,` to `settle_occurrence`.

- [ ] **Step 7: The old pay form**

In `app/routes/bills.py` `mark_paid`: change `payment_method: str = Form("card"),` to `payment_method: str = Form(""),` and replace the `pm = parse_payment_method(payment_method)` block with:

```python
    # Blank = the bill's own method (2d §7.0).
    try:
        pm = parse_payment_method(payment_method) if payment_method.strip() else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
```

In `templates/bills/list.html`, the pay modal's `<select name="payment_method">` becomes:

```html
        <select name="payment_method" class="w-full px-3.5 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 focus:border-primary-500 outline-none text-sm">
          <option value="" selected>Bill's default</option>
          {% for pm in payment_methods %}
          <option value="{{ pm.value }}">{{ pm.value | replace('_', ' ') | title }}</option>
          {% endfor %}
        </select>
```

The old bill create/edit form is unchanged (spec §7.0).

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bill_payment_method_api.py tests/test_bill_payment_method.py tests/test_api_recurring.py tests/test_bills.py tests/test_planning_old_app.py tests/test_api_plan.py tests/test_payment_method.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 9: Regenerate the web types and check they compile**

```bash
cd web && npm ci && npm run gen:api && npm run typecheck && cd ..
```
Expected: `schema.d.ts` gains `payment_method` on `EntryOut`, `RecurringItemOut`, `RecurringItemIn`, `EntryDoneIn`; typecheck passes.

- [ ] **Step 10: Format and commit**

```bash
.venv/bin/ruff format app tests alembic && .venv/bin/ruff check app tests alembic
git add app/validators.py app/api/recurring.py app/api/bills.py app/api/planning_models.py app/services/planning.py app/routes/bills.py templates/bills/list.html web/src/api/openapi.json web/src/api/schema.d.ts tests/test_bill_payment_method_api.py
git commit -m "feat(api): recurring items and bills take and return payment_method; Pay and Done default to it"
```

---
## Stream B: endpoints (no migration)

All B tasks run in one worktree, in order. **B1 may merge to `main` on its own as soon as it is green**, so 2b can regenerate its types and turn on its "Remember merchant" toggle. Before the last `gen:api` of any B task that follows an M merge, rebase on `main`.

### Task B1: Category rules API (`/settings/category-rules`) and category counts

**Stream:** B · **Depends on:** nothing · **Consumed by:** 2b (GET list, POST upsert), F4.1

**Files:**
- Create: `app/api/category_rules.py`
- Modify: `app/api/__init__.py` (import `category_rules`; `router.include_router(category_rules.router)` after `settings.router`)
- Modify: `app/api/settings.py` (`list_categories` adds `expense_count`, `rule_count`; `delete_category` deletes the category's rules explicitly)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/schema.d.ts`
- Test: `tests/test_api_category_rules.py` (create)

**Interfaces:**
- Produces (wire, binding for 2b):
  - `GET /api/v1/settings/category-rules` → `CategoryRuleOut[]` = `[{id, pattern, category_id, match_count, created_at}]`, most used first.
  - `POST` `{pattern, category_id}` → `CategoryRuleOut`, 201 new / 200 existing folded pattern (category re-pointed, `match_count` kept); 400 `"Enter at least 2 characters and pick a category from this household."`.
  - `PUT /{id}` same body → `CategoryRuleOut`; 400; 404 `"Rule not found"`; 409 `"Another rule already uses this pattern."`.
  - `DELETE /{id}` → 204; 404.
  - `GET /api/v1/settings/categories` rows gain `expense_count: int` (active expenses) and `rule_count: int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_category_rules.py`:

```python
"""2d §7.4: /api/v1/settings/category-rules. POST is an upsert by folded
pattern (201 new, 200 existing), so 2b can queue it."""

from datetime import date
from decimal import Decimal

from app.models import Category, CategoryRule, Transaction, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/settings/category-rules"
INVALID = "Enter at least 2 characters and pick a category from this household."


def _category(db, household_id, name="Groceries"):
    cat = Category(household_id=household_id, name=name)
    db.add(cat)
    db.commit()
    return cat.id


def test_post_creates_then_upserts_by_folded_pattern(client, db, api):  # noqa: F811
    headers, hh = api
    groceries = _category(db, hh.household_id)
    coffee = _category(db, hh.household_id, "Coffee")
    r = client.post(URL, headers=headers, json={"pattern": "  ΣΚΛΑΒΕΝΙΤΗΣ ", "category_id": groceries})
    assert r.status_code == 201, r.text
    rule = r.json()
    assert (rule["pattern"], rule["category_id"], rule["match_count"]) == (
        "σκλαβενιτησ",
        groceries,
        0,
    )
    db.query(CategoryRule).filter_by(id=rule["id"]).update({"match_count": 48})
    db.commit()

    r = client.post(URL, headers=headers, json={"pattern": "Σκλαβενίτης", "category_id": coffee})
    assert r.status_code == 200, r.text
    assert (r.json()["id"], r.json()["category_id"], r.json()["match_count"]) == (
        rule["id"],
        coffee,
        48,
    )
    assert db.query(CategoryRule).count() == 1


def test_post_rejects_short_patterns_and_foreign_categories(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    mine = _category(db, hh.household_id)
    other = make_household(name="Other", username="other")
    theirs = _category(db, other.household_id)
    for body in (
        {"pattern": "a", "category_id": mine},
        {"pattern": "  á  ", "category_id": mine},
        {"pattern": "lidl", "category_id": theirs},
        {"pattern": "lidl", "category_id": "nope"},
    ):
        r = client.post(URL, headers=headers, json=body)
        assert r.status_code == 400, body
        assert r.json()["detail"] == INVALID
    assert db.query(CategoryRule).count() == 0


def test_list_is_most_used_first_with_every_field(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id)
    for pattern, count in (("lidl", 3), ("ab", 9)):
        db.add(CategoryRule(household_id=hh.household_id, pattern=pattern, category_id=cat,
                            match_count=count))
    db.commit()
    rows = client.get(URL, headers=headers).json()
    assert [r["pattern"] for r in rows] == ["ab", "lidl"]
    assert set(rows[0]) == {"id", "pattern", "category_id", "match_count", "created_at"}


def test_put_repoints_and_keeps_match_count(client, db, api):  # noqa: F811
    headers, hh = api
    a, b = _category(db, hh.household_id), _category(db, hh.household_id, "B")
    rule = client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": a}).json()
    db.query(CategoryRule).filter_by(id=rule["id"]).update({"match_count": 7})
    db.commit()
    r = client.put(f"{URL}/{rule['id']}", headers=headers,
                   json={"pattern": "LIDL Express", "category_id": b})
    assert r.status_code == 200, r.text
    assert (r.json()["pattern"], r.json()["category_id"], r.json()["match_count"]) == (
        "lidl express",
        b,
        7,
    )


def test_put_collision_is_409_and_bad_input_400(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id)
    first = client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": cat}).json()
    second = client.post(URL, headers=headers, json={"pattern": "ab", "category_id": cat}).json()
    r = client.put(f"{URL}/{second['id']}", headers=headers,
                   json={"pattern": "Lidl", "category_id": cat})
    assert r.status_code == 409
    assert r.json()["detail"] == "Another rule already uses this pattern."
    # Saving a rule under its own pattern is not a collision.
    r = client.put(f"{URL}/{first['id']}", headers=headers, json={"pattern": "LIDL", "category_id": cat})
    assert r.status_code == 200
    r = client.put(f"{URL}/{first['id']}", headers=headers, json={"pattern": "x", "category_id": cat})
    assert r.status_code == 400


def test_other_households_rules_are_404(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    cat = _category(db, other.household_id)
    rule = CategoryRule(household_id=other.household_id, pattern="lidl", category_id=cat)
    db.add(rule)
    db.commit()
    mine = _category(db, hh.household_id)
    assert client.put(f"{URL}/{rule.id}", headers=headers,
                      json={"pattern": "lidl", "category_id": mine}).status_code == 404
    assert client.delete(f"{URL}/{rule.id}", headers=headers).status_code == 404
    assert rule.id not in {r["id"] for r in client.get(URL, headers=headers).json()}


def test_delete_is_204_then_404(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id)
    rule = client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": cat}).json()
    assert client.delete(f"{URL}/{rule['id']}", headers=headers).status_code == 204
    assert client.delete(f"{URL}/{rule['id']}", headers=headers).status_code == 404


def test_deleting_a_category_removes_its_rules(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id, "Snacks")
    client.post(URL, headers=headers, json={"pattern": "kiosk", "category_id": cat})
    r = client.delete(f"/api/v1/settings/categories/{cat}", headers=headers)
    assert r.status_code == 204
    assert db.query(CategoryRule).count() == 0


def test_categories_list_counts_expenses_and_rules(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id, "Snacks")
    for deleted in (False, False, True):
        t = Transaction(household_id=hh.household_id, bucket_id=hh.bucket_id, amount=Decimal("2"),
                        currency="EUR", type=TransactionType.expense, paid_by=hh.user_id,
                        category_id=cat, transaction_date=date(2026, 10, 1))
        if deleted:
            from app.core.clock import utcnow_naive

            t.deleted_at = utcnow_naive()
        db.add(t)
    db.add(CategoryRule(household_id=hh.household_id, pattern="kiosk", category_id=cat))
    db.commit()
    row = next(c for c in client.get("/api/v1/settings/categories", headers=headers).json()
               if c["id"] == cat)
    assert (row["expense_count"], row["rule_count"]) == (2, 1)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_category_rules.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — 404/405 on `/api/v1/settings/category-rules`; `KeyError: 'expense_count'`.

- [ ] **Step 3: Write the router**

Create `app/api/category_rules.py`:

```python
"""/api/v1/settings/category-rules: the household's "merchant contains X →
category" rules (2d spec §7.4).

2d owns this API. 2b's composer reads the list (to match merchants as the
server does) and POSTs to remember a merchant; POST is an upsert by folded
pattern, so a queued or repeated POST is harmless. The old form routes in
app/routes/settings.py keep working on the same table.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.models import Category, CategoryRule
from app.services.category_rules import learn_rule, list_rules, normalise_pattern

router = APIRouter(prefix="/settings/category-rules", tags=["settings"])

INVALID_RULE_MSG = "Enter at least 2 characters and pick a category from this household."
PATTERN_TAKEN_MSG = "Another rule already uses this pattern."


class CategoryRuleIn(BaseModel):
    pattern: str
    category_id: str


class CategoryRuleOut(BaseModel):
    id: str
    pattern: str  # as stored: folded (case, accents, final sigma)
    category_id: str
    match_count: int
    created_at: datetime | None


def _out(rule: CategoryRule) -> CategoryRuleOut:
    return CategoryRuleOut(
        id=rule.id,
        pattern=rule.pattern,
        category_id=rule.category_id,
        match_count=rule.match_count or 0,
        created_at=rule.created_at,
    )


def _validated(db: Session, hh_id: str, body: CategoryRuleIn) -> tuple[str, str]:
    """(folded pattern, category id), or 400 with the one message the spec gives."""
    pattern = normalise_pattern(body.pattern)
    category = db.get(Category, body.category_id) if body.category_id else None
    if not pattern or category is None or category.household_id != hh_id:
        raise HTTPException(status_code=400, detail=INVALID_RULE_MSG)
    return pattern, category.id


def _by_pattern(db: Session, hh_id: str, pattern: str) -> CategoryRule | None:
    return db.query(CategoryRule).filter_by(household_id=hh_id, pattern=pattern).first()


def _rule_or_404(db: Session, rule_id: str, hh_id: str) -> CategoryRule:
    rule = db.get(CategoryRule, rule_id)
    if rule is None or rule.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.get("", response_model=list[CategoryRuleOut])
def list_category_rules(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """The household's rules, most used first."""
    user, hh_id = auth
    return [_out(r) for r in list_rules(db, hh_id)]


@router.post(
    "",
    response_model=CategoryRuleOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": CategoryRuleOut, "description": "The pattern had a rule; re-pointed"}},
)
def upsert_category_rule(
    body: CategoryRuleIn,
    response: Response,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Teach a rule, or re-point the one with the same folded pattern (kept
    match_count). 201 when new, 200 when it existed."""
    user, hh_id = auth
    pattern, category_id = _validated(db, hh_id, body)
    existed = _by_pattern(db, hh_id, pattern) is not None
    rule = learn_rule(db, hh_id, pattern, category_id, created_by=user.id)
    if rule is None:  # _validated already ruled this out
        raise HTTPException(status_code=400, detail=INVALID_RULE_MSG)
    db.commit()
    db.refresh(rule)
    if existed:
        response.status_code = status.HTTP_200_OK
    return _out(rule)


@router.put("/{rule_id}", response_model=CategoryRuleOut)
def update_category_rule(
    rule_id: str,
    body: CategoryRuleIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Edit a rule's pattern and category; match_count is kept. A pattern
    another rule already folds to is a 409 (no silent merge on edit)."""
    user, hh_id = auth
    rule = _rule_or_404(db, rule_id, hh_id)
    pattern, category_id = _validated(db, hh_id, body)
    other = _by_pattern(db, hh_id, pattern)
    if other is not None and other.id != rule.id:
        raise HTTPException(status_code=409, detail=PATTERN_TAKEN_MSG)
    rule.pattern = pattern
    rule.category_id = category_id
    db.commit()
    db.refresh(rule)
    return _out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category_rule(rule_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    db.delete(_rule_or_404(db, rule_id, hh_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `app/api/__init__.py` add `category_rules` to the import list and, after `router.include_router(settings.router)`:

```python
# 2d §7.4: owned here, consumed by 2b's composer.
router.include_router(category_rules.router)
```

- [ ] **Step 4: Category counts and rule cleanup**

In `app/api/settings.py`: import `func` from `sqlalchemy`, and `CategoryRule`, `Transaction` from `app.models`. Replace `list_categories` with:

```python
@router.get("/categories")
def list_categories(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Categories with how many active expenses and rules use each (2d §5.3:
    the delete confirmation names both counts)."""
    user, hh_id = auth
    cats = (
        db.query(Category)
        .filter_by(household_id=hh_id)
        .order_by(Category.is_default.desc(), Category.name)
        .all()
    )
    expenses = dict(
        db.query(Transaction.category_id, func.count(Transaction.id))
        .filter(
            Transaction.household_id == hh_id,
            Transaction.active(),
            Transaction.category_id.isnot(None),
        )
        .group_by(Transaction.category_id)
        .all()
    )
    rules = dict(
        db.query(CategoryRule.category_id, func.count(CategoryRule.id))
        .filter(CategoryRule.household_id == hh_id)
        .group_by(CategoryRule.category_id)
        .all()
    )
    return [
        {**_category_dict(c), "expense_count": expenses.get(c.id, 0), "rule_count": rules.get(c.id, 0)}
        for c in cats
    ]
```

In `delete_category`, before `db.delete(cat)`:

```python
    # The FK cascades too, but not every SQLite connection enforces FKs.
    db.query(CategoryRule).filter_by(household_id=hh_id, category_id=category_id).delete(
        synchronize_session=False
    )
```

(and remove `Transaction` from the local `from app.models import RecurringBill, Transaction` there if it is now imported at the top).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_category_rules.py tests/test_category_rules.py tests/test_api.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Regenerate types, format, commit**

```bash
cd web && npm ci && npm run gen:api && npm run typecheck && cd ..
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
git add app/api/category_rules.py app/api/__init__.py app/api/settings.py tests/test_api_category_rules.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(api): category rules CRUD with an upsert POST; category expense and rule counts"
```

### Task B2: `GET /insights/person`

**Stream:** B · **Depends on:** B1 (same worktree; no code dependency)

**Files:**
- Modify: `app/api/insights.py` (models `PersonLargestOut`, `PersonShareOut`; route `/person`)
- Test: `tests/test_api_insights_person.py` (create)

**Interfaces:**
- Produces (wire): `GET /api/v1/insights/person?user_id=&preset=&start_date=&end_date=` → `PersonShareOut` = `{user_id, paid_out, my_share, balance, share_pct|null, household_total, largest: {amount, notes, date}|null, shared_count, transaction_count}`; `balance = paid_out - my_share`; no `net`, no `by_bucket`. Unknown or foreign `user_id` → 404 `"Member not found"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_insights_person.py`:

```python
"""2d §7.1: "Paid out vs my share" for a member lens, without settle-up's net."""

from decimal import Decimal

from app.core.clock import local_today
from app.models import Transaction, TransactionSplit, TransactionType
from app.services.insights import resolve_insight_period
from app.services.person import get_person_summary
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

URL = "/api/v1/insights/person"


def _expense(db, hh, amount, *, paid_by, splits=None, notes=None):
    t = Transaction(household_id=hh.household_id, bucket_id=hh.bucket_id, amount=Decimal(amount),
                    currency="EUR", type=TransactionType.expense, paid_by=paid_by, notes=notes,
                    transaction_date=local_today())
    db.add(t)
    db.flush()
    for uid, share in (splits or {}).items():
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=Decimal(share)))
    db.commit()
    return t


def test_figures_equal_the_person_summary_without_net(client, db, api):  # noqa: F811
    headers, hh = api
    maria, _ = _add_member_user(db, hh.household_id, "maria")
    _expense(db, hh, "100", paid_by=hh.user_id, splits={hh.user_id: "50", maria.id: "50"},
             notes="Groceries")
    _expense(db, hh, "40", paid_by=maria.id, splits={hh.user_id: "20", maria.id: "20"})
    r = client.get(URL, headers=headers, params={"user_id": hh.user_id, "preset": "this_month"})
    assert r.status_code == 200, r.text
    body = r.json()
    period = resolve_insight_period("this_month")
    expected = get_person_summary(db, hh.household_id, hh.user_id, period["start"], period["end"])
    for key in ("paid_out", "my_share", "balance", "household_total", "share_pct"):
        assert Decimal(str(body[key])) == expected[key], key
    assert (body["shared_count"], body["transaction_count"]) == (2, 2)
    assert body["balance"] == 30.0  # paid 100, share 70
    assert body["largest"]["amount"] == 50.0 and body["largest"]["notes"] == "Groceries"
    assert "net" not in body and "by_bucket" not in body


def test_a_non_member_is_404(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    stranger = make_household(name="Other", username="other")
    for uid in (stranger.user_id, "nobody"):
        r = client.get(URL, headers=headers, params={"user_id": uid})
        assert r.status_code == 404
        assert r.json()["detail"] == "Member not found"


def test_empty_period_has_no_largest(client, api):  # noqa: F811
    headers, hh = api
    body = client.get(URL, headers=headers, params={"user_id": hh.user_id}).json()
    assert body["largest"] is None and body["paid_out"] == 0 and body["share_pct"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_api_insights_person.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — 404 on `/api/v1/insights/person` for the member too (`detail` "Not Found").

- [ ] **Step 3: Implement**

In `app/api/insights.py` add imports:

```python
import datetime as dt

from fastapi import HTTPException
from pydantic import BaseModel

from app.api.planning_models import CategoryUsualOut, Money
from app.services.insights import resolve_insight_period
from app.services.person import get_person_summary
from app.validators import household_member_ids
```

Then, after the `insights` route:

```python
class PersonLargestOut(BaseModel):
    amount: Money
    notes: str | None
    date: dt.date


class PersonShareOut(BaseModel):
    user_id: str
    paid_out: Money
    my_share: Money
    balance: Money  # paid_out - my_share; positive: paid more than their share
    share_pct: Money | None
    household_total: Money
    largest: PersonLargestOut | None
    shared_count: int
    transaction_count: int


def _member_or_404(db: Session, hh_id: str, user_id: str) -> str:
    if user_id not in household_member_ids(db, hh_id):
        raise HTTPException(status_code=404, detail="Member not found")
    return user_id


@router.get("/person", response_model=PersonShareOut)
def person_share(
    user_id: str = Query(...),
    preset: str = Query(default="this_month"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Paid out vs my share for one member over the period (2d §7.1). The
    settle-up ``net`` and ``by_bucket`` of get_person_summary are left out:
    there is no settle up in the new app."""
    user, hh_id = auth
    _member_or_404(db, hh_id, user_id)
    period = resolve_insight_period(preset, start_date, end_date)
    s = get_person_summary(db, hh_id, user_id, period["start"], period["end"])
    return PersonShareOut(
        user_id=user_id,
        paid_out=s["paid_out"],
        my_share=s["my_share"],
        balance=s["balance"],
        share_pct=s["share_pct"],
        household_total=s["household_total"],
        largest=s["largest"],
        shared_count=s["shared_count"],
        transaction_count=s["transaction_count"],
    )
```

(`household_member_ids` exists in `app/validators.py`; `Money` exists in `app/api/planning_models.py`.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_api_insights_person.py tests/test_person_view.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
git add app/api/insights.py tests/test_api_insights_person.py
git commit -m "feat(api): GET /insights/person, paid out vs my share without settle-up net"
```

### Task B3: `monthly_in_out` and `category_id` on "Where it went" rows

**Stream:** B · **Depends on:** B2

**Files:**
- Modify: `app/services/insights.py` (new `monthly_in_out`; `build_insights` adds it; `get_insights_category_breakdown` rows gain `category_id`)
- Modify: `app/api/insights.py` (`"monthly_in_out": data["monthly_in_out"]` in the `insights` response)
- Test: `tests/test_monthly_in_out.py` (create)

**Interfaces:**
- Produces (Python): `monthly_in_out(db, household_id: str, n_months: int = 6, paid_by: str | None = None, *, today: date | None = None) -> list[dict]`.
- Produces (wire, untyped dict endpoint): `GET /insights` gains `monthly_in_out: [{year, month, label, in, out, net}]` (six calendar months ending with the current one, oldest first, lens-aware, ignores the period and the other filters), and every `categories[]` row gains `category_id: string | null` (`null` = uncategorised; `"__cash_not_logged__"` = cash not logged yet).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_monthly_in_out.py`:

```python
"""2d §7.3: In and Out by month for six calendar months, lens-aware; the
current month equals in_out for this_month."""

from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.core.clock import local_today
from app.models import Category, Transaction, TransactionSplit, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user


def _txn(db, hh, amount, *, when, kind=TransactionType.expense, paid_by=None, splits=None,
         category_id=None):
    t = Transaction(household_id=hh.household_id,
                    bucket_id=None if kind == TransactionType.income else hh.bucket_id,
                    amount=Decimal(amount), currency="EUR", type=kind,
                    paid_by=paid_by or hh.user_id, category_id=category_id, transaction_date=when)
    db.add(t)
    db.flush()
    for uid, share in (splits or {}).items():
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=Decimal(share)))
    db.commit()
    return t


def test_six_months_oldest_first_current_equals_in_out(client, db, api):  # noqa: F811
    headers, hh = api
    today = local_today()
    two_ago = today.replace(day=1) - relativedelta(months=2)
    _txn(db, hh, "120", when=today)
    _txn(db, hh, "2000", when=today, kind=TransactionType.income)
    _txn(db, hh, "80", when=two_ago)
    body = client.get("/api/v1/insights", headers=headers, params={"preset": "this_month"}).json()
    months = body["monthly_in_out"]
    assert len(months) == 6
    assert (months[-1]["year"], months[-1]["month"]) == (today.year, today.month)
    assert set(months[0]) == {"year", "month", "label", "in", "out", "net"}
    current = months[-1]
    assert (current["in"], current["out"], current["net"]) == (
        body["in_out"]["in"],
        body["in_out"]["out"],
        body["in_out"]["net"],
    )
    assert months[-3]["out"] == 80.0 and months[-3]["in"] == 0.0


def test_it_ignores_the_period_and_follows_the_lens(client, db, api):  # noqa: F811
    headers, hh = api
    maria, _ = _add_member_user(db, hh.household_id, "maria")
    today = local_today()
    _txn(db, hh, "100", when=today, splits={hh.user_id: "30", maria.id: "70"})
    _txn(db, hh, "500", when=today, kind=TransactionType.income, paid_by=maria.id)
    last_month = client.get(
        "/api/v1/insights", headers=headers, params={"preset": "last_month"}
    ).json()["monthly_in_out"]
    assert last_month[-1]["out"] == 100.0  # the period does not move the window
    lens = client.get(
        "/api/v1/insights", headers=headers, params={"preset": "this_month", "paid_by": maria.id}
    ).json()
    assert (lens["monthly_in_out"][-1]["out"], lens["monthly_in_out"][-1]["in"]) == (70.0, 500.0)
    assert lens["monthly_in_out"][-1]["out"] == lens["in_out"]["out"]


def test_category_rows_carry_their_id(client, db, api):  # noqa: F811
    headers, hh = api
    cat = Category(household_id=hh.household_id, name="Groceries")
    db.add(cat)
    db.commit()
    today = local_today()
    _txn(db, hh, "30", when=today, category_id=cat.id)
    _txn(db, hh, "10", when=today - timedelta(days=0))
    rows = client.get("/api/v1/insights", headers=headers).json()["categories"]
    assert {(r["name"], r["category_id"]) for r in rows} == {
        ("Groceries", cat.id),
        ("Uncategorised", None),
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_monthly_in_out.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — `KeyError: 'monthly_in_out'`, `KeyError: 'category_id'`.

- [ ] **Step 3: Implement the service**

In `app/services/insights.py`, after `in_out(...)`:

```python
def monthly_in_out(
    db: Session,
    household_id: str,
    n_months: int = 6,
    paid_by: str | None = None,
    *,
    today: date | None = None,
) -> list[dict]:
    """In, Out and Net for the last ``n_months`` calendar months, oldest first
    (2d §7.3).

    Ignores the insights period and every filter except the person
    (``paid_by``: their income received and their share of spending, as
    elsewhere). Each month is built exactly like :func:`in_out`: In from
    :func:`get_insights_income`, Out from :func:`get_insights_summary` with
    the not-yet-logged cash, over the same window, so the current month
    (clipped to today, like ``this_month``) equals ``in_out`` for this month.
    """
    today = today or local_today()
    person = paid_by or None
    cash_for = make_cash_lookup(db, household_id, person=person)
    split_members = settlement_members(db, household_id)
    rows = []
    for y, m in _recent_months(n_months, today):
        start, end = _month_range(y, m)
        end = min(end, today)
        income = get_insights_income(db, household_id, start, end, paid_by=person)
        out = get_insights_summary(
            db,
            household_id,
            start,
            end,
            paid_by=person,
            cash_for=cash_for,
            split_members=split_members,
        )["total_spent"]
        rows.append(
            {
                "year": y,
                "month": m,
                "label": date(y, m, 1).strftime("%b"),
                "in": quantize(income),
                "out": quantize(out),
                "net": quantize(income - out),
            }
        )
    return rows
```

In `get_insights_category_breakdown`, the row dict becomes:

```python
        rows.append(
            {
                # None: uncategorised; NOT_LOGGED_CASH: cash not logged yet.
                "category_id": cat_id,
                **_category_label(cat_id, cats),
                "amount": quantize(amount),
                "pct": quantize(amount / grand * 100, TENTH),
            }
        )
```

In `build_insights`, before `return {`:

```python
    months_in_out = monthly_in_out(
        db, household_id, 6, filters.paid_by or None, today=filters.today
    )
```

and add `"monthly_in_out": months_in_out,` to the returned dict.

In `app/api/insights.py` `insights()` response, after `"in_out": data["in_out"],`:

```python
        # Six calendar months to this one, oldest first; ignores the period (2d §7.3).
        "monthly_in_out": data["monthly_in_out"],
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_monthly_in_out.py tests/test_insights.py tests/test_shared_insights.py tests/test_kpis.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
git add app/services/insights.py app/api/insights.py tests/test_monthly_in_out.py
git commit -m "feat(insights): monthly_in_out for six months and category ids on the breakdown"
```

### Task B4: `GET /insights/categories/{category_id}`

**Stream:** B · **Depends on:** B3

**Files:**
- Modify: `app/services/insights.py` (new `get_category_detail`, `UNCATEGORISED`, `OTHER_MERCHANT`; import `CategoryRule`, `datetime`)
- Modify: `app/api/insights.py` (response models and route)
- Test: `tests/test_api_category_detail.py` (create)

**Interfaces:**
- Produces (Python): `get_category_detail(db, household_id, category_key: str, start: date | None, end: date | None, *, paid_by: str | None = None, today: date | None = None) -> dict | None` (None = not this household's category).
- Produces (wire): `GET /api/v1/insights/categories/{category_id}?preset=&start_date=&end_date=&paid_by=` → `CategoryDetailOut`:
  `{category: {id, name, icon, color}|null, total, count, avg_per_month|null, months: [{year, month, label, total}] (6, oldest first, ending at the period end), merchants: [{merchant, count, total}] (top 5; no merchant → "Other"), recent: [{id, date, merchant, notes, amount, paid_by}] (latest 10 in the period), rules: [{id, pattern, match_count}]}`. `category_id` may be `uncategorised`. Unknown or foreign id → 404 `"Category not found"`; foreign `paid_by` → 404 `"Member not found"`. `avg_per_month` is the mean of the six months that have ended (zero months included), null if none has.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_category_detail.py`:

```python
"""2d §7.2: one category over the period, six months, its shops and rules."""

from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.core.clock import local_today
from app.models import Category, CategoryRule, Transaction, TransactionSplit, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

URL = "/api/v1/insights/categories"


def _cat(db, household_id, name="Groceries"):
    c = Category(household_id=household_id, name=name, icon="🛒", color="#10b981")
    db.add(c)
    db.commit()
    return c


def _spend(db, hh, amount, *, cat_id, merchant=None, when=None, splits=None, paid_by=None):
    t = Transaction(household_id=hh.household_id, bucket_id=hh.bucket_id, amount=Decimal(amount),
                    currency="EUR", type=TransactionType.expense, paid_by=paid_by or hh.user_id,
                    category_id=cat_id, merchant=merchant, transaction_date=when or local_today())
    db.add(t)
    db.flush()
    for uid, share in (splits or {}).items():
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=Decimal(share)))
    db.commit()
    return t


def test_detail_has_merchants_months_recent_and_rules(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh.household_id)
    today = local_today()
    for merchant, amount in (("Sklavenitis", "40"), ("Sklavenitis", "20"), ("Lidl", "30"),
                             (None, "5"), ("AB", "4"), ("My market", "3"), ("Kiosk", "2")):
        _spend(db, hh, amount, cat_id=cat.id, merchant=merchant, when=today)
    _spend(db, hh, "90", cat_id=cat.id, merchant="Lidl",
           when=today.replace(day=1) - relativedelta(months=1))
    db.add(CategoryRule(household_id=hh.household_id, pattern="sklavenitis", category_id=cat.id,
                        match_count=48))
    db.commit()

    r = client.get(f"{URL}/{cat.id}", headers=headers, params={"preset": "this_month"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == {"id": cat.id, "name": "Groceries", "icon": "🛒", "color": "#10b981"}
    assert (body["total"], body["count"]) == (104.0, 7)
    assert [m["merchant"] for m in body["merchants"]] == ["Sklavenitis", "Lidl", "Other", "AB",
                                                          "My market"]
    assert body["merchants"][0] == {"merchant": "Sklavenitis", "count": 2, "total": 60.0}
    assert len(body["months"]) == 6
    assert (body["months"][-1]["month"], body["months"][-1]["total"]) == (today.month, 104.0)
    assert body["months"][-2]["total"] == 90.0
    # Five complete months: 90 and four zeros.
    assert body["avg_per_month"] == 18.0
    assert len(body["recent"]) == 7 and set(body["recent"][0]) == {
        "id", "date", "merchant", "notes", "amount", "paid_by"}
    assert body["rules"] == [{"id": body["rules"][0]["id"], "pattern": "sklavenitis",
                              "match_count": 48}]


def test_recent_is_the_latest_ten(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh.household_id)
    first = local_today().replace(day=1)
    for i in range(12):
        _spend(db, hh, "1", cat_id=cat.id, when=first, merchant=f"M{i}")
    body = client.get(f"{URL}/{cat.id}", headers=headers).json()
    assert len(body["recent"]) == 10


def test_uncategorised_works_and_has_no_rules(client, db, api):  # noqa: F811
    headers, hh = api
    _spend(db, hh, "12", cat_id=None, merchant="Kiosk")
    body = client.get(f"{URL}/uncategorised", headers=headers).json()
    assert body["category"] is None and body["total"] == 12.0 and body["rules"] == []


def test_lens_counts_the_members_share(client, db, api):  # noqa: F811
    headers, hh = api
    maria, _ = _add_member_user(db, hh.household_id, "maria")
    cat = _cat(db, hh.household_id)
    _spend(db, hh, "100", cat_id=cat.id, merchant="Lidl",
           splits={hh.user_id: "60", maria.id: "40"})
    body = client.get(f"{URL}/{cat.id}", headers=headers, params={"paid_by": maria.id}).json()
    assert body["total"] == 40.0 and body["merchants"][0]["total"] == 40.0
    assert body["recent"][0]["amount"] == 40.0


def test_foreign_or_unknown_category_and_member_are_404(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    theirs = _cat(db, other.household_id)
    assert client.get(f"{URL}/{theirs.id}", headers=headers).status_code == 404
    assert client.get(f"{URL}/nope", headers=headers).status_code == 404
    mine = _cat(db, hh.household_id, "Mine")
    r = client.get(f"{URL}/{mine.id}", headers=headers, params={"paid_by": other.user_id})
    assert r.status_code == 404


def test_months_end_at_the_period_end(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh.household_id)
    body = client.get(f"{URL}/{cat.id}", headers=headers, params={"preset": "last_month"}).json()
    last = local_today().replace(day=1) - timedelta(days=1)
    assert (body["months"][-1]["year"], body["months"][-1]["month"]) == (last.year, last.month)
    assert body["avg_per_month"] == 0.0 and body["total"] == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_api_category_detail.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — 404 "Not Found" for every call.

- [ ] **Step 3: Implement the service**

In `app/services/insights.py`: add `CategoryRule` to the `app.models` import and `from datetime import date, datetime, timedelta`. At the end of the file (after `get_insights_kpis`, so `_month_end` exists):

```python
# ---------------------------------------------------------------------------
# Category drill-down (2d §7.2)
# ---------------------------------------------------------------------------

UNCATEGORISED = "uncategorised"
OTHER_MERCHANT = "Other"


def get_category_detail(
    db: Session,
    household_id: str,
    category_key: str,
    start: date | None,
    end: date | None,
    *,
    paid_by: str | None = None,
    today: date | None = None,
) -> dict | None:
    """One category for the Insights drill-down, or None when ``category_key``
    is not one of this household's categories (``"uncategorised"`` is).

    Amounts follow the lens exactly as /insights does (:func:`_amount_for`,
    settle-up's split members), and labelled cash outs in the category count
    like they do in the breakdown. ``months`` are the six calendar months
    ending at the period end (today for all time); ``avg_per_month`` is the
    mean of those that have ended. ``merchants`` group the period's expenses
    by merchant (none → "Other"), top five by total; ``recent`` is the latest
    ten.
    """
    today = today or local_today()
    person = paid_by or None
    if category_key == UNCATEGORISED:
        category = None
        matches = Transaction.category_id.is_(None)
    else:
        category = db.get(Category, category_key)
        if category is None or category.household_id != household_id:
            return None
        matches = Transaction.category_id == category.id
    split_members = settlement_members(db, household_id)
    # Not-yet-logged cash has no category, so only labelled outs can join one.
    cash_for = (
        make_cash_lookup(db, household_id, person=person, category_ids=[category.id])
        if category
        else None
    )

    def rows(lo: date | None, hi: date | None) -> list[tuple[Transaction, Decimal]]:
        q = _build_expense_query(
            db, household_id, lo, hi, paid_by=person, split_members=split_members
        ).filter(matches)
        out = []
        for t in q.options(joinedload(Transaction.splits)).all():
            amount = _amount_for(t, person, split_members)
            if amount:
                out.append((t, amount))
        return out

    in_period = rows(start, end)
    cash = cash_for(start, end) if cash_for else CashSpend()
    total = sum((a for _, a in in_period), ZERO) + cash.total

    months = _recent_months(6, end or today)
    lo, hi = _month_range(*months[0])[0], _month_range(*months[-1])[1]
    by_month: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for t, a in rows(lo, hi):
        by_month[(t.transaction_date.year, t.transaction_date.month)] += a
    if cash_for:
        for key, a in cash_for(lo, hi).by_month().items():
            by_month[key] += a
    month_rows = [
        {
            "year": y,
            "month": m,
            "label": date(y, m, 1).strftime("%b"),
            "total": quantize(by_month.get((y, m), ZERO)),
        }
        for y, m in months
    ]
    ended = [r["total"] for r in month_rows if _month_end(r["year"], r["month"]) < today]
    avg = quantize(sum(ended, ZERO) / len(ended)) if ended else None

    groups: dict[str, list] = defaultdict(lambda: [0, ZERO])
    for t, a in in_period:
        group = groups[(t.merchant or "").strip() or OTHER_MERCHANT]
        group[0] += 1
        group[1] += a
    merchants = sorted(
        (
            {"merchant": name, "count": count, "total": quantize(value)}
            for name, (count, value) in groups.items()
        ),
        key=lambda r: (-r["total"], r["merchant"]),
    )[:5]

    latest = sorted(
        in_period,
        key=lambda pair: (pair[0].transaction_date, pair[0].created_at or datetime.min, pair[0].id),
        reverse=True,
    )[:10]
    recent = [
        {
            "id": t.id,
            "date": t.transaction_date,
            "merchant": t.merchant,
            "notes": t.notes,
            "amount": quantize(a),
            "paid_by": t.paid_by,
        }
        for t, a in latest
    ]

    rules = (
        db.query(CategoryRule)
        .filter_by(household_id=household_id, category_id=category.id)
        .order_by(CategoryRule.match_count.desc(), CategoryRule.pattern)
        .all()
        if category
        else []
    )
    return {
        "category": (
            {"id": category.id, "name": category.name, "icon": category.icon, "color": category.color}
            if category
            else None
        ),
        "total": quantize(total),
        "count": len(in_period),
        "avg_per_month": avg,
        "months": month_rows,
        "merchants": merchants,
        "recent": recent,
        "rules": [
            {"id": r.id, "pattern": r.pattern, "match_count": r.match_count or 0} for r in rules
        ],
    }
```

- [ ] **Step 4: Implement the route**

In `app/api/insights.py` (import `get_category_detail` from `app.services.insights`):

```python
class CategoryRefOut(BaseModel):
    id: str
    name: str
    icon: str | None
    color: str | None


class CategoryMonthOut(BaseModel):
    year: int
    month: int
    label: str
    total: Money


class CategoryMerchantOut(BaseModel):
    merchant: str  # "Other" groups expenses without one
    count: int
    total: Money


class CategoryExpenseOut(BaseModel):
    id: str
    date: dt.date
    merchant: str | None
    notes: str | None
    amount: Money  # the lens person's share under a member lens
    paid_by: str | None


class CategoryRuleRefOut(BaseModel):
    id: str
    pattern: str
    match_count: int


class CategoryDetailOut(BaseModel):
    category: CategoryRefOut | None  # null: uncategorised
    total: Money
    count: int
    avg_per_month: Money | None
    months: list[CategoryMonthOut]
    merchants: list[CategoryMerchantOut]
    recent: list[CategoryExpenseOut]
    rules: list[CategoryRuleRefOut]


@router.get("/categories/{category_id}", response_model=CategoryDetailOut)
def category_detail(
    category_id: str,
    preset: str = Query(default="this_month"),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    paid_by: str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """One category over the period (2d §7.2). ``category_id`` may be
    ``uncategorised``."""
    user, hh_id = auth
    if paid_by:
        _member_or_404(db, hh_id, paid_by)
    period = resolve_insight_period(preset, start_date, end_date)
    data = get_category_detail(
        db, hh_id, category_id, period["start"], period["end"], paid_by=paid_by or None
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return data
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_api_category_detail.py tests/test_insights.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
git add app/services/insights.py app/api/insights.py tests/test_api_category_detail.py
git commit -m "feat(api): GET /insights/categories/{id}: six months, top shops, latest ten, rules"
```

### Task B5: Security API (`/settings/security`), shared TOTP helpers, profile name limit

**Stream:** B · **Depends on:** B4

**Files:**
- Create: `app/services/totp.py`
- Create: `app/api/security.py`
- Modify: `app/api_auth.py` (`_cookie_auth` and `require_api_auth` take `allow_unenrolled`; new `require_api_auth_enrolling`)
- Modify: `app/routes/settings.py` (use the helpers; behaviour unchanged)
- Modify: `app/api/settings.py` (`update_profile`: display name 1–100 → 400)
- Modify: `app/api/__init__.py` (include `security.router`)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/schema.d.ts`
- Test: `tests/test_api_security.py` (create)

**Interfaces:**
- Produces (Python): `app.services.totp.pending_secret(db, user) -> str`, `otpauth_uri(user, secret) -> str`, `new_backup_codes() -> tuple[list[str], str]`, `backup_codes_remaining(user) -> int`, `turn_off_totp(db, user) -> None`; `app.api_auth.require_api_auth_enrolling` (like `require_api_auth`, but a cookie session whose user has 2FA off is accepted).
- Produces (wire):
  - `GET /api/v1/settings/security` → `{totp_enabled, backup_codes_remaining, passkey_available, passkey_linked, password_session}`.
  - `POST /totp/setup` → `{secret, otpauth_uri}`; reuses the pending secret; 409 when on; 10/min.
  - `POST /totp/enable` `{code}` → `{backup_codes: string[8]}`; 400 `"Invalid code. Please try again."`; 409 when on; 10/min.
  - `POST /totp/disable` `{current_password, code}` → 204 and, for a cookie session, a reissued cookie; 400 `"Incorrect password."` / `"Invalid authenticator code."`; 429 when locked; 5/min.
- **Resolved gap:** 2FA is mandatory for password sessions (`_cookie_auth` answers 403 "TOTP enrollment required" when it is off). After Turn off, the reissued cookie reaches only `GET /settings/security`, `/totp/setup` and `/totp/enable` (they use `require_api_auth_enrolling`); every other endpoint stays 403 until 2FA is set up again. A passkey session (`amr=oidc`) is unaffected. A fresh pending secret clears `last_totp_step`, or the new secret's first code could be refused as a replay of the old one's step.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_security.py`:

```python
"""2d §7.5: /api/v1/settings/security. 2FA set up, turned on and off from the
new app; the HTML routes behave as before (tests/test_auth.py)."""

import time

import pyotp

from app.auth import COOKIE_NAME, _serializer
from app.core.config import settings
from app.models import User
from tests.conftest import PASSWORD
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/settings/security"


def _later(secret, n=1):
    """login() spent the current step; a later one is still inside valid_window."""
    return pyotp.TOTP(secret).at(time.time() + 30 * n)


def test_get_reports_the_state(client, db, make_household, login):
    hh = make_household()
    login(hh.username, hh.secret)
    body = client.get(URL).json()
    assert body == {
        "totp_enabled": True,
        "backup_codes_remaining": 0,
        "passkey_available": bool(settings.new_app_enabled and settings.oidc_enabled),
        "passkey_linked": False,
        "password_session": True,
    }


def test_bearer_counts_as_a_password_session(client, api):  # noqa: F811
    headers, _ = api
    assert client.get(URL, headers=headers).json()["password_session"] is True


def test_a_passkey_session_is_not_a_password_session(client, db, make_household):
    hh = make_household()
    user = db.get(User, hh.user_id)
    user.oidc_subject = "sub-1"
    db.commit()
    # The payload set_session(..., amr="oidc") writes, sent as a raw Cookie header
    # (the test client's jar would need the cookie's domain).
    cookie = _serializer.dumps({
        "user_id": hh.user_id, "hh_id": hh.household_id, "sv": 0, "state": "authenticated",
        "amr": "oidc", "iat": int(time.time())})
    body = client.get(URL, headers={"Cookie": f"{COOKIE_NAME}={cookie}"}).json()
    assert (body["password_session"], body["passkey_linked"]) == (False, True)


def test_disable_needs_password_and_code(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = client.post(f"{URL}/totp/disable", headers=headers,
                    json={"current_password": "wrong", "code": _later(hh.secret)})
    assert (r.status_code, r.json()["detail"]) == (400, "Incorrect password.")
    r = client.post(f"{URL}/totp/disable", headers=headers,
                    json={"current_password": PASSWORD, "code": "000000"})
    assert (r.status_code, r.json()["detail"]) == (400, "Invalid authenticator code.")
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert user.totp_enabled and user.failed_logins == 2


def test_disable_keeps_the_caller_signed_in_for_setup(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = client.post(f"{URL}/totp/disable", headers=headers,
                    json={"current_password": PASSWORD, "code": _later(hh.secret)})
    assert r.status_code == 204, r.text
    user = db.get(User, hh.user_id)
    db.refresh(user)
    assert (user.totp_enabled, user.totp_secret, user.totp_backup_codes) == (False, None, None)
    # The reissued cookie reaches the security endpoints...
    assert client.get(URL).json()["totp_enabled"] is False
    # ...and nothing else until 2FA is back (2FA is mandatory for password sign-in).
    assert client.get("/api/v1/auth/me").status_code == 403

    csrf = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    setup = client.post(f"{URL}/totp/setup", headers=csrf)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert client.post(f"{URL}/totp/setup", headers=csrf).json()["secret"] == secret  # reused

    bad = client.post(f"{URL}/totp/enable", headers=csrf, json={"code": "000000"})
    assert (bad.status_code, bad.json()["detail"]) == (400, "Invalid code. Please try again.")
    ok = client.post(f"{URL}/totp/enable", headers=csrf, json={"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200, ok.text
    codes = ok.json()["backup_codes"]
    assert len(codes) == 8 and len(set(codes)) == 8
    assert client.get(URL).json()["backup_codes_remaining"] == 8
    assert client.get("/api/v1/auth/me").status_code == 200


def test_setup_and_enable_are_409_when_on(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    assert client.post(f"{URL}/totp/setup", headers=headers).status_code == 409
    assert client.post(f"{URL}/totp/enable", headers=headers,
                       json={"code": "123456"}).status_code == 409


def test_setup_is_rate_limited(client, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    codes = [client.post(f"{URL}/totp/setup", headers=headers).status_code for _ in range(11)]
    assert codes[:10] == [409] * 10 and codes[10] == 429


def test_disable_when_locked_is_429(client, db, make_household, login):
    from datetime import timedelta

    from app.core.clock import utcnow_naive

    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.locked_until = utcnow_naive() + timedelta(minutes=10)
    db.commit()
    r = client.post(f"{URL}/totp/disable", headers=headers,
                    json={"current_password": PASSWORD, "code": _later(hh.secret)})
    assert r.status_code == 429


def test_profile_name_must_be_1_to_100(client, api):  # noqa: F811
    headers, _ = api
    for name in ("", "   ", "x" * 101):
        r = client.put("/api/v1/settings/profile", headers=headers,
                       json={"display_name": name, "avatar_color": "#6366f1"})
        assert r.status_code == 400, name
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_api_security.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — 404 on `/api/v1/settings/security`; empty display name accepted (200).

- [ ] **Step 3: Shared TOTP helpers**

Create `app/services/totp.py`:

```python
"""TOTP enrolment shared by the old settings pages (app/routes/settings.py)
and /api/v1/settings/security (2d §7.5). The secret lives on the user row
while totp_enabled is False (an enrolment in progress); it grants nothing
until a valid code confirms it."""

import json
import logging
import secrets

import bcrypt as _bcrypt
import pyotp
from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.auth import invalidate_user_sessions
from app.core.config import settings
from app.models import User

security_logger = logging.getLogger("security")

BACKUP_CODE_COUNT = 8


def pending_secret(db: Session, user: User) -> str:
    """The user's in-progress TOTP secret, created (and committed) if needed."""
    secret = None
    if user.totp_secret:
        try:
            secret = user.get_totp_secret()
        except InvalidToken:
            # Unreadable pending secret (key changed): safe to replace only while
            # not enrolled; an enabled secret is never overwritten here.
            if user.totp_enabled:
                raise
            security_logger.error(
                "Pending TOTP secret for user_id=%s is unreadable; restarting enrollment", user.id
            )
    if not secret:
        secret = pyotp.random_base32()
        user.set_totp_secret(secret)
        # The step counter belongs to the old secret; keeping it could refuse
        # the new secret's first code as a replay.
        user.last_totp_step = None
        db.commit()
    return secret


def otpauth_uri(user: User, secret: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=settings.app_name)


def new_backup_codes() -> tuple[list[str], str]:
    """(plain codes to show once, JSON of their bcrypt hashes to store)."""
    plain = [secrets.token_hex(5).upper() for _ in range(BACKUP_CODE_COUNT)]
    hashed = [_bcrypt.hashpw(c.encode(), _bcrypt.gensalt()).decode() for c in plain]
    return plain, json.dumps(hashed)


def backup_codes_remaining(user: User) -> int:
    if not user.totp_enabled or not user.totp_backup_codes:
        return 0
    try:
        return len(json.loads(user.totp_backup_codes))
    except (ValueError, TypeError):
        return 0


def turn_off_totp(db: Session, user: User) -> None:
    """Clear the secret and codes, sign out everywhere, revoke Shortcut
    tokens. The caller has verified password and code, and commits."""
    from app.services import revoke_user_tokens

    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    user.last_totp_step = None
    invalidate_user_sessions(db, user)
    revoke_user_tokens(db, user.id)
```

In `app/routes/settings.py`:
- import `from app.services.totp import new_backup_codes, otpauth_uri, pending_secret, turn_off_totp`.
- replace the body of `_pending_secret` with `return pending_secret(db, user)` (keep the name: `enroll_totp_page` calls it).
- in `enroll_totp_page` and the retry branch of `enroll_totp_submit`, `totp_uri = otpauth_uri(user, secret)`.
- in `enroll_totp_submit` replace the two `plain_codes`/`hashed_codes` lines and `user.totp_backup_codes = json.dumps(hashed_codes)` with:

```python
    plain_codes, hashed_json = new_backup_codes()
    # secret is already on the row; confirming it is what flips enrollment on.
    user.totp_enabled = True
    user.totp_backup_codes = hashed_json
```

- in `disable_totp`, replace the six lines from `user.totp_secret = None` to `revoke_user_tokens(db, user.id)` with `turn_off_totp(db, user)`.
- remove imports that become unused (`secrets`, `_bcrypt`, `InvalidToken` if unused; `json` only if unused). Run `ruff check` to find them.

- [ ] **Step 4: The enrolling auth dependency**

In `app/api_auth.py`:

1. `_cookie_auth(request, db)` → `_cookie_auth(request, db, *, allow_unenrolled: bool = False)`, and its TOTP line becomes:

```python
    if not allow_unenrolled and not user.totp_enabled and session.get("amr") != "oidc":
        raise HTTPException(status_code=403, detail="TOTP enrollment required")
```

2. Rename the body of `require_api_auth` to a private `_api_auth(request, credentials, db, *, allow_unenrolled)`: it calls `_cookie_auth(request, db, allow_unenrolled=allow_unenrolled)` when there are no credentials, and its final TOTP check becomes `if not allow_unenrolled and not user.totp_enabled:`. Then:

```python
def require_api_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """(docstring unchanged)"""
    return _api_auth(request, credentials, db, allow_unenrolled=False)


def require_api_auth_enrolling(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """require_api_auth without the "2FA enrolled" check: for the three
    security endpoints a signed-in member needs to set 2FA up again after
    turning it off (2d §7.5). Everything else uses require_api_auth."""
    return _api_auth(request, credentials, db, allow_unenrolled=True)
```

- [ ] **Step 5: The router**

Create `app/api/security.py`:

```python
"""/api/v1/settings/security: 2FA set up, on and off, and passkey status
(2d §7.5). The passkey itself is linked and unlinked by native form posts to
/app/auth/link and /app/auth/unlink (app/web_app.py)."""

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth, require_api_auth_enrolling
from app.auth import (
    COOKIE_NAME,
    current_iat,
    decode_cookie,
    is_locked,
    register_failed_login,
    security_logger,
    set_session,
    verify_password,
    verify_totp,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.services.totp import (
    backup_codes_remaining,
    new_backup_codes,
    otpauth_uri,
    pending_secret,
    turn_off_totp,
)

router = APIRouter(prefix="/settings/security", tags=["settings"])

ALREADY_ON = "Two-factor authentication is already on."
LOCKED = "Too many failed attempts: the account is temporarily locked. Try again later."


class SecurityOut(BaseModel):
    totp_enabled: bool
    backup_codes_remaining: int
    passkey_available: bool  # the new app and the identity provider are configured
    passkey_linked: bool
    password_session: bool  # false on a passkey-only session: link/unlink need password + 2FA


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCodeIn(BaseModel):
    code: str


class BackupCodesOut(BaseModel):
    backup_codes: list[str]


class TotpDisableIn(BaseModel):
    current_password: str
    code: str


def _session_amr(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    # Cookies from before passkeys existed carry no "amr": they were all password + 2FA.
    return session.get("amr", "pwd") if session else None


def _password_session(request: Request) -> bool:
    if request.headers.get("authorization"):
        return True  # Bearer tokens come from password + TOTP sign-in only
    return _session_amr(request) == "pwd"


@router.get("", response_model=SecurityOut)
def security(
    request: Request, auth=Depends(require_api_auth_enrolling), db: Session = Depends(get_db)
):
    user, _ = auth
    return SecurityOut(
        totp_enabled=user.totp_enabled,
        backup_codes_remaining=backup_codes_remaining(user),
        passkey_available=bool(settings.new_app_enabled and settings.oidc_enabled),
        passkey_linked=bool(user.oidc_subject),
        password_session=_password_session(request),
    )


@router.post("/totp/setup", response_model=TotpSetupOut)
@limiter.limit("10/minute")
def totp_setup(
    request: Request,
    response: Response,
    auth=Depends(require_api_auth_enrolling),
    db: Session = Depends(get_db),
):
    """The pending secret (reused across calls) and its otpauth:// link."""
    user, _ = auth
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail=ALREADY_ON)
    secret = pending_secret(db, user)
    response.headers["Cache-Control"] = "no-store"
    return TotpSetupOut(secret=secret, otpauth_uri=otpauth_uri(user, secret))


@router.post("/totp/enable", response_model=BackupCodesOut)
@limiter.limit("10/minute")
def totp_enable(
    request: Request,
    response: Response,
    body: TotpCodeIn,
    auth=Depends(require_api_auth_enrolling),
    db: Session = Depends(get_db),
):
    """Confirm the pending secret with a code; returns the 8 backup codes once."""
    user, _ = auth
    if user.totp_enabled:
        raise HTTPException(status_code=409, detail=ALREADY_ON)
    try:
        has_secret = bool(user.totp_secret and user.get_totp_secret())
    except InvalidToken:
        has_secret = False
    if not has_secret or not verify_totp(db, user, body.code.strip()):
        raise HTTPException(status_code=400, detail="Invalid code. Please try again.")
    plain, hashed_json = new_backup_codes()
    user.totp_enabled = True
    user.totp_backup_codes = hashed_json
    db.commit()
    security_logger.info("TOTP enrolled for '%s' (new app)", user.username)
    response.headers["Cache-Control"] = "no-store"
    return BackupCodesOut(backup_codes=plain)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
def totp_disable(
    request: Request,
    body: TotpDisableIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Turn 2FA off: the same effects as the old route (secret and codes
    cleared, every session and token revoked), then this browser's cookie is
    reissued so the caller stays signed in, to set it up again."""
    user, hh_id = auth
    if is_locked(user):
        raise HTTPException(status_code=429, detail=LOCKED)
    if not verify_password(body.current_password, user.password_hash):
        register_failed_login(db, user)
        raise HTTPException(status_code=400, detail="Incorrect password.")
    if not user.totp_secret or not verify_totp(db, user, body.code.strip()):
        register_failed_login(db, user)
        raise HTTPException(status_code=400, detail="Invalid authenticator code.")
    amr = _session_amr(request)
    iat = current_iat(request)
    turn_off_totp(db, user)
    db.commit()
    security_logger.info("TOTP disabled for '%s' (new app)", user.username)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if amr and not request.headers.get("authorization"):
        set_session(response, user.id, hh_id, user.session_version, amr=amr, iat=iat)
    return response
```

In `app/api/__init__.py`, import `security` and add `router.include_router(security.router)` after the `category_rules` line.

- [ ] **Step 6: Profile name limit**

In `app/api/settings.py` `update_profile`, before the email check:

```python
    name = body.display_name.strip()
    if not 1 <= len(name) <= 100:
        raise HTTPException(status_code=400, detail="Name must be 1 to 100 characters.")
```

and use `user.display_name = name`.

- [ ] **Step 7: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_api_security.py tests/test_auth.py tests/test_api.py tests/test_api_cookie_auth.py tests/test_security_hardening_16.py -o addopts="" -p no:cacheprovider`
Expected: PASS (the HTML enrol/disable tests in `test_auth.py` prove the old routes still behave).

- [ ] **Step 8: Regenerate types, format, commit**

```bash
cd web && npm run gen:api && npm run typecheck && cd ..
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
git add app/services/totp.py app/api/security.py app/api_auth.py app/routes/settings.py app/api/settings.py app/api/__init__.py tests/test_api_security.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(api): /settings/security for 2FA set up, enable and disable; shared TOTP helpers"
```

### Task B6: Passkey link and unlink return to the app (`return_to=app`)

**Stream:** B · **Depends on:** B5

**Files:**
- Modify: `app/web_app.py` (`link`, `unlink`, `callback`, `_clear_link_state`; new `APP_RETURN`, `APP_PROFILE`, `_back`)
- Test: `tests/test_oidc_routes.py` (append; it carries the autouse OIDC fixtures)

**Interfaces:**
- Produces (wire): `POST /app/auth/link` and `/app/auth/unlink` accept an optional form field `return_to`; only the literal `app` is honoured. With it every outcome (including the callback that completes a link, remembered in the session as `link_return`) redirects to `/app/settings/profile?passkey=linked|unlinked|error`. Without it nothing changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_oidc_routes.py`:

```python
# --- 2d §7.5: return_to=app sends link/unlink back to the new app's Profile ----

PROFILE = "/app/settings/profile"


def _post_link(client, hh, headers, fake, **extra):
    with patch("app.web_app.oidc_client", return_value=fake):
        return client.post(
            "/app/auth/link",
            data={**_link_form(hh), **extra},
            headers=headers,
            follow_redirects=False,
        )


def test_link_with_return_to_app_lands_on_profile(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub"})
    r = _post_link(client, hh, headers, fake, return_to="app")
    assert r.headers["location"].startswith("https://id.example.test/")
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == f"{PROFILE}?passkey=linked"


def test_link_refusals_with_return_to_app_say_error(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = _post_link(client, hh, headers, _redirecting_client(), return_to="app", password="nope")
    assert r.headers["location"] == f"{PROFILE}?passkey=error"


def test_link_denied_at_the_provider_with_return_to_app_says_error(
    client, db, make_household, login
):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    fake = _redirecting_client({"sub": "new-sub"})
    _post_link(client, hh, headers, fake, return_to="app")
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?error=access_denied&state=s", follow_redirects=False)
    assert r.headers["location"] == f"{PROFILE}?passkey=error"


def test_unlink_with_return_to_app(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    r = client.post("/app/auth/unlink", data={"return_to": "app"}, headers=headers,
                    follow_redirects=False)
    assert r.headers["location"] == f"{PROFILE}?passkey=unlinked"


def test_unknown_return_to_is_ignored(client, db, make_household, login):
    hh = make_household()
    headers = login(hh.username, hh.secret)
    r = _post_link(client, hh, headers, _redirecting_client(), return_to="https://evil.test",
                   password="nope")
    assert r.headers["location"] == "/settings?passkey_error=1"
    user = db.get(User, hh.user_id)
    user.oidc_subject = "s1"
    db.commit()
    r = client.post("/app/auth/unlink", data={"return_to": "/elsewhere"}, headers=headers,
                    follow_redirects=False)
    assert r.headers["location"] == "/settings?passkey=unlinked"
```

(`_link_form(hh)` produces a later-step code. In `test_link_refusals...` `password="nope"` overrides it through `**extra`.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_oidc_routes.py -k "return_to" -o addopts="" -p no:cacheprovider`
Expected: FAIL — locations are `/app/?linked=1`, `/settings?passkey_error=1`, `/app/?auth_error=denied`, `/settings?passkey=unlinked`.

- [ ] **Step 3: Implement**

In `app/web_app.py` after `LINK_MAX_AGE_SECONDS`:

```python
# 2d §7.5: the new app's Profile screen posts return_to=app; only that literal
# is honoured, so the redirect target can never come from the request.
APP_RETURN = "app"
APP_PROFILE = "/app/settings/profile"


def _back(to_app: bool, outcome: str, legacy: str) -> RedirectResponse:
    """Where a link or unlink ends: the app's Profile with ?passkey=<outcome>
    when the form said return_to=app, else ``legacy`` (unchanged)."""
    return RedirectResponse(f"{APP_PROFILE}?passkey={outcome}" if to_app else legacy, status_code=302)
```

`_clear_link_state` also pops `"link_return"`.

`link`: add the parameter `return_to: str = Form(""),` and `to_app = return_to == APP_RETURN`. Then:
- `if not found:` → `return _back(to_app, "error", "") if to_app else _fail("link_requires_login")`
- each `return RedirectResponse("/settings?passkey_error=1", status_code=302)` → `return _back(to_app, "error", "/settings?passkey_error=1")`
- after `request.session["link_started_at"] = int(time.time())`: `if to_app: request.session["link_return"] = APP_RETURN`

`unlink`: signature `async def unlink(request: Request, return_to: str = Form(""), db: Session = Depends(get_db)):`, `to_app = return_to == APP_RETURN`; the not-found branch returns `_back(to_app, "error", "/settings?passkey_error=1")`; the success response is `response = _back(to_app, "unlinked", "/settings?passkey=unlinked")` (the `set_session(...)` line stays).

`callback`: next to the `link_user_id` pop add

```python
    link_to_app = request.session.pop("link_return", None) == APP_RETURN

    def fail(code: str) -> RedirectResponse:
        """A failed link started from the app goes back to its Profile screen."""
        if link_user_id and link_to_app:
            request.session.clear()
            return _back(True, "error", "")
        return _fail_clear(request, code)
```

and replace every `return _fail_clear(request, <code>)` in `callback` with `return fail(<code>)`. The link success becomes `return _back(link_to_app, "linked", "/app/?linked=1")`.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_oidc_routes.py tests/test_oidc_identity.py -o addopts="" -p no:cacheprovider`
Expected: PASS (all old link/unlink tests unchanged).

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff format app tests && .venv/bin/ruff check app tests
git add app/web_app.py tests/test_oidc_routes.py
git commit -m "feat(auth): passkey link and unlink accept return_to=app and land on the app's Profile"
```

---

## Stream N: notification mutes (after 2c's B1)

**Precondition:** `main` contains 2c's migration `c9d0e1f2a3b4` (2c stream B1 merged) as well as M and B. Create this stream's worktree **from that `main`**. A file with `down_revision = "c9d0e1f2a3b4"` in a tree without that revision breaks `upgrade head` and `test_single_head`, so N cannot be started earlier. Until N ships, the Notifications screen shows the push toggle only (F4.4 handles the 404).

### Task N1: Table `notification_mutes` and migration `d0e1f2a3b4c5`

**Stream:** N · **Depends on:** 2c B1 merged, M, B

**Files:**
- Create: `alembic/versions/d0e1f2a3b4c5_notification_mutes.py`
- Modify: `app/models.py` (`NotificationMute` after `PushSubscription`)
- Test: `tests/test_migrations.py` (append)

**Interfaces:**
- Produces: `app.models.NotificationMute(user_id, household_id, type)`; `type` is a `NotificationType` value stored as `String(32)` (never the native PG enum).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migrations.py`:

```python
def test_notification_mutes_migration_chain_and_round_trip(tmp_path):
    """2d §7.6: d0e1f2a3b4c5 follows 2c's c9d0e1f2a3b4 and round-trips."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "mutes_mig", ROOT / "alembic" / "versions" / "d0e1f2a3b4c5_notification_mutes.py"
    )
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert (mig.revision, mig.down_revision) == ("d0e1f2a3b4c5", "c9d0e1f2a3b4")

    db_url = _db_url(tmp_path, "mutes.db")
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    cols = {c["name"] for c in inspect(create_engine(db_url)).get_columns("notification_mutes")}
    assert cols == {"user_id", "household_id", "type"}
    down = _alembic(["downgrade", "c9d0e1f2a3b4"], db_url)
    assert down.returncode == 0, down.stderr
    assert "notification_mutes" not in inspect(create_engine(db_url)).get_table_names()
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_migrations.py -k mutes -o addopts="" -p no:cacheprovider`
Expected: FAIL — `FileNotFoundError` for the migration file.

- [ ] **Step 3: Implement**

Create `alembic/versions/d0e1f2a3b4c5_notification_mutes.py`:

```python
"""notification_mutes: alert types a member turned off in a household

A row means muted; no row means on (2d spec §7.6). ``type`` holds a
NotificationType value as plain VARCHAR(32), validated in Python, so this
table never touches the native notificationtype enum.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-07 13:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_mutes",
        sa.Column(
            "user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "household_id", "type", name="pk_notification_mutes"),
    )


def downgrade() -> None:
    op.drop_table("notification_mutes")
```

In `app/models.py`, after `class PushSubscription`:

```python
class NotificationMute(Base):
    """An alert type one member turned off in one household (2d §7.6). A row
    means muted; the default is everything on. create_notification checks it,
    so muting stops both the in-app notification and the push."""

    __tablename__ = "notification_mutes"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    household_id = Column(
        String, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True
    )
    # A NotificationType value as plain VARCHAR: never the native PG enum.
    type = Column(String(32), primary_key=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_migrations.py -o addopts="" -p no:cacheprovider`, then the same with `TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t`.
Expected: PASS, including `test_single_head` and `test_schema_matches_models`.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/d0e1f2a3b4c5_notification_mutes.py app/models.py tests/test_migrations.py
git commit -m "feat(notifications): notification_mutes table (d0e1f2a3b4c5)"
```

### Task N2: Mutes in `create_notification` and `/settings/notifications`

**Stream:** N · **Depends on:** N1

**Files:**
- Create: `app/services/notification_prefs.py`
- Create: `app/api/notification_prefs.py`
- Modify: `app/services/notifications.py` (`create_notification` returns None when muted)
- Modify: `app/api/__init__.py` (include the router)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/schema.d.ts`
- Test: `tests/test_notification_mutes.py` (create)

**Interfaces:**
- Produces (Python): `ALERT_TYPES: tuple[AlertType, ...]` (`type`, `group`, `label`), `muted_types(db, user_id, household_id) -> set[str]`, `is_muted(db, *, user_id, household_id, type) -> bool`, `set_muted(db, user_id, household_id, disabled: list[str]) -> None` (raises `ValueError`).
- Produces (wire): `GET /api/v1/settings/notifications` → `{types: [{type, group, label, enabled}], push_devices: int}` (every `NotificationType` except `general`; `push_devices` = the caller's push subscriptions in this household). `PUT` `{disabled: [type, ...]}` replaces the caller's set for this household and returns the same shape; unknown or `general` → 400.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notification_mutes.py`:

```python
"""2d §7.6: per-type mutes per member and household, applied inside
create_notification (no row, no push); general can't be muted."""

from app.models import (
    Household,
    HouseholdMember,
    MemberRole,
    Notification,
    NotificationType,
    PushSubscription,
)
from app.services.notification_prefs import ALERT_TYPES
from app.services.notifications import create_notification
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/settings/notifications"


def test_catalog_covers_every_type_but_general():
    assert {a.type for a in ALERT_TYPES} == {t.value for t in NotificationType} - {"general"}
    assert len(ALERT_TYPES) == 9


def test_get_lists_types_on_by_default_and_counts_devices(client, db, api):  # noqa: F811
    headers, hh = api
    db.add(PushSubscription(user_id=hh.user_id, household_id=hh.household_id,
                            endpoint="https://web.push.apple.com/x", p256dh="k", auth="a"))
    db.commit()
    body = client.get(URL, headers=headers).json()
    assert body["push_devices"] == 1
    assert [t["type"] for t in body["types"]][:3] == ["bill_due", "bill_overdue", "bill_auto_paid"]
    assert all(t["enabled"] for t in body["types"])
    assert {t["group"] for t in body["types"]} == {"Bills", "Budgets", "Pantry", "Apple Pay"}


def test_put_replaces_the_set_and_mutes_creation(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.put(URL, headers=headers, json={"disabled": ["bill_due", "price_drop"]})
    assert r.status_code == 200, r.text
    off = {t["type"] for t in r.json()["types"] if not t["enabled"]}
    assert off == {"bill_due", "price_drop"}
    assert create_notification(db, household_id=hh.household_id, user_id=hh.user_id,
                               type=NotificationType.bill_due, title="Due") is None
    assert create_notification(db, household_id=hh.household_id, user_id=hh.user_id,
                               type=NotificationType.bill_overdue, title="Late") is not None
    db.commit()
    assert db.query(Notification).count() == 1

    r = client.put(URL, headers=headers, json={"disabled": []})
    assert all(t["enabled"] for t in r.json()["types"])


def test_general_and_unknown_cannot_be_muted(client, api):  # noqa: F811
    headers, _ = api
    for bad in (["general"], ["nope"]):
        assert client.put(URL, headers=headers, json={"disabled": bad}).status_code == 400


def test_mutes_are_per_household(client, db, api):  # noqa: F811
    headers, hh = api
    client.put(URL, headers=headers, json={"disabled": ["bill_due"]})
    second = Household(name="Second", default_currency="EUR")
    db.add(second)
    db.flush()
    db.add(HouseholdMember(household_id=second.id, user_id=hh.user_id, role=MemberRole.member))
    db.commit()
    assert create_notification(db, household_id=second.id, user_id=hh.user_id,
                               type=NotificationType.bill_due, title="Due") is not None


def test_a_muted_scheduler_alert_sends_no_push(db, make_household, monkeypatch):
    from app.scheduler import _notify_members
    from app.services.notification_prefs import set_muted

    hh = make_household()
    set_muted(db, hh.user_id, hh.household_id, ["bill_auto_paid"])
    db.commit()
    sent = []
    monkeypatch.setattr("app.services.notifications.send_push_for_notification",
                        lambda db, n, target_subs=None: sent.append(n) or 0)
    _notify_members(db, [hh.user_id], household_id=hh.household_id,
                    type=NotificationType.bill_auto_paid, title="Auto-paid: X", body=None,
                    link="/bills", dedupe_key="bill_auto_paid:x")
    db.commit()
    assert db.query(Notification).count() == 0 and sent == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_notification_mutes.py -o addopts="" -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: app.services.notification_prefs`.

- [ ] **Step 3: The service**

Create `app/services/notification_prefs.py`:

```python
"""Which alert types a member gets, per household (2d §7.6). Everything is on
by default; a NotificationMute row turns one type off for in-app and push.
``general`` (sign-in alerts, test pushes) can never be muted."""

from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models import NotificationMute, NotificationType


class AlertType(NamedTuple):
    type: str
    group: str
    label: str


ALERT_TYPES: tuple[AlertType, ...] = (
    AlertType(NotificationType.bill_due.value, "Bills", "Due in 3 days"),
    AlertType(NotificationType.bill_overdue.value, "Bills", "Overdue"),
    AlertType(NotificationType.bill_auto_paid.value, "Bills", "Paid automatically"),
    AlertType(NotificationType.contract_expiring.value, "Bills", "Contract ending"),
    AlertType(NotificationType.bill_drift.value, "Bills", "Amount changed"),
    AlertType(NotificationType.budget_warning.value, "Budgets", "Budget limit reached"),
    AlertType(NotificationType.stock_low.value, "Pantry", "Running low"),
    AlertType(NotificationType.price_drop.value, "Pantry", "Price drops"),
    AlertType(NotificationType.ingest_created.value, "Apple Pay", "Each new purchase"),
)
MUTABLE = frozenset(a.type for a in ALERT_TYPES)


def muted_types(db: Session, user_id: str, household_id: str) -> set[str]:
    return {
        t
        for (t,) in db.query(NotificationMute.type).filter_by(
            user_id=user_id, household_id=household_id
        )
    }


def is_muted(db: Session, *, user_id: str, household_id: str, type) -> bool:
    value = NotificationType(type).value
    if value not in MUTABLE:
        return False
    return (
        db.query(NotificationMute.type)
        .filter_by(user_id=user_id, household_id=household_id, type=value)
        .first()
        is not None
    )


def set_muted(db: Session, user_id: str, household_id: str, disabled: list[str]) -> None:
    """Replace this member's muted set for the household. Raises ValueError
    for an unknown type or ``general``. Does not commit."""
    wanted = set()
    for value in disabled:
        if value == NotificationType.general.value:
            raise ValueError("General alerts can't be turned off.")
        if value not in MUTABLE:
            raise ValueError(f"Unknown alert type '{value}'.")
        wanted.add(value)
    db.query(NotificationMute).filter_by(user_id=user_id, household_id=household_id).delete(
        synchronize_session=False
    )
    for value in sorted(wanted):
        db.add(NotificationMute(user_id=user_id, household_id=household_id, type=value))
    db.flush()
```

In `app/services/notifications.py` `create_notification`, first lines of the body (docstring: "Returns None, creating nothing, when the recipient muted this type in this household (2d §7.6)."):

```python
    from app.services.notification_prefs import is_muted

    if is_muted(db, user_id=user_id, household_id=household_id, type=type):
        return None
```

- [ ] **Step 4: The router**

Create `app/api/notification_prefs.py`:

```python
"""/api/v1/settings/notifications: alert types on or off for the caller in
this household (2d §7.6). Push subscriptions themselves stay on the cookie
routes /push/* (app/routes/notifications.py)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.models import PushSubscription
from app.services.notification_prefs import ALERT_TYPES, muted_types, set_muted

router = APIRouter(prefix="/settings/notifications", tags=["settings"])


class AlertTypeOut(BaseModel):
    type: str
    group: str  # Bills | Budgets | Pantry | Apple Pay
    label: str
    enabled: bool


class NotificationPrefsOut(BaseModel):
    types: list[AlertTypeOut]
    push_devices: int  # the caller's push subscriptions in this household


class NotificationPrefsIn(BaseModel):
    disabled: list[str]


def _prefs(db: Session, user_id: str, hh_id: str) -> NotificationPrefsOut:
    muted = muted_types(db, user_id, hh_id)
    devices = (
        db.query(PushSubscription).filter_by(user_id=user_id, household_id=hh_id).count()
    )
    return NotificationPrefsOut(
        types=[
            AlertTypeOut(type=a.type, group=a.group, label=a.label, enabled=a.type not in muted)
            for a in ALERT_TYPES
        ],
        push_devices=devices,
    )


@router.get("", response_model=NotificationPrefsOut)
def get_prefs(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return _prefs(db, user.id, hh_id)


@router.put("", response_model=NotificationPrefsOut)
def put_prefs(
    body: NotificationPrefsIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    user, hh_id = auth
    try:
        set_muted(db, user.id, hh_id, body.disabled)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    return _prefs(db, user.id, hh_id)
```

In `app/api/__init__.py`, import `notification_prefs` and add `router.include_router(notification_prefs.router)` after the `security` line.

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_notification_mutes.py tests/test_alerts.py tests/test_scheduler.py tests/test_ingest.py tests/test_login_alerts.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Regenerate types, format, commit**

```bash
cd web && npm ci && npm run gen:api && npm run typecheck && cd ..
.venv/bin/ruff format app tests alembic && .venv/bin/ruff check app tests alembic
git add app/services/notification_prefs.py app/api/notification_prefs.py app/services/notifications.py app/api/__init__.py tests/test_notification_mutes.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(notifications): per-type mutes in create_notification and /settings/notifications"
```

---
## Stream F1: kit additions, charts, period and lens, data plumbing

F1.1–F1.4 need only 2a stream A on `main`. F1.5–F1.7 also need stream B on `main` (they read B's generated types); rebase before starting F1.5.

### Task F1.1: `Chips` and `Toggle`

**Stream:** F1 · **Depends on:** 2a stream A merged

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/ui/Chips.tsx`, `web/src/ui/Toggle.tsx`, `web/src/ui/controls.css`
- Test: `web/src/ui/controls.test.tsx` (create)

**Interfaces:**
- Produces:
  - `Chips<T extends string>(props: { label: string; options: { value: T; label: string }[] } & ({ multiple?: false; value: T; onChange(v: T): void } | { multiple: true; value: T[]; onChange(v: T[]): void }))` — a `role="group"` of `<button aria-pressed>`.
  - `Toggle(props: { label: string; checked: boolean; onChange(next: boolean): void; busy?: boolean; disabled?: boolean })` — `role="switch"`, `aria-checked`, ignores taps while `busy`.
  - (Secret sheets use 2a's `<Sheet closeOnBackdrop={false}>`; nothing to add to `Sheet`.)

- [ ] **Step 1: Write the failing tests**

Create `web/src/ui/controls.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Chips } from './Chips'
import { Toggle } from './Toggle'

const OPTIONS = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
] as const

describe('Chips', () => {
  it('single select presses one chip and reports the new value', () => {
    const onChange = vi.fn()
    render(<Chips label="Period" options={[...OPTIONS]} value="a" onChange={onChange} />)
    expect(screen.getByRole('group', { name: 'Period' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
    expect(onChange).toHaveBeenCalledWith('b')
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    expect(onChange).toHaveBeenCalledTimes(1) // re-selecting the selected chip is a no-op
  })

  it('multi select toggles membership', () => {
    const onChange = vi.fn()
    render(<Chips multiple label="Budgets" options={[...OPTIONS]} value={['a']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    expect(onChange).toHaveBeenLastCalledWith([])
    fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
    expect(onChange).toHaveBeenLastCalledWith(['a', 'b'])
  })
})

describe('Toggle', () => {
  it('is a labelled switch that reports the next state', () => {
    const onChange = vi.fn()
    render(<Toggle label="Overdue" checked onChange={onChange} />)
    const sw = screen.getByRole('switch', { name: 'Overdue' })
    expect(sw).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(sw)
    expect(onChange).toHaveBeenCalledWith(false)
  })

  it('ignores taps while busy and when disabled', () => {
    const onChange = vi.fn()
    const { rerender } = render(<Toggle label="Push" checked={false} busy onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(screen.getByRole('switch')).toHaveAttribute('aria-busy', 'true')
    rerender(<Toggle label="Push" checked={false} disabled onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(onChange).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run (in `web/`): `npm test -- src/ui/controls.test.tsx`
Expected: FAIL — cannot resolve `./Chips` / `./Toggle`.

- [ ] **Step 3: Implement**

`web/src/ui/Chips.tsx`:

```tsx
import './controls.css'

interface Option<T extends string> { value: T; label: string }
interface Common<T extends string> { label: string; options: Option<T>[] }
type Single<T extends string> = Common<T> & { multiple?: false; value: T; onChange(value: T): void }
type Multi<T extends string> = Common<T> & { multiple: true; value: T[]; onChange(value: T[]): void }

/** Single- or multi-select chips: buttons with aria-pressed in a labelled group. */
export function Chips<T extends string>(props: Single<T> | Multi<T>) {
  const pressed = (v: T) => (props.multiple ? props.value.includes(v) : props.value === v)
  const tap = (v: T) => {
    if (props.multiple) {
      props.onChange(pressed(v) ? props.value.filter((x) => x !== v) : [...props.value, v])
    } else if (props.value !== v) {
      props.onChange(v)
    }
  }
  return (
    <div className="chips" role="group" aria-label={props.label}>
      {props.options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="chip"
          aria-pressed={pressed(o.value)}
          onClick={() => tap(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
```

`web/src/ui/Toggle.tsx`:

```tsx
import './controls.css'

export interface ToggleProps {
  label: string
  checked: boolean
  onChange(next: boolean): void
  /** A request is in flight: taps are ignored and the switch says so. */
  busy?: boolean
  disabled?: boolean
}

export function Toggle({ label, checked, onChange, busy = false, disabled = false }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      className="toggle"
      aria-label={label}
      aria-checked={checked}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={() => {
        if (!busy && !disabled) onChange(!checked)
      }}
    >
      <span className="toggle__thumb" aria-hidden="true" />
    </button>
  )
}
```

`web/src/ui/controls.css` (tokens from `tokens.css`; 44 px targets; no load animation; transitions only on state change and off under reduced motion):

```css
.chips { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; padding: 2px 0; }
.chips::-webkit-scrollbar { display: none; }
.chip {
  min-height: 44px; padding: 0 14px; border-radius: 999px; flex: none;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink-2);
  font: 600 14px/1 var(--font-text, inherit); -webkit-tap-highlight-color: transparent;
}
.chip[aria-pressed='true'] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.chip:focus-visible, .toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.toggle {
  position: relative; flex: none; width: 51px; height: 31px; border-radius: 999px;
  border: 0; background: var(--line); padding: 0; margin: 6.5px 0; /* 44px tap row */
  -webkit-tap-highlight-color: transparent;
}
.toggle::after { content: ''; position: absolute; inset: -6.5px 0; } /* extends the hit area */
.toggle[aria-checked='true'] { background: var(--pos, var(--c2)); }
.toggle[aria-busy='true'] { opacity: 0.6; }
.toggle:disabled { opacity: 0.4; }
.toggle__thumb {
  position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%;
  background: #fff; box-shadow: 0 2px 4px rgb(0 0 0 / 0.25); transition: transform 0.2s ease;
}
.toggle[aria-checked='true'] .toggle__thumb { transform: translateX(20px); }
@media (prefers-reduced-motion: reduce) { .toggle__thumb { transition: none; } }
```

(Use the variable names `tokens.css` really defines for line, surface, ink and accent; check the file and the mock `components.css` `.chip` / `.toggle` rules.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/ui/controls.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui/Chips.tsx web/src/ui/Toggle.tsx web/src/ui/controls.css web/src/ui/controls.test.tsx
git commit -m "feat(web/ui): Chips and Toggle"
```

### Task F1.2: Chart scale helpers, `HBarList` and `StackBar`

**Stream:** F1 · **Depends on:** F1.1

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/ui/charts/scale.ts`, `web/src/ui/charts/HBarList.tsx`, `web/src/ui/charts/StackBar.tsx`, `web/src/ui/charts/charts.css`
- Test: `web/src/ui/charts/bars.test.tsx`

**Interfaces:**
- Produces:
  - `scaleMax(values: readonly number[]): number` (never 0), `barPct(value: number, max: number): number` (0–100, 0 for ≤0/NaN), `seriesColor(index: number): string` (`var(--c1)`..`var(--c6)`).
  - `HBarList(props: { label: string; rows: HBarRow[]; format(n: number): string; onSelect?(row: HBarRow): void })`, `HBarRow = { id: string; label: string; value: number; icon?: string; hatched?: boolean }`. Values are printed on every row (the text equivalent); hatched rows say "not logged" and are never buttons.
  - `StackBar(props: { label: string; segments: StackSegment[]; format(n: number): string })`, `StackSegment = { id: string; label: string; value: number; hatched?: boolean }`; `role="img"` with an `aria-label` listing every segment.

- [ ] **Step 1: Write the failing tests**

Create `web/src/ui/charts/bars.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { barPct, scaleMax, seriesColor } from './scale'
import { HBarList } from './HBarList'
import { StackBar } from './StackBar'

const eur = (n: number) => `€${n.toFixed(2)}`

describe('scale', () => {
  it('never divides by zero', () => {
    expect(scaleMax([0, 0])).toBe(1)
    expect(scaleMax([])).toBe(1)
    expect(scaleMax([3, Number.NaN, 7])).toBe(7)
    expect(barPct(0, 1)).toBe(0)
    expect(barPct(-5, 10)).toBe(0)
    expect(barPct(5, 10)).toBe(50)
    expect(barPct(50, 10)).toBe(100)
  })
  it('cycles the six token colours', () => {
    expect(seriesColor(0)).toBe('var(--c1)')
    expect(seriesColor(6)).toBe('var(--c1)')
  })
})

describe('HBarList', () => {
  const rows = [
    { id: 'g', label: 'Groceries', value: 400 },
    { id: 'uncategorised', label: 'Uncategorised', value: 100 },
    { id: '__cash_not_logged__', label: 'Cash (not yet logged)', value: 45, hatched: true },
  ]

  it('prints every value and scales bars to the largest', () => {
    const { container } = render(<HBarList label="Where it went" rows={rows} format={eur} />)
    expect(screen.getByText('€400.00')).toBeInTheDocument()
    expect(screen.getByText('€45.00')).toBeInTheDocument()
    const fills = container.querySelectorAll<HTMLElement>('.hbars__fill')
    expect(fills[0].style.width).toBe('100%')
    expect(fills[1].style.width).toBe('25%')
  })

  it('hatched rows say "not logged" and are not tappable', () => {
    const onSelect = vi.fn()
    const { container } = render(<HBarList label="Where" rows={rows} format={eur} onSelect={onSelect} />)
    expect(screen.getByText('not logged')).toBeInTheDocument()
    expect(container.querySelector('.hbars__fill--hatched')).not.toBeNull()
    expect(screen.getAllByRole('button')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: /Uncategorised/ }))
    expect(onSelect).toHaveBeenCalledWith(rows[1])
  })

  it('survives an all-zero list', () => {
    const { container } = render(
      <HBarList label="Where" rows={[{ id: 'a', label: 'A', value: 0 }]} format={eur} />,
    )
    expect(container.innerHTML).not.toContain('NaN')
  })
})

describe('StackBar', () => {
  it('sizes segments by share and names them all', () => {
    const { container } = render(
      <StackBar
        label="How you paid"
        format={eur}
        segments={[
          { id: 'card', label: 'Card', value: 75 },
          { id: 'cash', label: 'Cash', value: 25 },
        ]}
      />,
    )
    expect(screen.getByRole('img', { name: 'How you paid: Card €75.00, Cash €25.00' })).toBeInTheDocument()
    const parts = container.querySelectorAll<HTMLElement>('.stackbar__seg')
    expect([parts[0].style.width, parts[1].style.width]).toEqual(['75%', '25%'])
  })

  it('draws an empty track for a zero total', () => {
    const { container } = render(<StackBar label="How you paid" format={eur} segments={[]} />)
    expect(container.querySelectorAll('.stackbar__seg')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('NaN')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/ui/charts/bars.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`web/src/ui/charts/scale.ts`:

```ts
/** The value bars are scaled against. Never 0, so an all-zero series draws empty bars, not NaN. */
export function scaleMax(values: readonly number[]): number {
  let max = 0
  for (const v of values) if (Number.isFinite(v) && v > max) max = v
  return max > 0 ? max : 1
}

/** A bar's length as a percentage of `max`, clamped to 0–100; negative and NaN draw nothing. */
export function barPct(value: number, max: number): number {
  if (!Number.isFinite(value) || value <= 0 || !(max > 0)) return 0
  return Math.min(100, (value / max) * 100)
}

/** The token series: --c1..--c6 switch with the theme (tokens.css). */
export function seriesColor(index: number): string {
  return `var(--c${(index % 6) + 1})`
}
```

`web/src/ui/charts/HBarList.tsx`:

```tsx
import type { CSSProperties } from 'react'
import { barPct, scaleMax, seriesColor } from './scale'
import './charts.css'

export interface HBarRow {
  id: string
  label: string
  value: number
  icon?: string
  /** Cash not logged yet: hatched, labelled "not logged", never tappable. */
  hatched?: boolean
}

export interface HBarListProps {
  label: string
  rows: HBarRow[]
  format(n: number): string
  onSelect?(row: HBarRow): void
}

/** Horizontal bars with the value written on every row (the text equivalent). */
export function HBarList({ label, rows, format, onSelect }: HBarListProps) {
  const max = scaleMax(rows.map((r) => r.value))
  return (
    <ul className="hbars" aria-label={label}>
      {rows.map((row, i) => {
        const style = { width: `${barPct(row.value, max)}%`, '--bar': seriesColor(i) } as CSSProperties
        const body = (
          <>
            <span className="hbars__head">
              {row.icon && <span className="hbars__icon" aria-hidden="true">{row.icon}</span>}
              <span className="hbars__label">{row.label}</span>
              {row.hatched && <span className="hbars__note">not logged</span>}
              <span className="hbars__value num">{format(row.value)}</span>
            </span>
            <span className="hbars__track" aria-hidden="true">
              <span className={row.hatched ? 'hbars__fill hbars__fill--hatched' : 'hbars__fill'} style={style} />
            </span>
          </>
        )
        return (
          <li key={row.id}>
            {onSelect && !row.hatched ? (
              <button type="button" className="hbars__row" onClick={() => onSelect(row)}>{body}</button>
            ) : (
              <div className="hbars__row">{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
```

`web/src/ui/charts/StackBar.tsx`:

```tsx
import type { CSSProperties } from 'react'
import { seriesColor } from './scale'
import './charts.css'

export interface StackSegment { id: string; label: string; value: number; hatched?: boolean }

/** One horizontal bar split by share. The accessible name lists every segment; callers
 *  also render the list underneath (widget 8), so the numbers are visible too. */
export function StackBar({ label, segments, format }: { label: string; segments: StackSegment[]; format(n: number): string }) {
  const shown = segments.filter((s) => Number.isFinite(s.value) && s.value > 0)
  const total = shown.reduce((sum, s) => sum + s.value, 0)
  const name = `${label}: ${shown.map((s) => `${s.label} ${format(s.value)}`).join(', ')}`
  return (
    <div className="stackbar" role="img" aria-label={shown.length ? name : `${label}: nothing yet`}>
      {total > 0 &&
        shown.map((s, i) => (
          <span
            key={s.id}
            className={s.hatched ? 'stackbar__seg stackbar__seg--hatched' : 'stackbar__seg'}
            style={{ width: `${Math.round((s.value / total) * 1000) / 10}%`, '--bar': seriesColor(i) } as CSSProperties}
          />
        ))}
    </div>
  )
}
```

`web/src/ui/charts/charts.css` (shared by every chart; no load animation):

```css
.hbars { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.hbars__row {
  display: grid; gap: 6px; width: 100%; min-height: 44px; padding: 8px 0;
  background: none; border: 0; color: inherit; text-align: left; font: inherit;
  -webkit-tap-highlight-color: transparent;
}
.hbars__head { display: flex; align-items: baseline; gap: 8px; }
.hbars__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hbars__note { font-size: 12px; color: var(--ink-3, var(--ink-2)); }
.hbars__value, .num { font-variant-numeric: tabular-nums; }
.hbars__track { height: 8px; border-radius: 4px; background: color-mix(in srgb, var(--ink) 8%, transparent); overflow: hidden; }
.hbars__fill { display: block; height: 100%; border-radius: 4px; background: var(--bar); }
.hbars__fill--hatched, .stackbar__seg--hatched {
  background: repeating-linear-gradient(135deg, var(--bar) 0 3px, transparent 3px 6px);
  box-shadow: inset 0 0 0 1px var(--bar);
}
.stackbar { display: flex; height: 14px; border-radius: 7px; overflow: hidden; gap: 2px;
  background: color-mix(in srgb, var(--ink) 8%, transparent); }
.stackbar__seg { display: block; height: 100%; background: var(--bar); }
.chart { display: block; width: 100%; height: auto; overflow: visible; }
.chart text { font: 500 10px/1 var(--font-mono, ui-monospace, monospace); fill: var(--ink-2); font-variant-numeric: tabular-nums; }
.chart .chart__grid { stroke: var(--line); stroke-width: 1; }
.chart-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
```

(Check the real token names in `web/src/styles/tokens.css`; `--ink`, `--ink-2`, `--line`, `--accent` are the mock's.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/ui/charts/bars.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui/charts/scale.ts web/src/ui/charts/HBarList.tsx web/src/ui/charts/StackBar.tsx web/src/ui/charts/charts.css web/src/ui/charts/bars.test.tsx
git commit -m "feat(web/charts): scale helpers, HBarList and StackBar with text equivalents"
```

### Task F1.3: `MonthBars` and `LineChart` (SVG)

**Stream:** F1 · **Depends on:** F1.2

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/ui/charts/MonthBars.tsx`, `web/src/ui/charts/LineChart.tsx`, `web/src/ui/charts/index.ts`
- Test: `web/src/ui/charts/svg.test.tsx`

**Interfaces:**
- Produces:
  - `MonthBars(props: { title: string; months: string[]; series: { name: string; values: number[] }[]; format(n: number): string; current?: boolean; height?: number; width?: number })` — 1 or 2 series (grouped), the largest value printed above its bar, month initials under the bars, the running month drawn lighter when `current`; a visually hidden `<table>` with every value (the SVG is `aria-hidden`).
  - `LineChart(props: { title: string; points: { label: string; value: number }[]; format(n: number): string; average?: number | null; height?: number })` — line plus dots, first and last value printed, optional dashed average line; a visually hidden table.
  - `web/src/ui/charts/index.ts` re-exports `HBarList`, `StackBar`, `MonthBars`, `LineChart` and their types.

- [ ] **Step 1: Write the failing tests**

Create `web/src/ui/charts/svg.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LineChart, MonthBars } from './index'

const eur = (n: number) => `€${n.toFixed(2)}`
const MONTHS = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']

describe('MonthBars', () => {
  it('has a table with every value for two series', () => {
    render(
      <MonthBars
        title="In and Out by month"
        months={MONTHS}
        series={[
          { name: 'In', values: [3000, 3000, 3100, 3000, 3000, 1500] },
          { name: 'Out', values: [2180, 2410, 2050, 2960, 2240, 1284.6] },
        ]}
        format={eur}
        current
      />,
    )
    const table = screen.getByRole('table', { name: 'In and Out by month' })
    expect(within(table).getAllByRole('row')).toHaveLength(7)
    expect(within(table).getByRole('rowheader', { name: 'Oct (so far)' })).toBeInTheDocument()
    expect(within(table).getByText('€1284.60')).toBeInTheDocument()
  })

  it('draws one bar per month per series and labels the largest', () => {
    const { container } = render(
      <MonthBars title="Spend" months={MONTHS} series={[{ name: 'Spend', values: [1, 2, 9, 3, 4, 5] }]} format={eur} />,
    )
    expect(container.querySelectorAll('svg rect.chart__bar')).toHaveLength(6)
    expect(container.querySelector('svg text.chart__max')?.textContent).toBe('€9.00')
  })

  it('survives an all-zero series', () => {
    const { container } = render(
      <MonthBars title="Spend" months={MONTHS} series={[{ name: 'Spend', values: [0, 0, 0, 0, 0, 0] }]} format={eur} />,
    )
    expect(container.innerHTML).not.toContain('NaN')
    expect(container.querySelector('svg text.chart__max')).toBeNull()
  })
})

describe('LineChart', () => {
  const points = [1.79, 1.82, 1.86, 1.88, 1.83, 1.859].map((v, i) => ({ label: `Fill ${i + 1}`, value: v }))
  const per = (n: number) => `€${n.toFixed(3)}`

  it('has a table and prints the first and last values', () => {
    const { container } = render(<LineChart title="Price per litre" points={points} format={per} average={1.84} />)
    expect(screen.getByRole('table', { name: 'Price per litre' })).toBeInTheDocument()
    const labels = [...container.querySelectorAll('svg text')].map((t) => t.textContent)
    expect(labels).toEqual(expect.arrayContaining(['€1.790', '€1.859', 'avg €1.840']))
    expect(container.querySelectorAll('svg circle')).toHaveLength(6)
  })

  it('survives one point and a flat series', () => {
    const one = render(<LineChart title="P" points={[{ label: 'a', value: 2 }]} format={per} />)
    expect(one.container.innerHTML).not.toContain('NaN')
    const flat = render(<LineChart title="Q" points={[{ label: 'a', value: 0 }, { label: 'b', value: 0 }]} format={per} />)
    expect(flat.container.innerHTML).not.toContain('NaN')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/ui/charts/svg.test.tsx`
Expected: FAIL — `./index` not found.

- [ ] **Step 3: Implement**

`web/src/ui/charts/MonthBars.tsx`:

```tsx
import { scaleMax, seriesColor } from './scale'
import './charts.css'

export interface MonthSeries { name: string; values: number[] }
export interface MonthBarsProps {
  /** Accessible name, also the hidden table's caption. */
  title: string
  /** Oldest first. */
  months: string[]
  /** One or two series, one value per month. */
  series: MonthSeries[]
  format(n: number): string
  /** The last month is still running: drawn lighter and called "so far". */
  current?: boolean
  width?: number
  height?: number
}

const TOP = 16 // room for the max label
const BOTTOM = 18 // room for the month initials

export function MonthBars({ title, months, series, format, current = false, width = 306, height = 130 }: MonthBarsProps) {
  const all = series.flatMap((s) => s.values)
  const max = scaleMax(all)
  const realMax = Math.max(0, ...all.filter(Number.isFinite))
  const plotH = height - TOP - BOTTOM
  const group = width / Math.max(months.length, 1)
  const gap = 2
  const bar = series.length > 1 ? Math.min(14, group * 0.32) : Math.min(22, group * 0.5)
  const span = series.length * bar + (series.length - 1) * gap
  let maxLabel: { x: number; y: number } | null = null

  const rects = months.flatMap((_, m) =>
    series.map((s, k) => {
      const v = Number.isFinite(s.values[m]) && s.values[m] > 0 ? s.values[m] : 0
      const h = (v / max) * plotH
      const x = m * group + (group - span) / 2 + k * (bar + gap)
      const y = TOP + plotH - h
      if (realMax > 0 && v === realMax && !maxLabel) maxLabel = { x: x + bar / 2, y: y - 4 }
      const running = current && m === months.length - 1
      return (
        <rect
          key={`${m}-${k}`}
          className="chart__bar"
          x={x}
          y={y}
          width={bar}
          height={h}
          rx={Math.min(3, bar / 2)}
          style={{ fill: seriesColor(k), fillOpacity: running ? 0.5 : 1 }}
        />
      )
    }),
  )
  const label = maxLabel as { x: number; y: number } | null

  return (
    <figure className="chart-fig">
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
        <line className="chart__grid" x1={0} x2={width} y1={TOP + plotH} y2={TOP + plotH} />
        {rects}
        {label && (
          <text className="chart__max" x={label.x} y={Math.max(10, label.y)} textAnchor="middle">
            {format(realMax)}
          </text>
        )}
        {months.map((m, i) => (
          <text key={m + i} x={i * group + group / 2} y={height - 4} textAnchor="middle">
            {m.slice(0, 1)}
          </text>
        ))}
      </svg>
      <table className="chart-sr">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Month</th>
            {series.map((s) => <th scope="col" key={s.name}>{s.name}</th>)}
          </tr>
        </thead>
        <tbody>
          {months.map((m, i) => (
            <tr key={m + i}>
              <th scope="row">{current && i === months.length - 1 ? `${m} (so far)` : m}</th>
              {series.map((s) => <td key={s.name}>{format(s.values[i] ?? 0)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
```

`web/src/ui/charts/LineChart.tsx`:

```tsx
import './charts.css'

export interface LinePoint { label: string; value: number }
export interface LineChartProps {
  title: string
  points: LinePoint[]
  format(n: number): string
  average?: number | null
  width?: number
  height?: number
}

const PAD_X = 28
const PAD_TOP = 18
const PAD_BOTTOM = 14

export function LineChart({ title, points, format, average = null, width = 306, height = 132 }: LineChartProps) {
  const values = points.map((p) => (Number.isFinite(p.value) ? p.value : 0))
  const domain = average != null ? [...values, average] : values
  let lo = Math.min(...domain, Infinity)
  let hi = Math.max(...domain, -Infinity)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) { lo = 0; hi = 1 }
  if (hi - lo < 1e-9) { const pad = Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad }
  const plotH = height - PAD_TOP - PAD_BOTTOM
  const y = (v: number) => PAD_TOP + plotH - ((v - lo) / (hi - lo)) * plotH
  const x = (i: number) => (points.length > 1 ? PAD_X + (i / (points.length - 1)) * (width - 2 * PAD_X) : width / 2)
  const path = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const last = values.length - 1

  return (
    <figure className="chart-fig">
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
        {average != null && (
          <>
            <line className="chart__grid" x1={PAD_X} x2={width - PAD_X} y1={y(average)} y2={y(average)} strokeDasharray="4 4" />
            <text x={width - PAD_X} y={y(average) - 4} textAnchor="end">{`avg ${format(average)}`}</text>
          </>
        )}
        {values.length > 1 && <path d={path} fill="none" style={{ stroke: 'var(--c1)', strokeWidth: 2 }} />}
        {values.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={i === last ? 4 : 3} style={{ fill: 'var(--c1)' }} />
        ))}
        {values.length > 0 && <text x={x(0)} y={y(values[0]) - 8} textAnchor="middle">{format(values[0])}</text>}
        {last > 0 && <text x={x(last)} y={y(values[last]) - 8} textAnchor="middle">{format(values[last])}</text>}
      </svg>
      <table className="chart-sr">
        <caption>{title}</caption>
        <tbody>
          {points.map((p, i) => (
            <tr key={i}><th scope="row">{p.label}</th><td>{format(values[i])}</td></tr>
          ))}
          {average != null && <tr><th scope="row">Average</th><td>{format(average)}</td></tr>}
        </tbody>
      </table>
    </figure>
  )
}
```

`web/src/ui/charts/index.ts`:

```ts
export { HBarList, type HBarRow } from './HBarList'
export { StackBar, type StackSegment } from './StackBar'
export { MonthBars, type MonthSeries } from './MonthBars'
export { LineChart, type LinePoint } from './LineChart'
export { barPct, scaleMax, seriesColor } from './scale'
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/ui/charts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui/charts/MonthBars.tsx web/src/ui/charts/LineChart.tsx web/src/ui/charts/index.ts web/src/ui/charts/svg.test.tsx
git commit -m "feat(web/charts): MonthBars and LineChart as SVG with hidden data tables"
```

### Task F1.4: `period.ts` and `lens.ts`

**Stream:** F1 · **Depends on:** F1.1 (no code dependency; same worktree)

**Files:**
- Create: `web/src/features/insights/period.ts`, `web/src/features/insights/lens.ts`
- Test: `web/src/features/insights/period.test.tsx`, `web/src/features/insights/lens.test.tsx`

**Interfaces:**
- Produces (`period.ts`): `type Preset = 'this_month' | 'last_month' | 'last_3m' | 'last_6m' | 'this_year' | 'custom'`; `interface Period { preset: Preset; from?: string; to?: string }`; `DEFAULT_PERIOD`; `PRESETS: { value: Preset; label: string }[]`; `isIsoDate(s)`; `rangeError(from?, to?): string | null`; `normalisePeriod(p): Period | null`; `parsePeriod(params: URLSearchParams): Period | null`; `writePeriod(params, p): URLSearchParams`; `periodQuery(p): { preset: Preset; start_date?: string; end_date?: string }`; `periodKey(p): string`; `periodPhrase(p): string`; `previousPeriod(p, rangeStart: string | null, rangeEnd: string | null): Period | null`; `PERIOD_STORAGE_KEY`; `usePeriod(): [Period, (next: Period) => void]`.
- Produces (`lens.ts`): `type Lens = string`; `HOUSEHOLD = 'household'`; `interface LensMember { user_id: string; display_name: string | null; username: string | null }`; `lensOptions(members, meId): { value: string; label: string }[]`; `resolveLens(raw: string | null, members?: LensMember[]): Lens`; `lensQuery(lens): { paid_by?: string }`; `insightsSearch(period: Period, lens: Lens): string` (`"?p=…&lens=…"`); `LENS_STORAGE_KEY`; `useLens(members?: LensMember[]): [Lens, (next: Lens) => void]`.

- [ ] **Step 1: Write the failing tests**

`web/src/features/insights/period.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import {
  PERIOD_STORAGE_KEY,
  parsePeriod,
  periodKey,
  periodQuery,
  previousPeriod,
  rangeError,
  usePeriod,
  writePeriod,
} from './period'

const q = (s: string) => new URLSearchParams(s)

describe('parsePeriod', () => {
  it('reads presets and valid custom ranges', () => {
    expect(parsePeriod(q('p=last_3m'))).toEqual({ preset: 'last_3m' })
    expect(parsePeriod(q('p=custom&from=2026-09-01&to=2026-09-30'))).toEqual({
      preset: 'custom', from: '2026-09-01', to: '2026-09-30',
    })
  })
  it('rejects junk, From after To and malformed dates', () => {
    expect(parsePeriod(q(''))).toBeNull()
    expect(parsePeriod(q('p=all_time'))).toBeNull()
    expect(parsePeriod(q('p=custom&from=2026-10-06&to=2026-10-01'))).toBeNull()
    expect(parsePeriod(q('p=custom&from=2026-02-30&to=2026-03-01'))).toBeNull()
    expect(parsePeriod(q('p=custom&from=2026-10-01'))).toBeNull()
  })
})

describe('helpers', () => {
  it('writes and clears from/to', () => {
    const custom = writePeriod(q('lens=u1'), { preset: 'custom', from: '2026-09-01', to: '2026-09-02' })
    expect(custom.toString()).toBe('lens=u1&p=custom&from=2026-09-01&to=2026-09-02')
    expect(writePeriod(custom, { preset: 'this_year' }).toString()).toBe('lens=u1&p=this_year')
  })
  it('maps to the API query and a cache key', () => {
    expect(periodQuery({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' })).toEqual({
      preset: 'custom', start_date: '2026-09-01', end_date: '2026-09-30',
    })
    expect(periodKey({ preset: 'last_month' })).toBe('last_month')
    expect(periodKey({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' })).toBe('custom:2026-09-01:2026-09-30')
  })
  it('explains range errors', () => {
    expect(rangeError('', '2026-10-01')).toBe('Pick both dates.')
    expect(rangeError('2026-10-02', '2026-10-01')).toBe('From must be on or before To.')
    expect(rangeError('2026-10-01', '2026-10-01')).toBeNull()
  })
  it('finds the previous period', () => {
    expect(previousPeriod({ preset: 'this_month' }, '2026-10-01', '2026-10-06')).toEqual({ preset: 'last_month' })
    expect(previousPeriod({ preset: 'last_3m' }, '2026-07-01', '2026-10-06')).toEqual({
      preset: 'custom', from: '2026-03-25', to: '2026-06-30',
    })
    expect(previousPeriod({ preset: 'this_year' }, null, null)).toBeNull()
  })
})

function wrapper(initial: string) {
  return ({ children }: { children: ReactNode }) => <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
}

describe('usePeriod', () => {
  afterEach(() => localStorage.clear())

  it('URL wins, then storage, then this_month', () => {
    localStorage.setItem(PERIOD_STORAGE_KEY, JSON.stringify({ preset: 'last_6m' }))
    expect(renderHook(() => usePeriod(), { wrapper: wrapper('/insights?p=last_month') }).result.current[0])
      .toEqual({ preset: 'last_month' })
    expect(renderHook(() => usePeriod(), { wrapper: wrapper('/insights') }).result.current[0])
      .toEqual({ preset: 'last_6m' })
    localStorage.setItem(PERIOD_STORAGE_KEY, '{not json')
    expect(renderHook(() => usePeriod(), { wrapper: wrapper('/insights') }).result.current[0])
      .toEqual({ preset: 'this_month' })
  })

  it('setting writes the URL and storage (round trip)', () => {
    const { result } = renderHook(() => ({ p: usePeriod(), loc: useLocation() }), { wrapper: wrapper('/insights') })
    act(() => result.current.p[1]({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' }))
    expect(result.current.loc.search).toBe('?p=custom&from=2026-09-01&to=2026-09-30')
    expect(result.current.p[0]).toEqual({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' })
    expect(JSON.parse(localStorage.getItem(PERIOD_STORAGE_KEY)!)).toEqual(result.current.p[0])
  })
})
```

`web/src/features/insights/lens.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { HOUSEHOLD, LENS_STORAGE_KEY, insightsSearch, lensOptions, lensQuery, resolveLens, useLens } from './lens'

const members = [
  { user_id: 'me', display_name: 'Giorgos Charitidis', username: 'giorgos' },
  { user_id: 'm', display_name: 'Maria Papadopoulou', username: 'maria' },
  { user_id: 'k', display_name: 'Kostas A', username: 'kostas1' },
  { user_id: 'k2', display_name: 'Kostas B', username: 'kostas2' },
]

describe('lensOptions', () => {
  it('is Household, Me, then others by first name; duplicate first names use full names', () => {
    expect(lensOptions(members, 'me')).toEqual([
      { value: HOUSEHOLD, label: 'Household' },
      { value: 'me', label: 'Me' },
      { value: 'k', label: 'Kostas A' },
      { value: 'k2', label: 'Kostas B' },
      { value: 'm', label: 'Maria' },
    ])
  })
})

describe('resolveLens', () => {
  it('falls back to Household for a member who left', () => {
    expect(resolveLens('gone', members)).toBe(HOUSEHOLD)
    expect(resolveLens('m', members)).toBe('m')
    expect(resolveLens(null, members)).toBe(HOUSEHOLD)
    expect(resolveLens('m', undefined)).toBe('m') // members not loaded yet: trust it
  })
  it('maps to paid_by', () => {
    expect(lensQuery(HOUSEHOLD)).toEqual({})
    expect(lensQuery('m')).toEqual({ paid_by: 'm' })
  })
  it('builds drill-down search strings', () => {
    expect(insightsSearch({ preset: 'last_month' }, 'm')).toBe('?p=last_month&lens=m')
    expect(insightsSearch({ preset: 'this_month' }, HOUSEHOLD)).toBe('?p=this_month')
  })
})

describe('useLens', () => {
  afterEach(() => localStorage.clear())
  const wrapper = (initial: string) => ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[initial]}>{children}</MemoryRouter>
  )

  it('reads URL, then storage, and writes both', () => {
    localStorage.setItem(LENS_STORAGE_KEY, 'm')
    const { result } = renderHook(() => ({ l: useLens(members), loc: useLocation() }), { wrapper: wrapper('/insights') })
    expect(result.current.l[0]).toBe('m')
    act(() => result.current.l[1]('k'))
    expect(result.current.loc.search).toBe('?lens=k')
    expect(localStorage.getItem(LENS_STORAGE_KEY)).toBe('k')
    act(() => result.current.l[1](HOUSEHOLD))
    expect(result.current.loc.search).toBe('')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/insights/period.test.tsx src/features/insights/lens.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`web/src/features/insights/period.ts`:

```ts
import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

export type Preset = 'this_month' | 'last_month' | 'last_3m' | 'last_6m' | 'this_year' | 'custom'
export interface Period { preset: Preset; from?: string; to?: string }

export const DEFAULT_PERIOD: Period = { preset: 'this_month' }
export const PERIOD_STORAGE_KEY = 'tameio.insights.period'
export const PRESETS: { value: Preset; label: string }[] = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_3m', label: '3 months' },
  { value: 'last_6m', label: '6 months' },
  { value: 'this_year', label: 'This year' },
  { value: 'custom', label: 'Custom' },
]

const ISO = /^\d{4}-\d{2}-\d{2}$/

/** A real calendar date in YYYY-MM-DD (2026-02-30 is not). */
export function isIsoDate(s: string | null | undefined): s is string {
  if (!s || !ISO.test(s)) return false
  const d = new Date(`${s}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s
}

export function rangeError(from?: string, to?: string): string | null {
  if (!isIsoDate(from) || !isIsoDate(to)) return 'Pick both dates.'
  if (from > to) return 'From must be on or before To.'
  return null
}

export function normalisePeriod(p: Partial<Period> | null | undefined): Period | null {
  if (!p || !PRESETS.some((x) => x.value === p.preset)) return null
  if (p.preset === 'custom') return rangeError(p.from, p.to) ? null : { preset: 'custom', from: p.from, to: p.to }
  return { preset: p.preset as Preset }
}

export function parsePeriod(params: URLSearchParams): Period | null {
  return normalisePeriod({
    preset: (params.get('p') ?? undefined) as Preset | undefined,
    from: params.get('from') ?? undefined,
    to: params.get('to') ?? undefined,
  })
}

export function writePeriod(params: URLSearchParams, p: Period): URLSearchParams {
  const next = new URLSearchParams(params)
  next.set('p', p.preset)
  if (p.preset === 'custom' && p.from && p.to) {
    next.set('from', p.from)
    next.set('to', p.to)
  } else {
    next.delete('from')
    next.delete('to')
  }
  return next
}

/** The `GET /insights` (and drill-down) query for a period. */
export function periodQuery(p: Period): { preset: Preset; start_date?: string; end_date?: string } {
  return p.preset === 'custom' ? { preset: 'custom', start_date: p.from, end_date: p.to } : { preset: p.preset }
}

export function periodKey(p: Period): string {
  return p.preset === 'custom' ? `custom:${p.from}:${p.to}` : p.preset
}

/** Words for sentences: "this month", "last month", "in this period". */
export function periodPhrase(p: Period): string {
  if (p.preset === 'this_month') return 'this month'
  if (p.preset === 'last_month') return 'last month'
  return 'in this period'
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** The same-length window just before (the server's range_start/range_end), for "See the previous period". */
export function previousPeriod(p: Period, rangeStart: string | null, rangeEnd: string | null): Period | null {
  if (p.preset === 'this_month') return { preset: 'last_month' }
  if (!isIsoDate(rangeStart) || !isIsoDate(rangeEnd)) return null
  const span = Math.round((Date.parse(rangeEnd) - Date.parse(rangeStart)) / 86_400_000) + 1
  const to = addDays(rangeStart, -1)
  return { preset: 'custom', from: addDays(to, -(span - 1)), to }
}

function readStored(): Period | null {
  try {
    const raw = localStorage.getItem(PERIOD_STORAGE_KEY)
    return raw ? normalisePeriod(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

function store(p: Period): void {
  try {
    localStorage.setItem(PERIOD_STORAGE_KEY, JSON.stringify(p))
  } catch {
    // Private mode or storage full: the URL still carries it.
  }
}

/** The one reader of the period on Insights and every drill-down: URL, then storage, then this month. */
export function usePeriod(): [Period, (next: Period) => void] {
  const [params, setParams] = useSearchParams()
  const period = parsePeriod(params) ?? readStored() ?? DEFAULT_PERIOD
  const set = useCallback(
    (next: Period) => {
      setParams((prev) => writePeriod(prev, next), { replace: true })
      store(next)
    },
    [setParams],
  )
  return [period, set]
}
```

`web/src/features/insights/lens.ts`:

```ts
import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { type Period, writePeriod } from './period'

export type Lens = string
export const HOUSEHOLD = 'household'
export const LENS_STORAGE_KEY = 'tameio.insights.lens'

export interface LensMember { user_id: string; display_name: string | null; username: string | null }

const firstName = (m: LensMember) => (m.display_name || m.username || '?').trim().split(/\s+/)[0]

/** "Household", "Me", then each other member by first name (full name when two share one). */
export function lensOptions(members: LensMember[], meId: string): { value: string; label: string }[] {
  const others = members.filter((m) => m.user_id !== meId)
  const counts = new Map<string, number>()
  for (const m of others) counts.set(firstName(m), (counts.get(firstName(m)) ?? 0) + 1)
  const labelled = others
    .map((m) => ({ value: m.user_id, label: (counts.get(firstName(m)) ?? 0) > 1 ? (m.display_name || m.username || '?') : firstName(m) }))
    .sort((a, b) => a.label.localeCompare(b.label))
  return [{ value: HOUSEHOLD, label: 'Household' }, { value: meId, label: 'Me' }, ...labelled]
}

/** A lens for someone no longer in the household (old link, stale storage) falls back to Household. */
export function resolveLens(raw: string | null, members?: LensMember[]): Lens {
  if (!raw || raw === HOUSEHOLD) return HOUSEHOLD
  if (!members) return raw
  return members.some((m) => m.user_id === raw) ? raw : HOUSEHOLD
}

export function lensQuery(lens: Lens): { paid_by?: string } {
  return lens === HOUSEHOLD ? {} : { paid_by: lens }
}

/** Search string carrying the view into a drill-down link. */
export function insightsSearch(period: Period, lens: Lens): string {
  const params = writePeriod(new URLSearchParams(), period)
  if (lens !== HOUSEHOLD) params.set('lens', lens)
  return `?${params.toString()}`
}

function readStored(): string | null {
  try {
    return localStorage.getItem(LENS_STORAGE_KEY)
  } catch {
    return null
  }
}

export function useLens(members?: LensMember[]): [Lens, (next: Lens) => void] {
  const [params, setParams] = useSearchParams()
  const lens = resolveLens(params.get('lens') ?? readStored(), members)
  const set = useCallback(
    (next: Lens) => {
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          if (next === HOUSEHOLD) p.delete('lens')
          else p.set('lens', next)
          return p
        },
        { replace: true },
      )
      try {
        localStorage.setItem(LENS_STORAGE_KEY, next)
      } catch {
        // storage unavailable: the URL still carries it
      }
    },
    [setParams],
  )
  return [lens, set]
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/insights/period.test.tsx src/features/insights/lens.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/insights/period.ts web/src/features/insights/lens.ts web/src/features/insights/period.test.tsx web/src/features/insights/lens.test.tsx
git commit -m "feat(web/insights): period and lens in the URL with a storage fallback"
```

### Task F1.5: Data plumbing: `rawJson.ts`, `useOnlineAction`, the 2d keys

**Stream:** F1 · **Depends on:** F1.4, **B merged** (rebase first)

**Files:**
- Create: `web/src/data/rawJson.ts`, `web/src/data/onlineAction.ts`
- Modify: `web/src/data/keys.ts` (2a's; append the 2d section)
- Test: `web/src/data/onlineAction.test.tsx`

**Interfaces:**
- Consumes: 2a's `detailOf(error, status?)` (`data/http.ts`), `isOnline()` (`data/online.ts`), `useToast()`, `keys`.
- Produces (`rawJson.ts`): `interface RawResult<T> { data?: T; error?: unknown; response: Response }` (the openapi-fetch shape); `fetchJson<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<RawResult<T>>` (same-origin, `X-CSRF-Token` on unsafe methods, `redirect: 'manual'` so the cookie routes' login redirect reads as 401). For routes outside the generated types: `/push/*` and `/api/v1/settings/notifications` before N.
- Produces (`onlineAction.ts`): `OFFLINE_MESSAGE`, `RATE_MESSAGE`; `type OnlineOutcome<T> = { ok: true; data: T; status: number } | { ok: false; status: number | null; message: string; kind: 'offline' | 'rate' | 'rejected' | 'auth' }`; `runOnline<T>(call: () => Promise<RawResult<T>>, online?: () => boolean): Promise<OnlineOutcome<T>>`; `useOnlineAction(): <T>(call: () => Promise<RawResult<T>>, opts?: { invalidates?: readonly QueryKey[]; success?: string }) => Promise<OnlineOutcome<T>>` (toasts every failure except 401; invalidates on success).
- Produces (`keys.ts`): `insightsKeys`, `settingsKeys` (below). They take the household id like 2d's call sites do; keys shared with 2a **are** 2a's keys (the id is ignored there, since 2a scopes the device cache by household instead), so Insights, Plan and the composer share one cache entry per endpoint.

- [ ] **Step 1: Write the failing test**

`web/src/data/onlineAction.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import { OFFLINE_MESSAGE, RATE_MESSAGE, runOnline } from './onlineAction'

const res = (status: number, data?: unknown, error?: unknown) =>
  Promise.resolve({ data, error, response: new Response(null, { status }) })

describe('runOnline', () => {
  it('sends nothing while offline', async () => {
    const call = vi.fn(() => res(200, {}))
    const out = await runOnline(call, () => false)
    expect(call).not.toHaveBeenCalled()
    expect(out).toEqual({ ok: false, status: null, kind: 'offline', message: OFFLINE_MESSAGE })
  })
  it('treats a network failure and a 5xx as offline', async () => {
    expect((await runOnline(() => Promise.reject(new TypeError('Failed to fetch')), () => true)).message).toBe(OFFLINE_MESSAGE)
    expect((await runOnline(() => res(502), () => true)).message).toBe(OFFLINE_MESSAGE)
  })
  it('maps 429 and passes the server detail for 4xx', async () => {
    expect((await runOnline(() => res(429), () => true)).message).toBe(RATE_MESSAGE)
    const out = await runOnline(() => res(409, undefined, { detail: 'Email already registered to another account' }), () => true)
    expect(out).toMatchObject({ ok: false, status: 409, kind: 'rejected', message: 'Email already registered to another account' })
  })
  it('leaves 401 to the session', async () => {
    expect(await runOnline(() => res(401), () => true)).toMatchObject({ ok: false, kind: 'auth' })
  })
  it('returns data on success', async () => {
    expect(await runOnline(() => res(201, { id: 'x' }), () => true)).toEqual({ ok: true, status: 201, data: { id: 'x' } })
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/data/onlineAction.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`web/src/data/rawJson.ts`:

```ts
import { readCsrf } from '../api/client'

/** The openapi-fetch result shape, also produced by fetchJson. */
export interface RawResult<T> { data?: T; error?: unknown; response: Response }

/** Same-origin JSON for routes outside the generated types (the cookie /push/* routes,
 *  /settings/notifications before stream N is merged). The cookie routes answer an
 *  expired session with a redirect to /login; `manual` turns that into a 401. */
export async function fetchJson<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<RawResult<T>> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-CSRF-Token'] = readCsrf()
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await globalThis.fetch(new URL(path, globalThis.location.origin), {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    redirect: 'manual',
  })
  const response = res.type === 'opaqueredirect' ? new Response(null, { status: 401 }) : res
  const text = response.status === 204 ? '' : await response.text()
  let json: unknown
  try {
    json = text ? JSON.parse(text) : undefined
  } catch {
    json = undefined
  }
  return response.ok ? { data: json as T, response } : { error: json, response }
}
```

`web/src/data/onlineAction.ts`:

```ts
import { type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useToast } from '../ui/Toast'
import { detailOf } from './http'
import { isOnline } from './online'
import type { RawResult } from './rawJson'

export const OFFLINE_MESSAGE = "You're offline. This change needs a connection."
export const RATE_MESSAGE = 'Too many attempts. Try again in a minute.'

export type OnlineOutcome<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; status: number | null; message: string; kind: 'offline' | 'rate' | 'rejected' | 'auth' }

/** Settings writes are never queued (2d §6.2): offline or a network failure changes nothing. */
export async function runOnline<T>(call: () => Promise<RawResult<T>>, online: () => boolean = isOnline): Promise<OnlineOutcome<T>> {
  const offline = { ok: false as const, status: null, kind: 'offline' as const, message: OFFLINE_MESSAGE }
  if (!online()) return offline
  let res: RawResult<T>
  try {
    res = await call()
  } catch {
    return offline
  }
  const { status } = res.response
  if (res.response.ok) return { ok: true, status, data: res.data as T }
  if (status === 401) return { ok: false, status, kind: 'auth', message: '' }
  if (status === 429) return { ok: false, status, kind: 'rate', message: RATE_MESSAGE }
  if (status >= 500) return { ...offline, status }
  return { ok: false, status, kind: 'rejected', message: detailOf(res.error, status) }
}

/** Run a write online only; toast its failure (except 401, which Phase 1's session handles);
 *  invalidate keys on success. The caller keeps its sheet open when `ok` is false. */
export function useOnlineAction() {
  const qc = useQueryClient()
  const toast = useToast()
  return useCallback(
    async <T,>(call: () => Promise<RawResult<T>>, opts: { invalidates?: readonly QueryKey[]; success?: string } = {}) => {
      const out = await runOnline(call)
      if (out.ok) {
        await Promise.all((opts.invalidates ?? []).map((queryKey) => qc.invalidateQueries({ queryKey })))
        if (opts.success) toast.show(opts.success)
      } else if (out.kind !== 'auth') {
        toast.show(out.message)
      }
      return out
    },
    [qc, toast],
  )
}
```

Append to 2a's `web/src/data/keys.ts`:

```ts
// ---- 2d: Insights and Settings ------------------------------------------------------------
// Call sites pass the household id; 2d-only keys carry it, keys shared with 2a ignore it
// (2a scopes the device cache by household) so both phases hit one cache entry.
export const insightsKeys = {
  all: (_hh: string) => keys.insights.all,
  overview: (hh: string, period: string, lens: string, filters: string) => ['insights', 'overview', hh, period, lens, filters] as const,
  person: (hh: string, period: string, userId: string) => ['insights', 'person', hh, period, userId] as const,
  category: (hh: string, id: string, period: string, lens: string) => ['insights', 'category', hh, id, period, lens] as const,
  vsUsual: (_hh: string, month: string) => keys.insights.categoriesVsUsual(month),
  planMonth: (_hh: string, month: string) => keys.plan.month(month),
}

export const settingsKeys = {
  profile: (hh: string) => ['settings', 'profile', hh] as const,
  security: (hh: string) => ['settings', 'security', hh] as const,
  tokens: (hh: string) => ['settings', 'tokens', hh] as const,
  notifications: (hh: string) => ['settings', 'notifications', hh] as const,
  household: (_hh: string) => keys.household(),
  categories: (_hh: string) => keys.categories(),
  rules: (_hh: string) => keys.categoryRules(),
  buckets: (_hh: string) => keys.buckets(),
}
```

(Every 2d insights key starts with `keys.insights.all`, so 2a's `affects.entry`/`affects.sync` refresh Insights after a payment or a queue replay.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/data/onlineAction.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/data/rawJson.ts web/src/data/onlineAction.ts web/src/data/keys.ts web/src/data/onlineAction.test.tsx
git commit -m "feat(web/data): online-only actions, raw JSON helper, 2d query keys"
```

### Task F1.6: Read hooks and types for Insights and Settings, `palette.ts`, `format.ts`

**Stream:** F1 · **Depends on:** F1.5

**Files:**
- Create: `web/src/features/insights/types.ts`, `web/src/features/insights/hooks.ts`, `web/src/features/insights/format.ts`
- Create: `web/src/features/settings/hooks.ts`, `web/src/features/settings/palette.ts`
- Modify: 2a's `web/src/data/types.ts` and `web/src/data/reads.ts` (`Category` keeps `is_default`, `system_key`, `locked`, `expense_count`, `rule_count`)
- Test: `web/src/features/insights/hooks.test.tsx`, `web/src/features/insights/format.test.ts`, 2a's `web/src/data/reads.test.ts` (one case added)

**Interfaces:**
- Produces (`insights/types.ts`): `InsightsData` (the untyped `GET /insights` dict: see code), `CategoryRow`, `FuelData`, `FuelCar`, `InsightFilters = { bucketIds: string[]; categoryIds: string[] }`, `NO_FILTERS`, `filtersKey(f): string`, `CASH_NOT_LOGGED = '__cash_not_logged__'`; `PersonShare` and `CategoryDetail` from the generated schema.
- Produces (`insights/hooks.ts`): `useHouseholdId(): string`; `useInsights(period, lens, filters)`; `usePersonShare(period, userId: string | null)` (disabled, no request, for the Household lens); `useCategoryDetail(id, period, lens)`; re-exports of 2a's `usePlanMonth(month)` and `useCategoriesVsUsual(month)` (`features/plan/hooks.ts`) and `useMembers` = 2a's `useHousehold` (`data/reads.ts`). All return 2a's `CachedQuery<T>`.
- Produces (`insights/format.ts`): `eur(n: number): string` ("€1,284.60"), `eurWhole(n)` ("€2,310"), `pctText(n)` ("8%"), `dayRange(start: string | null, end: string | null): string` ("Oct 1 – 6", "Sep 3 – Oct 6", "All time"), `monthEnd(iso: string): string` ("Oct 31").
- Produces (`settings/hooks.ts`): types `Profile`, `TokenItem`, `NotificationPrefs` (local), `HouseholdInfo`/`HouseholdMember`/`BucketRef`/`CategoryItem` (aliases of 2a's `Household`/`Member`/`Bucket`/`Category`), `Security`, `Rule`; hooks `useProfile`, `useSecurity`, `useRules`, `useTokens`, `useNotificationPrefs` (`null` when the endpoint is missing, i.e. before stream N), and re-exports of 2a's `useHousehold`, `useBuckets`, `useCategories` (same keys, one cache entry).
- Produces (`settings/palette.ts`): `SWATCHES: readonly string[]` (8 hex colours), `swatchName(hex): string`.

- [ ] **Step 1: Write the failing tests**

`web/src/features/insights/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { dayRange, eur, eurWhole, monthEnd, pctText } from './format'

describe('format', () => {
  it('formats euros', () => {
    expect(eur(1284.6)).toBe('€1,284.60')
    expect(eur(-3)).toBe('−€3.00')
    expect(eurWhole(2310.4)).toBe('€2,310')
    expect(pctText(-8)).toBe('8%')
  })
  it('formats ranges', () => {
    expect(dayRange('2026-10-01', '2026-10-06')).toBe('Oct 1 – 6')
    expect(dayRange('2026-09-03', '2026-10-06')).toBe('Sep 3 – Oct 6')
    expect(dayRange(null, null)).toBe('All time')
    expect(monthEnd('2026-02-10')).toBe('Feb 28')
  })
})
```

`web/src/features/insights/hooks.test.tsx` (the fake `fetch` pattern Phase 1 tests use; mock the session so the household id is known):

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }),
}))

import { useInsights, usePersonShare } from './hooks'
import { NO_FILTERS } from './types'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

afterEach(() => vi.restoreAllMocks())

describe('insights hooks', () => {
  it('sends the period, lens and filters', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ total_spent: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const { result } = renderHook(
      () => useInsights({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' }, 'm', { bucketIds: ['b1'], categoryIds: [] }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.data).toBeDefined())
    const url = new URL((fetch.mock.calls[0][0] as Request).url)
    expect(url.pathname).toBe('/api/v1/insights')
    expect(Object.fromEntries(url.searchParams)).toMatchObject({
      preset: 'custom', start_date: '2026-09-01', end_date: '2026-09-30', paid_by: 'm', bucket_ids: 'b1',
    })
  })

  it('does not call /insights/person for the Household lens', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    const { result } = renderHook(() => usePersonShare({ preset: 'this_month' }, null), { wrapper })
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current.data).toBeUndefined()
    expect(fetch).not.toHaveBeenCalled()
    void NO_FILTERS
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/insights/format.test.ts src/features/insights/hooks.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`web/src/features/insights/format.ts`:

```ts
const money = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })
const whole = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const MINUS = '−'

const signed = (s: string) => s.replace('-', MINUS)
export const eur = (n: number) => signed(money.format(n))
export const eurWhole = (n: number) => signed(whole.format(n))
export const pctText = (n: number) => `${Math.abs(Math.round(n))}%`

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const parts = (iso: string) => iso.split('-').map(Number) as [number, number, number]

export function dayRange(start: string | null, end: string | null): string {
  if (!start || !end) return 'All time'
  const [, sm, sd] = parts(start)
  const [, em, ed] = parts(end)
  return sm === em ? `${MON[sm - 1]} ${sd} – ${ed}` : `${MON[sm - 1]} ${sd} – ${MON[em - 1]} ${ed}`
}

/** "Oct 31": the last day of the month `iso` is in. */
export function monthEnd(iso: string): string {
  const [y, m] = parts(iso)
  return `${MON[m - 1]} ${new Date(Date.UTC(y, m, 0)).getUTCDate()}`
}
```

`web/src/features/insights/types.ts`:

```ts
import type { components } from '../../api/schema'

/** GET /insights returns an untyped dict; these mirror app/api/insights.py's keys. */
export interface CategoryRow { category_id: string | null; name: string; icon: string; color: string; amount: number; pct: number }
export interface FuelMonth { year: number; month: number; label: string; litres: number; spend: number; avg_price_per_litre: number | null }
export interface FuelRefuel { date: string; price_per_litre: number; litres: number; spend: number }
export interface FuelCar {
  bucket_id: string; name: string; icon: string; litres: number; spend: number
  avg_price_per_litre: number | null; fills: number; months: FuelMonth[]; refuels: FuelRefuel[]
}
export interface FuelData {
  litres: number; spend: number; avg_price_per_litre: number | null; fills: number
  unpriced_count: number; months: FuelMonth[]; cars: FuelCar[]
}
export interface InsightsData {
  preset: string
  period_label: string
  start_date: string | null
  end_date: string | null
  total_spent: number
  logged_total: number
  cash_not_logged: number
  income_total: number
  in_out: { in: number; out: number; logged: number; cash_not_logged: number; net: number }
  kpis: {
    total: number; count: number; avg_per_month: number
    largest: { amount: number; notes: string | null; date: string; category: string | null } | null
    previous_total: number | null; change_pct: number | null; savings_rate: number | null
    range_start: string | null; range_end: string | null
  }
  categories: CategoryRow[]
  monthly_trend: { label: string; year: number; month: number; total: number; is_current: boolean }[]
  monthly_in_out: { year: number; month: number; label: string; in: number; out: number; net: number }[]
  by_method: { method: string; label: string; amount: number; pct: number }[]
  cash_share: number
  budget_status: {
    bucket_id: string; bucket_name: string; icon: string | null; color: string | null
    spent: number; budget: number | null; pct: number | null; remaining: number | null; over_budget: boolean
  }[]
  fuel: FuelData | null
}

export const CASH_NOT_LOGGED = '__cash_not_logged__'
export const UNCATEGORISED = 'uncategorised'

export interface InsightFilters { bucketIds: string[]; categoryIds: string[] }
export const NO_FILTERS: InsightFilters = { bucketIds: [], categoryIds: [] }
export const filtersKey = (f: InsightFilters) => `${[...f.bucketIds].sort().join(',')}|${[...f.categoryIds].sort().join(',')}`

export type PersonShare = components['schemas']['PersonShareOut']
export type CategoryDetail = components['schemas']['CategoryDetailOut']
export type CategoryUsual = components['schemas']['CategoryUsualOut']
export type MonthPicture = components['schemas']['MonthPictureOut']
```

`web/src/features/insights/hooks.ts`:

```ts
import { api } from '../../api/client'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { insightsKeys } from '../../data/keys'
import { useHousehold } from '../../data/reads'
import { useSession } from '../../session/SessionProvider'
import { type Lens, lensQuery } from './lens'
import { type Period, periodKey, periodQuery } from './period'
import { type CategoryDetail, type InsightFilters, type InsightsData, type PersonShare, filtersKey } from './types'

// 2a's reads, shared so Insights, Plan and Settings use one cache entry each.
export { useCategoriesVsUsual, usePlanMonth } from '../plan/hooks'
export const useMembers = useHousehold

export const useHouseholdId = () => useSession().me?.household_id ?? ''

export function useInsights(period: Period, lens: Lens, filters: InsightFilters) {
  const hh = useHouseholdId()
  return useCachedQuery(insightsKeys.overview(hh, periodKey(period), lens, filtersKey(filters)), async (signal) =>
    (await unwrap(
      api.GET('/api/v1/insights', {
        params: {
          query: {
            ...periodQuery(period),
            ...lensQuery(lens),
            bucket_ids: filters.bucketIds.join(','),
            category_ids: filters.categoryIds.join(','),
          },
        },
        signal,
      }),
    )) as InsightsData,
  )
}

/** Paid out vs my share; disabled (no request) for the Household lens. */
export function usePersonShare(period: Period, userId: string | null) {
  const hh = useHouseholdId()
  return useCachedQuery(
    insightsKeys.person(hh, periodKey(period), userId ?? 'household'),
    (signal): Promise<PersonShare> =>
      unwrap(api.GET('/api/v1/insights/person', { params: { query: { user_id: userId ?? '', ...periodQuery(period) } }, signal })),
    { enabled: !!userId },
  )
}

export function useCategoryDetail(id: string, period: Period, lens: Lens) {
  const hh = useHouseholdId()
  return useCachedQuery(insightsKeys.category(hh, id, periodKey(period), lens), (signal): Promise<CategoryDetail> =>
    unwrap(
      api.GET('/api/v1/insights/categories/{category_id}', {
        params: { path: { category_id: id }, query: { ...periodQuery(period), ...lensQuery(lens) } },
        signal,
      }),
    ),
  )
}
```

(Check the generated path and query names in `web/src/api/schema.d.ts`. `GET /insights` is an untyped dict, hence the cast to the local `InsightsData`.)

`web/src/features/settings/hooks.ts`:

```ts
import { api } from '../../api/client'
import type { components } from '../../api/schema'
import { useCachedQuery } from '../../data/cachedQuery'
import { ApiError, unwrap } from '../../data/http'
import { settingsKeys } from '../../data/keys'
import { fetchJson } from '../../data/rawJson'
import type { Bucket, Category, Household, Member } from '../../data/types'
import { useSession } from '../../session/SessionProvider'

// 2a's narrowed reads, shared (one cache entry each).
export { useBuckets, useCategories, useHousehold } from '../../data/reads'
export type HouseholdInfo = Household
export type HouseholdMember = Member
export type BucketRef = Bucket
export type CategoryItem = Category

/* Untyped dict endpoints (no response_model): local types mirroring app/api/settings.py. */
export interface Profile { id: string; username: string; display_name: string; email: string | null; avatar_color: string | null; totp_enabled: boolean; household_id: string }
export interface TokenItem { id: string; name: string; prefix: string; scopes: string[]; default_bucket_id: string | null; last_used_at: string | null; created_at: string | null }
export interface NotificationPrefs { types: { type: string; group: string; label: string; enabled: boolean }[]; push_devices: number }
export type Security = components['schemas']['SecurityOut']
export type Rule = components['schemas']['CategoryRuleOut']

const useHh = () => useSession().me?.household_id ?? ''

export const useProfile = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.profile(hh), async (signal) => (await unwrap(api.GET('/api/v1/settings/profile', { signal }))) as Profile)
}
export const useSecurity = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.security(hh), (signal): Promise<Security> => unwrap(api.GET('/api/v1/settings/security', { signal })))
}
export const useRules = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.rules(hh), (signal): Promise<Rule[]> => unwrap(api.GET('/api/v1/settings/category-rules', { signal })))
}
export const useTokens = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.tokens(hh), async (signal) => (await unwrap(api.GET('/api/v1/settings/tokens', { signal }))) as TokenItem[])
}

/** Alert types (stream N). Null while the server has no such endpoint: the screen then shows push only. */
export const useNotificationPrefs = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.notifications(hh), async (): Promise<NotificationPrefs | null> => {
    const res = await fetchJson<NotificationPrefs>('GET', '/api/v1/settings/notifications')
    if (res.response.status === 404) return null
    if (!res.response.ok) throw new ApiError(res.response.status, res.response.statusText)
    return res.data ?? null
  })
}
```

In 2a's `web/src/data/types.ts`, widen `Category` (the composer and Plan ignore the new fields):

```ts
export interface Category {
  id: string; name: string; icon: string | null; color: string | null
  /** Settings › Categories (2d): defaults can't be deleted; locked (system) ones can't be edited. */
  is_default: boolean; system_key: string | null; locked: boolean
  /** Active expenses and rules using it, for the delete confirmation. */
  expense_count: number; rule_count: number
}
```

and in 2a's `toCategories` (`web/src/data/reads.ts`) map them with safe defaults: `is_default: d.is_default === true`, `system_key: strOrNull(d.system_key)`, `locked: d.locked === true`, `expense_count: num(d.expense_count ?? 0)`, `rule_count: num(d.rule_count ?? 0)`. Add a case to 2a's `reads.test.ts`: a raw row with these fields keeps them, a row without them gets `false`/`null`/`0`.

`web/src/features/settings/palette.ts`:

```ts
/** The 8 swatches for avatars and categories (a subset of the server's AVATAR_COLORS). */
export const SWATCHES = ['#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316', '#f59e0b', '#10b981', '#06b6d4'] as const
const NAMES = ['Indigo', 'Violet', 'Pink', 'Red', 'Orange', 'Amber', 'Green', 'Cyan']
/** Accessible name for a swatch button: colour is never the only signal. */
export const swatchName = (hex: string) => NAMES[SWATCHES.indexOf(hex.toLowerCase() as (typeof SWATCHES)[number])] ?? hex
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/insights/format.test.ts src/features/insights/hooks.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/insights/types.ts web/src/features/insights/hooks.ts web/src/features/insights/format.ts web/src/features/insights/format.test.ts web/src/features/insights/hooks.test.tsx web/src/features/settings/hooks.ts web/src/features/settings/palette.ts
git commit -m "feat(web): read hooks and types for Insights and Settings; money and palette helpers"
```

### Task F1.7: Push client, `BackHeader`, route stubs and the router

**Stream:** F1 · **Depends on:** F1.6

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/pwa/pushClient.ts`, `web/src/ui/BackHeader.tsx`
- Create (stubs that F2/F3/F4 overwrite): `web/src/features/insights/Insights.tsx`, `CategoryScreen.tsx`, `FuelScreen.tsx`; `web/src/features/settings/Settings.tsx`, `Profile.tsx`, `Household.tsx`, `Categories.tsx`, `Automations.tsx`, `Notifications.tsx`
- Modify: `web/src/screens/Insights.tsx` (one-line re-export), `web/src/router.tsx`
- Test: `web/src/pwa/pushClient.test.ts`, `web/src/router.test.tsx`

**Interfaces:**
- Produces (`pushClient.ts`): `type PushState = 'unsupported' | 'not-installed' | 'denied' | 'off' | 'on'`; `interface PushEnv { standalone: boolean; supported: boolean; permission(): NotificationPermission; requestPermission(): Promise<NotificationPermission>; registration(): Promise<ServiceWorkerRegistration> }`; `browserEnv(): PushEnv`; `pushState(env?): Promise<PushState>`; `enablePush(env?): Promise<RawResult<unknown>>`; `disablePush(env?): Promise<RawResult<unknown>>`; `sendTestPush(env?): Promise<RawResult<{ sent: boolean; error: string | null }>>`; `urlBase64ToUint8Array(s): Uint8Array`; `usePushState(): { state: PushState | null; refresh(): void }`. The functions return `RawResult` so callers wrap them in `useOnlineAction`.
- Produces (`BackHeader.tsx`): `BackHeader(props: { title: string; back: string; keepSearch?: boolean; action?: ReactNode })`.
- Produces (routes): `/app/insights`, `/app/insights/category/:id`, `/app/insights/fuel`, `/app/settings`, `/app/settings/{profile,household,categories,automations,notifications}`.

- [ ] **Step 1: Write the failing tests**

`web/src/pwa/pushClient.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enablePush, pushState, urlBase64ToUint8Array, type PushEnv } from './pushClient'

function env(over: Partial<PushEnv> & { sub?: PushSubscription | null } = {}): PushEnv {
  const subscribe = vi.fn(async () => ({ endpoint: 'https://web.push.apple.com/x', toJSON: () => ({ endpoint: 'https://web.push.apple.com/x', keys: { p256dh: 'p', auth: 'a' } }) }))
  const registration = { pushManager: { getSubscription: vi.fn(async () => over.sub ?? null), subscribe } } as unknown as ServiceWorkerRegistration
  return {
    standalone: true,
    supported: true,
    permission: () => 'default',
    requestPermission: vi.fn(async () => 'granted' as NotificationPermission),
    registration: async () => registration,
    ...over,
  }
}

afterEach(() => vi.restoreAllMocks())

describe('pushState', () => {
  it('names each state', async () => {
    expect(await pushState(env({ supported: false }))).toBe('unsupported')
    expect(await pushState(env({ standalone: false }))).toBe('not-installed')
    expect(await pushState(env({ permission: () => 'denied' }))).toBe('denied')
    expect(await pushState(env())).toBe('off')
    expect(await pushState(env({ permission: () => 'granted', sub: {} as PushSubscription }))).toBe('on')
  })
})

describe('enablePush', () => {
  it('asks permission, subscribes with the server key and posts it with the CSRF header', async () => {
    document.cookie = 'csrf_token=tok'
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ public_key: 'BEl6' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    const res = await enablePush(env())
    expect(res.response.ok).toBe(true)
    const [, post] = fetch.mock.calls
    expect(String(post[0])).toContain('/push/subscribe')
    expect((post[1] as RequestInit).headers).toMatchObject({ 'X-CSRF-Token': 'tok' })
    expect(JSON.parse((post[1] as RequestInit).body as string)).toEqual({ endpoint: 'https://web.push.apple.com/x', keys: { p256dh: 'p', auth: 'a' } })
  })

  it('stops at a refused permission without calling the server', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    const res = await enablePush(env({ requestPermission: async () => 'denied' }))
    expect(res.response.status).toBe(403)
    expect(fetch).not.toHaveBeenCalled()
  })
})

it('decodes a VAPID key', () => {
  expect([...urlBase64ToUint8Array('AQID')]).toEqual([1, 2, 3])
})
```

`web/src/router.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { router } from './router'

describe('router', () => {
  it('has every 2d route under the shell', () => {
    const paths = (router.routes[0].children ?? []).map((r) => r.path ?? '(index)')
    expect(paths).toEqual(expect.arrayContaining([
      'insights', 'insights/category/:id', 'insights/fuel',
      'settings', 'settings/profile', 'settings/household', 'settings/categories',
      'settings/automations', 'settings/notifications',
    ]))
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/pwa/pushClient.test.ts src/router.test.tsx`
Expected: FAIL — module not found; routes missing.

- [ ] **Step 3: Implement the push client**

`web/src/pwa/pushClient.ts`:

```ts
import { useCallback, useEffect, useState } from 'react'
import { fetchJson, type RawResult } from '../data/rawJson'

export type PushState = 'unsupported' | 'not-installed' | 'denied' | 'off' | 'on'

export interface PushEnv {
  /** Installed to the Home Screen: iOS only offers push there. */
  standalone: boolean
  supported: boolean
  permission(): NotificationPermission
  requestPermission(): Promise<NotificationPermission>
  /** The /app/ worker's registration (the old app's / worker is a separate one). */
  registration(): Promise<ServiceWorkerRegistration>
}

export function browserEnv(): PushEnv {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  return {
    standalone: window.matchMedia?.('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true,
    supported,
    permission: () => (supported ? Notification.permission : 'denied'),
    requestPermission: () => Notification.requestPermission(),
    registration: () => navigator.serviceWorker.ready,
  }
}

export function urlBase64ToUint8Array(s: string): Uint8Array {
  const padded = (s + '='.repeat((4 - (s.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(padded)
  return Uint8Array.from(bin, (c) => c.charCodeAt(0))
}

export async function pushState(env: PushEnv = browserEnv()): Promise<PushState> {
  if (!env.supported) return 'unsupported'
  if (!env.standalone) return 'not-installed'
  if (env.permission() === 'denied') return 'denied'
  const sub = await (await env.registration()).pushManager.getSubscription()
  return sub && env.permission() === 'granted' ? 'on' : 'off'
}

const synthetic = (status: number): RawResult<unknown> => ({ response: new Response(null, { status }), error: { detail: 'Allowed in iOS Settings' } })

/** Permission (from the tap), the server's key, subscribe, POST /push/subscribe. */
export async function enablePush(env: PushEnv = browserEnv()): Promise<RawResult<unknown>> {
  const permission = await env.requestPermission()
  if (permission !== 'granted') return synthetic(403)
  const key = await fetchJson<{ public_key: string }>('GET', '/push/vapid-public-key')
  if (!key.response.ok || !key.data) return key
  const reg = await env.registration()
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key.data.public_key) })
  return fetchJson('POST', '/push/subscribe', sub.toJSON())
}

export async function disablePush(env: PushEnv = browserEnv()): Promise<RawResult<unknown>> {
  const sub = await (await env.registration()).pushManager.getSubscription()
  if (!sub) return { data: { ok: true }, response: new Response(null, { status: 200 }) }
  const res = await fetchJson('DELETE', '/push/subscribe', { endpoint: sub.endpoint })
  if (res.response.ok) await sub.unsubscribe()
  return res
}

export async function sendTestPush(env: PushEnv = browserEnv()): Promise<RawResult<{ sent: boolean; error: string | null }>> {
  const sub = await (await env.registration()).pushManager.getSubscription()
  return fetchJson('POST', '/push/test', { endpoint: sub?.endpoint ?? null })
}

/** This device's push state, re-read on demand (after a toggle) and when the app returns. */
export function usePushState(): { state: PushState | null; refresh(): void } {
  const [state, setState] = useState<PushState | null>(null)
  const refresh = useCallback(() => {
    pushState().then(setState, () => setState('unsupported'))
  }, [])
  useEffect(() => {
    refresh()
    const onVisible = () => { if (document.visibilityState === 'visible') refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [refresh])
  return { state, refresh }
}
```

- [ ] **Step 4: `BackHeader`, stubs, router**

`web/src/ui/BackHeader.tsx`:

```tsx
import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router'

/** Sub-screen header: Back (to a fixed parent, keeping the period/lens query when asked), title, one action. */
export function BackHeader({ title, back, keepSearch = false, action }: { title: string; back: string; keepSearch?: boolean; action?: ReactNode }) {
  const { search } = useLocation()
  return (
    <header className="topbar backheader">
      <Link className="backheader__back" to={{ pathname: back, search: keepSearch ? search : '' }} aria-label="Back">
        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M15 18l-6-6 6-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </Link>
      <h1 className="topbar__title">{title}</h1>
      <div className="backheader__action">{action}</div>
    </header>
  )
}
```

(Style `.backheader` next to Phase 1's `.topbar` in `shell.css`'s spirit: a 44 px back target, safe-area top padding; put the rules in `web/src/ui/controls.css`.)

Each stub (example `web/src/features/settings/Profile.tsx`; the others change the name, title and `back`):

```tsx
import { BackHeader } from '../../ui/BackHeader'

/** Placeholder until stream F3 replaces this file. */
export function Profile() {
  return (
    <>
      <BackHeader title="Profile & security" back="/settings" />
      <section className="screen"><p className="screen__note">Coming soon</p></section>
    </>
  )
}
```

| File | Export | Title | Back |
|---|---|---|---|
| `features/insights/Insights.tsx` | `Insights` | uses Phase 1 `<TopBar title="Insights" />` | — |
| `features/insights/CategoryScreen.tsx` | `CategoryScreen` | "Category" | `/insights` (keepSearch) |
| `features/insights/FuelScreen.tsx` | `FuelScreen` | "Fuel" | `/insights` (keepSearch) |
| `features/settings/Settings.tsx` | `Settings` | "Settings" | `/` |
| `features/settings/Profile.tsx` | `Profile` | "Profile & security" | `/settings` |
| `features/settings/Household.tsx` | `Household` | "Household" | `/settings` |
| `features/settings/Categories.tsx` | `Categories` | "Categories & rules" | `/settings` |
| `features/settings/Automations.tsx` | `Automations` | "Apple Pay" | `/settings` |
| `features/settings/Notifications.tsx` | `Notifications` | "Notifications" | `/settings` |

`web/src/screens/Insights.tsx` becomes:

```tsx
export { Insights } from '../features/insights/Insights'
```

`web/src/router.tsx`: import the eight feature screens and add to the shell's `children` (before the `*` catch-all):

```tsx
        { path: 'insights/category/:id', element: <CategoryScreen /> },
        { path: 'insights/fuel', element: <FuelScreen /> },
        { path: 'settings', element: <Settings /> },
        { path: 'settings/profile', element: <Profile /> },
        { path: 'settings/household', element: <Household /> },
        { path: 'settings/categories', element: <Categories /> },
        { path: 'settings/automations', element: <Automations /> },
        { path: 'settings/notifications', element: <Notifications /> },
```

- [ ] **Step 5: Run to verify pass**

Run: `npm test -- src/pwa/pushClient.test.ts src/router.test.tsx && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/pwa/pushClient.ts web/src/pwa/pushClient.test.ts web/src/ui/BackHeader.tsx web/src/ui/controls.css web/src/features web/src/screens/Insights.tsx web/src/router.tsx web/src/router.test.tsx
git commit -m "feat(web): push client, BackHeader, 2d routes with placeholder screens"
```

---
## Stream F2: Insights

All F2 tasks share a test fixture file created in F2.1. Every F2 test renders inside `MemoryRouter` and a fresh `QueryClientProvider`, and mocks `../../session/SessionProvider` (`useSession` → `{ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos' }, signOut: vi.fn() }`) and `./hooks` (the read hooks) with `vi.mock`, so no network is involved.

### Task F2.1: Insights screen, widget order, headline, identity and "Paid out vs my share"

**Stream:** F2 · **Depends on:** F1, B

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/features/insights/overview.ts`, `web/src/features/insights/LensControl.tsx`, `web/src/features/insights/widgets/Card.tsx`, `web/src/features/insights/widgets/summary.tsx`, `web/src/features/insights/insights.css`, `web/src/features/insights/fixtures.ts`
- Replace (stub from F1.7): `web/src/features/insights/Insights.tsx`
- Test: `web/src/features/insights/overview.test.ts`, `web/src/features/insights/Insights.test.tsx`

**Interfaces:**
- Consumes: `usePeriod`, `useLens`, `lensOptions`, `HOUSEHOLD` (F1.4); `useInsights`, `usePersonShare`, `useMembers` (F1.6); 2a's `QueryView`; `Chips` (F1.1); 2a `Segmented`, `Money`.
- Produces (`overview.ts`): `type WidgetId = 'identity' | 'headline' | 'share' | 'empty' | 'onTrack' | 'inOut' | 'where' | 'inOutMonths' | 'trend' | 'biggest' | 'method' | 'budgets' | 'savings' | 'vsUsual' | 'fuel'`; `isEmptyPeriod(d)`; `singleMonth(p, d): string | null` (`YYYY-MM` for `this_month`/`last_month`); `visibleWidgets(d, { lens, period }): WidgetId[]`; `deltaText(changePct: number | null): string | null`; `paidOutSentence(balance: number, who: { me: boolean; name: string }, phrase: string): string`.
- Produces (`widgets/Card.tsx`): `Card(props: { title: string; children; action?: ReactNode })` (a `<section>` labelled by its `<h2>`).
- Produces (`Insights.tsx`): `Insights()`; internal `RENDER: Record<WidgetId, (ctx: WidgetCtx) => ReactNode>` with `WidgetCtx = { data: InsightsData; period: Period; lens: Lens; members: HouseholdMember[]; meId: string; setPeriod(p: Period): void }`. F2.2 fills the entries this task leaves as `() => null`.
- Produces (`fixtures.ts`): `makeInsights(over?: Partial<InsightsData>): InsightsData`, `query<T>(data: T | undefined, over?)` (a 2a `CachedQuery`-shaped value).

- [ ] **Step 1: Write the failing tests**

`web/src/features/insights/fixtures.ts`:

```ts
import type { InsightsData } from './types'

export function makeInsights(over: Partial<InsightsData> = {}): InsightsData {
  return {
    preset: 'this_month', period_label: 'October 2026', start_date: '2026-10-01', end_date: '2026-10-06',
    total_spent: 1284.6, logged_total: 1239.6, cash_not_logged: 45, income_total: 3000,
    in_out: { in: 3000, out: 1284.6, logged: 1239.6, cash_not_logged: 45, net: 1715.4 },
    kpis: {
      total: 1284.6, count: 31, avg_per_month: 1284.6,
      largest: { amount: 420, notes: 'IKEA', date: '2026-10-03', category: 'Home' },
      previous_total: 1396.3, change_pct: -8, savings_rate: 57.2, range_start: '2026-10-01', range_end: '2026-10-06',
    },
    categories: [
      { category_id: 'g', name: 'Groceries', icon: '🛒', color: '#10b981', amount: 362.4, pct: 28.2 },
      { category_id: null, name: 'Uncategorised', icon: '📦', color: '#9ca3af', amount: 80, pct: 6.2 },
      { category_id: '__cash_not_logged__', name: 'Cash (not yet logged)', icon: '💵', color: '#a8a29e', amount: 45, pct: 3.5 },
    ],
    monthly_trend: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'].map((label, i) => ({ label, year: 2026, month: i + 5, total: [2180, 2410, 2050, 2960, 2240, 1284.6][i], is_current: i === 5 })),
    monthly_in_out: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'].map((label, i) => ({ label, year: 2026, month: i + 5, in: 3000, out: [2180, 2410, 2050, 2960, 2240, 1284.6][i], net: 3000 - [2180, 2410, 2050, 2960, 2240, 1284.6][i] })),
    by_method: [
      { method: 'card', label: 'Card', amount: 1100, pct: 85.6 },
      { method: 'cash', label: 'Cash', amount: 184.6, pct: 14.4 },
    ],
    cash_share: 14.4,
    budget_status: [{ bucket_id: 'b1', bucket_name: 'Daily', icon: null, color: null, spent: 1310, budget: 1200, pct: 109, remaining: -110, over_budget: true }],
    fuel: {
      litres: 64, spend: 114.6, avg_price_per_litre: 1.84, fills: 2, unpriced_count: 1,
      months: [], cars: [
        { bucket_id: 'car1', name: 'Golf', icon: '🚗', litres: 40, spend: 72, avg_price_per_litre: 1.8, fills: 1, months: [], refuels: [{ date: '2026-10-02', price_per_litre: 1.8, litres: 40, spend: 72 }] },
        { bucket_id: 'car2', name: 'Yaris', icon: '🚙', litres: 24, spend: 42.6, avg_price_per_litre: 1.775, fills: 1, months: [], refuels: [{ date: '2026-10-05', price_per_litre: 1.775, litres: 24, spend: 42.6 }] },
      ],
    },
    ...over,
  }
}

/** A 2a CachedQuery-shaped value for mocked read hooks. */
export function query<T>(data: T | undefined, over: Record<string, unknown> = {}) {
  return {
    data, dataUpdatedAt: data === undefined ? 0 : Date.now(), fromCache: false, isLoading: data === undefined,
    isError: false, offline: false, stale: false, noData: false, refetch: () => {}, ...over,
  }
}
```

`web/src/features/insights/overview.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { makeInsights } from './fixtures'
import { deltaText, paidOutSentence, visibleWidgets } from './overview'

const THIS = { preset: 'this_month' } as const

describe('visibleWidgets', () => {
  it('is the fixed order for the household this month', () => {
    expect(visibleWidgets(makeInsights(), { lens: 'household', period: THIS })).toEqual([
      'headline', 'onTrack', 'inOut', 'where', 'inOutMonths', 'trend', 'biggest', 'method', 'budgets', 'savings', 'vsUsual', 'fuel',
    ])
  })
  it('a member lens adds identity and share and hides the household-only widgets', () => {
    expect(visibleWidgets(makeInsights(), { lens: 'm', period: THIS })).toEqual([
      'identity', 'headline', 'share', 'inOut', 'where', 'inOutMonths', 'trend', 'biggest', 'method', 'budgets', 'savings', 'fuel',
    ])
  })
  it('hides widgets on null data and On track outside this month', () => {
    const d = makeInsights({ fuel: null, kpis: { ...makeInsights().kpis, savings_rate: null, largest: null } })
    const ids = visibleWidgets(d, { lens: 'household', period: { preset: 'last_3m' } })
    expect(ids).not.toContain('fuel')
    expect(ids).not.toContain('savings')
    expect(ids).not.toContain('biggest')
    expect(ids).not.toContain('onTrack')
    expect(ids).not.toContain('vsUsual') // not a single month
  })
  it('an empty period shows the empty card only', () => {
    const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, total: 0 } })
    expect(visibleWidgets(empty, { lens: 'household', period: THIS })).toEqual(['headline', 'empty'])
  })
})

describe('sentences', () => {
  it('says more, less or about the same', () => {
    expect(paidOutSentence(141.2, { me: true, name: 'Giorgos' }, 'this month')).toBe('You paid €141.20 more than your share this month')
    expect(paidOutSentence(-20, { me: false, name: 'Maria' }, 'last month')).toBe('Maria paid €20.00 less than their share last month')
    expect(paidOutSentence(0.6, { me: true, name: 'G' }, 'in this period')).toBe('You paid about the same as your share in this period')
  })
  it('writes the delta in words and signs', () => {
    expect(deltaText(-8)).toBe('−8% vs the previous period')
    expect(deltaText(12.5)).toBe('+12.5% vs the previous period')
    expect(deltaText(0)).toBe('Same as the previous period')
    expect(deltaText(null)).toBeNull()
  })
})
```

`web/src/features/insights/Insights.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeInsights, query } from './fixtures'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))
const hooks = vi.hoisted(() => ({
  useInsights: vi.fn(), usePersonShare: vi.fn(), useMembers: vi.fn(), useCategoriesVsUsual: vi.fn(), usePlanMonth: vi.fn(), useHouseholdId: () => 'hh1',
}))
vi.mock('./hooks', () => hooks)

import { Insights } from './Insights'

const MEMBERS = { id: 'hh1', name: 'Home', default_currency: 'EUR', members: [
  { user_id: 'me', role: 'owner', joined_at: null, display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'm', role: 'member', joined_at: null, display_name: 'Maria', username: 'maria', avatar_color: null },
] }

function renderAt(url: string) {
  const qc = new QueryClient()
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[url]}>{children}</MemoryRouter></QueryClientProvider>
  )
  return render(<Insights />, { wrapper: wrap })
}

beforeEach(() => {
  localStorage.clear()
  hooks.useInsights.mockReturnValue(query(makeInsights()))
  hooks.usePersonShare.mockReturnValue(query(null))
  hooks.useMembers.mockReturnValue(query(MEMBERS))
  hooks.useCategoriesVsUsual.mockReturnValue(query([]))
  hooks.usePlanMonth.mockReturnValue(query(undefined))
})

const order = (c: HTMLElement) => [...c.querySelectorAll('[data-widget]')].map((e) => e.getAttribute('data-widget'))

describe('Insights', () => {
  it('renders the widgets in the fixed order with the headline', () => {
    const { container } = renderAt('/insights')
    expect(order(container)[0]).toBe('headline')
    expect(screen.getByText('Spent · Oct 1 – 6')).toBeInTheDocument()
    expect(screen.getByText('−8% vs the previous period')).toBeInTheDocument()
  })

  it('the lens is a labelled group of Household, Me and Maria', () => {
    renderAt('/insights')
    expect(screen.getByRole('radiogroup', { name: 'Whose spending' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Maria' })).toBeInTheDocument()
  })

  it('a member lens shows identity, the share card and its sentence', () => {
    hooks.usePersonShare.mockReturnValue(query({ user_id: 'm', paid_out: 600, my_share: 458.8, balance: 141.2, share_pct: 36, household_total: 1284.6, largest: null, shared_count: 4, transaction_count: 31 }))
    const { container } = renderAt('/insights?lens=m')
    expect(order(container).slice(0, 3)).toEqual(['identity', 'headline', 'share'])
    expect(screen.getByText('Maria paid €141.20 more than their share this month')).toBeInTheDocument()
    expect(hooks.usePersonShare).toHaveBeenLastCalledWith({ preset: 'this_month' }, 'm')
  })

  it('the share card fails on its own with Retry', () => {
    const refetch = vi.fn()
    hooks.usePersonShare.mockReturnValue(query(undefined, { isError: true, refetch }))
    renderAt('/insights?lens=m')
    expect(screen.getByText("Couldn't load this")).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetch).toHaveBeenCalled()
    expect(screen.getByText('Spent · Oct 1 – 6')).toBeInTheDocument() // the rest renders
  })

  it('an empty period links to the previous one when it had spending', () => {
    hooks.useInsights.mockReturnValue(query(makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, total: 0, previous_total: 900 } })))
    renderAt('/insights')
    expect(screen.getByText('No spending in this period')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'See the previous period' }))
    expect(screen.getByRole('button', { name: 'Last month' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('offline without cache says so', () => {
    hooks.useInsights.mockReturnValue(query(undefined, { noData: true, offline: true, isLoading: false }))
    renderAt('/insights')
    expect(screen.getByText('No saved data yet. Connect once to load Insights.')).toBeInTheDocument()
  })

  it('another view never loaded says so', () => {
    hooks.useInsights.mockReturnValue(query(undefined, { noData: true, offline: true, isLoading: false }))
    renderAt('/insights?p=last_month')
    expect(screen.getByText('No saved data for this view. Connect once to load it.')).toBeInTheDocument()
  })
})
```

(2a's `Segmented` is a button group with `aria-pressed`; the spec wants the lens to be a labelled radio group, so F2.1 adds a small `LensControl` with `role="radiogroup"` that reuses 2a's `.ui-seg` styles, instead of changing 2a's component.)

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/insights/overview.test.ts src/features/insights/Insights.test.tsx`
Expected: FAIL — `./overview` not found; the stub Insights renders no widgets.

- [ ] **Step 3: Implement `overview.ts`**

```ts
import { eur } from './format'
import { HOUSEHOLD, type Lens } from './lens'
import type { Period } from './period'
import type { InsightsData } from './types'

export type WidgetId =
  | 'identity' | 'headline' | 'share' | 'empty' | 'onTrack' | 'inOut' | 'where' | 'inOutMonths'
  | 'trend' | 'biggest' | 'method' | 'budgets' | 'savings' | 'vsUsual' | 'fuel'

export const isEmptyPeriod = (d: InsightsData) => d.kpis.count === 0 && d.total_spent === 0 && d.in_out.in === 0

/** YYYY-MM when the period is one calendar month (Categories vs usual compares a month). */
export function singleMonth(p: Period, d: InsightsData): string | null {
  return (p.preset === 'this_month' || p.preset === 'last_month') && d.start_date ? d.start_date.slice(0, 7) : null
}

/** The spec's fixed order (§4), minus what this lens, period or data hides. */
export function visibleWidgets(d: InsightsData, { lens, period }: { lens: Lens; period: Period }): WidgetId[] {
  const member = lens !== HOUSEHOLD
  const ids: WidgetId[] = member ? ['identity', 'headline', 'share'] : ['headline']
  if (isEmptyPeriod(d)) return [...ids, 'empty']
  if (!member && period.preset === 'this_month') ids.push('onTrack')
  ids.push('inOut')
  if (d.categories.length) ids.push('where')
  ids.push('inOutMonths', 'trend')
  if (d.kpis.largest) ids.push('biggest')
  if (d.by_method.length) ids.push('method')
  if (d.budget_status.length) ids.push('budgets')
  if (d.kpis.savings_rate != null) ids.push('savings')
  if (!member && singleMonth(period, d)) ids.push('vsUsual')
  if (d.fuel) ids.push('fuel')
  return ids
}

export function deltaText(changePct: number | null): string | null {
  if (changePct == null) return null
  if (changePct === 0) return 'Same as the previous period'
  return `${changePct < 0 ? '−' : '+'}${Math.abs(changePct)}% vs the previous period`
}

/** "You paid €141.20 more than your share this month" (less, or about the same under €1). */
export function paidOutSentence(balance: number, who: { me: boolean; name: string }, phrase: string): string {
  const subject = who.me ? 'You' : who.name
  const their = who.me ? 'your' : 'their'
  if (Math.abs(balance) < 1) return `${subject} paid about the same as ${their} share ${phrase}`
  return `${subject} paid ${eur(Math.abs(balance))} ${balance > 0 ? 'more' : 'less'} than ${their} share ${phrase}`
}
```

- [ ] **Step 4: Implement the lens control, the card, the summary widgets and the screen**

`web/src/features/insights/LensControl.tsx` (arrow keys move the choice, as a radio group should):

```tsx
import type { KeyboardEvent } from 'react'

export function LensControl({ label, options, value, onChange }: {
  label: string; options: { value: string; label: string }[]; value: string; onChange(v: string): void
}) {
  const move = (e: KeyboardEvent, i: number) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = options[(i + step + options.length) % options.length]
    onChange(next.value)
    ;(e.currentTarget.parentElement?.children[(i + step + options.length) % options.length] as HTMLElement | undefined)?.focus()
  }
  return (
    <div className="ui-seg insights__lens" role="radiogroup" aria-label={label}>
      {options.map((o, i) => (
        <button key={o.value} type="button" role="radio" className="ui-seg__opt" aria-checked={o.value === value}
          tabIndex={o.value === value ? 0 : -1} onClick={() => onChange(o.value)} onKeyDown={(e) => move(e, i)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
```

(`.ui-seg__opt[aria-checked='true']` needs the same look as 2a's `[aria-pressed='true']`; add that selector in `insights.css`.)

`web/src/features/insights/widgets/Card.tsx`:

```tsx
import { type ReactNode, useId } from 'react'

export function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  const id = useId()
  return (
    <section className="card insights__card" aria-labelledby={id}>
      <div className="insights__cardhead">
        <h2 id={id} className="insights__cardtitle">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}
```

`web/src/features/insights/widgets/summary.tsx`:

```tsx
import { HBarList } from '../../../ui/charts'
import { Badge } from '../../../ui/Badge'
import { Money } from '../../../ui/Money'
import type { HouseholdMember } from '../../settings/hooks'
import { eur, dayRange } from '../format'
import { deltaText, paidOutSentence } from '../overview'
import { type Period, periodPhrase, previousPeriod } from '../period'
import type { InsightsData, PersonShare } from '../types'
import { Card } from './Card'

export function Identity({ member }: { member: HouseholdMember | undefined }) {
  const name = member?.display_name || member?.username || 'Member'
  return (
    <div className="insights__identity">
      <span className="avatar" style={member?.avatar_color ? { background: member.avatar_color } : undefined} aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
      <span>Viewing <strong>{name}</strong>’s share</span>
    </div>
  )
}

export function Headline({ data }: { data: InsightsData }) {
  const delta = deltaText(data.kpis.change_pct)
  return (
    <div className="insights__headline">
      <p className="insights__eyebrow">Spent · {dayRange(data.start_date, data.end_date)}</p>
      <p className="insights__big num"><Money amount={data.total_spent} /></p>
      {delta && (
        <Badge tone={data.kpis.change_pct! > 0 ? 'warn' : 'pos'}>{delta}</Badge>
      )}
    </div>
  )
}

export function ShareCard({ query, who, period }: {
  query: { data?: PersonShare | null; isError: boolean; refetch(): unknown }
  who: { me: boolean; name: string }
  period: Period
}) {
  if (query.data === undefined || query.data === null) {
    return (
      <Card title="Paid out vs share">
        {query.isError ? (
          <p className="insights__error">Couldn't load this <button type="button" className="btn btn--sm" onClick={() => void query.refetch()}>Retry</button></p>
        ) : (
          <div className="skeleton" aria-busy="true" aria-label="Loading" />
        )}
      </Card>
    )
  }
  const s = query.data
  return (
    <Card title="Paid out vs share">
      <HBarList
        label="Paid out and share"
        format={eur}
        rows={[
          { id: 'paid', label: 'Paid out', value: s.paid_out },
          { id: 'share', label: who.me ? 'Your share' : 'Their share', value: s.my_share },
        ]}
      />
      <p className="insights__sentence">{paidOutSentence(s.balance, who, periodPhrase(period))}</p>
    </Card>
  )
}

export function EmptyPeriod({ data, period, onPeriod }: { data: InsightsData; period: Period; onPeriod(p: Period): void }) {
  const prev = (data.kpis.previous_total ?? 0) > 0 ? previousPeriod(period, data.kpis.range_start, data.kpis.range_end) : null
  return (
    <Card title="No spending in this period">
      {prev && <button type="button" className="btn" onClick={() => onPeriod(prev)}>See the previous period</button>}
    </Card>
  )
}
```

(`Card title` is rendered as the `h2`, so "No spending in this period" is a heading.)

`web/src/features/insights/Insights.tsx`:

```tsx
import type { ReactNode } from 'react'
import { useSession } from '../../session/SessionProvider'
import { TopBar } from '../../shell/TopBar'
import { Chips } from '../../ui/Chips'
import { QueryView } from '../../ui/QueryView'
import type { HouseholdMember } from '../settings/hooks'
import { LensControl } from './LensControl'
import { useInsights, useMembers, usePersonShare } from './hooks'
import { HOUSEHOLD, type Lens, lensOptions, useLens } from './lens'
import { type WidgetId, visibleWidgets } from './overview'
import { type Period, type Preset, PRESETS, usePeriod } from './period'
import { type InsightsData, NO_FILTERS } from './types'
import { EmptyPeriod, Headline, Identity, ShareCard } from './widgets/summary'
import './insights.css'

export interface WidgetCtx {
  data: InsightsData
  period: Period
  lens: Lens
  members: HouseholdMember[]
  meId: string
  setPeriod(p: Period): void
}

// F2.2 replaces the `() => null` entries.
const RENDER: Record<Exclude<WidgetId, 'identity' | 'share'>, (ctx: WidgetCtx) => ReactNode> = {
  headline: ({ data }) => <Headline data={data} />,
  empty: ({ data, period, setPeriod }) => <EmptyPeriod data={data} period={period} onPeriod={setPeriod} />,
  onTrack: () => null,
  inOut: () => null,
  where: () => null,
  inOutMonths: () => null,
  trend: () => null,
  biggest: () => null,
  method: () => null,
  budgets: () => null,
  savings: () => null,
  vsUsual: () => null,
  fuel: () => null,
}

export function Insights() {
  const { me } = useSession()
  const household = useMembers()
  const members = household.data?.members
  const [period, setPeriod] = usePeriod()
  const [lens, setLens] = useLens(members)
  const filters = NO_FILTERS // F2.3 wires the Filters sheet
  const insights = useInsights(period, lens, filters)
  const share = usePersonShare(period, lens === HOUSEHOLD ? null : lens)
  const meId = me?.id ?? ''
  const member = members?.find((m) => m.user_id === lens)
  const firstView = period.preset === 'this_month' && lens === HOUSEHOLD

  const pickPreset = (p: Preset) => {
    if (p !== 'custom') setPeriod({ preset: p })
  }

  return (
    <>
      <TopBar title="Insights" />
      <section className="screen insights">
        <div className="insights__bar">
          <Chips label="Period" options={PRESETS} value={period.preset} onChange={pickPreset} />
        </div>
        {members && meId && (
          <LensControl label="Whose spending" options={lensOptions(members, meId)} value={lens} onChange={setLens} />
        )}
        <QueryView
          result={insights}
          noDataText={firstView ? 'No saved data yet. Connect once to load Insights.' : 'No saved data for this view. Connect once to load it.'}
        >
          {(data) => {
            const ctx: WidgetCtx = { data, period, lens, members: members ?? [], meId, setPeriod }
            return visibleWidgets(data, { lens, period }).map((id) => (
              <div key={id} data-widget={id}>
                {id === 'identity' ? (
                  <Identity member={member} />
                ) : id === 'share' ? (
                  <ShareCard query={share} period={period} who={{ me: lens === meId, name: (member?.display_name || member?.username || '').split(' ')[0] }} />
                ) : (
                  RENDER[id](ctx)
                )}
              </div>
            ))
          }}
        </QueryView>
      </section>
    </>
  )
}
```

`web/src/features/insights/insights.css`: the screen column (centred, `max-width: 480px`), card spacing, `.insights__big` in Sora with tabular numerals, `.insights__bar` sticky under the top bar (the "pinned chip row") with a solid background, `.insights__identity`, `.insights__sentence`, `.insights__error`. Follow `docs/redesign/mocks/insights-settings.html` and `components.css`; no load animation.

- [ ] **Step 5: Run to verify pass**

Run: `npm test -- src/features/insights`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/insights
git commit -m "feat(web/insights): Insights screen with widget order, headline and paid out vs share"
```

### Task F2.2: The overview widgets (On track to Fuel)

**Stream:** F2 · **Depends on:** F2.1

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/features/insights/widgets/cards.tsx`
- Modify: `web/src/features/insights/Insights.tsx` (fill the `RENDER` entries)
- Test: `web/src/features/insights/widgets/cards.test.tsx`

**Interfaces:**
- Consumes: `HBarList`, `MonthBars`, `StackBar` (F1.2–F1.3), `insightsSearch` (F1.4), `usePlanMonth`, `useCategoriesVsUsual` (F1.6), `singleMonth` (F2.1), 2a `ProgressBar`, `Money`.
- Produces: `OnTrack`, `InOut`, `WhereItWent`, `InOutMonths`, `SpendTrend`, `Biggest`, `HowYouPaid`, `BudgetsCard`, `SavingsRate`, `VsUsual`, `FuelCard`, each taking `WidgetCtx` (or the fields it needs).

- [ ] **Step 1: Write the failing tests**

`web/src/features/insights/widgets/cards.test.tsx`:

```tsx
import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { makeInsights, query } from '../fixtures'

const hooks = vi.hoisted(() => ({ usePlanMonth: vi.fn(), useCategoriesVsUsual: vi.fn() }))
vi.mock('../hooks', () => hooks)

import { BudgetsCard, HowYouPaid, InOut, InOutMonths, OnTrack, SavingsRate, VsUsual, WhereItWent } from './cards'

const ctx = { data: makeInsights(), period: { preset: 'this_month' as const }, lens: 'household', members: [], meId: 'me', setPeriod: vi.fn() }

function Where() { const l = useLocation(); return <p data-testid="at">{l.pathname + l.search}</p> }
const wrap = (ui: ReactNode) => render(
  <MemoryRouter initialEntries={['/insights']}>
    <Routes><Route path="/insights" element={ui} /><Route path="*" element={<Where />} /></Routes>
  </MemoryRouter>,
)

describe('Where it went', () => {
  it('opens a category, opens Uncategorised, and leaves cash not logged untappable', () => {
    wrap(<WhereItWent {...ctx} lens="m" />)
    expect(screen.getByText('not logged')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cash \(not yet logged\)/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Uncategorised/ }))
    expect(screen.getByTestId('at')).toHaveTextContent('/insights/category/uncategorised?p=this_month&lens=m')
  })
})

describe('cards', () => {
  it('On track uses Out projected from the plan', () => {
    hooks.usePlanMonth.mockReturnValue(query({ month: '2026-10', fixed: { so_far: 600, still_to_come: 200, projected: 800 }, buckets: { so_far: 684.6, still_to_come: 825.4, projected: 1510, rows: [] }, income: { so_far: 3000, still_to_come: 0, projected: 3000 }, net_projected: 690, events_spent: 0, cash: 45, estimated: false }))
    wrap(<OnTrack {...ctx} />)
    expect(screen.getByText('On track for €2,310 by Oct 31')).toBeInTheDocument()
  })

  it('In / Out / Net, and In is what the member received under a lens', () => {
    wrap(<InOut {...ctx} lens="m" members={[{ user_id: 'm', role: 'member', joined_at: null, display_name: 'Maria P', username: 'maria', avatar_color: null }]} />)
    expect(screen.getByText('In · received by Maria')).toBeInTheDocument()
    expect(screen.getByText('€1,715.40')).toBeInTheDocument()
  })

  it('In and Out by month has a table and the six-month totals', () => {
    wrap(<InOutMonths {...ctx} />)
    expect(screen.getByRole('table', { name: 'In and Out by month' })).toBeInTheDocument()
    expect(screen.getByText(/6 months: In €18,000.00 · Out €13,124.60 · Net €4,875.40/)).toBeInTheDocument()
  })

  it('How you paid leaves out cash not logged and says so', () => {
    wrap(<HowYouPaid {...ctx} />)
    expect(screen.getByRole('img', { name: 'How you paid: Card €1,100.00, Cash €139.60' })).toBeInTheDocument()
    expect(screen.getByText('Leaves out the €45.00 cash not logged yet')).toBeInTheDocument()
  })

  it('Budgets says "over" in words and links to Plan', () => {
    wrap(<BudgetsCard {...ctx} />)
    expect(screen.getByText('€1,310.00 of €1,200.00 · over')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Plan › Budgets' })).toBeInTheDocument()
  })

  it('Savings rate reads as a sentence', () => {
    wrap(<SavingsRate {...ctx} />)
    expect(screen.getByText('You kept 57% of what came in')).toBeInTheDocument()
  })

  it('Categories vs usual lists flagged rows first with words', () => {
    hooks.useCategoriesVsUsual.mockReturnValue(query([
      { category_id: 'a', name: 'Eating out', icon: '🍽', color: '#f00', this_month: 90, usual: 120, flagged: false },
      { category_id: 'g', name: 'Groceries', icon: '🛒', color: '#0f0', this_month: 480, usual: 395, flagged: true },
    ]))
    wrap(<VsUsual {...ctx} />)
    const rows = within(screen.getByRole('list', { name: 'Categories vs usual' })).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Groceries')
    expect(rows[0]).toHaveTextContent('above usual')
    expect(hooks.useCategoriesVsUsual).toHaveBeenCalledWith('2026-10')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/insights/widgets/cards.test.tsx`
Expected: FAIL — `./cards` not found.

- [ ] **Step 3: Implement**

`web/src/features/insights/widgets/cards.tsx`:

```tsx
import { Link, useNavigate } from 'react-router'
import { HBarList, MonthBars, StackBar } from '../../../ui/charts'
import { Money } from '../../../ui/Money'
import { ProgressBar } from '../../../ui/ProgressBar'
import type { WidgetCtx } from '../Insights'
import { eur, monthEnd } from '../format'
import { useCategoriesVsUsual, usePlanMonth } from '../hooks'
import { HOUSEHOLD, insightsSearch } from '../lens'
import { singleMonth } from '../overview'
import { CASH_NOT_LOGGED, UNCATEGORISED } from '../types'
import { Card } from './Card'

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)

/** "On track for €2,310 by Oct 31": Out projected (Fixed + Buckets), not the straight-line forecast. */
export function OnTrack({ data }: WidgetCtx) {
  const plan = usePlanMonth((data.start_date ?? '').slice(0, 7)).data
  if (!plan) return null
  const out = plan.fixed.projected + plan.buckets.projected
  return (
    <Card title="This month">
      <p className="insights__sentence">On track for {eur(Math.round(out)).replace(/\.00$/, '')} by {monthEnd(data.start_date ?? `${plan.month}-01`)}</p>
    </Card>
  )
}

export function InOut({ data, lens, members }: WidgetCtx) {
  const who = members.find((m) => m.user_id === lens)
  const inLabel = lens === HOUSEHOLD || !who ? 'In' : `In · received by ${(who.display_name || who.username || '').split(' ')[0]}`
  return (
    <Card title="In / Out / Net">
      <dl className="insights__trio">
        <div><dt>{inLabel}</dt><dd className="num">{eur(data.in_out.in)}</dd></div>
        <div><dt>Out</dt><dd className="num">{eur(data.in_out.out)}</dd></div>
        <div><dt>Net</dt><dd className="num">{eur(data.in_out.net)}</dd></div>
      </dl>
    </Card>
  )
}

export function WhereItWent({ data, period, lens }: WidgetCtx) {
  const navigate = useNavigate()
  const rows = data.categories.slice(0, 9).map((c) => ({
    id: c.category_id === null ? UNCATEGORISED : c.category_id,
    label: c.name,
    icon: c.icon,
    value: c.amount,
    hatched: c.category_id === CASH_NOT_LOGGED,
  }))
  return (
    <Card title="Where it went">
      <HBarList label="Where it went" rows={rows} format={eur}
        onSelect={(row) => navigate(`/insights/category/${encodeURIComponent(row.id)}${insightsSearch(period, lens)}`)} />
    </Card>
  )
}

export function InOutMonths({ data }: WidgetCtx) {
  const m = data.monthly_in_out
  const totIn = sum(m.map((r) => r.in))
  const totOut = sum(m.map((r) => r.out))
  return (
    <Card title="In and Out by month">
      <MonthBars title="In and Out by month" months={m.map((r) => r.label)} current format={eur}
        series={[{ name: 'In', values: m.map((r) => r.in) }, { name: 'Out', values: m.map((r) => r.out) }]} />
      <p className="insights__foot num">6 months: In {eur(totIn)} · Out {eur(totOut)} · Net {eur(totIn - totOut)}</p>
    </Card>
  )
}

export function SpendTrend({ data }: WidgetCtx) {
  const t = data.monthly_trend
  const done = t.filter((r) => !r.is_current)
  const avg = done.length ? sum(done.map((r) => r.total)) / done.length : null
  return (
    <Card title="Spend trend">
      <MonthBars title="Spend by month" months={t.map((r) => r.label)} current={t.at(-1)?.is_current}
        series={[{ name: 'Spent', values: t.map((r) => r.total) }]} format={eur} />
      {avg != null && <p className="insights__foot num">Average {eur(avg)} a month</p>}
    </Card>
  )
}

export function Biggest({ data }: WidgetCtx) {
  const l = data.kpis.largest
  if (!l) return null
  return (
    <Card title="Biggest expense">
      <div className="row"><div className="main"><div className="t">{l.notes || l.category || 'Expense'}</div><div className="s">{l.date}{l.category ? ` · ${l.category}` : ''}</div></div><span className="num"><Money amount={l.amount} /></span></div>
    </Card>
  )
}

export function HowYouPaid({ data }: WidgetCtx) {
  const notLogged = data.in_out.cash_not_logged
  const segments = data.by_method
    .map((m) => ({ id: m.method, label: m.label, value: m.method === 'cash' ? Math.max(0, m.amount - notLogged) : m.amount }))
    .filter((s) => s.value > 0)
  const total = sum(segments.map((s) => s.value))
  return (
    <Card title="How you paid">
      <StackBar label="How you paid" segments={segments} format={eur} />
      <ul className="insights__list">
        {segments.map((s) => (
          <li key={s.id} className="row"><span className="main">{s.label}</span><span className="num">{eur(s.value)} · {total ? Math.round((s.value / total) * 100) : 0}%</span></li>
        ))}
      </ul>
      {notLogged > 0 && <p className="insights__foot">Leaves out the {eur(notLogged)} cash not logged yet</p>}
    </Card>
  )
}

export function BudgetsCard({ data }: WidgetCtx) {
  return (
    <Card title="Budgets" action={<Link to="/plan?view=budgets">Plan › Budgets</Link>}>
      <ul className="insights__list">
        {data.budget_status.map((b) => (
          <li key={b.bucket_id}>
            <div className="row"><span className="main">{b.bucket_name}</span>
              <span className="num">{b.budget != null ? `${eur(b.spent)} of ${eur(b.budget)}${b.over_budget ? ' · over' : ''}` : eur(b.spent)}</span></div>
            {b.budget != null && <ProgressBar value={b.spent} max={b.budget} label={`${b.bucket_name} budget`} />}
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function SavingsRate({ data }: WidgetCtx) {
  const r = data.kpis.savings_rate
  if (r == null) return null
  return (
    <Card title="Savings rate">
      <p className="insights__sentence">{r >= 0 ? `You kept ${Math.round(r)}% of what came in` : `You spent ${Math.abs(Math.round(r))}% more than came in`}</p>
    </Card>
  )
}

export function VsUsual({ data, period }: WidgetCtx) {
  // Only rendered for single-month periods (visibleWidgets), so the month is known.
  const rows = useCategoriesVsUsual(singleMonth(period, data) ?? '').data ?? []
  const sorted = [...rows].sort((a, b) => Number(b.flagged) - Number(a.flagged))
  if (!sorted.length) return null
  return (
    <Card title="Categories vs usual">
      <ul className="insights__list" aria-label="Categories vs usual">
        {sorted.map((c) => (
          <li key={c.category_id ?? c.name} className={c.flagged ? 'row row--flag' : 'row'}>
            <span className="main">{c.icon} {c.name}{c.flagged ? ' · above usual' : ''}</span>
            <span className="num">{eur(c.this_month)} · usual {c.usual != null ? eur(c.usual) : '—'}</span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function FuelCard({ data, period, lens }: WidgetCtx) {
  const fuel = data.fuel
  if (!fuel) return null
  return (
    <Card title="Fuel" action={<Link to={`/insights/fuel${insightsSearch(period, lens)}`}>All cars</Link>}>
      <ul className="insights__list">
        {fuel.cars.map((c) => (
          <li key={c.bucket_id}>
            <Link className="row" to={`/insights/fuel${insightsSearch(period, lens)}&car=${encodeURIComponent(c.bucket_id)}`}>
              <span className="main">{c.icon} {c.name}</span>
              <span className="num">{c.litres} L · {c.avg_price_per_litre != null ? `€${c.avg_price_per_litre.toFixed(3)}/L` : '—'}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}
```

(For `OnTrack`: `eurWhole` from `format.ts` gives "€2,310"; use it instead of the `.replace`. The Plan link's `?view=budgets` must match how 2a deep-links the Budgets segment; read 2a's `Plan.tsx`.)

In `Insights.tsx`, import these and replace the `() => null` entries: `onTrack: (c) => <OnTrack {...c} />`, `inOut: (c) => <InOut {...c} />`, `where: (c) => <WhereItWent {...c} />`, `inOutMonths: (c) => <InOutMonths {...c} />`, `trend: (c) => <SpendTrend {...c} />`, `biggest: (c) => <Biggest {...c} />`, `method: (c) => <HowYouPaid {...c} />`, `budgets: (c) => <BudgetsCard {...c} />`, `savings: (c) => <SavingsRate {...c} />`, `vsUsual: (c) => <VsUsual {...c} />`, `fuel: (c) => <FuelCard {...c} />`.

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/insights`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/insights
git commit -m "feat(web/insights): overview cards from On track to Fuel"
```

### Task F2.3: Filters: `RangeSheet` and `filters.ts`

**Stream:** F2 · **Depends on:** F2.2

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Create: `web/src/features/insights/filters.ts`, `web/src/features/insights/RangeSheet.tsx`
- Modify: `web/src/features/insights/Insights.tsx` (Filters button, Custom chip, the sheet, `useInsightFilters`)
- Test: `web/src/features/insights/RangeSheet.test.tsx`

**Interfaces:**
- Consumes: `rangeError`, `writePeriod` (F1.4), `useBuckets`, `useCategories` (F1.6), `Chips`, 2a `Sheet`.
- Produces: `parseFilters(params): InsightFilters`, `writeFilters(params, f): URLSearchParams` (`bucket_ids`, `category_ids` comma lists), `useInsightFilters(): [InsightFilters, (f: InsightFilters) => void]`; `RangeSheet(props: { open: boolean; onClose(): void; initialFrom: string; initialTo: string; filters: InsightFilters; onApply(p: Period, f: InsightFilters): void; onReset(): void })`.

- [ ] **Step 1: Write the failing test**

`web/src/features/insights/RangeSheet.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { query } from './fixtures'

vi.mock('../settings/hooks', () => ({
  useBuckets: () => query([{ id: 'b1', name: 'Daily' }, { id: 'b2', name: 'Trip' }]),
  useCategories: () => query([{ id: 'c1', name: 'Groceries', color: '#000', icon: '🛒', is_default: false, system_key: null, locked: false, expense_count: 0, rule_count: 0 }]),
}))

import { parseFilters, writeFilters } from './filters'
import { RangeSheet } from './RangeSheet'

describe('filters', () => {
  it('round-trips through the URL', () => {
    const p = writeFilters(new URLSearchParams('p=last_month'), { bucketIds: ['b1', 'b2'], categoryIds: [] })
    expect(p.toString()).toBe('p=last_month&bucket_ids=b1%2Cb2')
    expect(parseFilters(p)).toEqual({ bucketIds: ['b1', 'b2'], categoryIds: [] })
  })
})

describe('RangeSheet', () => {
  const base = { open: true, onClose: vi.fn(), initialFrom: '2026-10-01', initialTo: '2026-10-06', filters: { bucketIds: [], categoryIds: [] }, onReset: vi.fn() }

  it('applies a custom range and chips', () => {
    const onApply = vi.fn()
    render(<RangeSheet {...base} onApply={onApply} />)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
    fireEvent.click(screen.getByRole('button', { name: 'Daily' }))
    fireEvent.click(screen.getByRole('button', { name: 'Groceries' }))
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(onApply).toHaveBeenCalledWith({ preset: 'custom', from: '2026-09-01', to: '2026-10-06' }, { bucketIds: ['b1'], categoryIds: ['c1'] })
  })

  it('refuses From after To and an empty date', () => {
    const onApply = vi.fn()
    render(<RangeSheet {...base} onApply={onApply} />)
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-10-09' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByText('From must be on or before To.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(screen.getByText('Pick both dates.')).toBeInTheDocument()
    expect(onApply).not.toHaveBeenCalled()
  })

  it('Reset clears', () => {
    const onReset = vi.fn()
    render(<RangeSheet {...base} onReset={onReset} onApply={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(onReset).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/insights/RangeSheet.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

`web/src/features/insights/filters.ts`:

```ts
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { InsightFilters } from './types'

const list = (v: string | null) => (v ? v.split(',').filter(Boolean) : [])

export function parseFilters(params: URLSearchParams): InsightFilters {
  return { bucketIds: list(params.get('bucket_ids')), categoryIds: list(params.get('category_ids')) }
}

export function writeFilters(params: URLSearchParams, f: InsightFilters): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const [key, ids] of [['bucket_ids', f.bucketIds], ['category_ids', f.categoryIds]] as const) {
    if (ids.length) next.set(key, ids.join(','))
    else next.delete(key)
  }
  return next
}

/** Budget and category filters live in the URL only (not storage): they are a one-off look. */
export function useInsightFilters(): [InsightFilters, (f: InsightFilters) => void] {
  const [params, setParams] = useSearchParams()
  const set = useCallback((f: InsightFilters) => setParams((prev) => writeFilters(prev, f), { replace: true }), [setParams])
  // A stable object per URL, so consumers' effects don't re-run on every render.
  const search = params.toString()
  const filters = useMemo(() => parseFilters(new URLSearchParams(search)), [search])
  return [filters, set]
}
```

`web/src/features/insights/RangeSheet.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Chips } from '../../ui/Chips'
import { Sheet } from '../../ui/Sheet'
import { useBuckets, useCategories } from '../settings/hooks'
import { type Period, rangeError } from './period'
import { type InsightFilters, filtersKey } from './types'

export interface RangeSheetProps {
  open: boolean
  onClose(): void
  initialFrom: string
  initialTo: string
  filters: InsightFilters
  onApply(p: Period, f: InsightFilters): void
  onReset(): void
}

/** Custom range (native date inputs, both required, From ≤ To) and budget/category chips.
 *  "Paid by" is the lens, so it is not repeated here. */
export function RangeSheet({ open, onClose, initialFrom, initialTo, filters, onApply, onReset }: RangeSheetProps) {
  const [from, setFrom] = useState(initialFrom)
  const [to, setTo] = useState(initialTo)
  const [bucketIds, setBucketIds] = useState(filters.bucketIds)
  const [categoryIds, setCategoryIds] = useState(filters.categoryIds)
  const [error, setError] = useState<string | null>(null)
  const buckets = useBuckets().data ?? []
  const categories = useCategories().data ?? []

  // Reset only when the sheet opens (or what it opens with changes), never on a parent
  // re-render: a refetch while the sheet is open must not wipe what the user typed.
  const fkey = filtersKey(filters)
  useEffect(() => {
    if (!open) return
    setFrom(initialFrom); setTo(initialTo); setBucketIds(filters.bucketIds); setCategoryIds(filters.categoryIds); setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialFrom, initialTo, fkey])

  const apply = () => {
    const problem = rangeError(from, to)
    if (problem) return setError(problem)
    onApply({ preset: 'custom', from, to }, { bucketIds, categoryIds })
  }

  return (
    <Sheet open={open} onClose={onClose} title="Filters">
      <div className="field-row">
        <label className="field">From<input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} required /></label>
        <label className="field">To<input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} required /></label>
      </div>
      {error && <p className="field__error" role="alert">{error}</p>}
      {buckets.length > 0 && (
        <Chips multiple label="Budgets" options={buckets.map((b) => ({ value: b.id, label: b.name }))} value={bucketIds} onChange={setBucketIds} />
      )}
      {categories.length > 0 && (
        <Chips multiple label="Categories" options={categories.map((c) => ({ value: c.id, label: c.name }))} value={categoryIds} onChange={setCategoryIds} />
      )}
      <div className="sheet__actions">
        <button type="button" className="btn" onClick={onReset}>Reset</button>
        <button type="button" className="btn btn--primary" onClick={apply}>Apply</button>
      </div>
    </Sheet>
  )
}
```

In `Insights.tsx`: replace `const filters = NO_FILTERS` with `const [filters, setFilters] = useInsightFilters()`; add `const [sheet, setSheet] = useState(false)`; the Custom chip opens the sheet (`if (p === 'custom') setSheet(true)`); add a Filters icon button (`aria-label="Filters"`, 44 px) next to the chips; render

```tsx
      <RangeSheet
        open={sheet}
        onClose={() => setSheet(false)}
        initialFrom={period.from ?? insights.data?.kpis.range_start ?? ''}
        initialTo={period.to ?? insights.data?.kpis.range_end ?? ''}
        filters={filters}
        onApply={(p, f) => { setPeriod(p); setFilters(f); setSheet(false) }}
        onReset={() => { setPeriod({ preset: 'this_month' }); setFilters(NO_FILTERS); setSheet(false) }}
      />
```

Add a test to `Insights.test.tsx`: clicking "Filters" opens the sheet (`screen.getByRole('dialog', { name: 'Filters' })`), and with `?bucket_ids=b1` in the URL `useInsights` receives `{ bucketIds: ['b1'], categoryIds: [] }`. Mock `../settings/hooks` there as in `RangeSheet.test.tsx`.

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/insights`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/insights
git commit -m "feat(web/insights): Filters sheet with a custom range and budget and category chips"
```

### Task F2.4: Category drill-down and Fuel per car

**Stream:** F2 · **Depends on:** F2.3

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stubs from F1.7): `web/src/features/insights/CategoryScreen.tsx`, `web/src/features/insights/FuelScreen.tsx`
- Test: `web/src/features/insights/drilldowns.test.tsx`

**Interfaces:**
- Consumes: `useCategoryDetail` (F1.6), `usePeriod`, `useLens` (F1.4), `MonthBars`, `LineChart` (F1.3), `BackHeader` (F1.7), `useInsights` (fuel comes from `GET /insights`), `Chips`.
- Produces: `CategoryScreen()` at `/insights/category/:id`; `FuelScreen()` at `/insights/fuel` with `?car=<bucket_id>`.

- [ ] **Step 1: Write the failing test**

`web/src/features/insights/drilldowns.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeInsights, query } from './fixtures'

vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
const hooks = vi.hoisted(() => ({ useCategoryDetail: vi.fn(), useInsights: vi.fn(), useMembers: vi.fn(), useHouseholdId: () => 'hh1' }))
vi.mock('./hooks', () => hooks)

import { CategoryScreen } from './CategoryScreen'
import { FuelScreen } from './FuelScreen'

const DETAIL = {
  category: { id: 'g', name: 'Groceries', icon: '🛒', color: '#10b981' },
  total: 362.4, count: 12, avg_per_month: 395,
  months: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'].map((label, i) => ({ year: 2026, month: i + 5, label, total: [402, 388, 371, 356, 458, 362.4][i] })),
  merchants: [{ merchant: 'Sklavenitis', count: 6, total: 210 }, { merchant: 'Other', count: 1, total: 5 }],
  recent: [{ id: 't1', date: '2026-10-05', merchant: 'Sklavenitis', notes: null, amount: 40, paid_by: 'me' }],
  rules: [{ id: 'r1', pattern: 'sklaven', match_count: 48 }],
}

const at = (url: string, path: string, el: ReactElement) => render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={[url]}><Routes><Route path={path} element={el} /></Routes></MemoryRouter>
  </QueryClientProvider>,
)

beforeEach(() => {
  hooks.useMembers.mockReturnValue(query({ members: [{ user_id: 'm', role: 'member', joined_at: null, display_name: 'Maria', username: 'maria', avatar_color: null }] }))
  hooks.useCategoryDetail.mockReturnValue(query(DETAIL))
  hooks.useInsights.mockReturnValue(query(makeInsights()))
})

describe('CategoryScreen', () => {
  it('shows the total, average, months, shops, rules and recent expenses', () => {
    at('/insights/category/g?p=last_month&lens=m', '/insights/category/:id', <CategoryScreen />)
    expect(hooks.useCategoryDetail).toHaveBeenCalledWith('g', { preset: 'last_month' }, 'm')
    expect(screen.getByRole('heading', { name: 'Groceries' })).toBeInTheDocument()
    expect(screen.getByText('Average €395.00/mo')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Groceries per month' })).toBeInTheDocument()
    expect(screen.getByText('Sklavenitis')).toBeInTheDocument()
    expect(screen.getByText('sklaven 48')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Edit rules' })).toHaveAttribute('href', '/settings/categories')
    expect(screen.queryByRole('link', { name: 'See all' })).toBeNull() // until 2c ships Activity
  })

  it('names uncategorised', () => {
    hooks.useCategoryDetail.mockReturnValue(query({ ...DETAIL, category: null, rules: [] }))
    at('/insights/category/uncategorised', '/insights/category/:id', <CategoryScreen />)
    expect(screen.getByRole('heading', { name: 'Uncategorised' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit rules' })).toBeNull()
  })
})

describe('FuelScreen', () => {
  it('has a chip per car plus All cars, and ?car= picks one', () => {
    at('/insights/fuel?car=car2', '/insights/fuel', <FuelScreen />)
    expect(screen.getByRole('button', { name: 'All cars' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Yaris' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText(/Last fill/)).toBeInTheDocument()
    expect(screen.getByText(/2026-10-05 · 24 L/)).toBeInTheDocument()
  })

  it('says when there are no fills with litres, and counts unpriced fills', () => {
    hooks.useInsights.mockReturnValue(query(makeInsights({ fuel: null })))
    at('/insights/fuel', '/insights/fuel', <FuelScreen />)
    expect(screen.getByText('No fill-ups with litres in this period.')).toBeInTheDocument()
  })

  it('notes unpriced fills', () => {
    at('/insights/fuel', '/insights/fuel', <FuelScreen />)
    expect(screen.getByText('1 fill-ups have no price and are left out')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/insights/drilldowns.test.tsx`
Expected: FAIL — the stubs render "Coming soon".

- [ ] **Step 3: Implement**

`web/src/features/insights/CategoryScreen.tsx`:

```tsx
import { Link, useParams } from 'react-router'
import { BackHeader } from '../../ui/BackHeader'
import { Chips } from '../../ui/Chips'
import { MonthBars } from '../../ui/charts'
import { QueryView } from '../../ui/QueryView'
import { Card } from './widgets/Card'
import { eur } from './format'
import { useCategoryDetail, useMembers } from './hooks'
import { useLens } from './lens'
import { PRESETS, usePeriod } from './period'

/** /insights/category/:id: same period chips and lens as Insights (from the URL). */
export function CategoryScreen() {
  const { id = 'uncategorised' } = useParams()
  const members = useMembers().data?.members
  const [period, setPeriod] = usePeriod()
  const [lens] = useLens(members)
  const detail = useCategoryDetail(id, period, lens)
  const name = detail.data ? detail.data.category?.name ?? 'Uncategorised' : 'Category'

  return (
    <>
      <BackHeader title={name} back="/insights" keepSearch />
      <section className="screen insights">
        <Chips label="Period" options={PRESETS.filter((p) => p.value !== 'custom')} value={period.preset}
          onChange={(p) => setPeriod({ preset: p })} />
        <QueryView result={detail} noDataText="No saved data for this view. Connect once to load it.">
          {(d) => (
            <>
              <div className="insights__headline">
                <p className="insights__big num">{eur(d.total)}</p>
                {d.avg_per_month != null && <p className="insights__eyebrow num">Average {eur(d.avg_per_month)}/mo</p>}
              </div>
              <Card title="Six months">
                <MonthBars title={`${name} per month`} months={d.months.map((m) => m.label)} current
                  series={[{ name, values: d.months.map((m) => m.total) }]} format={eur} />
              </Card>
              {d.merchants.length > 0 && (
                <Card title="Top shops">
                  <ul className="insights__list">
                    {d.merchants.map((m) => (
                      <li key={m.merchant} className="row"><span className="main">{m.merchant}</span><span className="num">{m.count} · {eur(m.total)}</span></li>
                    ))}
                  </ul>
                </Card>
              )}
              {d.category && (
                <Card title="Rules" action={<Link to="/settings/categories">Edit rules</Link>}>
                  {d.rules.length ? (
                    <ul className="chips" aria-label="Rules">
                      {d.rules.map((r) => <li key={r.id} className="chip chip--static">{`${r.pattern} ${r.match_count}`}</li>)}
                    </ul>
                  ) : <p className="insights__foot">No rules yet.</p>}
                </Card>
              )}
              <Card title="Latest">
                <ul className="insights__list">
                  {d.recent.map((t) => (
                    <li key={t.id} className="row"><span className="main">{t.merchant || t.notes || name}<span className="s"> · {t.date}</span></span><span className="num">{eur(t.amount)}</span></li>
                  ))}
                </ul>
              </Card>
            </>
          )}
        </QueryView>
      </section>
    </>
  )
}
```

(The "See all" link to Activity with `category_id` is added by 2c once Activity exists; do not render it here.)

`web/src/features/insights/FuelScreen.tsx`:

```tsx
import { useSearchParams } from 'react-router'
import { BackHeader } from '../../ui/BackHeader'
import { Chips } from '../../ui/Chips'
import { LineChart, MonthBars } from '../../ui/charts'
import { QueryView } from '../../ui/QueryView'
import { Card } from './widgets/Card'
import { eur } from './format'
import { useInsights, useMembers } from './hooks'
import { useLens } from './lens'
import { usePeriod } from './period'
import { type FuelData, NO_FILTERS } from './types'

const ALL = 'all'
const perLitre = (n: number) => `€${n.toFixed(3)}`

function view(fuel: FuelData, car: string) {
  const one = fuel.cars.find((c) => c.bucket_id === car)
  const refuels = one ? one.refuels : fuel.cars.flatMap((c) => c.refuels).sort((a, b) => a.date.localeCompare(b.date))
  return {
    months: one ? one.months : fuel.months,
    refuels,
    litres: one ? one.litres : fuel.litres,
    spend: one ? one.spend : fuel.spend,
    avg: one ? one.avg_price_per_litre : fuel.avg_price_per_litre,
  }
}

/** /insights/fuel: data is `fuel` from GET /insights (no new endpoint). */
export function FuelScreen() {
  const members = useMembers().data?.members
  const [period] = usePeriod()
  const [lens] = useLens(members)
  const [params, setParams] = useSearchParams()
  const insights = useInsights(period, lens, NO_FILTERS)

  return (
    <>
      <BackHeader title="Fuel" back="/insights" keepSearch />
      <section className="screen insights">
        <QueryView result={insights} noDataText="No saved data for this view. Connect once to load it.">
          {(data) => {
            const fuel = data.fuel
            if (!fuel) return <p className="screen__note">No fill-ups with litres in this period.</p>
            const car = fuel.cars.some((c) => c.bucket_id === params.get('car')) ? params.get('car')! : ALL
            const v = view(fuel, car)
            const last = v.refuels.at(-1)
            const six = v.refuels.slice(-6)
            return (
              <>
                <Chips label="Car" value={car}
                  options={[{ value: ALL, label: 'All cars' }, ...fuel.cars.map((c) => ({ value: c.bucket_id, label: c.name }))]}
                  onChange={(c) => setParams((p) => { const n = new URLSearchParams(p); if (c === ALL) n.delete('car'); else n.set('car', c); return n }, { replace: true })} />
                {last && (
                  <Card title="Last fill">
                    <p className="num">{last.date} · {last.litres} L · {perLitre(last.price_per_litre)}/L · {eur(last.spend)}</p>
                  </Card>
                )}
                {six.length > 0 && (
                  <Card title="Price per litre">
                    <LineChart title="Price per litre, last fills" format={perLitre} average={v.avg}
                      points={six.map((r) => ({ label: r.date, value: r.price_per_litre }))} />
                  </Card>
                )}
                {v.months.length > 0 && (
                  <div className="insights__pair">
                    <Card title="Litres / month">
                      <MonthBars title="Litres per month" width={140} height={100} months={v.months.map((m) => m.label.slice(0, 3))}
                        series={[{ name: 'Litres', values: v.months.map((m) => m.litres) }]} format={(n) => `${Math.round(n)} L`} />
                    </Card>
                    <Card title="Spend / month">
                      <MonthBars title="Fuel spend per month" width={140} height={100} months={v.months.map((m) => m.label.slice(0, 3))}
                        series={[{ name: 'Spend', values: v.months.map((m) => m.spend) }]} format={eur} />
                    </Card>
                  </div>
                )}
                <dl className="insights__trio">
                  <div><dt>Average price</dt><dd className="num">{v.avg != null ? `${perLitre(v.avg)}/L` : '—'}</dd></div>
                  <div><dt>Litres</dt><dd className="num">{v.litres} L</dd></div>
                  <div><dt>Spend</dt><dd className="num">{eur(v.spend)}</dd></div>
                </dl>
                {fuel.unpriced_count > 0 && <p className="insights__foot">{fuel.unpriced_count} fill-ups have no price and are left out</p>}
              </>
            )
          }}
        </QueryView>
      </section>
    </>
  )
}
```

(`/insights/fuel` shares the overview's cache entry for the same period, lens and no filters, so it opens offline whenever Insights did.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/insights && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/insights
git commit -m "feat(web/insights): category drill-down and fuel per car"
```

---
## Stream F3: Settings hub, Profile & security, Household

F3 tests render inside `MemoryRouter` and a fresh `QueryClientProvider`, mock `../../session/SessionProvider` and mock 2a's toast (`vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))` with a hoisted `toast = vi.fn()`). Network is a `vi.spyOn(globalThis, 'fetch')` that answers by URL. Read hooks (`./hooks`) are mocked with `vi.mock` returning `query(...)` values (copy the `query` helper from `features/insights/fixtures.ts` or import it).

### Task F3.1: Settings hub and the account-sheet entry

**Stream:** F3 · **Depends on:** F1, B

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stub): `web/src/features/settings/Settings.tsx`
- Create: `web/src/features/settings/subtitles.ts`, `web/src/features/settings/settings.css`
- Modify: `web/src/shell/TopBar.tsx` (a "Settings" row above "Sign out")
- Test: `web/src/features/settings/Settings.test.tsx`

**Interfaces:**
- Consumes: `useProfile`, `useSecurity`, `useHousehold`, `useCategories`, `useRules`, `useTokens`, `useNotificationPrefs` (F1.6); `usePushState` (F1.7); `BackHeader`; Phase 1 `useSession().signOut`.
- Produces: `hubSubtitles(input: { security?: Security; household?: HouseholdInfo; categories?: CategoryItem[]; rules?: Rule[]; tokens?: TokenItem[]; prefs?: NotificationPrefs | null; push: PushState | null }): Record<'profile' | 'household' | 'categories' | 'automations' | 'notifications', string>`; `buildString(scriptUrl?: string): string`.

- [ ] **Step 1: Write the failing test**

`web/src/features/settings/Settings.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const signOut = vi.hoisted(() => vi.fn())
vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos', email: 'g@x.t' }, signOut }),
}))
vi.mock('../../pwa/pushClient', () => ({ usePushState: () => ({ state: 'on', refresh: vi.fn() }) }))
vi.mock('./hooks', () => ({
  useProfile: () => query({ id: 'me', username: 'g', display_name: 'Giorgos', email: 'g@x.t', avatar_color: '#6366f1', totp_enabled: true, household_id: 'hh1' }),
  useSecurity: () => query({ totp_enabled: true, backup_codes_remaining: 8, passkey_available: true, passkey_linked: true, password_session: true }),
  useHousehold: () => query({ id: 'hh1', name: 'Home', default_currency: 'EUR', members: [{ user_id: 'me' }, { user_id: 'm' }] }),
  useCategories: () => query(Array.from({ length: 11 }, (_, i) => ({ id: `c${i}` }))),
  useRules: () => query(Array.from({ length: 96 }, (_, i) => ({ id: `r${i}` }))),
  useTokens: () => query([{ id: 't1' }]),
  useNotificationPrefs: () => query({ types: Array.from({ length: 9 }, (_, i) => ({ type: `t${i}`, group: 'Bills', label: 'x', enabled: true })), push_devices: 1 }),
}))

import { Settings } from './Settings'
import { buildString, hubSubtitles } from './subtitles'

const renderHub = () => render(
  <QueryClientProvider client={new QueryClient()}><MemoryRouter><Settings /></MemoryRouter></QueryClientProvider>,
)

describe('Settings hub', () => {
  it('shows live subtitles and links to each screen', () => {
    renderHub()
    for (const [name, sub, href] of [
      ['Profile & security', '2FA on · passkey linked', '/settings/profile'],
      ['Household', 'Home · 2 members · EUR', '/settings/household'],
      ['Categories & rules', '11 categories · 96 rules', '/settings/categories'],
      ['Automations', 'Apple Pay Shortcut · 1 token', '/settings/automations'],
      ['Notifications', 'Push on · 9 of 9 alerts', '/settings/notifications'],
    ]) {
      const link = screen.getByRole('link', { name: new RegExp(name) })
      expect(link).toHaveAttribute('href', href)
      expect(link).toHaveTextContent(sub)
    }
  })

  it('signs out', () => {
    renderHub()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(signOut).toHaveBeenCalled()
  })
})

describe('hubSubtitles', () => {
  it('copes with missing data and the mutes API not being there yet', () => {
    const s = hubSubtitles({ push: 'off', prefs: null, tokens: [], security: { totp_enabled: false, backup_codes_remaining: 0, passkey_available: false, passkey_linked: false, password_session: true } })
    expect(s.profile).toBe('2FA off')
    expect(s.automations).toBe('Apple Pay Shortcut · no tokens')
    expect(s.notifications).toBe('Push off')
    expect(s.household).toBe('')
  })
  it('reads the build from the script name', () => {
    expect(buildString('https://x.test/app/assets/index-Ab12Cd.js')).toBe('Build Ab12Cd')
    expect(buildString('https://x.test/src/main.tsx')).toBe('Build dev')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/settings/Settings.test.tsx`
Expected: FAIL — `./subtitles` not found; the stub hub has no rows.

- [ ] **Step 3: Implement**

`web/src/features/settings/subtitles.ts`:

```ts
import type { PushState } from '../../pwa/pushClient'
import type { CategoryItem, HouseholdInfo, NotificationPrefs, Rule, Security, TokenItem } from './hooks'

const n = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`

export function hubSubtitles(i: {
  security?: Security; household?: HouseholdInfo; categories?: CategoryItem[]; rules?: Rule[]
  tokens?: TokenItem[]; prefs?: NotificationPrefs | null; push: PushState | null
}) {
  const sec = i.security
  const profile = !sec ? '' : [
    sec.totp_enabled ? '2FA on' : '2FA off',
    ...(sec.passkey_available ? [sec.passkey_linked ? 'passkey linked' : 'no passkey'] : []),
  ].join(' · ')
  const household = i.household ? `${i.household.name} · ${n(i.household.members.length, 'member')} · ${i.household.default_currency}` : ''
  const categories = i.categories ? `${n(i.categories.length, 'category', 'categories')}${i.rules ? ` · ${n(i.rules.length, 'rule')}` : ''}` : ''
  const automations = i.tokens ? `Apple Pay Shortcut · ${i.tokens.length ? n(i.tokens.length, 'token') : 'no tokens'}` : 'Apple Pay Shortcut'
  const push = i.push === 'on' ? 'Push on' : 'Push off'
  const alerts = i.prefs ? ` · ${i.prefs.types.filter((t) => t.enabled).length} of ${i.prefs.types.length} alerts` : ''
  return { profile, household, categories, automations, notifications: push + alerts }
}

/** "Build Ab12Cd" from the hashed entry script name; "Build dev" under the dev server. */
export function buildString(scriptUrl: string = import.meta.url): string {
  const m = /index-([A-Za-z0-9_-]+)\.js$/.exec(scriptUrl)
  return `Build ${m ? m[1] : 'dev'}`
}
```

`web/src/features/settings/Settings.tsx`:

```tsx
import { Link } from 'react-router'
import { usePushState } from '../../pwa/pushClient'
import { useSession } from '../../session/SessionProvider'
import { BackHeader } from '../../ui/BackHeader'
import { useCategories, useHousehold, useNotificationPrefs, useProfile, useRules, useSecurity, useTokens } from './hooks'
import { buildString, hubSubtitles } from './subtitles'
import './settings.css'

const ROWS = [
  { key: 'profile', title: 'Profile & security', to: '/settings/profile' },
  { key: 'household', title: 'Household', to: '/settings/household' },
  { key: 'categories', title: 'Categories & rules', to: '/settings/categories' },
  { key: 'automations', title: 'Automations', to: '/settings/automations' },
  { key: 'notifications', title: 'Notifications', to: '/settings/notifications' },
] as const

/** A short hub; subtitles come from cached queries, so it works offline. */
export function Settings() {
  const { me, signOut } = useSession()
  const profile = useProfile().data
  const subs = hubSubtitles({
    security: useSecurity().data,
    household: useHousehold().data,
    categories: useCategories().data,
    rules: useRules().data,
    tokens: useTokens().data,
    prefs: useNotificationPrefs().data,
    push: usePushState().state,
  })
  const name = profile?.display_name ?? me?.display_name ?? ''
  return (
    <>
      <BackHeader title="Settings" back="/" />
      <section className="screen settings">
        <Link to="/settings/profile" className="card settings__who">
          <span className="avatar avatar--lg" style={profile?.avatar_color ? { background: profile.avatar_color } : undefined} aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
          <span><span className="settings__name">{name}</span>{(profile?.email ?? me?.email) && <span className="settings__sub">{profile?.email ?? me?.email}</span>}</span>
        </Link>
        <nav className="card settings__list" aria-label="Settings">
          {ROWS.map((r) => (
            <Link key={r.key} to={r.to} className="row">
              <span className="main"><span className="t">{r.title}</span>{subs[r.key] && <span className="s">{subs[r.key]}</span>}</span>
              <span className="chev" aria-hidden="true">›</span>
            </Link>
          ))}
        </nav>
        <button type="button" className="btn btn--danger btn--block" onClick={() => void signOut()}>Sign out</button>
        <p className="settings__build">{buildString()}</p>
      </section>
    </>
  )
}
```

(The profile card's link name includes the user's name; the test queries rows by their title, so the `Profile & security` row is matched, not the card. If both match, give the card `aria-label="Your profile"`.)

`web/src/shell/TopBar.tsx`: import `Link` from `react-router`; inside the sheet body, before the Sign out button:

```tsx
          <Link to="/settings" className="btn btn--block" onClick={close}>Settings</Link>
```

Add to `Settings.test.tsx` a test rendering `<TopBar title="Home" />` inside `MemoryRouter` that finds `screen.getByRole('link', { name: 'Settings', hidden: true })` with `href="/settings"` (the dialog content is hidden until opened). Run Phase 1's `npm test -- src/shell` too: any Phase 1 test that renders `TopBar` (or a screen containing it) without a router now throws "useHref() may be used only in the context of a <Router>"; wrap those renders in `<MemoryRouter>` (test-only change, same assertions).

`settings.css`: the hub layout from `docs/redesign/mocks/insights-settings.html` (the Settings phone): identity card, grouped list with chevrons, 44 px rows, the build string small and muted; centred 480 px column.

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/settings/Settings.test.tsx src/shell`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/Settings.tsx web/src/features/settings/subtitles.ts web/src/features/settings/settings.css web/src/features/settings/Settings.test.tsx web/src/shell/TopBar.tsx
git commit -m "feat(web/settings): Settings hub with live subtitles; entry in the account sheet"
```

### Task F3.2: Profile & security

**Stream:** F3 · **Depends on:** F3.1

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stub): `web/src/features/settings/Profile.tsx`
- Create: `web/src/features/settings/profileHooks.ts`, `web/src/features/settings/TwoFactor.tsx`, `web/src/features/settings/Passkey.tsx`, `web/src/session/notice.ts`
- Modify: `web/src/session/SignIn.tsx` (show a one-shot notice)
- Test: `web/src/features/settings/Profile.test.tsx`

**Interfaces:**
- Consumes: `useOnlineAction` (F1.5), `useProfile`, `useSecurity` (F1.6), `SWATCHES`, `swatchName` (F1.6), 2a's `Sheet` (`closeOnBackdrop`), `readCsrf` (Phase 1 `api/client.ts`), `useSession().signOut`.
- Produces: `useProfileActions(): { saveProfile(body); changePassword(body); totpSetup(); totpEnable(code); totpDisable(body) }` (each returns `OnlineOutcome`); `groupSecret(secret: string): string`; `setSignInNotice(text: string): void`, `takeSignInNotice(): string | null`; `PASSKEY_MESSAGES: Record<'linked' | 'unlinked' | 'error', string>`.
- Behaviour (resolved gap): after a successful Turn off **on a password session**, the Set up sheet opens straight away with "Password sign-in needs 2FA. Set it up again to keep using Tameio." — the rest of the app answers 403 until it is back on.

- [ ] **Step 1: Write the failing test**

`web/src/features/settings/Profile.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const { toast, signOut, security } = vi.hoisted(() => ({ toast: vi.fn(), signOut: vi.fn(async () => {}), security: { current: {} as Record<string, unknown> } }))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' }, signOut }) }))
vi.mock('./hooks', () => ({
  useProfile: () => query({ id: 'me', username: 'g', display_name: 'Giorgos', email: 'g@x.t', avatar_color: '#6366f1', totp_enabled: true, household_id: 'hh1' }),
  useSecurity: () => query(security.current),
}))

import { takeSignInNotice } from '../../session/notice'
import { Profile } from './Profile'
import { groupSecret } from './TwoFactor'

const ON = { totp_enabled: true, backup_codes_remaining: 6, passkey_available: true, passkey_linked: false, password_session: true }
let qc: QueryClient

function Loc() { return <p data-testid="loc">{useLocation().search}</p> }
function renderAt(url = '/settings/profile') {
  qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}><Routes><Route path="/settings/profile" element={<><Profile /><Loc /></>} /></Routes></MemoryRouter>
    </QueryClientProvider>,
  )
}
function answer(routes: Record<string, () => Response>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input))
    const hit = routes[url.pathname]
    return hit ? hit() : new Response('{}', { status: 404 })
  })
}
const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => { security.current = ON; document.cookie = 'csrf_token=tok' })
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); sessionStorage.clear() })

describe('Profile', () => {
  it('blocks a save offline, sends nothing and says why', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection."))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('checks the new password length before sending', () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    const sheet = screen.getByRole('dialog', { name: 'Change password', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Current password'), { target: { value: 'old-password-123' } })
    fireEvent.change(within(sheet).getByLabelText('New password'), { target: { value: 'short' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Change and sign out', hidden: true }))
    expect(within(sheet).getByText('Use at least 12 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('a password change ends signed out with a notice', async () => {
    answer({ '/api/v1/settings/profile/password': () => new Response(null, { status: 204 }) })
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    const sheet = screen.getByRole('dialog', { name: 'Change password', hidden: true })
    expect(within(sheet).getByText(/You'll be signed out everywhere and your Apple Pay tokens will stop working/)).toBeInTheDocument()
    fireEvent.change(within(sheet).getByLabelText('Current password'), { target: { value: 'old-password-123' } })
    fireEvent.change(within(sheet).getByLabelText('New password'), { target: { value: 'a-long-new-password' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Change and sign out', hidden: true }))
    await waitFor(() => expect(signOut).toHaveBeenCalled())
    expect(takeSignInNotice()).toBe('Password changed. Sign in again.')
  })

  it('sets up 2FA: grouped secret, otpauth link, then backup codes that ignore the backdrop', async () => {
    security.current = { ...ON, totp_enabled: false, backup_codes_remaining: 0 }
    answer({
      '/api/v1/settings/security/totp/setup': json({ secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Tameio:g?secret=JBSWY3DPEHPK3PXP' }),
      '/api/v1/settings/security/totp/enable': json({ backup_codes: ['AAAA1', 'BBBB2', 'CCCC3', 'DDDD4', 'EEEE5', 'FFFF6', 'GGGG7', 'HHHH8'] }),
    })
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Set up' }))
    expect(await screen.findByText('JBSW Y3DP EHPK 3PXP')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in authenticator' })).toHaveAttribute('href', expect.stringMatching(/^otpauth:\/\//))
    const code = screen.getByLabelText('6-digit code')
    expect(code).toHaveAttribute('autocomplete', 'one-time-code')
    expect(code).toHaveAttribute('inputmode', 'numeric')
    fireEvent.change(code, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    const sheet = await screen.findByRole('dialog', { name: 'Backup codes', hidden: true })
    expect(within(sheet).getByText('AAAA1')).toBeInTheDocument()
    fireEvent.click(screen.getAllByTestId('sheet-backdrop').at(-1)!) // 2a's backdrop element
    expect(screen.getByRole('dialog', { name: 'Backup codes', hidden: true })).toBeInTheDocument()
    // Never cached, never stored.
    const cached = JSON.stringify(qc.getQueryCache().getAll().map((q) => q.state.data))
    expect(cached).not.toContain('AAAA1')
    expect(cached).not.toContain('JBSWY3DPEHPK3PXP')
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('AAAA1')
    fireEvent.click(within(sheet).getByRole('button', { name: "I've saved these" }))
    await waitFor(() => expect(screen.queryByText('AAAA1')).toBeNull())
  })

  it('after Turn off on a password session the Set up sheet opens', async () => {
    answer({
      '/api/v1/settings/security/totp/disable': () => new Response(null, { status: 204 }),
      '/api/v1/settings/security/totp/setup': json({ secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/x' }),
    })
    renderAt()
    expect(screen.getByText('6 backup codes left')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    const sheet = screen.getByRole('dialog', { name: 'Turn off 2FA', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Password'), { target: { value: 'pw-123456789012' } })
    fireEvent.change(within(sheet).getByLabelText('Authenticator code'), { target: { value: '123456' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Turn off 2FA', hidden: true }))
    expect(await screen.findByText('Password sign-in needs 2FA. Set it up again to keep using Tameio.')).toBeInTheDocument()
  })

  it('links a passkey with a native form carrying CSRF and return_to', () => {
    renderAt()
    const form = screen.getByRole('button', { name: 'Link passkey' }).closest('form')!
    expect(form).toHaveAttribute('action', '/app/auth/link')
    expect(form).toHaveAttribute('method', 'post')
    const data = new FormData(form)
    expect(data.get('_csrf_token')).toBe('tok')
    expect(data.get('return_to')).toBe('app')
    expect(within(form).getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password')
  })

  it('unlinks with the same hidden fields', () => {
    security.current = { ...ON, passkey_linked: true }
    renderAt()
    const form = screen.getByRole('button', { name: 'Unlink' }).closest('form')!
    expect(form).toHaveAttribute('action', '/app/auth/unlink')
    expect(new FormData(form).get('return_to')).toBe('app')
  })

  it('a passkey-only session cannot change the passkey', () => {
    security.current = { ...ON, password_session: false, passkey_linked: true }
    renderAt()
    expect(screen.getByText('Sign in with your password and 2FA to change this.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Unlink' })).toBeNull()
  })

  it('toasts ?passkey= once and drops it from the URL', async () => {
    renderAt('/settings/profile?passkey=error')
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Couldn't link the passkey. Check your password and code."))
    expect(toast).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('loc')).toHaveTextContent('')
  })
})

describe('groupSecret', () => {
  it('groups in fours', () => {
    expect(groupSecret('JBSWY3DPEHPK3PXP')).toBe('JBSW Y3DP EHPK 3PXP')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/settings/Profile.test.tsx`
Expected: FAIL — modules not found; the stub has none of this.

- [ ] **Step 3: Implement the notice and the actions**

`web/src/session/notice.ts`:

```ts
const KEY = 'tameio.signin.notice'

/** A one-line message the sign-in screen shows once (e.g. after a password change). Not sensitive. */
export function setSignInNotice(text: string): void {
  try { sessionStorage.setItem(KEY, text) } catch { /* storage unavailable: no notice */ }
}

export function takeSignInNotice(): string | null {
  try {
    const text = sessionStorage.getItem(KEY)
    sessionStorage.removeItem(KEY)
    return text
  } catch {
    return null
  }
}
```

In `web/src/session/SignIn.tsx`: `const [notice] = useState(takeSignInNotice)` and render `{notice && <p role="status" className="notice notice--ok">{notice}</p>}` above the sign-in buttons. Add a case to `src/session/SessionProvider.test.tsx` or a new `SignIn.test.tsx`: with `setSignInNotice('Password changed. Sign in again.')`, `<SignIn result={{ error: null, linked: false }} />` shows it, and a second render does not.

`web/src/features/settings/profileHooks.ts`:

```ts
import { api } from '../../api/client'
import { settingsKeys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import { useSession } from '../../session/SessionProvider'

export function useProfileActions() {
  const act = useOnlineAction()
  const hh = useSession().me?.household_id ?? ''
  const security = [settingsKeys.security(hh), settingsKeys.profile(hh)]
  return {
    saveProfile: (body: { display_name: string; email: string | null; avatar_color: string }) =>
      act(() => api.PUT('/api/v1/settings/profile', { body }), { invalidates: [settingsKeys.profile(hh), settingsKeys.household(hh)], success: 'Profile saved' }),
    changePassword: (body: { current_password: string; new_password: string }) =>
      act(() => api.POST('/api/v1/settings/profile/password', { body })),
    // Responses carry secrets: returned to the component, never cached.
    totpSetup: () => act(() => api.POST('/api/v1/settings/security/totp/setup')),
    totpEnable: (code: string) => act(() => api.POST('/api/v1/settings/security/totp/enable', { body: { code } }), { invalidates: security }),
    totpDisable: (body: { current_password: string; code: string }) =>
      act(() => api.POST('/api/v1/settings/security/totp/disable', { body }), { invalidates: security }),
  }
}
```

- [ ] **Step 4: Implement the screen**

`web/src/features/settings/TwoFactor.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Sheet } from '../../ui/Sheet'
import type { Security } from './hooks'
import { useProfileActions } from './profileHooks'

export const groupSecret = (s: string) => s.replace(/\s+/g, '').match(/.{1,4}/g)?.join(' ') ?? ''
export const REENROL = 'Password sign-in needs 2FA. Set it up again to keep using Tameio.'

const copy = (text: string) => void navigator.clipboard?.writeText(text)

export function TwoFactor({ security }: { security: Security }) {
  const actions = useProfileActions()
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [setupOpen, setSetupOpen] = useState(false)
  const [reason, setReason] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [offOpen, setOffOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [offCode, setOffCode] = useState('')

  // Secrets live in this component only and go when it unmounts.
  useEffect(() => () => { setSetup(null); setCodes(null) }, [])

  const openSetup = async (why: string | null = null) => {
    setReason(why); setCode(''); setSetupOpen(true)
    const out = await actions.totpSetup()
    if (out.ok) setSetup(out.data as { secret: string; otpauth_uri: string })
    else setSetupOpen(false)
  }
  const closeSetup = () => { setSetupOpen(false); setSetup(null); setCode('') }
  const enable = async () => {
    const out = await actions.totpEnable(code.trim())
    if (out.ok) { closeSetup(); setCodes((out.data as { backup_codes: string[] }).backup_codes) }
  }
  const turnOff = async () => {
    const out = await actions.totpDisable({ current_password: password, code: offCode.trim() })
    if (!out.ok) return
    setOffOpen(false); setPassword(''); setOffCode('')
    if (security.password_session) void openSetup(REENROL)
  }

  return (
    <section className="card" aria-labelledby="tfa">
      <h2 id="tfa">Two-factor</h2>
      {security.totp_enabled ? (
        <div className="row">
          <span className="main">{`${security.backup_codes_remaining} backup codes left`}</span>
          <button type="button" className="btn" onClick={() => setOffOpen(true)}>Turn off</button>
        </div>
      ) : (
        <div className="row"><span className="main">Off</span><button type="button" className="btn btn--primary" onClick={() => void openSetup()}>Set up</button></div>
      )}

      <Sheet open={setupOpen} onClose={closeSetup} title="Set up 2FA" closeOnBackdrop={false}>
        {reason && <p role="status" className="notice">{reason}</p>}
        {setup ? (
          <>
            <p className="secret num" style={{ userSelect: 'all' }}>{groupSecret(setup.secret)}</p>
            <div className="sheet__actions">
              <button type="button" className="btn" onClick={() => copy(setup.secret)}>Copy</button>
              <a className="btn" href={setup.otpauth_uri}>Open in authenticator</a>
            </div>
            <label className="field">6-digit code
              <input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} />
            </label>
            <div className="sheet__actions">
              <button type="button" className="btn" onClick={closeSetup}>Cancel</button>
              <button type="button" className="btn btn--primary" onClick={() => void enable()}>Turn on</button>
            </div>
          </>
        ) : <div className="skeleton" aria-busy="true" aria-label="Loading" />}
      </Sheet>

      <Sheet open={codes !== null} onClose={() => setCodes(null)} title="Backup codes" closeOnBackdrop={false}>
        <p>Each code works once if you lose your phone. They are shown only now.</p>
        <ul className="codes num" style={{ userSelect: 'all' }}>{codes?.map((c) => <li key={c}>{c}</li>)}</ul>
        <div className="sheet__actions">
          <button type="button" className="btn" onClick={() => copy((codes ?? []).join('\n'))}>Copy all</button>
          <button type="button" className="btn btn--primary" onClick={() => setCodes(null)}>I've saved these</button>
        </div>
      </Sheet>

      <Sheet open={offOpen} onClose={() => setOffOpen(false)} title="Turn off 2FA">
        <p>Your Apple Pay tokens will stop working and other devices will be signed out.</p>
        <label className="field">Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <label className="field">Authenticator code<input autoComplete="one-time-code" inputMode="numeric" maxLength={6} value={offCode} onChange={(e) => setOffCode(e.target.value)} /></label>
        <div className="sheet__actions">
          <button type="button" className="btn" onClick={() => setOffOpen(false)}>Cancel</button>
          <button type="button" className="btn btn--danger" onClick={() => void turnOff()}>Turn off 2FA</button>
        </div>
      </Sheet>
    </section>
  )
}
```

`web/src/features/settings/Passkey.tsx`:

```tsx
import { useEffect, useRef, type FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import { readCsrf } from '../../api/client'
import { OFFLINE_MESSAGE } from '../../data/onlineAction'
import { useToast } from '../../ui/Toast'
import type { Security } from './hooks'

export const PASSKEY_MESSAGES = {
  linked: 'Passkey linked.',
  unlinked: 'Passkey unlinked.',
  // Never says which factor was wrong.
  error: "Couldn't link the passkey. Check your password and code.",
} as const

/** Native form posts: the server redirects to the identity provider, then back to
 *  /app/settings/profile?passkey=linked|unlinked|error. */
export function Passkey({ security }: { security: Security }) {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const shown = useRef(false)
  const outcome = params.get('passkey') as keyof typeof PASSKEY_MESSAGES | null

  useEffect(() => {
    if (!outcome || shown.current) return
    shown.current = true
    if (outcome in PASSKEY_MESSAGES) toast.show(PASSKEY_MESSAGES[outcome])
    setParams((p) => { const n = new URLSearchParams(p); n.delete('passkey'); return n }, { replace: true })
  }, [outcome, setParams, toast])

  if (!security.passkey_available) return null
  const guard = (e: FormEvent) => { if (!navigator.onLine) { e.preventDefault(); toast.show(OFFLINE_MESSAGE) } }
  const hidden = (
    <>
      <input type="hidden" name="_csrf_token" value={readCsrf()} />
      <input type="hidden" name="return_to" value="app" />
    </>
  )

  return (
    <section className="card" aria-labelledby="passkey">
      <h2 id="passkey">Passkey</h2>
      {!security.password_session ? (
        <p className="settings__sub">Sign in with your password and 2FA to change this.</p>
      ) : security.passkey_linked ? (
        <form method="post" action="/app/auth/unlink" onSubmit={guard} className="row">
          {hidden}
          <span className="main">Linked</span>
          <button type="submit" className="btn">Unlink</button>
        </form>
      ) : (
        <form method="post" action="/app/auth/link" onSubmit={guard}>
          {hidden}
          <label className="field">Password<input type="password" name="password" autoComplete="current-password" required /></label>
          <label className="field">Authenticator code<input name="totp_code" autoComplete="one-time-code" inputMode="numeric" maxLength={6} required /></label>
          <button type="submit" className="btn btn--primary">Link passkey</button>
        </form>
      )}
    </section>
  )
}
```

`web/src/features/settings/Profile.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { useSession } from '../../session/SessionProvider'
import { setSignInNotice } from '../../session/notice'
import { BackHeader } from '../../ui/BackHeader'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { useProfile, useSecurity } from './hooks'
import { SWATCHES, swatchName } from './palette'
import { Passkey } from './Passkey'
import { useProfileActions } from './profileHooks'
import { TwoFactor } from './TwoFactor'
import './settings.css'

export function Profile() {
  const { signOut } = useSession()
  const profile = useProfile()
  const security = useSecurity()
  const actions = useProfileActions()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [color, setColor] = useState<string>(SWATCHES[0])
  const [nameError, setNameError] = useState<string | null>(null)
  const [pwOpen, setPwOpen] = useState(false)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)

  useEffect(() => {
    if (!profile.data) return
    setName(profile.data.display_name); setEmail(profile.data.email ?? ''); setColor(profile.data.avatar_color ?? SWATCHES[0])
  }, [profile.data])

  const save = () => {
    const trimmed = name.trim()
    if (trimmed.length < 1 || trimmed.length > 100) return setNameError('Use 1 to 100 characters.')
    setNameError(null)
    void actions.saveProfile({ display_name: trimmed, email: email.trim() || null, avatar_color: color })
  }
  const changePassword = async () => {
    if (next.length < 12) return setPwError('Use at least 12 characters.')
    setPwError(null)
    const out = await actions.changePassword({ current_password: current, new_password: next })
    if (!out.ok) return
    setSignInNotice('Password changed. Sign in again.')
    await signOut() // the server ended every session
  }

  return (
    <>
      <BackHeader title="Profile & security" back="/settings" />
      <section className="screen settings">
        <QueryView result={profile} noDataText="No saved data yet. Connect once to load Settings.">
          {() => (
            <section className="card" aria-labelledby="profile-h">
              <h2 id="profile-h">Profile</h2>
              <label className="field">Name<input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
              {nameError && <p className="field__error" role="alert">{nameError}</p>}
              <label className="field">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></label>
              <div className="swatches" role="radiogroup" aria-label="Avatar colour">
                {SWATCHES.map((hex) => (
                  <button key={hex} type="button" role="radio" aria-checked={color === hex} aria-label={swatchName(hex)} className="swatch" style={{ background: hex }} onClick={() => setColor(hex)} />
                ))}
              </div>
              <button type="button" className="btn btn--primary" onClick={save}>Save profile</button>
            </section>
          )}
        </QueryView>

        <section className="card" aria-labelledby="pw-h">
          <h2 id="pw-h">Password</h2>
          <button type="button" className="btn" onClick={() => setPwOpen(true)}>Change password</button>
        </section>
        <Sheet open={pwOpen} onClose={() => setPwOpen(false)} title="Change password">
          <p>You'll be signed out everywhere and your Apple Pay tokens will stop working.</p>
          <label className="field">Current password<input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
          <label className="field">New password<input type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} /></label>
          {pwError && <p className="field__error" role="alert">{pwError}</p>}
          <div className="sheet__actions">
            <button type="button" className="btn" onClick={() => setPwOpen(false)}>Cancel</button>
            <button type="button" className="btn btn--danger" onClick={() => void changePassword()}>Change and sign out</button>
          </div>
        </Sheet>

        {security.data && <TwoFactor security={security.data} />}
        {security.data && <Passkey security={security.data} />}

        <button type="button" className="btn btn--danger btn--block" onClick={() => void signOut()}>Sign out</button>
      </section>
    </>
  )
}
```

(Every server error is toasted by `useOnlineAction` and the sheet stays open with the input, as §6.3 says. Add `.swatch` (44 px, round, a visible ring on `aria-checked="true"`), `.secret`, `.codes` and `.field` styles to `settings.css`.)

- [ ] **Step 5: Run to verify pass**

Run: `npm test -- src/features/settings/Profile.test.tsx src/session`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/settings/Profile.tsx web/src/features/settings/TwoFactor.tsx web/src/features/settings/Passkey.tsx web/src/features/settings/profileHooks.ts web/src/features/settings/Profile.test.tsx web/src/features/settings/settings.css web/src/session/notice.ts web/src/session/SignIn.tsx web/src/session/*.test.tsx
git commit -m "feat(web/settings): Profile & security with password, 2FA and passkey"
```

### Task F3.3: Household

**Stream:** F3 · **Depends on:** F3.2

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stub): `web/src/features/settings/Household.tsx`
- Create: `web/src/features/settings/householdHooks.ts`
- Test: `web/src/features/settings/Household.test.tsx`

**Interfaces:**
- Consumes: `useHousehold` (F1.6), `useOnlineAction`, `runOnline`, `RATE_MESSAGE` (F1.5), `useToast`.
- Produces: `useHouseholdActions(): { rename(name: string, currency: string); removeMember(userId: string); invite(): Promise<OnlineOutcome<{ token: string; expires_at: string }>> }`; `inviteUrl(token: string, origin?: string): string`.

- [ ] **Step 1: Write the failing test**

`web/src/features/settings/Household.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const { toast, me } = vi.hoisted(() => ({ toast: vi.fn(), me: { current: 'me' } }))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: me.current, household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({
  useHousehold: () => query({ id: 'hh1', name: 'Home', default_currency: 'EUR', members: [
    { user_id: 'me', role: 'owner', joined_at: null, display_name: 'Giorgos', username: 'g', avatar_color: null },
    { user_id: 'm', role: 'member', joined_at: null, display_name: 'Maria', username: 'maria', avatar_color: null },
  ] }),
}))

import { Household } from './Household'

const renderIt = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Household /></MemoryRouter></QueryClientProvider>)
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); me.current = 'me' })

describe('Household', () => {
  it('owner: members with you and roles, currency fixed, remove with confirm', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))
    renderIt()
    expect(screen.getByText('Giorgos (you)')).toBeInTheDocument()
    expect(screen.getByText('EUR · Fixed')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Maria' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove from household' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Maria' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect([req.method, new URL(req.url).pathname]).toEqual(['DELETE', '/api/v1/settings/household/members/m'])
  })

  it('owner: a new invite link is shown once', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ token: 'tok123', expires_at: '2026-10-14T00:00:00' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'New link' }))
    expect(await screen.findByText(`${location.origin}/join/tok123`)).toBeInTheDocument()
    expect(screen.getByText('Expires in 7 days · single use')).toBeInTheDocument()
  })

  it('invite 429 says to wait', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 429 }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'New link' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Too many links, wait a minute.'))
  })

  it('a member sees no edit, menu or invite', () => {
    me.current = 'm'
    renderIt()
    expect(screen.queryByRole('button', { name: /Actions for/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'New link' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Edit name' })).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/settings/Household.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/src/features/settings/householdHooks.ts`:

```ts
import { api } from '../../api/client'
import type { RawResult } from '../../data/rawJson'
import { insightsKeys, settingsKeys } from '../../data/keys'
import { runOnline, useOnlineAction } from '../../data/onlineAction'
import { useSession } from '../../session/SessionProvider'
import { useToast } from '../../ui/Toast'

export const inviteUrl = (token: string, origin = globalThis.location.origin) => `${origin}/join/${token}`

export function useHouseholdActions() {
  const act = useOnlineAction()
  const toast = useToast()
  const hh = useSession().me?.household_id ?? ''
  const keys = [settingsKeys.household(hh), insightsKeys.all(hh)]
  return {
    rename: (name: string, currency: string) =>
      act(() => api.PUT('/api/v1/settings/household', { body: { name, default_currency: currency } }), { invalidates: keys, success: 'Saved' }),
    removeMember: (userId: string) =>
      act(() => api.DELETE('/api/v1/settings/household/members/{member_user_id}', { params: { path: { member_user_id: userId } } }), { invalidates: keys }),
    /** The link is shown once and never stored; 429 has its own wording. */
    invite: async () => {
      const out = await runOnline(
        () => api.POST('/api/v1/settings/household/invite') as Promise<RawResult<{ token: string; expires_at: string }>>,
      )
      if (!out.ok && out.kind !== 'auth') toast.show(out.kind === 'rate' ? 'Too many links, wait a minute.' : out.message)
      return out // the token goes to component state only, never the cache
    },
  }
}
```

`web/src/features/settings/Household.tsx`:

```tsx
import { useState } from 'react'
import { useSession } from '../../session/SessionProvider'
import { BackHeader } from '../../ui/BackHeader'
import { Badge } from '../../ui/Badge'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type HouseholdMember, useHousehold } from './hooks'
import { inviteUrl, useHouseholdActions } from './householdHooks'
import './settings.css'

const nameOf = (m: HouseholdMember) => m.display_name || m.username || 'Member'

export function Household() {
  const me = useSession().me
  const household = useHousehold()
  const actions = useHouseholdActions()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [menuFor, setMenuFor] = useState<HouseholdMember | null>(null)
  const [confirm, setConfirm] = useState<HouseholdMember | null>(null)
  const [link, setLink] = useState<string | null>(null)

  return (
    <>
      <BackHeader title="Household" back="/settings" />
      <section className="screen settings">
        <QueryView result={household} noDataText="No saved data yet. Connect once to load Settings.">
          {(h) => {
            const owner = h.members.some((m) => m.user_id === me?.id && m.role === 'owner')
            return (
              <>
                <section className="card">
                  {editing ? (
                    <div className="row">
                      <input className="main" aria-label="Household name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
                      <button type="button" className="btn btn--primary" onClick={async () => { if ((await actions.rename(name.trim(), h.default_currency)).ok) setEditing(false) }}>Save</button>
                    </div>
                  ) : (
                    <div className="row">
                      <span className="main t">{h.name}</span>
                      {owner && <button type="button" className="btn" aria-label="Edit name" onClick={() => { setName(h.name); setEditing(true) }}>Edit</button>}
                    </div>
                  )}
                  <div className="row"><span className="main">Currency</span><span>{h.default_currency} · Fixed</span></div>
                </section>

                <section className="card" aria-labelledby="members-h">
                  <h2 id="members-h">Members</h2>
                  <ul className="settings__list">
                    {h.members.map((m) => (
                      <li key={m.user_id} className="row">
                        <span className="avatar" style={m.avatar_color ? { background: m.avatar_color } : undefined} aria-hidden="true">{nameOf(m).slice(0, 1)}</span>
                        <span className="main">{m.user_id === me?.id ? `${nameOf(m)} (you)` : nameOf(m)}</span>
                        <Badge>{m.role === 'owner' ? 'Owner' : 'Member'}</Badge>
                        {owner && m.user_id !== me?.id && (
                          <button type="button" className="iconbtn" aria-label={`Actions for ${nameOf(m)}`} onClick={() => setMenuFor(m)}>⋯</button>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>

                {owner && (
                  <section className="card" aria-labelledby="invite-h">
                    <h2 id="invite-h">Invite</h2>
                    {link ? (
                      <>
                        <p className="secret" style={{ userSelect: 'all' }}>{link}</p>
                        <button type="button" className="btn" onClick={() => void navigator.clipboard?.writeText(link)}>Copy</button>
                        <p className="settings__sub">Expires in 7 days · single use</p>
                      </>
                    ) : null}
                    <button type="button" className="btn" onClick={async () => { const out = await actions.invite(); if (out.ok) setLink(inviteUrl(out.data.token)) }}>New link</button>
                  </section>
                )}
              </>
            )
          }}
        </QueryView>
      </section>

      <Sheet open={menuFor !== null} onClose={() => setMenuFor(null)} title={menuFor ? nameOf(menuFor) : ''}>
        <button type="button" className="btn btn--danger btn--block" onClick={() => { setConfirm(menuFor); setMenuFor(null) }}>Remove from household</button>
      </Sheet>
      <Sheet open={confirm !== null} onClose={() => setConfirm(null)} title="Remove member">
        <p>{confirm ? `${nameOf(confirm)} loses access to this household's data.` : ''}</p>
        <div className="sheet__actions">
          <button type="button" className="btn" onClick={() => setConfirm(null)}>Cancel</button>
          <button type="button" className="btn btn--danger" onClick={async () => { if (confirm && (await actions.removeMember(confirm.user_id)).ok) setConfirm(null) }}>
            {confirm ? `Remove ${nameOf(confirm)}` : 'Remove'}
          </button>
        </div>
      </Sheet>
    </>
  )
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/settings && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/Household.tsx web/src/features/settings/householdHooks.ts web/src/features/settings/Household.test.tsx
git commit -m "feat(web/settings): Household: name, members, remove, one-time invite link"
```

---
## Stream F4: Categories & rules, Automations, the service worker, Notifications

Same test conventions as F3 (mocked session, toast and read hooks; `fetch` spy answering by path).

### Task F4.1: Categories & rules

**Stream:** F4 · **Depends on:** F1, B

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stub): `web/src/features/settings/Categories.tsx`
- Create: `web/src/features/settings/categoryHooks.ts`, `web/src/features/settings/RuleSheet.tsx`
- Test: `web/src/features/settings/Categories.test.tsx`

**Interfaces:**
- Consumes: `useCategories`, `useRules` (F1.6; categories carry `expense_count`, `rule_count`), `SWATCHES`, `swatchName`, `useOnlineAction`, `runOnline`, `OFFLINE_MESSAGE` (F1.5), `BackHeader`, 2a `Sheet`, `Badge`.
- Produces: `useCategoryActions(): { create(body); update(id, body); remove(id); saveRule(rule: { id?: string; pattern: string; category_id: string }): Promise<OnlineOutcome<Rule>>; deleteRule(id) }`; `ruleChip(r: { pattern: string; match_count: number }): string` ("sklaven 48"); `deleteMessage(c: CategoryItem): string`.
- Rules editing shows server 400/409 `detail` **as the field's error** (not a toast); offline and 429 still toast. Every category or rule write invalidates `settingsKeys.categories`, `settingsKeys.rules` and `insightsKeys.all`.

- [ ] **Step 1: Write the failing test**

`web/src/features/settings/Categories.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const toast = vi.hoisted(() => vi.fn())
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({
  useCategories: () => query([
    { id: 'g', name: 'Groceries', color: '#10b981', icon: '🛒', is_default: false, system_key: null, locked: false, expense_count: 31, rule_count: 2 },
    { id: 'f', name: 'Fuel', color: '#f97316', icon: '⛽', is_default: true, system_key: 'fuel', locked: true, expense_count: 9, rule_count: 0 },
  ]),
  useRules: () => query([
    { id: 'r1', pattern: 'sklaven', category_id: 'g', match_count: 48, created_at: null },
    { id: 'r2', pattern: 'lidl', category_id: 'g', match_count: 3, created_at: null },
  ]),
}))

import { Categories } from './Categories'
import { deleteMessage, ruleChip } from './categoryHooks'

const renderIt = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Categories /></MemoryRouter></QueryClientProvider>)
afterEach(() => { vi.restoreAllMocks(); toast.mockClear() })

describe('Categories & rules', () => {
  it('lists categories with System badges and rule chips beside them', () => {
    renderIt()
    expect(screen.getByRole('button', { name: 'sklaven 48' })).toBeInTheDocument()
    expect(within(screen.getByTestId('cat-f')).getByText('System')).toBeInTheDocument()
  })

  it('a locked category explains itself and has no editor', () => {
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Fuel/ }))
    expect(screen.getByText('The composer needs this one to ask for litres.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Category name')).toBeNull()
  })

  it('delete confirms with both counts', () => {
    expect(deleteMessage({ expense_count: 31, rule_count: 2 } as never)).toBe('31 expenses will become uncategorised and its 2 rules will be deleted.')
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(screen.getByText('31 expenses will become uncategorised and its 2 rules will be deleted.')).toBeInTheDocument()
  })

  it('a rule collision is shown on the field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Another rule already uses this pattern.' }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'lidl 3' }))
    const sheet = screen.getByRole('dialog', { name: 'Edit rule', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Merchant contains'), { target: { value: 'Sklaven' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save rule', hidden: true }))
    expect(await within(sheet).findByText('Another rule already uses this pattern.')).toBeInTheDocument()
    expect(toast).not.toHaveBeenCalled()
  })

  it('adds a rule with POST and the expanded category', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 'r3', pattern: 'ab', category_id: 'g', match_count: 0, created_at: null }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.click(screen.getByRole('button', { name: '＋ Rule' }))
    const sheet = screen.getByRole('dialog', { name: 'New rule', hidden: true })
    expect(within(sheet).getByText('Matches any merchant containing this text, ignoring case and accents. Minimum 2 characters.')).toBeInTheDocument()
    fireEvent.change(within(sheet).getByLabelText('Merchant contains'), { target: { value: 'AB' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Save rule', hidden: true }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect([req.method, new URL(req.url).pathname]).toEqual(['POST', '/api/v1/settings/category-rules'])
    expect(await req.json()).toEqual({ pattern: 'AB', category_id: 'g' })
  })

  it('writes are blocked offline', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection."))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('chip text', () => {
    expect(ruleChip({ pattern: 'sklaven', match_count: 48 })).toBe('sklaven 48')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/settings/Categories.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/src/features/settings/categoryHooks.ts`:

```ts
import { api } from '../../api/client'
import type { RawResult } from '../../data/rawJson'
import { insightsKeys, settingsKeys } from '../../data/keys'
import { type OnlineOutcome, runOnline, useOnlineAction } from '../../data/onlineAction'
import { useQueryClient } from '@tanstack/react-query'
import { useSession } from '../../session/SessionProvider'
import { useToast } from '../../ui/Toast'
import type { CategoryItem, Rule } from './hooks'

export const ruleChip = (r: { pattern: string; match_count: number }) => `${r.pattern} ${r.match_count}`
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
export const deleteMessage = (c: CategoryItem) =>
  `${plural(c.expense_count, 'expense', 'expenses')} will become uncategorised and its ${plural(c.rule_count, 'rule', 'rules')} will be deleted.`

export interface CategoryBody { name: string; color: string; icon: string }

export function useCategoryActions() {
  const act = useOnlineAction()
  const qc = useQueryClient()
  const toast = useToast()
  const hh = useSession().me?.household_id ?? ''
  const keys = [settingsKeys.categories(hh), settingsKeys.rules(hh), insightsKeys.all(hh)]
  const refresh = () => Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })))
  return {
    create: (body: CategoryBody) => act(() => api.POST('/api/v1/settings/categories', { body }), { invalidates: keys }),
    update: (id: string, body: CategoryBody) =>
      act(() => api.PUT('/api/v1/settings/categories/{category_id}', { params: { path: { category_id: id } }, body }), { invalidates: keys }),
    remove: (id: string) =>
      act(() => api.DELETE('/api/v1/settings/categories/{category_id}', { params: { path: { category_id: id } } }), { invalidates: keys }),
    /** POST (an upsert by pattern) for a new rule, PUT for an edit. 400/409 come back for the field. */
    saveRule: async (rule: { id?: string; pattern: string; category_id: string }): Promise<OnlineOutcome<Rule>> => {
      const body = { pattern: rule.pattern, category_id: rule.category_id }
      const out = await runOnline(() =>
        (rule.id
          ? api.PUT('/api/v1/settings/category-rules/{rule_id}', { params: { path: { rule_id: rule.id } }, body })
          : api.POST('/api/v1/settings/category-rules', { body })) as Promise<RawResult<Rule>>,
      )
      if (out.ok) await refresh()
      else if (out.kind === 'offline' || out.kind === 'rate') toast.show(out.message)
      return out
    },
    deleteRule: (id: string) =>
      act(() => api.DELETE('/api/v1/settings/category-rules/{rule_id}', { params: { path: { rule_id: id } } }), { invalidates: keys }),
  }
}
```

`web/src/features/settings/RuleSheet.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Sheet } from '../../ui/Sheet'
import { useCategoryActions } from './categoryHooks'
import type { CategoryItem, Rule } from './hooks'

export const RULE_HELP = 'Matches any merchant containing this text, ignoring case and accents. Minimum 2 characters.'

/** New rule (from "＋ Rule") or an existing one (tap on its chip). The pattern shows as stored. */
export function RuleSheet({ open, onClose, rule, categoryId, categories }: {
  open: boolean; onClose(): void; rule: Rule | null; categoryId: string; categories: CategoryItem[]
}) {
  const actions = useCategoryActions()
  const [pattern, setPattern] = useState('')
  const [cat, setCat] = useState(categoryId)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { if (open) { setPattern(rule?.pattern ?? ''); setCat(rule?.category_id ?? categoryId); setError(null) } }, [open, rule, categoryId])

  const save = async () => {
    if (pattern.trim().length < 2) return setError('Enter at least 2 characters.')
    const out = await actions.saveRule({ id: rule?.id, pattern, category_id: cat })
    if (out.ok) onClose()
    else if (out.kind === 'rejected') setError(out.message)
  }
  const remove = async () => { if (rule && (await actions.deleteRule(rule.id)).ok) onClose() }

  return (
    <Sheet open={open} onClose={onClose} title={rule ? 'Edit rule' : 'New rule'}>
      <label className="field">Merchant contains
        <input value={pattern} onChange={(e) => setPattern(e.target.value)} autoCapitalize="none" autoCorrect="off" aria-describedby="rule-help" aria-invalid={!!error} />
      </label>
      <p id="rule-help" className="settings__sub">{RULE_HELP}</p>
      {error && <p className="field__error" role="alert">{error}</p>}
      <label className="field">Category
        <select value={cat} onChange={(e) => setCat(e.target.value)}>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.icon} {c.name}</option>)}
        </select>
      </label>
      <div className="sheet__actions">
        {rule && <button type="button" className="btn btn--danger" onClick={() => void remove()}>Delete rule</button>}
        <button type="button" className="btn btn--primary" onClick={() => void save()}>Save rule</button>
      </div>
    </Sheet>
  )
}
```

`web/src/features/settings/Categories.tsx`:

```tsx
import { useState } from 'react'
import { BackHeader } from '../../ui/BackHeader'
import { Badge } from '../../ui/Badge'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type CategoryBody, deleteMessage, ruleChip, useCategoryActions } from './categoryHooks'
import { type CategoryItem, type Rule, useCategories, useRules } from './hooks'
import { SWATCHES, swatchName } from './palette'
import { RuleSheet } from './RuleSheet'
import './settings.css'

const LOCKED_NOTE = 'The composer needs this one to ask for litres.'

function Editor({ initial, onSave, onCancel, onDelete }: { initial: CategoryBody; onSave(b: CategoryBody): void; onCancel(): void; onDelete?(): void }) {
  const [body, setBody] = useState(initial)
  return (
    <div className="settings__editor">
      <label className="field">Category name<input value={body.name} maxLength={50} onChange={(e) => setBody({ ...body, name: e.target.value })} /></label>
      <div className="swatches" role="radiogroup" aria-label="Colour">
        {SWATCHES.map((hex) => (
          <button key={hex} type="button" role="radio" aria-checked={body.color === hex} aria-label={swatchName(hex)} className="swatch" style={{ background: hex }} onClick={() => setBody({ ...body, color: hex })} />
        ))}
      </div>
      <label className="field">Icon<input value={body.icon} maxLength={10} onChange={(e) => setBody({ ...body, icon: e.target.value })} /></label>
      <div className="sheet__actions">
        {onDelete && <button type="button" className="btn btn--danger" onClick={onDelete}>Delete</button>}
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button type="button" className="btn btn--primary" onClick={() => onSave({ ...body, name: body.name.trim() })}>Save</button>
      </div>
    </div>
  )
}

export function Categories() {
  const categories = useCategories()
  const rules = useRules().data ?? []
  const actions = useCategoryActions()
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [rule, setRule] = useState<{ rule: Rule | null; categoryId: string } | null>(null)
  const [confirm, setConfirm] = useState<CategoryItem | null>(null)
  const byCategory = (id: string) => rules.filter((r) => r.category_id === id)

  return (
    <>
      <BackHeader title="Categories & rules" back="/settings"
        action={<button type="button" className="iconbtn" aria-label="Add category" onClick={() => setAdding(true)}>＋</button>} />
      <section className="screen settings">
        {adding && (
          <section className="card">
            <Editor initial={{ name: '', color: SWATCHES[0], icon: '📦' }} onCancel={() => setAdding(false)}
              onSave={async (b) => { if ((await actions.create(b)).ok) setAdding(false) }} />
          </section>
        )}
        <QueryView result={categories} noDataText="No saved data yet. Connect once to load Settings.">
          {(list) => (
            <ul className="card settings__list">
              {list.map((c) => (
                <li key={c.id} data-testid={`cat-${c.id}`}>
                  <button type="button" className="row" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>
                    <span className="ico" style={c.color ? { background: c.color } : undefined} aria-hidden="true">{c.icon ?? '📦'}</span>
                    <span className="main t">{c.name}</span>
                    {c.locked && <Badge>System</Badge>}
                  </button>
                  <div className="rules chips" aria-label={`Rules for ${c.name}`}>
                    {byCategory(c.id).map((r) => (
                      <button key={r.id} type="button" className="chip" onClick={() => setRule({ rule: r, categoryId: c.id })}>{ruleChip(r)}</button>
                    ))}
                  </div>
                  {open === c.id && (c.locked ? (
                    <p className="settings__sub">{LOCKED_NOTE}</p>
                  ) : (
                    <>
                      <Editor initial={{ name: c.name, color: c.color ?? SWATCHES[0], icon: c.icon ?? '📦' }} onCancel={() => setOpen(null)}
                        onSave={async (b) => { if ((await actions.update(c.id, b)).ok) setOpen(null) }}
                        onDelete={c.is_default ? undefined : () => setConfirm(c)} />
                      <button type="button" className="btn" onClick={() => setRule({ rule: null, categoryId: c.id })}>＋ Rule</button>
                    </>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </QueryView>
      </section>

      <RuleSheet open={rule !== null} onClose={() => setRule(null)} rule={rule?.rule ?? null} categoryId={rule?.categoryId ?? ''} categories={categories.data ?? []} />
      <Sheet open={confirm !== null} onClose={() => setConfirm(null)} title={confirm ? `Delete ${confirm.name}?` : 'Delete'}>
        <p>{confirm ? deleteMessage(confirm) : ''}</p>
        <div className="sheet__actions">
          <button type="button" className="btn" onClick={() => setConfirm(null)}>Cancel</button>
          <button type="button" className="btn btn--danger" onClick={async () => { if (confirm && (await actions.remove(confirm.id)).ok) { setConfirm(null); setOpen(null) } }}>Delete category</button>
        </div>
      </Sheet>
    </>
  )
}
```

(Rule chips here are tappable buttons — `aria-pressed` is for selection chips only. The `Delete` in the editor opens the confirm sheet; the destructive call is "Delete category" inside it.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/settings/Categories.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/Categories.tsx web/src/features/settings/categoryHooks.ts web/src/features/settings/RuleSheet.tsx web/src/features/settings/Categories.test.tsx
git commit -m "feat(web/settings): Categories with their rules: edit, add, delete, rule upsert"
```

### Task F4.2: Automations (Apple Pay tokens)

**Stream:** F4 · **Depends on:** F4.1

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stub): `web/src/features/settings/Automations.tsx`
- Create: `web/src/features/settings/tokenHooks.ts`
- Test: `web/src/features/settings/Automations.test.tsx`

**Interfaces:**
- Consumes: `useTokens`, `useBuckets` (F1.6), `useOnlineAction`, `runOnline` (F1.5).
- Produces: `useTokenActions(): { create(body: { name: string; default_bucket_id: string | null }): Promise<OnlineOutcome<TokenItem & { token: string }>>; revoke(id: string) }`; `lastUsed(iso: string | null, now?: number): string` ("Last used 2h ago", "Never used").
- The new token lives in component state only: never the query cache, the encrypted store or the URL; leaving the screen discards it.

- [ ] **Step 1: Write the failing test**

`web/src/features/settings/Automations.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const toast = vi.hoisted(() => vi.fn())
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({
  useTokens: () => query([{ id: 't1', name: 'iPhone', prefix: 'pat_ab12', scopes: ['ingest'], default_bucket_id: 'b1', last_used_at: new Date(Date.now() - 2 * 3600_000).toISOString(), created_at: null }]),
  useBuckets: () => query([{ id: 'b1', name: 'Daily' }]),
}))

import { Automations } from './Automations'
import { lastUsed } from './tokenHooks'

let qc: QueryClient
function Loc() { return <p data-testid="loc">{useLocation().search}{useLocation().hash}</p> }
const renderIt = () => { qc = new QueryClient(); return render(<QueryClientProvider client={qc}><MemoryRouter><Automations /><Loc /></MemoryRouter></QueryClientProvider>) }
afterEach(() => { vi.restoreAllMocks(); toast.mockClear() })

describe('Automations', () => {
  it('lists tokens with prefix, bucket and last use, in setup order', () => {
    renderIt()
    expect(screen.getByText('iPhone')).toBeInTheDocument()
    expect(screen.getByText(/pat_ab12 · Daily · Last used 2h ago/)).toBeInTheDocument()
    expect(screen.getByText('Purchases arrive tagged Apple Pay with no payer. You pick who paid from Home.')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem', { name: /^Step/ })).toHaveLength(3)
  })

  it('shows a new token once and never caches or stores it', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 't2', name: 'Watch', prefix: 'pat_cd34', scopes: ['ingest'], default_bucket_id: null, last_used_at: null, created_at: null, token: 'pat_cd34SECRETSECRET' }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'Watch' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const card = await screen.findByRole('alert')
    expect(within(card).getByText('pat_cd34SECRETSECRET')).toBeInTheDocument()
    expect(JSON.stringify(qc.getQueryCache().getAll().map((q) => q.state.data))).not.toContain('SECRET')
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('SECRET')
    expect(screen.getByTestId('loc').textContent).not.toContain('SECRET')
  })

  it('validates the name length before sending', () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'x'.repeat(61) } })
    fireEvent.click(screen.getByRole('button', { name: 'Create token' }))
    expect(screen.getByText('Use 1 to 60 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('revoke asks first', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Revoke iPhone' }))
    fireEvent.click(screen.getByRole('button', { name: 'Revoke token' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect((fetch.mock.calls[0][0] as Request).method).toBe('DELETE')
  })

  it('formats last use', () => {
    const now = Date.parse('2026-10-07T12:00:00Z')
    expect(lastUsed(null, now)).toBe('Never used')
    expect(lastUsed('2026-10-07T11:59:30Z', now)).toBe('Last used just now')
    expect(lastUsed('2026-10-07T10:00:00Z', now)).toBe('Last used 2h ago')
    expect(lastUsed('2026-10-04T12:00:00Z', now)).toBe('Last used 3d ago')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/settings/Automations.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/src/features/settings/tokenHooks.ts`:

```ts
import { api } from '../../api/client'
import type { RawResult } from '../../data/rawJson'
import { settingsKeys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import { useSession } from '../../session/SessionProvider'
import type { TokenItem } from './hooks'

/** Server timestamps are naive UTC ("2026-10-07T10:00:00"): read them as UTC. */
const utc = (iso: string) => Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)

export function lastUsed(iso: string | null, now = Date.now()): string {
  if (!iso) return 'Never used'
  const mins = Math.max(0, Math.floor((now - utc(iso)) / 60_000))
  if (mins < 1) return 'Last used just now'
  if (mins < 60) return `Last used ${mins}m ago`
  if (mins < 48 * 60) return `Last used ${Math.round(mins / 60)}h ago`
  return `Last used ${Math.round(mins / 1440)}d ago`
}

export function useTokenActions() {
  const act = useOnlineAction()
  const hh = useSession().me?.household_id ?? ''
  return {
    // The response carries the plaintext token: returned to the screen, never cached.
    create: (body: { name: string; default_bucket_id: string | null }) =>
      act(() => api.POST('/api/v1/settings/tokens', { body }) as Promise<RawResult<TokenItem & { token: string }>>, { invalidates: [settingsKeys.tokens(hh)] }),
    revoke: (id: string) =>
      act(() => api.DELETE('/api/v1/settings/tokens/{token_id}', { params: { path: { token_id: id } } }), { invalidates: [settingsKeys.tokens(hh)] }),
  }
}
```

(Invalidating `tokens` refetches the list; the list endpoint never includes the plaintext, so the cache stays clean.)

`web/src/features/settings/Automations.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { BackHeader } from '../../ui/BackHeader'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { type TokenItem, useBuckets, useTokens } from './hooks'
import { lastUsed, useTokenActions } from './tokenHooks'
import './settings.css'

const STEPS = [
  'Create a token here and copy it.',
  'In the Shortcuts app, add the Tameio Apple Pay shortcut and paste the token when it asks.',
  'In Shortcuts › Automation, run it on "When I tap Apple Pay" (Wallet transaction).',
]

export function Automations() {
  const tokens = useTokens()
  const buckets = useBuckets().data ?? []
  const actions = useTokenActions()
  const [name, setName] = useState('')
  const [bucket, setBucket] = useState('')
  const [nameError, setNameError] = useState<string | null>(null)
  const [fresh, setFresh] = useState<string | null>(null) // the plaintext token, this screen only
  const [revoking, setRevoking] = useState<TokenItem | null>(null)
  useEffect(() => () => setFresh(null), [])
  const bucketName = (id: string | null) => buckets.find((b) => b.id === id)?.name ?? 'No default bucket'

  const create = async () => {
    const trimmed = name.trim()
    if (trimmed.length < 1 || trimmed.length > 60) return setNameError('Use 1 to 60 characters.')
    setNameError(null)
    const out = await actions.create({ name: trimmed, default_bucket_id: bucket || null })
    if (out.ok) { setFresh(out.data.token); setName('') }
  }

  return (
    <>
      <BackHeader title="Apple Pay" back="/settings" />
      <section className="screen settings">
        <ol className="card settings__steps">
          {STEPS.map((s, i) => <li key={i} aria-label={`Step ${i + 1}`}>{s}</li>)}
        </ol>

        {fresh && (
          <div className="card notice notice--warn" role="alert">
            <p>Copy this token now. It won't be shown again.</p>
            <p className="secret num" style={{ userSelect: 'all' }}>{fresh}</p>
            <button type="button" className="btn" onClick={() => void navigator.clipboard?.writeText(fresh)}>Copy token</button>
          </div>
        )}

        <QueryView result={tokens} noDataText="No saved data yet. Connect once to load Settings.">
          {(list) => (
            <ul className="card settings__list" aria-label="Tokens">
              {list.map((t) => (
                <li key={t.id} className="row">
                  <span className="main"><span className="t">{t.name}</span><span className="s">{`${t.prefix} · ${bucketName(t.default_bucket_id)} · ${lastUsed(t.last_used_at)}`}</span></span>
                  <button type="button" className="btn" aria-label={`Revoke ${t.name}`} onClick={() => setRevoking(t)}>Revoke</button>
                </li>
              ))}
            </ul>
          )}
        </QueryView>

        <section className="card" aria-labelledby="new-token">
          <h2 id="new-token">New token</h2>
          <label className="field">Token name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          {nameError && <p className="field__error" role="alert">{nameError}</p>}
          <label className="field">Default bucket
            <select value={bucket} onChange={(e) => setBucket(e.target.value)}>
              <option value="">None</option>
              {buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </label>
          <button type="button" className="btn btn--primary" onClick={() => void create()}>Create token</button>
        </section>

        <p className="settings__sub">Purchases arrive tagged Apple Pay with no payer. You pick who paid from Home.</p>
      </section>

      <Sheet open={revoking !== null} onClose={() => setRevoking(null)} title="Revoke token">
        <p>{revoking ? `The Shortcut using “${revoking.name}” stops working.` : ''}</p>
        <div className="sheet__actions">
          <button type="button" className="btn" onClick={() => setRevoking(null)}>Cancel</button>
          <button type="button" className="btn btn--danger" onClick={async () => { if (revoking && (await actions.revoke(revoking.id)).ok) setRevoking(null) }}>Revoke token</button>
        </div>
      </Sheet>
    </>
  )
}
```

(The name-error `role="alert"` and the token card's `role="alert"` never show together in the test; if they do in practice, give the token card `role="status"` and update the test's query. Write the three steps to match the real Shortcut flow in `docs/redesign/mocks/insights-settings.html`'s Apple Pay screen.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/settings/Automations.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/Automations.tsx web/src/features/settings/tokenHooks.ts web/src/features/settings/Automations.test.tsx
git commit -m "feat(web/settings): Apple Pay tokens: create once, list, revoke"
```

### Task F4.3: Service worker on `injectManifest` with push and notification click

**Stream:** F4 · **Depends on:** F4.2 (same worktree; no code dependency)

**Files:**
- Create: `web/src/sw.ts`, `web/src/pwa/appRoute.ts`, `web/src/pwa/pushPayload.ts`, `web/tsconfig.sw.json`
- Modify: `web/vite.config.ts`, `web/tsconfig.app.json` (exclude `src/sw.ts`), `web/tsconfig.json` (reference `tsconfig.sw.json`), `web/package.json` + `package-lock.json` (devDependencies `workbox-precaching`, `workbox-routing`, `workbox-core`)
- Test: `web/src/pwa/appRoute.test.ts`, `web/src/pwa/pushPayload.test.ts`; a build check

**Interfaces:**
- Produces: `appRoute(link: string | null | undefined): string` — `/bills`, `/buckets*` → `/app/plan`; `/transactions*`, `/search*` → `/app/activity`; `/settings*` → `/app/settings`; anything else → `/app/`. `noticeFromPush(text: string | null): { title: string; options: NotificationOptions & { data: { url: string } } }`.
- Keeps (Phase 1): scope `/app/`, navigate fallback `/app/index.html` with denylist `/^\/app\/auth\//` and `/^\/api\//`, the same precache globs and ignores, **no runtime caching**, prompt-style updates: the worker waits until `src/pwa/update.ts` posts `{ type: 'SKIP_WAITING' }` (what the generated worker did in prompt mode: no `skipWaiting()` on install, no `clientsClaim()`). The output stays `/app/sw.js`, so existing installs update in place. `static/sw.js` is untouched.

- [ ] **Step 1: Write the failing tests**

`web/src/pwa/appRoute.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { appRoute } from './appRoute'

describe('appRoute', () => {
  it.each([
    // every link the server creates (scheduler, ingest, login alerts, push test)
    ['/bills', '/app/plan'],
    ['/buckets/3f2a', '/app/plan'],
    ['/buckets', '/app/plan'],
    ['/transactions/abc/edit', '/app/activity'],
    ['/search?q=x', '/app/activity'],
    ['/settings', '/app/settings'],
    ['/settings/2fa/enroll', '/app/settings'],
    ['/stock/shopping', '/app/'],
    ['/stock', '/app/'],
    ['/', '/app/'],
    [null, '/app/'],
    ['', '/app/'],
    ['/billsfoo', '/app/'],
    ['https://elsewhere.example/settings', '/app/settings'], // only the path is used
  ])('%s → %s', (link, expected) => {
    expect(appRoute(link)).toBe(expected)
  })
})
```

`web/src/pwa/pushPayload.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { noticeFromPush } from './pushPayload'

describe('noticeFromPush', () => {
  it('maps the server payload', () => {
    const n = noticeFromPush(JSON.stringify({ title: 'Auto-paid: Cosmote', body: '€38.90 marked as paid', link: '/bills' }))
    expect(n.title).toBe('Auto-paid: Cosmote')
    expect(n.options.body).toBe('€38.90 marked as paid')
    expect(n.options.data.url).toBe('/app/plan')
    expect(n.options.icon).toBe('/app/icons/icon-192.png')
  })
  it('survives an empty or non-JSON push', () => {
    expect(noticeFromPush(null)).toMatchObject({ title: 'Tameio', options: { body: '', data: { url: '/app/' } } })
    expect(noticeFromPush('plain text').options.body).toBe('plain text')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/pwa/appRoute.test.ts src/pwa/pushPayload.test.ts`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement the pure modules**

`web/src/pwa/appRoute.ts`:

```ts
/** Where a notification's server link opens in the app (2d §6.4). The old app's links
 *  (/bills, /transactions/…/edit, …) have no /app/ equivalent of the same path. */
export function appRoute(link: string | null | undefined): string {
  let path: string
  try {
    path = new URL(link || '/', 'https://app.invalid').pathname
  } catch {
    return '/app/'
  }
  const under = (prefix: string) => path === prefix || path.startsWith(`${prefix}/`)
  if (under('/bills') || under('/buckets')) return '/app/plan'
  if (under('/transactions') || under('/search')) return '/app/activity'
  if (under('/settings')) return '/app/settings'
  return '/app/'
}
```

`web/src/pwa/pushPayload.ts`:

```ts
import { appRoute } from './appRoute'

export interface PushNotice { title: string; options: NotificationOptions & { data: { url: string } } }

/** The server sends {title, body, link} (app/services/notifications.py). */
export function noticeFromPush(text: string | null): PushNotice {
  let p: { title?: unknown; body?: unknown; link?: unknown } = {}
  if (text) {
    try {
      p = JSON.parse(text)
    } catch {
      p = { body: text }
    }
  }
  return {
    title: typeof p.title === 'string' && p.title ? p.title : 'Tameio',
    options: {
      body: typeof p.body === 'string' ? p.body : '',
      icon: '/app/icons/icon-192.png',
      badge: '/app/icons/icon-192.png',
      data: { url: appRoute(typeof p.link === 'string' ? p.link : '/') },
    },
  }
}
```

- [ ] **Step 4: The worker**

Install the Workbox runtime modules at the version `vite-plugin-pwa` already pulls in:

```bash
cd web && npm ls workbox-build   # e.g. workbox-build@7.4.1
npm install -D workbox-precaching@^7.4.0 workbox-routing@^7.4.0 workbox-core@^7.4.0
```

`web/src/sw.ts`:

```ts
/// <reference lib="webworker" />
// The /app/ service worker (vite-plugin-pwa injectManifest). Phase 1 behaviour, kept:
// precache the build, answer navigations with the app shell except /app/auth/* and /api/*,
// no runtime caching (API data lives in the encrypted Dexie store), and wait for
// src/pwa/update.ts to say SKIP_WAITING. Added in 2d: push and notificationclick.
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute, type PrecacheEntry } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { noticeFromPush } from './pwa/pushPayload'

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: Array<PrecacheEntry | string> }

precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()
registerRoute(
  new NavigationRoute(createHandlerBoundToURL('/app/index.html'), {
    denylist: [/^\/app\/auth\//, /^\/api\//],
  }),
)

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') void self.skipWaiting()
})

self.addEventListener('push', (event) => {
  const notice = noticeFromPush(event.data ? event.data.text() : null)
  event.waitUntil(self.registration.showNotification(notice.title, notice.options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL((event.notification.data as { url?: string } | null)?.url ?? '/app/', self.location.origin).href
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of windows) {
        if (new URL(client.url).pathname.startsWith('/app/')) {
          await client.focus()
          try {
            await client.navigate(target)
            return
          } catch {
            break // not controlled by this worker: open a fresh window instead
          }
        }
      }
      await self.clients.openWindow(target)
    })(),
  )
})
```

`web/vite.config.ts` — the `VitePWA({...})` call becomes (manifest unchanged):

```ts
    VitePWA({
      // 2d: injectManifest so src/sw.ts can handle push. Updates are still applied by
      // src/pwa/update.ts at a safe moment (prompt), never mid-use.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'prompt',
      injectRegister: false,
      includeManifestIcons: false,
      scope: '/app/',
      base: '/app/',
      manifest: { /* unchanged */ },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,woff2,svg,png}'],
        // Latin + Greek (merchant names) only; and never precache the worker itself.
        globIgnores: ['**/*-cyrillic*.woff2', '**/*-vietnamese*.woff2', '**/sw.js'],
        // One classic script, as the generated worker was (iOS registers it as classic).
        rollupFormat: 'iife',
      },
    }),
```

(The `workbox: {...}` block goes away: its navigate fallback and denylist now live in `sw.ts`, and `runtimeCaching: []` is implied because `sw.ts` registers no runtime routes.)

`web/tsconfig.sw.json`:

```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.sw.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023", "WebWorker"],
    "types": [],
    "module": "esnext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "skipLibCheck": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true
  },
  "include": ["src/sw.ts", "src/pwa/appRoute.ts", "src/pwa/pushPayload.ts"]
}
```

`web/tsconfig.app.json`: add `"exclude": ["src/sw.ts"]` (the DOM program must not see the worker globals). `web/tsconfig.json`: add `{ "path": "./tsconfig.sw.json" }` to `references`.

- [ ] **Step 5: Verify tests, types and the built worker**

```bash
cd web
npm test -- src/pwa
npm run typecheck && npm run lint
npm run build
grep -c "notificationclick" dist/sw.js            # ≥ 1
grep -c "SKIP_WAITING" dist/sw.js                 # ≥ 1
grep -c "/app/index.html" dist/sw.js              # ≥ 1
! grep -q "self.__WB_MANIFEST" dist/sw.js         # the manifest was injected
! grep -qE '[{,]"?url"?:"sw\.js"' dist/sw.js      # the worker does not precache itself
! grep -q 'clientsClaim()' dist/sw.js            # prompt mode: no claim call
git -C .. diff --quiet -- static/sw.js            # untouched
```

Expected: tests and typecheck pass; every grep line succeeds. Then run Phase 1's update tests: `npm test -- src/pwa/update.test.ts` (unchanged, PASS).

- [ ] **Step 6: Commit**

```bash
git add web/src/sw.ts web/src/pwa/appRoute.ts web/src/pwa/pushPayload.ts web/src/pwa/appRoute.test.ts web/src/pwa/pushPayload.test.ts web/vite.config.ts web/tsconfig.app.json web/tsconfig.json web/tsconfig.sw.json web/package.json web/package-lock.json
git commit -m "feat(web/pwa): injectManifest worker with push and notification click; Phase 1 behaviour kept"
```

### Task F4.4: Notifications screen

**Stream:** F4 · **Depends on:** F4.3, F1.7; the alert-type toggles need **N** (before N merges they are hidden: `useNotificationPrefs()` returns `null`)

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Replace (stub): `web/src/features/settings/Notifications.tsx`
- Create: `web/src/features/settings/notificationHooks.ts`
- Test: `web/src/features/settings/Notifications.test.tsx`

**Interfaces:**
- Consumes: `usePushState`, `enablePush`, `disablePush`, `sendTestPush` (F1.7); `useNotificationPrefs` (F1.6); `fetchJson` (F1.5); `Toggle` (F1.1); `useOnlineAction`.
- Produces: `useNotificationActions(): { setDisabled(types: string[]); pushOn(); pushOff(); test() }`; `disabledAfter(prefs: NotificationPrefs, type: string, enabled: boolean): string[]`.

- [ ] **Step 1: Write the failing test**

`web/src/features/settings/Notifications.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const { toast, push, prefs } = vi.hoisted(() => ({
  toast: vi.fn(),
  push: { state: 'off' as string, enablePush: vi.fn(), disablePush: vi.fn(), sendTestPush: vi.fn() },
  prefs: { current: null as unknown },
}))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('../../pwa/pushClient', () => ({
  usePushState: () => ({ state: push.state, refresh: vi.fn() }),
  enablePush: push.enablePush, disablePush: push.disablePush, sendTestPush: push.sendTestPush,
}))
vi.mock('./hooks', () => ({ useNotificationPrefs: () => query(prefs.current) }))

import { disabledAfter } from './notificationHooks'
import { Notifications } from './Notifications'

const PREFS = { push_devices: 1, types: [
  { type: 'bill_due', group: 'Bills', label: 'Due in 3 days', enabled: true },
  { type: 'bill_overdue', group: 'Bills', label: 'Overdue', enabled: false },
  { type: 'ingest_created', group: 'Apple Pay', label: 'Each new purchase', enabled: true },
] }
const renderIt = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Notifications /></MemoryRouter></QueryClientProvider>)

beforeEach(() => { push.state = 'off'; prefs.current = PREFS })
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); push.enablePush.mockReset() })

describe('Notifications', () => {
  it('push off → on subscribes through the client', async () => {
    push.enablePush.mockResolvedValue({ data: { ok: true }, response: new Response(null, { status: 200 }) })
    renderIt()
    fireEvent.click(screen.getByRole('switch', { name: 'Push on this device' }))
    await waitFor(() => expect(push.enablePush).toHaveBeenCalled())
  })

  it('denied is disabled and says where to allow it', () => {
    push.state = 'denied'
    renderIt()
    expect(screen.getByRole('switch', { name: 'Push on this device' })).toBeDisabled()
    expect(screen.getByText('Allowed in iOS Settings')).toBeInTheDocument()
  })

  it('in a browser tab it asks to install first', () => {
    push.state = 'not-installed'
    renderIt()
    expect(screen.getByText('Add Tameio to your Home Screen to get push alerts.')).toBeInTheDocument()
  })

  it('alert toggles are grouped and PUT the whole disabled set', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(PREFS), { status: 200 }))
    renderIt()
    expect(screen.getByRole('heading', { name: 'Bills' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Overdue' })).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(screen.getByRole('switch', { name: 'Due in 3 days' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const [url, init] = fetch.mock.calls[0] as [URL, RequestInit]
    expect(String(url)).toContain('/api/v1/settings/notifications')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body as string)).toEqual({ disabled: ['bill_due', 'bill_overdue'] })
  })

  it('without the mutes API there are no alert toggles', () => {
    prefs.current = null
    renderIt()
    expect(screen.getAllByRole('switch')).toHaveLength(1)
  })

  it('offline changes nothing', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.click(screen.getByRole('switch', { name: 'Due in 3 days' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection."))
    expect(fetch).not.toHaveBeenCalled()
    expect(push.enablePush).not.toHaveBeenCalled()
  })

  it('computes the next disabled set', () => {
    expect(disabledAfter(PREFS, 'bill_overdue', true)).toEqual([])
    expect(disabledAfter(PREFS, 'ingest_created', false)).toEqual(['bill_overdue', 'ingest_created'])
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/settings/Notifications.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/src/features/settings/notificationHooks.ts`:

```ts
import { fetchJson } from '../../data/rawJson'
import { settingsKeys } from '../../data/keys'
import { useOnlineAction } from '../../data/onlineAction'
import { disablePush, enablePush, sendTestPush } from '../../pwa/pushClient'
import { useSession } from '../../session/SessionProvider'
import type { NotificationPrefs } from './hooks'

export const disabledAfter = (prefs: NotificationPrefs, type: string, enabled: boolean) =>
  prefs.types.filter((t) => (t.type === type ? !enabled : !t.enabled)).map((t) => t.type)

/** Push routes are the cookie + CSRF ones outside OpenAPI (/push/*); all online only. */
export function useNotificationActions() {
  const act = useOnlineAction()
  const hh = useSession().me?.household_id ?? ''
  const prefsKey = [settingsKeys.notifications(hh)]
  return {
    setDisabled: (disabled: string[]) =>
      act(() => fetchJson<NotificationPrefs>('PUT', '/api/v1/settings/notifications', { disabled }), { invalidates: prefsKey }),
    pushOn: () => act(() => enablePush(), { invalidates: prefsKey, success: 'Push is on for this device' }),
    pushOff: () => act(() => disablePush(), { invalidates: prefsKey }),
    test: () => act(() => sendTestPush()),
  }
}
```

`web/src/features/settings/Notifications.tsx`:

```tsx
import { useState } from 'react'
import { usePushState } from '../../pwa/pushClient'
import { BackHeader } from '../../ui/BackHeader'
import { Toggle } from '../../ui/Toggle'
import { useToast } from '../../ui/Toast'
import { type NotificationPrefs, useNotificationPrefs } from './hooks'
import { disabledAfter, useNotificationActions } from './notificationHooks'
import './settings.css'

const GROUPS = ['Bills', 'Budgets', 'Pantry', 'Apple Pay']

export function Notifications() {
  const { state, refresh } = usePushState()
  const prefs = useNotificationPrefs().data as NotificationPrefs | null | undefined
  const actions = useNotificationActions()
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key)
    try { await fn() } finally { setBusy(null); refresh() }
  }
  const pushNote =
    state === 'denied' ? 'Allowed in iOS Settings'
    : state === 'not-installed' ? 'Add Tameio to your Home Screen to get push alerts.'
    : state === 'unsupported' ? "This browser can't receive push alerts."
    : null

  return (
    <>
      <BackHeader title="Notifications" back="/settings" />
      <section className="screen settings">
        <section className="card" aria-labelledby="push-h">
          <h2 id="push-h" className="sr-only">Push</h2>
          <div className="row">
            <span className="main"><span className="t">Push on this device</span>{pushNote && <span className="s">{pushNote}</span>}</span>
            <Toggle label="Push on this device" checked={state === 'on'} busy={busy === 'push'}
              disabled={state === 'denied' || state === 'not-installed' || state === 'unsupported'}
              onChange={(on) => void run('push', on ? actions.pushOn : actions.pushOff)} />
          </div>
          {state === 'on' && (
            <button type="button" className="btn" onClick={() => void run('test', async () => {
              const out = await actions.test()
              if (out.ok) toast.show((out.data as { sent: boolean; error: string | null }).sent ? 'Test sent' : ((out.data as { error: string | null }).error ?? 'Not sent'))
            })}>Send test</button>
          )}
        </section>

        {prefs && GROUPS.map((group) => {
          const types = prefs.types.filter((t) => t.group === group)
          if (!types.length) return null
          return (
            <section key={group} className="card" aria-labelledby={`g-${group}`}>
              <h2 id={`g-${group}`}>{group}</h2>
              {types.map((t) => (
                <div key={t.type} className="row">
                  <span className="main">{t.label}</span>
                  <Toggle label={t.label} checked={t.enabled} busy={busy === t.type}
                    onChange={(on) => void run(t.type, () => actions.setDisabled(disabledAfter(prefs, t.type, on)))} />
                </div>
              ))}
            </section>
          )
        })}
        {prefs && <p className="settings__sub">Off stops both the in-app notification and the push, for you in this household.</p>}
      </section>
    </>
  )
}
```

(`useOnlineAction` blocks offline before `enablePush` runs, so a denied or offline device never sees the iOS permission prompt for nothing. iOS only shows the permission prompt in response to a tap: `enablePush` is called synchronously from the toggle's click handler chain.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/settings && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/settings/Notifications.tsx web/src/features/settings/notificationHooks.ts web/src/features/settings/Notifications.test.tsx
git commit -m "feat(web/settings): Notifications: push on this device and alert types"
```

---

## Stream F5: payment method in 2a's sheets, and Archive

F5 edits 2a's files. **Before writing anything, read 2a's merged `features/plan/items/ItemSheet.tsx`, `features/plan/EntrySheet.tsx`, `Budgets.tsx` and their tests**, and follow their structure (state, submit, how they call `useAction`); the snippets below show the change, not 2a's whole component.

### Task F5.1: Payment method in the Item and Entry sheets

**Stream:** F5 · **Depends on:** M merged (types regenerated), 2a streams C and D merged

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Modify: `web/src/features/plan/items/ItemSheet.tsx`, `web/src/features/plan/EntrySheet.tsx`
- Create: `web/src/features/plan/paymentMethods.ts`
- Test: append to 2a's `web/src/features/plan/items/ItemSheet.test.tsx` and `EntrySheet.test.tsx`

**Interfaces:**
- Consumes: `RecurringItemOut.payment_method`, `RecurringItemIn.payment_method`, `EntryOut.payment_method`, `EntryDoneIn.payment_method` (M3).
- Produces: `PAYMENT_METHODS: { value: PaymentMethod; label: string }[]` (2a's `PaymentMethod` from `data/types.ts`).

- [ ] **Step 1: Write the failing tests**

Append to 2a's `ItemSheet.test.tsx` (reuse its render helper and its way of capturing the request body; the names below are placeholders for those):

```tsx
describe('payment method (2d §5.6)', () => {
  it('out items offer the method and send it', async () => {
    const sent = renderItemSheet({ item: { ...outItem, payment_method: 'card' } })
    fireEvent.click(screen.getByRole('button', { name: 'Transfer' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect((await sent()).payment_method).toBe('transfer')
  })

  it('in items hide it and send nothing', async () => {
    const sent = renderItemSheet({ item: { ...inItem } })
    expect(screen.queryByRole('group', { name: 'Payment method' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await sent()).not.toHaveProperty('payment_method')
  })

  it('a new out item defaults to card', () => {
    renderItemSheet({ item: null })
    expect(screen.getByRole('button', { name: 'Card' })).toHaveAttribute('aria-pressed', 'true')
  })
})
```

Append to 2a's `EntrySheet.test.tsx`:

```tsx
describe('payment method (2d §5.6)', () => {
  it('preselects the entry’s method and sends it when paying', async () => {
    const sent = renderEntrySheet({ entry: { ...expectedOutEntry, payment_method: 'transfer' } })
    fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
    expect(screen.getByRole('button', { name: 'Transfer' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect((await sent()).payment_method).toBe('transfer')
  })

  it('an in entry preselects its own method too (no more fixed transfer)', () => {
    renderEntrySheet({ entry: { ...expectedInEntry, payment_method: 'cash' } })
    fireEvent.click(screen.getByRole('button', { name: 'Received' }))
    expect(screen.getByRole('button', { name: 'Cash' })).toHaveAttribute('aria-pressed', 'true')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/plan/items/ItemSheet.test.tsx src/features/plan/EntrySheet.test.tsx`
Expected: FAIL — no "Payment method" control; the entry preselects card/transfer by direction.

- [ ] **Step 3: Implement**

`web/src/features/plan/paymentMethods.ts`:

```ts
import type { PaymentMethod } from '../../data/types' // 2a's union

export const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'card', label: 'Card' },
  { value: 'cash', label: 'Cash' },
  { value: 'apple_pay', label: 'Apple Pay' },
  { value: 'transfer', label: 'Transfer' },
  { value: 'other', label: 'Other' },
]
```

`ItemSheet.tsx`: add state initialised from the item (`useState<PaymentMethod>((item?.payment_method as PaymentMethod) ?? 'card')`), render for out items only, next to the bucket field:

```tsx
{direction === 'out' && (
  <Segmented label="Payment method" options={PAYMENT_METHODS} value={paymentMethod} onChange={setPaymentMethod} />
)}
```

and in the body builder:

```ts
  ...(direction === 'out' ? { payment_method: paymentMethod } : {}),
```

(In items send nothing: the server defaults a new one to transfer and keeps an existing one's.)

`EntrySheet.tsx`: replace the "card for out, transfer for in" default with `entry.payment_method` (`useState<PaymentMethod>(entry.payment_method as PaymentMethod)`); the per-payment control stays and its value is still sent as `payment_method` in the `done` body.

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/plan && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/paymentMethods.ts web/src/features/plan/items/ItemSheet.tsx web/src/features/plan/EntrySheet.tsx web/src/features/plan/items/ItemSheet.test.tsx web/src/features/plan/EntrySheet.test.tsx
git commit -m "feat(web/plan): payment method on recurring items; the Entry sheet preselects it"
```

### Task F5.2: Archive an event bucket from Plan › Budgets

**Stream:** F5 · **Depends on:** F5.1, F1.5 (`useOnlineAction`)

Load skills frontend-design, mobile-native, apple-design, dataviz (for charts) before writing UI code.

**Files:**
- Modify: `web/src/features/plan/Budgets.tsx` (2a's)
- Test: append to 2a's `web/src/features/plan/Budgets.test.tsx`

**Interfaces:**
- Consumes: `BudgetRowOut.archive_suggested`, `POST /api/v1/buckets/{bucket_id}/archive`, `useOnlineAction` (F1.5), 2a's budgets keys.
- Produces: an **Archive** button on event-bucket rows with `archive_suggested`, replacing 2a's "Archive?" label; a confirm sheet that says there is no undo; online only; on success the budgets keys are invalidated.

- [ ] **Step 1: Write the failing test**

Append to 2a's `Budgets.test.tsx` (reuse its render helper and fixtures; mock `../../ui/Toast` if 2a does not):

```tsx
describe('Archive (2d §5.6)', () => {
  const trip = { ...eventRow, bucket_id: 'trip1', name: 'Crete', archive_suggested: true }

  it('asks, then archives online', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    renderBudgets([trip])
    fireEvent.click(screen.getByRole('button', { name: 'Archive Crete' }))
    expect(screen.getByText('Archive Crete? There is no undo: it leaves Plan and the new app.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect([req.method, new URL(req.url).pathname]).toEqual(['POST', '/api/v1/buckets/trip1/archive'])
  })

  it('is blocked offline', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderBudgets([trip])
    fireEvent.click(screen.getByRole('button', { name: 'Archive Crete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection."))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('rows without the suggestion have no button', () => {
    renderBudgets([{ ...trip, archive_suggested: false }])
    expect(screen.queryByRole('button', { name: /Archive/ })).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/plan/Budgets.test.tsx`
Expected: FAIL — only the "Archive?" label exists.

- [ ] **Step 3: Implement**

In `Budgets.tsx`, replace 2a's `archive_suggested` label with:

```tsx
{row.kind === 'event' && row.archive_suggested && (
  <button type="button" className="btn btn--sm" aria-label={`Archive ${row.name}`} onClick={() => setArchiving(row)}>Archive</button>
)}
```

and add, once per screen:

```tsx
const act = useOnlineAction()
const [archiving, setArchiving] = useState<BudgetRow | null>(null)
// …
<Sheet open={archiving !== null} onClose={() => setArchiving(null)} title="Archive bucket">
  <p>{archiving ? `Archive ${archiving.name}? There is no undo: it leaves Plan and the new app.` : ''}</p>
  <div className="sheet__actions">
    <button type="button" className="btn" onClick={() => setArchiving(null)}>Cancel</button>
    <button type="button" className="btn btn--danger" onClick={async () => {
      if (!archiving) return
      const out = await act(
        () => api.POST('/api/v1/buckets/{bucket_id}/archive', { params: { path: { bucket_id: archiving.bucket_id } } }),
        { invalidates: BUDGETS_KEYS /* 2a's plan budgets + pace keys for this household */ },
      )
      if (out.ok) setArchiving(null)
    }}>Archive</button>
  </div>
</Sheet>
```

(Use 2a's real key builders for `/plan/budgets` and `/plan/pace` in place of `BUDGETS_KEYS`. If 2a's Budgets screen calls hooks instead of `api` directly, add an `useArchiveBucket()` to 2a's `features/plan/hooks.ts` wrapping the same call, and use it here.)

- [ ] **Step 4: Run to verify pass**

Run: `npm test -- src/features/plan && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/Budgets.tsx web/src/features/plan/Budgets.test.tsx web/src/features/plan/hooks.ts
git commit -m "feat(web/plan): archive a suggested event bucket from Budgets (online only)"
```

---

## Integration

### Task I1: Merge, full verification and the hand-over checks

**Stream:** I · **Depends on:** every stream above merged in the stated order (N may be absent if 2c's B1 has not merged; then run this task again after N)

**Files:**
- Modify: only what the checks below find broken.

- [ ] **Step 1: Merge in order and regenerate the API types once**

On an integration branch from `main`: merge M, B, F1, F2, F3, F4, F5 (and N when available) in that order. Resolve any conflict in `web/src/api/openapi.json` / `schema.d.ts` by taking either side, then:

```bash
cd web && npm ci && npm run gen:api && cd ..
git diff --stat web/src/api   # commit it if anything changed
```

- [ ] **Step 2: Migration chain**

```bash
DATABASE_URL=sqlite:///./heads.db APP_SECRET_KEY='test-secret-key-at-least-32-chars-long!!' DEBUG=true \
  .venv/bin/python -m alembic heads        # exactly one head: d0e1f2a3b4c5 with N, else c9d0e1f2a3b4 (2c) or b8c9d0e1f2a3
rm -f heads.db
.venv/bin/python -m pytest tests/test_migrations.py tests/test_planning_upgrade.py -o addopts="" -p no:cacheprovider
TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t .venv/bin/python -m pytest tests/test_migrations.py tests/test_planning_upgrade.py -o addopts="" -p no:cacheprovider
```

Expected: one head; PASS on both dialects.

- [ ] **Step 3: Full suites**

```bash
.venv/bin/python -m pytest -n 8 -o addopts="" -p no:cacheprovider
TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t .venv/bin/python -m pytest -o addopts="" -p no:cacheprovider
.venv/bin/ruff format --check . && .venv/bin/ruff check .
cd web && npm run typecheck && npm test && npm run lint && npm run build && cd ..
```

Expected: everything green. Then repeat the F4.3 Step 5 `grep` checks on `web/dist/sw.js`, and `git diff main -- static/sw.js` is empty.

- [ ] **Step 4: Manual pass (Chrome, 390×844, light and dark, seeded data)**

Run the app (`.venv/bin/uvicorn app.main:app --reload` with `NEW_APP_ENABLED=true`, and `npm run dev` in `web/`, or the built `dist` served by FastAPI). Sign in, then check and note results:
- Insights: chips and lens switch every figure; a category opens six months, shops and rules; Uncategorised opens; the cash row is not tappable; Fuel with two cars and with none; Filters with From after To refuses; nothing overflows at 360 px; charts readable in both themes (3:1).
- Offline (DevTools → Offline) after one online load: Insights and every Settings screen open with "Offline · updated HH:MM"; an unvisited period says "No saved data for this view. Connect once to load it."; every Settings write toasts the offline message and changes nothing; reload offline still opens `/app/insights` (navigate fallback), while `/app/auth/login` is not served by the worker.
- Settings: profile save; password change ends signed out with "Password changed. Sign in again."; 2FA set up (secret, otpauth link, 8 codes, backdrop does not close), turn off then set up again; passkey link/unlink round trip lands on `/app/settings/profile` with one toast; household invite link; categories edit, rule add (upsert), rule collision on the field; token shown once and gone after navigating away; notifications toggles.
- Plan: Item sheet payment method (out only); Entry sheet preselects it; Archive on a suggested event bucket.
- `prefers-reduced-motion`: sheets do not slide.

- [ ] **Step 5: Push on an installed iPhone (once)**

Install `/app/` to the Home Screen, open Settings › Notifications, turn push on (permission prompt from the tap), "Send test" arrives, tapping it opens `/app/settings`. Trigger an auto-pay or a bill reminder on seeded data (or wait for the scheduler) and check its tap opens `/app/plan`. Mute "Due in 3 days" (after N) and confirm no push and no in-app row for it.

- [ ] **Step 6: Commit the fixes, if any, and hand over**

```bash
git add -A && git commit -m "chore: 2d integration fixes"   # only if Steps 1–5 changed files
```

Hand the branch to the user for review and `git push` to `main`. Production runs `b8c9d0e1f2a3` (and later `d0e1f2a3b4c5`) on deploy; both are additive. Push needs the existing `VAPID_*` settings.

---

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| §1 success 1 (offline Insights) | 2a `QueryView` + `useCachedQuery`, F2.1, I1 |
| §1 success 2 (lens changes every figure) | F1.4, F1.6, F2.1–F2.4 (every query keyed and sent with `paid_by`) |
| §1 success 3 (category: six months, shops, rules) | B4, F2.4 |
| §1 success 4 (password, 2FA, passkey, sign out) | B5, B6, F3.2 |
| §1 success 5 (categories and rules, tokens, alerts) | B1, N2, F4.1, F4.2, F4.4 |
| §1 success 6 (transfer recorded when paid, auto-paid, completed) | M1–M3 |
| §3 architecture, routes, Settings entry in the account sheet | F1.7, F3.1 |
| §3.1 period and lens | F1.4 |
| §3.2 charts | F1.2, F1.3 |
| §4 widgets 1–12, member lens, empty period, Filters | F2.1, F2.2, F2.3 |
| §4.1 category drill-down | B4, F2.4 |
| §4.2 fuel per car | F2.4 |
| §5 hub | F3.1 |
| §5.1 Profile & security | B5, B6, F3.2 |
| §5.2 Household | F3.3 |
| §5.3 Categories & rules | B1, F4.1 |
| §5.4 Automations | F4.2 |
| §5.5 Notifications | N2, F1.7, F4.4 |
| §5.6 payment method in 2a's sheets, Archive | F5.1, F5.2 |
| §6.1–6.3 reads, online-only writes, errors | F1.5, every Settings task |
| §6.4 service worker | F4.3 |
| §7.0–7.6 backend | M1–M3, B1–B6, N1–N2 |
| §8 look and accessibility | Global Constraints; F1.1 (switch, chips), F2.1 (radio group), F3.2 (autocomplete, secrets), F4.3 |
| §9 testing, §10 delivery | every task; I1 |

## Spec gaps resolved in this plan

1. **2FA "Turn off" keeps the user signed in, but 2FA is mandatory for password sessions** (`_cookie_auth` answers 403 when it is off). The three security endpoints use a new `require_api_auth_enrolling`; everything else stays 403 until 2FA is back; after Turn off on a password session the Set up sheet opens straight away (B5, F3.2). A fresh pending secret clears `last_totp_step` so its first code is not refused as a replay.
2. **Update without `payment_method`** keeps the item's method (the spec only defines the create default); a direction change without one resets to the new direction's default (M3). The ORM default follows direction too (M1).
3. **"Invalid is 400"**: validated in the handlers (not pydantic, which gives 422); `parse_payment_method` keeps mapping blank to card for transactions (M3).
4. **`receive_occurrence` also takes an explicit method** so the Entry sheet's per-payment choice works for in entries (M2).
5. **`EntryOut.payment_method`** needs the `Entry` dataclass in `app/services/planning.py` (not in the spec's file table) (M3).
6. **"Where it went" rows had no category id**; B3 adds `category_id` (null = uncategorised, the cash sentinel for not-logged cash).
7. **Delete confirmation counts**: `GET /settings/categories` gains `expense_count` and `rule_count` (B1); category delete removes its rules explicitly too.
8. **`monthly_in_out` equality**: each month uses the same functions and windows as `in_out`, the current month clipped to today (B3).
9. **`avg_per_month`** on category detail = mean of the six months that have ended (matches the mock's €395); `push_devices` = the caller's subscriptions in this household (B4, N2).
10. **Profile name 1–100** was not enforced by the server; B5 adds a 400.
11. **Categories vs usual** is shown only for single-month periods (`this_month`, `last_month`), Household lens (F2.1).
12. **On track** = `fixed.projected + buckets.projected` from `/plan/month` (F2.2).
13. **"How you paid"**: the server folds not-logged cash into the cash method; the card subtracts it so the footnote "Leaves out the €X cash not logged yet" is true (F2.2).
14. **File ownership for parallel F streams**: F1 adds every 2d route (with placeholder screens), every 2d key and `useOnlineAction`; Settings write hooks are split per screen (`profileHooks`, `householdHooks`, `categoryHooks`, `tokenHooks`, `notificationHooks`) instead of one `hooks.ts`, which holds the shared reads. F3 therefore depends on F1 as well as B.
15. **Notifications before N**: `useNotificationPrefs` treats 404 as "no alert types" and the screen shows push only (F1.6, F4.4).
16. **Password-change notice** survives the sign-out via a one-shot `sessionStorage` notice the sign-in screen shows (F3.2).
17. **The lens must be a labelled radio group**, but 2a's `Segmented` is a button group with `aria-pressed`; F2.1 adds a `LensControl` (`role="radiogroup"`, arrow keys) on 2a's styles instead of changing 2a's component.
18. **Settings › Categories needs fields 2a's narrowed `Category` drops** (`is_default`, `locked`, `system_key`, `expense_count`, `rule_count`); F1.6 widens 2a's `Category` type and `toCategories` so both phases keep one `keys.categories()` cache entry. Likewise `useHousehold`, `useBuckets`, `usePlanMonth`, `useCategoriesVsUsual` and `keys.categoryRules()` are 2a's, reused, not redefined.
