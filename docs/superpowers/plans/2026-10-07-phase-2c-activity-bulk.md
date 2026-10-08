# Phase 2c: Activity and bulk changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Activity screen in the React PWA to find, check and fix transactions: a searchable, filterable feed, a read-first detail, swipe actions, and multi-select bulk changes with a budget preview and a 24-hour undo. It is backed by new FastAPI endpoints and one additive migration.

**Architecture:** On the backend, one `TransactionFilter` (`app/services/transaction_filter.py`) drives both the feed (`GET /api/v1/transactions`) and bulk-by-filter. Bulk changes are split into pure per-row rules (`app/services/bulk_rules.py`) and an orchestrator (`app/services/bulk.py`). The orchestrator loads rows `with_for_update(of=Transaction)`, writes fields directly, and stores old and new values in `bulk_batches`/`bulk_batch_rows` so a batch can be undone. On the frontend, `web/src/features/activity/` holds the screens. They use 2a's kit and data layer through `features/activity/hooks.ts`. Five small kit components are added under `web/src/ui/`.

**Tech Stack:** FastAPI 0.142, SQLAlchemy 2.0, Pydantic 2.13, Alembic (SQLite and Postgres 18), pytest. On the frontend: React 19, react-router 7, TanStack Query 5, openapi-fetch, Vitest and Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-07-phase-2c-activity-bulk-design.md` (the authority). Read it alongside `2026-10-07-phase-2a-plan-home-design.md` (kit, `useCachedQuery`, `useAction`, `keys.ts`, the test kit) and its "Stream A exports" section, which is the contract this plan codes against and `2026-10-07-phase-2b-composer-design.md` (`/new?from=`, `/edit/:id`, `usePendingTransactions`).

## Global Constraints

- Migration `revision = "c9d0e1f2a3b4"`, `down_revision = "b8c9d0e1f2a3"`. It is additive, works on SQLite and Postgres 18, and its downgrade drops all three tables.
- All endpoints live under `/api/v1/transactions`, use `require_api_auth`, and are isolated per household.
- Route order: `GET /transactions/counts`, `/duplicates` and `/bulk` are registered **before** `GET /transactions/{txn_id}`. `app/api/bulk.py`'s router is included ahead of the transactions router.
- Feed page size is 50 (max 200), ordered by date desc, then `created_at` desc.
- A batch matches at most 1,000 rows. More is a 400 ("Narrow the filter").
- Undo is allowed within 24 h, once per batch, by any member. Batch tables are never purged.
- Duplicates look back 90 days with a ±3-day window. The gap badge reads "2 min apart" when the pair was created ≤10 min apart, else "N days apart".
- Swipe threshold is 40% of the row width. A long-press is 500 ms. SearchField debounces for 250 ms.
- Toasts: "Deleted · Undo" lasts 5 s and the DELETE is sent when it ends, or at once when the page is hidden. "Moved N payments · Undo" lasts 10 s.
- "Recent bulk changes" shows the last 10 (`GET /transactions/bulk?limit=10`, max 50).
- Bulk preview, apply, undo and duplicate dismiss are **online only** and never queued. Swipe delete and field edits go through `useAction` (optimistic, queued offline).
- Screens never import `api`. Only `features/activity/hooks.ts` does (2a §3).
- Filters live in the URL under the API's names: `q, category_id, bucket_id, paid_by, payment_method, type, recurring_bill_id, missing_payer=1, dups=1, from_date, to_date, min_amount, max_amount`.
- Look and accessibility follow 2a §7: 44 pt tap targets, tabular numerals, colour is never the only signal, chips have `aria-pressed`, selected rows have `aria-selected` plus a tick, and the BulkBar is labelled "Bulk actions for N selected" and sits above the tab bar.
- Every UI task must **load skills frontend-design, mobile-native, apple-design before writing UI code**. The visual source is `docs/redesign/mocks/access-home.html` §03 Activity, on `tokens.css` and `components.css`.
- Commands: `.venv/bin/python -m pytest <files> -o addopts="" -p no:cacheprovider`. In `web/`: `npm test -- <file>`, `npm run typecheck`, `npm run build`, `npm run lint`, `npm run gen:api`.
- **Speed mode:** each task runs only its own tests. The full suites run once, in Task 22.

## Review Focus

These are inputs the spec implies but doesn't spell out. Each one has a test in the task that owns the code:

1. **LIKE wildcards in search.** `q=100%` or `q=a_b` must match those characters literally, not everything. Test: Task 7, `test_q_treats_like_wildcards_literally`.
2. **Comma decimals.** `q=42,50` and `min_amount=12,5` mean 42.50 and 12.50, as the old search did, rather than a 400 or no match. Test: Task 7, `test_comma_decimals_in_q_and_amounts`.
3. **Foreign-currency rows in a bulk preview.** `total_out` and the bucket `spent_before → spent_after` are in base currency (amount × rate), the same figures 2a Budgets shows. Test: Task 3, `test_totals_and_budget_effect_use_base_currency`.
4. **"Keep both" tapped twice, or by both members.** The second call is a 204 with no duplicate rows and no 500 from the unique pair. Test: Task 5, `test_dismiss_is_idempotent`.
5. **Swipe-delete, then the app is backgrounded.** The held DELETE is sent at once on `visibilitychange`→hidden or `pagehide`, not lost. Test: Task 15, `sends at once when the page is hidden`.

## Streams and dependencies

| Stream | Tasks | Branch / worktree | Depends on |
|---|---|---|---|
| **B1** backend bulk | 1–6, then the join task 10 | `feat/2c-b1`, branched from 2d stream M (see Task 1) | 2d M (`b8c9d0e1f2a3`). Task 5 needs Task 7 (cherry-picked). Task 10 needs B2 merged into B1 |
| **B2** backend feed | 7–9 | `feat/2c-b2`, branched from `main` | nothing |
| **F1** frontend feed | 11–17 | `feat/2c-f1` | 2a stream A merged (kit plus `data/`); Task 9 (types); 2b's `usePendingTransactions` (stubbed `[]` until then) |
| **F2** frontend bulk | 18–21 | `feat/2c-f2`, branched from F1 | F1; Task 10 merged (bulk types). Task 21 also needs 2a's `ItemSheet.tsx` |
| **Integration** | 22 | the merge of all | all |

**Disjoint files.** B1 owns `alembic/versions/c9d0e1f2a3b4_*`, `app/models.py`, `app/services/bulk*.py`, `app/api/bulk.py`, `app/api/__init__.py`, `app/services/duplicates.py` and `tests/test_bulk*.py`/`tests/bulk_fixtures.py`. B2 owns `app/services/transaction_filter.py`, `app/services/history.py`, `app/api/transaction_models.py`, `app/api/transactions.py` and `tests/test_activity_*.py`. The only file both touch is `transaction_filter.py`: Task 7 creates it, and B1 cherry-picks that commit, so the later merge is a no-op. Task 10 runs after the merge and is the only one that edits B2's files from B1.

**Merge order** (spec §10): 2d M → B2 → B1 (with Task 10) → F1 → F2. Take a `pg_dump` before deploying, because a migration runs. The user pushes to `main`.

## File map

**Backend (create):**
- `alembic/versions/c9d0e1f2a3b4_bulk_changes.py`: the three tables.
- `app/services/transaction_filter.py`: `TransactionFilter`, `StrictTransactionFilter`, `apply_filter`, `maybe_number`.
- `app/services/bulk_rules.py`: `Changes`, `Payer`, `RowContext`, `RowPlan`, `Skip`, `plan_row`, `UndoContext`, `undo_problem`, the skip codes and reasons.
- `app/services/bulk.py`: `Selection`, `run_bulk`, `undo_batch`, `recent_batches`, `bulk_history_events`, `dismiss_duplicates`, `can_undo`.
- `app/services/history.py`: `transaction_history`.
- `app/api/bulk.py`: `POST /bulk`, `GET /bulk`, `POST /bulk/{batch_id}/undo`, `POST /duplicates/dismiss`, with their models.
- `app/api/transaction_models.py`: `TransactionOut`, `TransactionPage`, `CountsOut`, `DuplicateGroupOut`, `DuplicatesOut`, `HistoryEventOut`, `HistoryOut`.
- Tests: `tests/bulk_fixtures.py`, `tests/test_bulk_migration.py`, `tests/test_bulk_rules.py`, `tests/test_bulk_api.py`, `tests/test_bulk_undo.py`, `tests/test_bulk_filter.py`, `tests/test_bulk_pg.py`, `tests/test_activity_filter.py`, `tests/test_activity_feed.py`, `tests/test_activity_misc.py`, `tests/test_activity_join.py`.

**Backend (modify):** `app/models.py` (three models), `app/api/__init__.py` (include `bulk.router` first), `app/api/transactions.py` (feed, counts, duplicates, receipt, history), `app/services/duplicates.py` (`drop_dismissed`).

**Frontend (create):**
- `web/src/ui/`: `Chip.tsx`, `SearchField.tsx`, `Check.tsx`, `SwipeRow.tsx`, `BulkBar.tsx`, `ui-2c.css`, and their `*.test.tsx`.
- `web/src/features/activity/`:
  - screens: `Activity.tsx`, `Feed.tsx`, `FeedRow.tsx`, `FiltersSheet.tsx`, `Duplicates.tsx`, `Detail.tsx`, `OptionSheet.tsx`, `NotesSheet.tsx`;
  - bulk: `selection.ts`, `BulkSheet.tsx`, `BulkPreview.tsx`, `RecentBulk.tsx`;
  - plumbing: `filters.ts`, `hooks.ts`, `heldDeletes.ts`, `pending.ts`, `format.ts`, `activity.css`, `testing.tsx`, and tests next to each.

**Frontend (modify):** `web/src/data/keys.ts` (additions), `web/src/screens/Activity.tsx` (re-export), `web/src/router.tsx` (`activity/:id`), and 2a's `web/src/features/plan/ItemSheet.tsx` ("See payments").

## Rule → test map (spec §5.4)

Every rule row has a named test. "Unit" means `tests/test_bulk_rules.py` (Task 2) or the undo-rule unit tests in `tests/test_bulk_undo.py` (Task 4). "HTTP" means the API test that proves the rule end to end.

| Rule | Test(s) |
|---|---|
| R1 | `test_bulk_api.py::test_r01_foreign_or_missing_reference_is_404_and_nothing_changes` (ids, bucket, category, payer, bill); `test_bulk_filter.py::test_r01_filter_never_touches_another_household` |
| R2 | `test_bulk_rules.py::test_r02_deleted_row_is_skipped`; `test_bulk_api.py::test_r02_own_deleted_id_is_skipped_not_404` |
| R3 | `test_bulk_api.py::test_r03_archived_target_bucket_is_400` |
| R4 | `test_bulk_rules.py::test_r04_income_into_a_bucket_without_income_tracking_is_skipped`; `test_bulk_api.py::test_r04_r07_null_bucket_and_income_rules` |
| R5 | `test_bulk_rules.py::test_r05_income_to_no_bucket_is_allowed`; `test_bulk_api.py::test_r04_r07_null_bucket_and_income_rules` |
| R6 | `test_bulk_rules.py::test_r06_expense_or_transfer_to_no_bucket_needs_a_bucket`; `test_bulk_api.py::test_r04_r07_null_bucket_and_income_rules` |
| R7 | `test_bulk_rules.py::test_r07_bucketed_bill_payment_to_no_bucket_keeps_its_bucket`, `::test_r07_bucketless_fixed_cost_stays_or_moves_into_a_monthly_bucket`; `test_bulk_api.py::test_r04_r07_null_bucket_and_income_rules`, `::test_r07_single_put_rules_are_unchanged` |
| R8 | `test_bulk_api.py::test_r08_event_bucket_preview_matches_bucket_spent` |
| R9 | `test_bulk_api.py::test_r09_move_bill_needs_bill_selection_and_bucket_change` |
| R10 | `test_bulk_api.py::test_r10_move_bill_refuses_event_bucket_and_in_items` |
| R11 | `test_bulk_api.py::test_r11_move_bill_moves_the_item_and_its_entries` |
| R12 | `test_bulk_api.py::test_r12_r18_links_stay_and_entry_payer_follows` |
| R13 | `test_bulk_rules.py::test_r13_payer_change_on_a_row_with_a_take_is_skipped`; `test_bulk_api.py::test_r13_r15_cash_takes` |
| R14 | `test_bulk_rules.py::test_r14_method_away_from_cash_with_a_take_is_skipped`; `test_bulk_api.py::test_r13_r15_cash_takes` |
| R15 | `test_bulk_rules.py::test_r15_cash_needs_a_payer`; `test_bulk_api.py::test_r13_r15_cash_takes` |
| R16 | `test_bulk_rules.py::test_r16_own_share_only_for_expenses` |
| R17 | `test_bulk_rules.py::test_r17_own_share_needs_covering_splits`; `test_bulk_api.py::test_r17_r19_own_share_cent_and_fuel` |
| R18 | `test_bulk_api.py::test_r12_r18_links_stay_and_entry_payer_follows`; `test_bulk_undo.py::test_u06_restores_values_and_entry_payer` |
| R19 | `test_bulk_rules.py::test_r19_fuel_rows_with_litres_keep_the_fuel_category`; `test_bulk_api.py::test_r17_r19_own_share_cent_and_fuel` |
| R20 | `test_bulk_api.py::test_r20_r21_dry_run_writes_nothing_and_suggestions_stay` |
| R21 | `test_bulk_api.py::test_r20_r21_dry_run_writes_nothing_and_suggestions_stay` |
| U1 | `test_bulk_undo.py::test_u01_deleted_since_is_skipped` |
| U2 | `test_bulk_undo.py::test_u02_changed_since_is_skipped_others_restored` |
| U3 | `test_bulk_undo.py::test_u03_old_target_gone_is_skipped` |
| U4 | `test_bulk_undo.py::test_u04_fixed_cost_whose_item_was_deleted_is_skipped` |
| U5 | `test_bulk_undo.py::test_u05_take_and_split_rules_against_old_values` |
| U6 | `test_bulk_undo.py::test_u06_restores_values_and_entry_payer` |
| U7 | `test_bulk_undo.py::test_u07_bill_move_restored_only_if_untouched` |
| U8 | `test_bulk_undo.py::test_u08_own_share_cent_is_kept` |

---

## Stream B1: backend bulk changes

### Task 1: Migration `c9d0e1f2a3b4` and the three models

**Stream:** B1. **Depends on:** 2d stream M (`b8c9d0e1f2a3`).

> **Precondition (read first).** 2d's migration `b8c9d0e1f2a3` (`alembic/versions/b8c9d0e1f2a3_bill_payment_method.py`) does not exist on `main` yet. Do one of these:
> - branch `feat/2c-b1` from 2d's stream M branch once M is committed; or
> - create B1 on a branch that already contains `b8c9d0e1f2a3`.
>
> Check with `ls alembic/versions/b8c9d0e1f2a3_*.py`. If the file is missing, **stop**: alembic fails with "Can't locate revision identified by 'b8c9d0e1f2a3'", and `test_schema_matches_models` fails because the new models have no migration.

**Files:**
- Create: `alembic/versions/c9d0e1f2a3b4_bulk_changes.py`
- Modify: `app/models.py` (append three classes after `MatchSuggestion`)
- Test: `tests/test_bulk_migration.py`

**Interfaces:**
- Consumes: `app.core.database.Base`, `gen_id`, `utcnow_naive`. `tests/test_migrations.py`'s `_alembic(args, db_url)` and `_db_url(tmp_path, name)`.
- Produces: the ORM classes `BulkBatch`, `BulkBatchRow` and `DuplicateDismissal` in `app.models`, with exactly the columns below. `BulkBatch.rows` is a relationship to `BulkBatchRow`.

- [ ] **Step 1: Write the failing tests**

`tests/test_bulk_migration.py`:

```python
"""Migration c9d0e1f2a3b4 (2c spec §5.5): three additive tables, a clean
round trip from b8c9d0e1f2a3, and the dismissal pair CHECK."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

from app.models import DuplicateDismissal, Transaction, TransactionType
from tests.test_migrations import _alembic, _db_url

TABLES = {"bulk_batches", "bulk_batch_rows", "duplicate_dismissals"}


def _tables(db_url):
    eng = create_engine(db_url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_upgrade_creates_the_tables_and_round_trips(tmp_path):
    db_url = _db_url(tmp_path, "bulk.db")
    before = _alembic(["upgrade", "b8c9d0e1f2a3"], db_url)
    assert before.returncode == 0, before.stderr
    assert not TABLES & _tables(db_url)

    up = _alembic(["upgrade", "c9d0e1f2a3b4"], db_url)
    assert up.returncode == 0, up.stderr
    assert TABLES <= _tables(db_url)
    eng = create_engine(db_url)
    insp = inspect(eng)
    assert "ix_bulk_batches_household_created" in {
        i["name"] for i in insp.get_indexes("bulk_batches")
    }
    assert "ix_bulk_batch_rows_transaction_id" in {
        i["name"] for i in insp.get_indexes("bulk_batch_rows")
    }
    row_cols = {c["name"] for c in insp.get_columns("bulk_batch_rows")}
    for field in ("bucket_id", "category_id", "paid_by", "payer_mode", "payment_method"):
        assert {f"old_{field}", f"new_{field}"} <= row_cols
    # The old_/new_ values carry no FKs, so history survives deletions.
    assert {fk["referred_table"] for fk in insp.get_foreign_keys("bulk_batch_rows")} == {
        "bulk_batches",
        "transactions",
    }
    eng.dispose()

    down = _alembic(["downgrade", "b8c9d0e1f2a3"], db_url)
    assert down.returncode == 0, down.stderr
    assert not TABLES & _tables(db_url)
    again = _alembic(["upgrade", "head"], db_url)
    assert again.returncode == 0, again.stderr


def test_dismissal_pair_must_be_ordered(db, make_household):
    hh = make_household()
    a, b = (
        Transaction(
            household_id=hh.household_id,
            bucket_id=hh.bucket_id,
            amount=Decimal("5"),
            type=TransactionType.expense,
            transaction_date=date(2026, 10, 1),
        )
        for _ in range(2)
    )
    db.add_all([a, b])
    db.flush()
    lo, hi = sorted([a.id, b.id])
    db.add(DuplicateDismissal(household_id=hh.household_id, first_id=hi, second_id=lo))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(DuplicateDismissal(household_id=hh.household_id, first_id=lo, second_id=hi))
    db.commit()
    db.add(DuplicateDismissal(household_id=hh.household_id, first_id=lo, second_id=hi))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bulk_migration.py -o addopts="" -p no:cacheprovider`
Expected: FAIL. The import fails with `ImportError: cannot import name 'DuplicateDismissal'`.

- [ ] **Step 3: Add the models**

Append to `app/models.py` after the `MatchSuggestion` class:

```python
# ---------------------------------------------------------------------------
# Bulk changes and dismissed duplicates (2c spec §5.3-5.5)
# ---------------------------------------------------------------------------


class BulkBatch(Base):
    """One applied bulk change: what it set, on how many rows, and the
    recurring item it moved. Undone at most once, within 24 hours of
    ``created_at`` (app.services.bulk). Never purged."""

    __tablename__ = "bulk_batches"
    __table_args__ = (Index("ix_bulk_batches_household_created", "household_id", "created_at"),)

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    undone_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    undone_at = Column(DateTime, nullable=True)
    selection = Column(String(8), nullable=False)  # ids | filter | bill
    fields = Column(String(64), nullable=False)  # comma list: bucket,category,payer,method
    summary = Column(String(200), nullable=False)
    row_count = Column(Integer, nullable=False)
    total_out = Column(Numeric(12, 4), nullable=False)
    total_in = Column(Numeric(12, 4), nullable=False)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="SET NULL"), nullable=True)
    bill_bucket_old = Column(String, nullable=True)
    bill_bucket_new = Column(String, nullable=True)
    bill_moved = Column(Boolean, default=False, server_default=text("false"), nullable=False)

    rows = relationship("BulkBatchRow", back_populates="batch", cascade="all, delete-orphan")


class BulkBatchRow(Base):
    """The old and new values of one transaction in a batch. Plain strings
    with no FKs, so the history reads the same after a bucket, category or
    member is gone (undo then skips the row, U3)."""

    __tablename__ = "bulk_batch_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "transaction_id", name="uq_bulk_batch_row"),
        Index("ix_bulk_batch_rows_transaction_id", "transaction_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    batch_id = Column(String, ForeignKey("bulk_batches.id", ondelete="CASCADE"), nullable=False)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    old_bucket_id = Column(String, nullable=True)
    new_bucket_id = Column(String, nullable=True)
    old_category_id = Column(String, nullable=True)
    new_category_id = Column(String, nullable=True)
    old_paid_by = Column(String, nullable=True)
    new_paid_by = Column(String, nullable=True)
    old_payer_mode = Column(String(16), nullable=True)
    new_payer_mode = Column(String(16), nullable=True)
    old_payment_method = Column(String(16), nullable=True)
    new_payment_method = Column(String(16), nullable=True)
    # The bill entry whose paid_by followed a single payer (R18), and its old value.
    occurrence_id = Column(String, nullable=True)
    old_occurrence_paid_by = Column(String, nullable=True)
    restored = Column(Boolean, default=False, server_default=text("false"), nullable=False)

    batch = relationship("BulkBatch", back_populates="rows")


class DuplicateDismissal(Base):
    """ "Keep both": a pair the duplicate finder must not show again, for
    every member. Stored smaller id first, once."""

    __tablename__ = "duplicate_dismissals"
    __table_args__ = (
        UniqueConstraint("first_id", "second_id", name="uq_duplicate_dismissal"),
        CheckConstraint("first_id < second_id", name="ck_duplicate_dismissals_order"),
        Index("ix_duplicate_dismissals_household", "household_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    first_id = Column(String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    second_id = Column(String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
```

All the imported names (`CheckConstraint`, `UniqueConstraint`, `Index`, `text`, `Boolean`, `Numeric`, `Integer`) are already imported at the top of `app/models.py`.

- [ ] **Step 4: Write the migration**

`alembic/versions/c9d0e1f2a3b4_bulk_changes.py`:

```python
"""bulk changes: batches with per-row undo, and dismissed duplicate pairs

Additive only (2c spec §5.5). Three new tables and nothing altered, so plain
create_table works on SQLite and Postgres alike. Batch mode is only needed to
alter an existing SQLite table, as in a7b8c9d0e1f2.

- bulk_batches: one row per applied bulk change (who, when, what, totals,
  and the recurring item it moved with its old and new bucket).
- bulk_batch_rows: per transaction, the old and new value of every field
  the batch set. Plain VARCHARs with no FKs, so the history survives
  deletions; undo checks existence itself.
- duplicate_dismissals: "Keep both" pairs, smaller id first, unique.

Downgrade drops all three; the batch history is lost and nothing else reads it.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-07 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

BATCH_INDEX = "ix_bulk_batches_household_created"
ROW_INDEX = "ix_bulk_batch_rows_transaction_id"
DISMISS_INDEX = "ix_duplicate_dismissals_household"
ROW_FIELDS = (
    ("bucket_id", sa.String()),
    ("category_id", sa.String()),
    ("paid_by", sa.String()),
    ("payer_mode", sa.String(16)),
    ("payment_method", sa.String(16)),
)


def upgrade() -> None:
    op.create_table(
        "bulk_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "undone_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.Column("selection", sa.String(8), nullable=False),
        sa.Column("fields", sa.String(64), nullable=False),
        sa.Column("summary", sa.String(200), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("total_out", sa.Numeric(12, 4), nullable=False),
        sa.Column("total_in", sa.Numeric(12, 4), nullable=False),
        sa.Column(
            "bill_id",
            sa.String(),
            sa.ForeignKey("recurring_bills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bill_bucket_old", sa.String(), nullable=True),
        sa.Column("bill_bucket_new", sa.String(), nullable=True),
        sa.Column("bill_moved", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(BATCH_INDEX, "bulk_batches", ["household_id", "created_at"])

    value_columns = []
    for name, type_ in ROW_FIELDS:
        value_columns.append(sa.Column(f"old_{name}", type_, nullable=True))
        value_columns.append(sa.Column(f"new_{name}", type_, nullable=True))
    op.create_table(
        "bulk_batch_rows",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(),
            sa.ForeignKey("bulk_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *value_columns,
        sa.Column("occurrence_id", sa.String(), nullable=True),
        sa.Column("old_occurrence_paid_by", sa.String(), nullable=True),
        sa.Column("restored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("batch_id", "transaction_id", name="uq_bulk_batch_row"),
    )
    op.create_index(ROW_INDEX, "bulk_batch_rows", ["transaction_id"])

    op.create_table(
        "duplicate_dismissals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "first_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "second_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("first_id", "second_id", name="uq_duplicate_dismissal"),
        sa.CheckConstraint("first_id < second_id", name="ck_duplicate_dismissals_order"),
    )
    op.create_index(DISMISS_INDEX, "duplicate_dismissals", ["household_id"])


def downgrade() -> None:
    op.drop_index(DISMISS_INDEX, table_name="duplicate_dismissals")
    op.drop_table("duplicate_dismissals")
    op.drop_index(ROW_INDEX, table_name="bulk_batch_rows")
    op.drop_table("bulk_batch_rows")
    op.drop_index(BATCH_INDEX, table_name="bulk_batches")
    op.drop_table("bulk_batches")
```

- [ ] **Step 5: Run the new tests and the migration guards**

Run: `.venv/bin/python -m pytest tests/test_bulk_migration.py tests/test_migrations.py tests/test_planning_upgrade.py -o addopts="" -p no:cacheprovider`
Expected: PASS. This includes `test_single_head`, `test_schema_matches_models`, `test_downgrade_then_upgrade_round_trips` and the production-shaped upgrade test (spec §9 item 12).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/c9d0e1f2a3b4_bulk_changes.py app/models.py tests/test_bulk_migration.py
git commit -m "feat(bulk): migration c9d0e1f2a3b4 with bulk batches and duplicate dismissals"
```

---

### Task 2: Per-row bulk rules (`plan_row`)

**Stream:** B1. **Depends on:** Task 1 (same branch; no model use, but it keeps the stream linear).

**Files:**
- Create: `app/services/bulk_rules.py`
- Test: `tests/test_bulk_rules.py`

**Interfaces:**
- Consumes: `app.models` (`PayerMode`, `PaymentMethod`, `Transaction`, `TransactionType`) and `app.schemas.own_share_problem(amount, split_amounts) -> str | None`.
- Produces (Tasks 3 and 4 use these exact names):
  - `FIELDS = ("bucket", "category", "payer", "method")`
  - `@dataclass(frozen=True) class Payer: mode: str; user_id: str | None = None`
  - `@dataclass(frozen=True) class Changes: has_bucket: bool = False; bucket_id: str | None = None; has_category: bool = False; category_id: str | None = None; payer: Payer | None = None; payment_method: str | None = None`, with the property `fields -> tuple[str, ...]`
  - `@dataclass(frozen=True) class RowContext: takers: dict[str, str]; fuel_category_id: str | None; target_takes_income: bool`
  - `@dataclass(frozen=True) class Skip: code: str; reason: str`
  - `@dataclass(frozen=True) class RowPlan: bucket_id, category_id, paid_by: str | None; payer_mode: str; payment_method: str; changed: bool; absorb_cent: bool = False`
  - `plan_row(t: Transaction, ch: Changes, ctx: RowContext) -> RowPlan | Skip`
  - `REASONS: dict[str, str]`, `BILL_KEEPS_BUCKET: str`, `skip(code, reason=None) -> Skip`

**Precedence when several rules fail on one row:** the first code in this order wins: `deleted`, `needs_bucket`, `income_bucket`, `fuel_data`, `own_share_type`, `cash_take` (payer), `no_split`, `cash_take` (method), `cash_needs_payer`. The spec doesn't fix an order. This one is stable and tested.

- [ ] **Step 1: Write the failing tests**

`tests/test_bulk_rules.py`:

```python
"""Per-row bulk rules (2c spec §5.4) on unsaved rows: no database needed.

Rows that can't take every requested change are skipped whole; rows that
already hold the targets are unchanged."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models import PayerMode, Transaction, TransactionSplit, TransactionType
from app.services.bulk_rules import (
    BILL_KEEPS_BUCKET,
    Changes,
    Payer,
    RowContext,
    RowPlan,
    Skip,
    plan_row,
)

ME, MARIA = "user-me", "user-maria"
FUEL, GROCERIES = "cat-fuel", "cat-groceries"


def txn(**kw) -> Transaction:
    splits = kw.pop("splits", [])
    fields = dict(
        id="t1",
        type=TransactionType.expense,
        bucket_id="day",
        category_id=GROCERIES,
        amount=Decimal("100.00"),
        paid_by=ME,
        payer_mode=PayerMode.single.value,
        payment_method="card",
        recurring_bill_id=None,
        fuel_litres=None,
        deleted_at=None,
    )
    fields.update(kw)
    t = Transaction(**fields)
    t.splits = [TransactionSplit(user_id=u, amount=Decimal(a)) for u, a in splits]
    return t


def ctx(takers=None, takes_income=True) -> RowContext:
    return RowContext(
        takers=takers or {}, fuel_category_id=FUEL, target_takes_income=takes_income
    )


def skipped(result) -> Skip:
    assert isinstance(result, Skip), result
    return result


def planned(result) -> RowPlan:
    assert isinstance(result, RowPlan), result
    return result


def test_changes_fields_lists_only_requested_keys():
    ch = Changes(has_bucket=True, bucket_id=None, payment_method="cash")
    assert ch.fields == ("bucket", "method")


def test_r02_deleted_row_is_skipped():
    r = plan_row(txn(deleted_at=datetime(2026, 10, 1)), Changes(has_bucket=True, bucket_id="b"), ctx())
    assert skipped(r).code == "deleted"


def test_r04_income_into_a_bucket_without_income_tracking_is_skipped():
    income = txn(type=TransactionType.income, bucket_id=None)
    ch = Changes(has_bucket=True, bucket_id="box")
    assert skipped(plan_row(income, ch, ctx(takes_income=False))).code == "income_bucket"
    assert planned(plan_row(income, ch, ctx(takes_income=True))).bucket_id == "box"


def test_r04_income_already_in_the_bucket_is_unchanged_not_skipped():
    income = txn(type=TransactionType.income, bucket_id="box")
    r = plan_row(income, Changes(has_bucket=True, bucket_id="box"), ctx(takes_income=False))
    assert planned(r).changed is False


def test_r05_income_to_no_bucket_is_allowed():
    r = planned(
        plan_row(txn(type=TransactionType.income), Changes(has_bucket=True, bucket_id=None), ctx())
    )
    assert r.bucket_id is None and r.changed


@pytest.mark.parametrize("kind", [TransactionType.expense, TransactionType.transfer])
def test_r06_expense_or_transfer_to_no_bucket_needs_a_bucket(kind):
    r = skipped(plan_row(txn(type=kind), Changes(has_bucket=True, bucket_id=None), ctx()))
    assert r.code == "needs_bucket" and r.reason != BILL_KEEPS_BUCKET


def test_r06_bill_linked_transfer_with_a_bucket_needs_a_bucket():
    t = txn(type=TransactionType.transfer, recurring_bill_id="salary")
    r = skipped(plan_row(t, Changes(has_bucket=True, bucket_id=None), ctx()))
    assert r.code == "needs_bucket"


def test_r07_bucketed_bill_payment_to_no_bucket_keeps_its_bucket():
    t = txn(recurring_bill_id="cosmote", bucket_id="bills")
    r = skipped(plan_row(t, Changes(has_bucket=True, bucket_id=None), ctx()))
    assert r.code == "needs_bucket" and r.reason == BILL_KEEPS_BUCKET


def test_r07_bucketless_fixed_cost_stays_or_moves_into_a_monthly_bucket():
    fixed = txn(recurring_bill_id="cosmote", bucket_id=None)
    assert planned(plan_row(fixed, Changes(has_bucket=True, bucket_id=None), ctx())).changed is False
    moved = planned(plan_row(fixed, Changes(has_bucket=True, bucket_id="bills"), ctx()))
    assert moved.changed and moved.bucket_id == "bills"


def test_r13_payer_change_on_a_row_with_a_take_is_skipped():
    cash = txn(payment_method="cash", paid_by=ME)
    takers = {"t1": ME}
    to_maria = plan_row(cash, Changes(payer=Payer("single", MARIA)), ctx(takers))
    assert skipped(to_maria).code == "cash_take"
    own = plan_row(cash, Changes(payer=Payer("own_share")), ctx(takers))
    assert skipped(own).code == "cash_take"
    same = plan_row(cash, Changes(payer=Payer("single", ME)), ctx(takers))
    assert planned(same).changed is False


def test_r14_method_away_from_cash_with_a_take_is_skipped():
    cash = txn(payment_method="cash", paid_by=ME)
    r = plan_row(cash, Changes(payment_method="card"), ctx({"t1": ME}))
    assert skipped(r).code == "cash_take"
    assert planned(plan_row(cash, Changes(payment_method="card"), ctx())).payment_method == "card"


def test_r15_cash_needs_a_payer():
    nobody = txn(paid_by=None)
    assert skipped(plan_row(nobody, Changes(payment_method="cash"), ctx())).code == "cash_needs_payer"
    both = planned(
        plan_row(nobody, Changes(payment_method="cash", payer=Payer("single", MARIA)), ctx())
    )
    assert both.payment_method == "cash" and both.paid_by == MARIA


@pytest.mark.parametrize("kind", [TransactionType.income, TransactionType.transfer])
def test_r16_own_share_only_for_expenses(kind):
    r = plan_row(txn(type=kind), Changes(payer=Payer("own_share")), ctx())
    assert skipped(r).code == "own_share_type"


def test_r17_own_share_needs_covering_splits():
    bare = plan_row(txn(), Changes(payer=Payer("own_share")), ctx())
    assert skipped(bare).code == "no_split"
    short = plan_row(txn(splits=[(ME, "30"), (MARIA, "30")]), Changes(payer=Payer("own_share")), ctx())
    assert skipped(short).code == "no_split"
    ok = planned(
        plan_row(
            txn(splits=[(ME, "33.33"), (MARIA, "66.66")]), Changes(payer=Payer("own_share")), ctx()
        )
    )
    assert ok.paid_by is None and ok.payer_mode == PayerMode.own_share.value and ok.absorb_cent


def test_r19_fuel_rows_with_litres_keep_the_fuel_category():
    fuel = txn(category_id=FUEL, fuel_litres=Decimal("40.000"))
    away = plan_row(fuel, Changes(has_category=True, category_id=GROCERIES), ctx())
    assert skipped(away).code == "fuel_data"
    into = planned(plan_row(txn(), Changes(has_category=True, category_id=FUEL), ctx()))
    assert into.category_id == FUEL and into.changed


def test_rows_are_skipped_whole_never_half_changed():
    # The bucket move alone would apply; the payer change can't, so nothing does.
    t = txn(payment_method="cash")
    r = plan_row(
        t, Changes(has_bucket=True, bucket_id="bills", payer=Payer("single", MARIA)), ctx({"t1": ME})
    )
    assert skipped(r).code == "cash_take"


def test_row_already_holding_every_target_is_unchanged():
    r = planned(plan_row(txn(), Changes(has_bucket=True, bucket_id="day", payment_method="card"), ctx()))
    assert r.changed is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bulk_rules.py -o addopts="" -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.bulk_rules'`.

- [ ] **Step 3: Implement `app/services/bulk_rules.py`**

```python
"""Per-row rules of a bulk change (2c spec §5.4). Nothing here writes.

A row that can't take every requested change is skipped whole, with a code
and a reason (the bulk_set_payer pattern); a row that already holds the
targets is unchanged. app.services.bulk applies the plans.
"""

from dataclasses import dataclass

from app.models import PayerMode, PaymentMethod, Transaction, TransactionType
from app.schemas import own_share_problem

FIELDS = ("bucket", "category", "payer", "method")

CASH = PaymentMethod.cash.value
SINGLE = PayerMode.single.value
OWN_SHARE = PayerMode.own_share.value

BILL_KEEPS_BUCKET = "Bill payments keep a bucket; move the bill instead"
REASONS = {
    "deleted": "Deleted",
    "needs_bucket": "Expenses and transfers need a bucket",
    "income_bucket": "This bucket doesn't track income",
    "fuel_data": "Has fuel litres; edit it to change the category",
    "own_share_type": "Each paid their own share is only for expenses",
    "cash_take": "Cash was taken for it, so it stays cash and paid by whoever took it",
    "no_split": "Its shares don't add up to the amount",
    "cash_needs_payer": "Cash needs a payer; choose who paid too",
    # Undo (U1-U5)
    "deleted_since": "Deleted since",
    "changed_since": "Changed since",
    "target_gone": "Its old bucket, category or payer no longer exists",
}


@dataclass(frozen=True)
class Payer:
    mode: str  # a PayerMode value
    user_id: str | None = None


@dataclass(frozen=True)
class Changes:
    """What a bulk change sets. ``has_*`` tells "set to none" from "leave"."""

    has_bucket: bool = False
    bucket_id: str | None = None
    has_category: bool = False
    category_id: str | None = None
    payer: Payer | None = None
    payment_method: str | None = None

    @property
    def fields(self) -> tuple[str, ...]:
        on = (
            self.has_bucket,
            self.has_category,
            self.payer is not None,
            self.payment_method is not None,
        )
        return tuple(f for f, set_ in zip(FIELDS, on, strict=True) if set_)


@dataclass(frozen=True)
class RowContext:
    """What the rules need beyond the row, loaded once per batch."""

    takers: dict[str, str]  # transaction id -> whose wallet its active linked take went to
    fuel_category_id: str | None
    target_takes_income: bool  # the target bucket is active with "Track income" on


@dataclass(frozen=True)
class Skip:
    code: str
    reason: str


@dataclass(frozen=True)
class RowPlan:
    bucket_id: str | None
    category_id: str | None
    paid_by: str | None
    payer_mode: str
    payment_method: str
    changed: bool
    absorb_cent: bool = False  # own share: give the rounding cent to a split (R17)


def skip(code: str, reason: str | None = None) -> Skip:
    return Skip(code, reason or REASONS[code])


def plan_row(t: Transaction, ch: Changes, ctx: RowContext) -> RowPlan | Skip:
    """The new values for ``t``, or why it is skipped. Pure: reads only ``t``,
    ``ch`` and ``ctx``."""
    if t.deleted_at is not None:
        return skip("deleted")  # R2
    expense = t.type == TransactionType.expense
    income = t.type == TransactionType.income
    taker = ctx.takers.get(t.id)

    bucket_id = t.bucket_id
    if ch.has_bucket:
        bucket_id = ch.bucket_id
        if bucket_id is None and not income:
            fixed_cost = expense and t.recurring_bill_id is not None and t.bucket_id is None
            if not fixed_cost:
                if expense and t.recurring_bill_id is not None:
                    return skip("needs_bucket", BILL_KEEPS_BUCKET)  # R7
                return skip("needs_bucket")  # R6
        if (
            income
            and bucket_id is not None
            and bucket_id != t.bucket_id
            and not ctx.target_takes_income
        ):
            return skip("income_bucket")  # R4 (R5: income to None is fine)

    category_id = t.category_id
    if ch.has_category:
        category_id = ch.category_id
        if t.fuel_litres is not None and category_id != ctx.fuel_category_id:
            return skip("fuel_data")  # R19

    paid_by, payer_mode = t.paid_by, t.payer_mode or SINGLE
    absorb = False
    if ch.payer is not None:
        if ch.payer.mode == OWN_SHARE:
            if not expense:
                return skip("own_share_type")  # R16
            if taker is not None:
                return skip("cash_take")  # R13
            if payer_mode != OWN_SHARE:
                if own_share_problem(t.amount, (s.amount for s in t.splits)):
                    return skip("no_split")  # R17
                absorb = True
            paid_by, payer_mode = None, OWN_SHARE
        else:
            if taker is not None and taker != ch.payer.user_id:
                return skip("cash_take")  # R13
            paid_by, payer_mode = ch.payer.user_id, SINGLE

    method = t.payment_method
    if ch.payment_method is not None:
        method = ch.payment_method
        if taker is not None and method != CASH:
            return skip("cash_take")  # R14: the take is never dropped
        if method == CASH and t.payment_method != CASH and payer_mode == SINGLE and not paid_by:
            return skip("cash_needs_payer")  # R15

    changed = (bucket_id, category_id, paid_by, payer_mode, method) != (
        t.bucket_id,
        t.category_id,
        t.paid_by,
        t.payer_mode or SINGLE,
        t.payment_method,
    )
    return RowPlan(bucket_id, category_id, paid_by, payer_mode, method, changed, absorb)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bulk_rules.py -o addopts="" -p no:cacheprovider`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/bulk_rules.py tests/test_bulk_rules.py
git commit -m "feat(bulk): per-row bulk rules R2-R7, R13-R17, R19"
```

---

### Task 3: `run_bulk` (preview and apply, by ids or by bill) and `POST /transactions/bulk`

**Stream:** B1. **Depends on:** Tasks 1–2.

**Files:**
- Create: `app/services/bulk.py`, `app/api/bulk.py`, `tests/bulk_fixtures.py`
- Modify: `app/api/__init__.py` (import `bulk`; include it **above** `transactions`)
- Test: `tests/test_bulk_api.py`

**Interfaces:**
- Consumes:
  - Task 2's `Changes`, `Payer`, `RowContext`, `RowPlan`, `Skip`, `plan_row`, `SINGLE`, `OWN_SHARE`;
  - `app.services.budgets.bucket_period(bucket, today)` and `bucket_spent(db, bucket, today) -> Decimal`;
  - `app.services.money.to_base` and `base_amount_expr`;
  - `app.services.fuel.fuel_category_id(db, hh)`;
  - `app.services.insights._month_range(y, m)`;
  - `app.validators.household_member_ids(db, hh) -> set[str]`;
  - `app.schemas.absorb_own_share_cent(amount, splits)`;
  - `app.api.planning_models.Money`.
- Produces:
  - `app.services.bulk`:
    - `BULK_MAX_ROWS = 1000`, `UNDO_WINDOW = timedelta(hours=24)`, `NO_BUCKET_NAME`, `BILL_EVENT_BUCKET`, `BILL_IN_ITEM`, `METHOD_LABELS`;
    - `@dataclass(frozen=True) class Selection: ids: list[str] | None = None; bill_id: str | None = None` with the property `kind -> "ids" | "bill"` (Task 5 adds `filter`);
    - `can_undo(batch, now=None) -> bool`;
    - `run_bulk(db, *, household_id, user_id, select, changes, move_bill=False, dry_run=True, expected_count=None, today=None) -> dict` (the `BulkResult` shape);
    - the helpers `_takers(db, ids) -> dict[str, str]` and `_bucket_names(db, hh) -> dict[str, str]`, reused by Task 4.
  - `app.api.bulk`:
    - `router` (prefix `/transactions`);
    - the models `PayerIn`, `ChangesIn` (with `to_changes()`), `SelectIn`, `BulkIn`, `SkippedOut`, `BucketEffectOut`, `BillMoveOut`, `BulkResult`.
  - `tests/bulk_fixtures.py`: the `env` fixture (see Step 1), used by Tasks 4–6 and 10.

- [ ] **Step 1: Write the shared fixture**

`tests/bulk_fixtures.py`:

```python
"""Shared seed for the bulk tests (2c spec §9): one household with two
members, monthly, event, archived and no-income buckets, a Fuel category,
an out item (Cosmote, in Bills) and an in item (Salary).

Import both names in a test module: ``from tests.bulk_fixtures import env``
and ``from tests.test_api import api``, each with ``# noqa: F401``.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.clock import local_today
from app.models import (
    FUEL_SYSTEM_KEY,
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    HouseholdMember,
    ItemDirection,
    MemberRole,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)

URL = "/api/v1/transactions/bulk"


@pytest.fixture()
def env(client, api, db):
    headers, hh = api
    hid, today = hh.household_id, local_today()

    maria = User(
        username="maria",
        display_name="Maria",
        email="maria@example.com",
        password_hash="x",
        session_version=0,
    )
    db.add(maria)
    db.flush()
    db.add(HouseholdMember(household_id=hid, user_id=maria.id, role=MemberRole.member))

    day = db.get(Bucket, hh.bucket_id)
    day.name, day.budget = "Day to day", Decimal("1000")
    bills = Bucket(household_id=hid, name="Bills", budget=Decimal("300"))
    box = Bucket(household_id=hid, name="Cash box", show_income=False)
    old = Bucket(household_id=hid, name="Old", status=BucketStatus.archived)
    trip = Bucket(
        household_id=hid,
        name="Crete",
        type=BucketType.trip,
        budget=Decimal("900"),
        start_date=today - timedelta(days=10),
        end_date=today + timedelta(days=10),
    )
    groceries = Category(household_id=hid, name="Groceries")
    utilities = Category(household_id=hid, name="Utilities")
    fuel = Category(household_id=hid, name="Fuel", system_key=FUEL_SYSTEM_KEY)
    db.add_all([bills, box, old, trip, groceries, utilities, fuel])
    db.flush()
    cosmote = RecurringBill(
        household_id=hid,
        bucket_id=bills.id,
        name="Cosmote",
        amount=Decimal("38.90"),
        currency="EUR",
        start_date=today - timedelta(days=90),
        is_active=True,
    )
    salary = RecurringBill(
        household_id=hid,
        name="Salary",
        direction=ItemDirection.in_.value,
        amount=Decimal("1500"),
        currency="EUR",
        start_date=today - timedelta(days=90),
        is_active=True,
    )
    db.add_all([cosmote, salary])
    db.commit()

    def add(amount="10.00", *, days_ago=0, **kw) -> str:
        fields = dict(
            household_id=hid,
            amount=Decimal(amount),
            currency="EUR",
            exchange_rate=Decimal("1"),
            type=TransactionType.expense,
            bucket_id=day.id,
            paid_by=hh.user_id,
            payer_mode="single",
            payment_method="card",
            transaction_date=today - timedelta(days=days_ago),
        )
        fields.update(kw)
        t = Transaction(**fields)
        db.add(t)
        db.commit()
        return t.id

    def bulk(select, changes, *, dry_run=False, **extra):
        body = {"select": select, "changes": changes, "dry_run": dry_run, **extra}
        return client.post(URL, headers=headers, json=body)

    def row(txn_id) -> Transaction:
        db.expire_all()
        return db.get(Transaction, txn_id)

    return SimpleNamespace(
        client=client,
        headers=headers,
        hh=hh,
        hid=hid,
        today=today,
        me=hh.user_id,
        maria=maria.id,
        day=day.id,
        bills=bills.id,
        box=box.id,
        old=old.id,
        trip=trip.id,
        groceries=groceries.id,
        utilities=utilities.id,
        fuel=fuel.id,
        cosmote=cosmote.id,
        salary=salary.id,
        add=add,
        bulk=bulk,
        row=row,
    )
```

- [ ] **Step 2: Write the failing API tests**

`tests/test_bulk_api.py`:

```python
"""POST /api/v1/transactions/bulk (2c spec §5.3-5.4; §9 items 1-9)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    Bucket,
    BulkBatch,
    BulkBatchRow,
    CashMovement,
    Category,
    MatchSuggestion,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services.budgets import bucket_spent
from app.services.bulk import BILL_EVENT_BUCKET, BILL_IN_ITEM, NO_BUCKET_NAME
from app.services.bulk_rules import BILL_KEEPS_BUCKET
from app.services.cash import FROM_BANK, link_take
from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.test_api import api  # noqa: F401


def codes(body) -> dict[str, str]:
    return {s["id"]: s["code"] for s in body["skipped"]}


@pytest.mark.parametrize("target", ["foreign_id", "missing_id", "bucket", "category", "payer", "bill"])
def test_r01_foreign_or_missing_reference_is_404_and_nothing_changes(
    env, db, make_household, target  # noqa: F811
):
    other = make_household(name="Other", username="other")
    theirs = Transaction(
        household_id=other.household_id,
        bucket_id=other.bucket_id,
        amount=Decimal("12.00"),
        type=TransactionType.expense,
        transaction_date=env.today,
    )
    their_cat = Category(household_id=other.household_id, name="Theirs")
    their_bill = RecurringBill(
        household_id=other.household_id,
        name="Their bill",
        amount=Decimal("9"),
        currency="EUR",
        start_date=env.today,
        is_active=True,
    )
    db.add_all([theirs, their_cat, their_bill])
    db.commit()
    mine = env.add("12.00")

    select, changes = {"ids": [mine]}, {"bucket_id": env.bills}
    if target == "foreign_id":
        select = {"ids": [mine, theirs.id]}
    elif target == "missing_id":
        select = {"ids": [mine, "no-such-id"]}
    elif target == "bucket":
        changes = {"bucket_id": other.bucket_id}
    elif target == "category":
        changes = {"category_id": their_cat.id}
    elif target == "payer":
        changes = {"payer": {"mode": "single", "user_id": other.user_id}}
    else:
        select = {"bill_id": their_bill.id}

    r = env.bulk(select, changes)
    assert r.status_code == 404, r.text
    assert env.row(mine).bucket_id == env.day
    assert env.row(theirs.id).bucket_id == other.bucket_id
    assert db.query(BulkBatch).count() == 0


def test_r02_own_deleted_id_is_skipped_not_404(env, db):  # noqa: F811
    gone = env.add("5.00", deleted_at=utcnow_naive())
    live = env.add("6.00")
    body = env.bulk({"ids": [gone, live]}, {"bucket_id": env.bills}).json()
    assert body["matched"] == 2 and body["changed"] == 1
    assert codes(body) == {gone: "deleted"}
    assert env.row(gone).bucket_id == env.day and env.row(live).bucket_id == env.bills


def test_r03_archived_target_bucket_is_400(env, db):  # noqa: F811
    a = env.add()
    r = env.bulk({"ids": [a]}, {"bucket_id": env.old})
    assert r.status_code == 400 and "archived" in r.json()["detail"]
    assert env.row(a).bucket_id == env.day


def test_r04_r07_null_bucket_and_income_rules(env, db):  # noqa: F811
    income = env.add("1500.00", type=TransactionType.income, bucket_id=env.day)
    plain = env.add("20.00")
    transfer = env.add("50.00", type=TransactionType.transfer)
    bill_paid = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)

    r = env.bulk({"ids": [income, plain, transfer, bill_paid, fixed]}, {"bucket_id": None})
    assert r.status_code == 200, r.text  # the CHECK is never hit: no IntegrityError
    body = r.json()
    assert body["changed"] == 1 and body["unchanged"] == 1
    assert codes(body) == {plain: "needs_bucket", transfer: "needs_bucket", bill_paid: "needs_bucket"}
    reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert reasons[bill_paid] == BILL_KEEPS_BUCKET
    assert env.row(income).bucket_id is None and env.row(fixed).bucket_id is None
    assert env.row(bill_paid).bucket_id == env.bills

    # A bucket-less Fixed cost may move into a monthly bucket.
    assert env.bulk({"ids": [fixed]}, {"bucket_id": env.bills}).json()["changed"] == 1
    assert env.row(fixed).bucket_id == env.bills

    # Income into a bucket that doesn't track income is skipped; the expense moves.
    loose = env.add("100.00", type=TransactionType.income, bucket_id=None)
    body = env.bulk({"ids": [loose, plain]}, {"bucket_id": env.box}).json()
    assert codes(body) == {loose: "income_bucket"} and body["changed"] == 1
    assert env.row(plain).bucket_id == env.box and env.row(loose).bucket_id is None


def test_r07_single_put_rules_are_unchanged(env, db):  # noqa: F811
    bill_paid = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)

    def put(txn_id, bucket_id):
        body = {"amount": "38.90", "type": "expense", "bucket_id": bucket_id}
        return env.client.put(f"/api/v1/transactions/{txn_id}", headers=env.headers, json=body)

    assert put(bill_paid, None).status_code == 400
    assert put(fixed, None).status_code == 200


def test_r08_event_bucket_preview_matches_bucket_spent(env, db):  # noqa: F811
    a, b = env.add("40.00"), env.add("60.00")
    early = env.add("25.00", days_ago=20)  # before the trip's start_date
    trip = db.get(Bucket, env.trip)
    before = bucket_spent(db, trip, env.today)

    preview = env.bulk({"ids": [a, b, early]}, {"bucket_id": env.trip}, dry_run=True).json()
    effect = next(e for e in preview["buckets"] if e["bucket_id"] == env.trip)
    assert effect["kind"] == "event"
    assert effect["period_start"] == (env.today - timedelta(days=10)).isoformat()
    assert effect["spent_before"] == pytest.approx(float(before))
    assert effect["spent_after"] - effect["spent_before"] == pytest.approx(100.00)
    assert effect["moved_in"] == pytest.approx(100.00) and effect["outside_period"] == 1

    assert env.bulk({"ids": [a, b, early]}, {"bucket_id": env.trip}).json()["changed"] == 3
    db.expire_all()
    after = bucket_spent(db, db.get(Bucket, env.trip), env.today)
    assert float(after) == pytest.approx(effect["spent_after"])


def test_r09_move_bill_needs_bill_selection_and_bucket_change(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    by_ids = env.bulk({"ids": [pay]}, {"bucket_id": env.day}, move_bill=True)
    no_bucket = env.bulk({"bill_id": env.cosmote}, {"category_id": env.utilities}, move_bill=True)
    assert by_ids.status_code == 400 and no_bucket.status_code == 400
    assert env.row(pay).bucket_id == env.bills


def test_r10_move_bill_refuses_event_bucket_and_in_items(env, db):  # noqa: F811
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    event = env.bulk({"bill_id": env.cosmote}, {"bucket_id": env.trip}, move_bill=True)
    assert event.status_code == 400 and event.json()["detail"] == BILL_EVENT_BUCKET
    in_item = env.bulk({"bill_id": env.salary}, {"bucket_id": env.day}, move_bill=True)
    assert in_item.status_code == 400 and in_item.json()["detail"] == BILL_IN_ITEM
    assert db.get(RecurringBill, env.cosmote).bucket_id == env.bills


def test_r11_move_bill_moves_the_item_and_its_entries(env, db):  # noqa: F811
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote, days_ago=31)
    db.add(
        BillOccurrence(
            bill_id=env.cosmote,
            due_date=env.today + timedelta(days=5),
            status=OccurrenceStatus.unpaid,
        )
    )
    db.commit()

    preview = env.bulk(
        {"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True, dry_run=True
    ).json()
    assert preview["matched"] == 2
    assert preview["bill"] == {
        "id": env.cosmote,
        "name": "Cosmote",
        "bucket_before": "Bills",
        "bucket_after": "Day to day",
    }
    r = env.bulk({"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True, expected_count=2)
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 2

    entries = env.client.get(
        "/api/v1/recurring/entries",
        headers=env.headers,
        params={"from": env.today.isoformat(), "to": (env.today + timedelta(days=10)).isoformat()},
    ).json()
    assert {e["bucket_id"] for e in entries if e["item_id"] == env.cosmote} == {env.day}
    db.expire_all()
    batch = db.query(BulkBatch).one()
    assert batch.bill_moved and batch.bill_bucket_old == env.bills
    assert batch.bill_bucket_new == env.day and batch.selection == "bill"


def test_r12_r18_links_stay_and_entry_payer_follows(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote, paid_by=env.me)
    occ = BillOccurrence(
        bill_id=env.cosmote,
        due_date=env.today,
        status=OccurrenceStatus.paid,
        paid_by=env.me,
        paid_at=utcnow_naive(),
        transaction_id=pay,
    )
    db.add(occ)
    db.commit()

    body = env.bulk({"ids": [pay]}, {"payer": {"mode": "single", "user_id": env.maria}}).json()
    assert body["changed"] == 1
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.paid_by == env.maria and occ.transaction_id == pay
    t = env.row(pay)
    assert t.recurring_bill_id == env.cosmote and t.paid_by == env.maria
    stored = db.query(BulkBatchRow).one()
    assert stored.occurrence_id == occ.id and stored.old_occurrence_paid_by == env.me


def test_r13_r15_cash_takes(env, db):  # noqa: F811
    cash = env.add("30.00", payment_method="cash", paid_by=env.me)
    link_take(db, db.get(Transaction, cash), env.me, FROM_BANK, "EUR")
    db.commit()
    take = db.query(CashMovement).filter_by(transaction_id=cash).one()
    take_id, take_amount = take.id, take.amount

    payer = env.bulk({"ids": [cash]}, {"payer": {"mode": "single", "user_id": env.maria}}).json()
    method = env.bulk({"ids": [cash]}, {"payment_method": "card"}).json()
    assert codes(payer) == {cash: "cash_take"} and codes(method) == {cash: "cash_take"}
    db.expire_all()
    mv = db.get(CashMovement, take_id)
    assert mv.deleted_at is None and mv.transaction_id == cash
    assert mv.user_id == env.me and mv.amount == take_amount
    assert env.row(cash).payment_method == "cash" and env.row(cash).paid_by == env.me

    nobody = env.add("8.00", paid_by=None)
    alone = env.bulk({"ids": [nobody]}, {"payment_method": "cash"}).json()
    assert codes(alone) == {nobody: "cash_needs_payer"}
    both = env.bulk(
        {"ids": [nobody]},
        {"payment_method": "cash", "payer": {"mode": "single", "user_id": env.maria}},
    ).json()
    assert both["changed"] == 1
    assert env.row(nobody).paid_by == env.maria and env.row(nobody).payment_method == "cash"


def test_r17_r19_own_share_cent_and_fuel(env, db):  # noqa: F811
    shared = env.add("100.00")
    db.add_all(
        [
            TransactionSplit(transaction_id=shared, user_id=env.me, amount=Decimal("33.33")),
            TransactionSplit(transaction_id=shared, user_id=env.maria, amount=Decimal("66.66")),
        ]
    )
    db.commit()
    assert env.bulk({"ids": [shared]}, {"payer": {"mode": "own_share"}}).json()["changed"] == 1
    db.expire_all()
    splits = db.query(TransactionSplit).filter_by(transaction_id=shared).all()
    assert sum(s.amount for s in splits) == Decimal("100.00")
    assert env.row(shared).paid_by is None and env.row(shared).payer_mode == "own_share"

    fuel = env.add(
        "70.00",
        category_id=env.fuel,
        fuel_price_per_litre=Decimal("1.75"),
        fuel_litres=Decimal("40.000"),
    )
    body = env.bulk({"ids": [fuel]}, {"category_id": env.groceries}).json()
    assert codes(body) == {fuel: "fuel_data"} and env.row(fuel).category_id == env.fuel


def test_r20_r21_dry_run_writes_nothing_and_suggestions_stay(env, db):  # noqa: F811
    pay = env.add("38.90")
    occ = BillOccurrence(bill_id=env.cosmote, due_date=env.today, status=OccurrenceStatus.unpaid)
    db.add(occ)
    db.flush()
    db.add(MatchSuggestion(household_id=env.hid, transaction_id=pay, occurrence_id=occ.id))
    db.commit()
    changes = {
        "bucket_id": env.bills,
        "category_id": env.utilities,
        "payer": {"mode": "single", "user_id": env.maria},
        "payment_method": "transfer",
    }

    def snapshot():
        t = env.row(pay)
        return (
            t.bucket_id,
            t.category_id,
            t.paid_by,
            t.payment_method,
            db.query(BulkBatch).count(),
            db.query(BulkBatchRow).count(),
            db.query(MatchSuggestion).filter_by(dismissed=False).count(),
        )

    before = snapshot()
    preview = env.bulk({"ids": [pay]}, changes, dry_run=True).json()
    assert preview["dry_run"] is True and preview["batch_id"] is None and preview["changed"] == 1
    assert snapshot() == before

    assert env.bulk({"ids": [pay]}, changes).json()["changed"] == 1
    db.expire_all()
    suggestion = db.query(MatchSuggestion).one()
    assert suggestion.dismissed is False and suggestion.transaction_id == pay
    assert db.get(BillOccurrence, occ.id).transaction_id is None
    assert env.row(pay).recurring_bill_id is None


def test_limits_shape_and_auth(env, db):  # noqa: F811
    a = env.add()
    too_many = [f"id-{i}" for i in range(1001)]
    assert env.bulk({"ids": too_many}, {"bucket_id": env.bills}).status_code == 400
    assert env.bulk({"ids": [a]}, {}).status_code == 400
    two_keys = {"ids": [a], "bill_id": env.cosmote}
    assert env.bulk(two_keys, {"bucket_id": env.bills}).status_code == 422
    assert env.bulk({}, {"bucket_id": env.bills}).status_code == 422
    assert env.bulk({"ids": [a]}, {"payer": None}).status_code == 400
    assert env.bulk({"ids": [a]}, {"payment_method": "cheque"}).status_code == 400
    # A fresh client: no Bearer token and no cookies from the API login.
    anonymous = TestClient(env.client.app)
    assert anonymous.post(URL, json={"select": {"ids": [a]}, "changes": {}}).status_code == 401


def test_expected_count_mismatch_is_409_with_no_writes(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    r = env.bulk({"bill_id": env.cosmote}, {"bucket_id": env.day}, expected_count=2)
    assert r.status_code == 409
    assert r.json()["detail"] == "The selection changed: 1 now match. Preview again."
    assert env.row(pay).bucket_id == env.bills and db.query(BulkBatch).count() == 0


def test_unchanged_rows_are_not_stored_and_zero_changes_make_no_batch(env, db):  # noqa: F811
    a, b = env.add(), env.add(bucket_id=env.bills)
    body = env.bulk({"ids": [a, b]}, {"bucket_id": env.bills}).json()
    assert body["changed"] == 1 and body["unchanged"] == 1 and body["undo_until"]
    batch = db.query(BulkBatch).one()
    assert body["batch_id"] == batch.id and batch.row_count == 1 and batch.fields == "bucket"
    assert db.query(BulkBatchRow).count() == 1
    again = env.bulk({"ids": [a, b]}, {"bucket_id": env.bills}).json()
    assert again["changed"] == 0 and again["batch_id"] is None
    assert db.query(BulkBatch).count() == 1


def test_totals_and_budget_effect_use_base_currency(env, db):  # noqa: F811
    usd = env.add("100.00", currency="USD", exchange_rate=Decimal("0.9"))
    eur = env.add("10.00")
    inc = env.add("50.00", type=TransactionType.income, bucket_id=None)
    body = env.bulk({"ids": [usd, eur, inc]}, {"bucket_id": env.bills}, dry_run=True).json()
    assert body["total_out"] == pytest.approx(100.00)  # 90 + 10, base currency
    assert body["total_in"] == pytest.approx(50.00)
    bills = next(e for e in body["buckets"] if e["bucket_id"] == env.bills)
    assert bills["moved_in"] == pytest.approx(100.00)
    assert bills["spent_after"] - bills["spent_before"] == pytest.approx(100.00)
    assert bills["budget"] == pytest.approx(300.00)


def test_no_bucket_effect_is_fixed_costs_this_month(env, db):  # noqa: F811
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)
    body = env.bulk({"ids": [fixed]}, {"bucket_id": env.bills}, dry_run=True).json()
    none = next(e for e in body["buckets"] if e["bucket_id"] is None)
    assert none["name"] == NO_BUCKET_NAME and none["budget"] is None
    assert none["spent_before"] == pytest.approx(38.90) and none["spent_after"] == pytest.approx(0)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bulk_api.py -o addopts="" -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.bulk'`.

- [ ] **Step 4: Implement `app/services/bulk.py`**

```python
"""Bulk changes to transactions, previewed then applied (2c spec §5.3).

run_bulk previews (dry_run) or applies one change to a selection: by ids or
by recurring item (Task 5 adds by filter). The per-row rules live in
app.services.bulk_rules. Apply is one database transaction with the rows
locked, committed once at the end; nothing else here commits.

Fields are written directly, never through update_transaction: its
sync_linked_take drops a take when the method leaves cash, which R14 forbids,
and its Fixed-cost rule is already mirrored by R7 in plan_row.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Query, Session, joinedload

from app.core.clock import local_today, utcnow_naive
from app.core.money import quantize
from app.models import (
    BillOccurrence,
    Bucket,
    BucketKind,
    BucketStatus,
    BulkBatch,
    BulkBatchRow,
    CashMovement,
    Category,
    ItemDirection,
    PaymentMethod,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)
from app.schemas import absorb_own_share_cent
from app.services.budgets import bucket_period, bucket_spent
from app.services.bulk_rules import OWN_SHARE, SINGLE, Changes, RowContext, RowPlan, Skip, plan_row
from app.services.fuel import fuel_category_id
from app.services.insights import _month_range
from app.services.money import base_amount_expr, to_base
from app.validators import household_member_ids

BULK_MAX_ROWS = 1000
UNDO_WINDOW = timedelta(hours=24)
NO_BUCKET_NAME = "No bucket (Fixed costs)"
# app.api.recurring's messages for the same refusals (R10), kept identical.
BILL_EVENT_BUCKET = "A recurring item can use a monthly bucket only."
BILL_IN_ITEM = "Income has no bucket, auto-pay or shares."
METHOD_LABELS = {
    "card": "Card",
    "cash": "Cash",
    "apple_pay": "Apple Pay",
    "transfer": "Transfer",
    "other": "Other",
}


@dataclass(frozen=True)
class Selection:
    """Exactly one of: hand-picked ids, or every active payment of an item."""

    ids: list[str] | None = None
    bill_id: str | None = None

    @property
    def kind(self) -> str:
        return "ids" if self.ids is not None else "bill"


def can_undo(batch: BulkBatch, now: datetime | None = None) -> bool:
    now = now or utcnow_naive()
    return batch.undone_at is None and now <= batch.created_at + UNDO_WINDOW


# ------------------------------------------------------------ request checks


def _check_changes(db: Session, hh: str, ch: Changes) -> Bucket | None:
    """400/404 for the whole request (R1, R3); returns the target bucket."""
    if not ch.fields:
        raise HTTPException(status_code=400, detail="Choose at least one change.")
    target = None
    if ch.has_bucket and ch.bucket_id is not None:
        target = db.get(Bucket, ch.bucket_id)
        if target is None or target.household_id != hh:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        if target.status != BucketStatus.active:
            raise HTTPException(
                status_code=400, detail="That bucket is archived. Choose an active one."
            )
    if ch.has_category and ch.category_id is not None:
        category = db.get(Category, ch.category_id)
        if category is None or category.household_id != hh:
            raise HTTPException(status_code=404, detail="Category not found.")
    if ch.payer is not None and ch.payer.mode == SINGLE:
        if not ch.payer.user_id:
            raise HTTPException(status_code=400, detail="Choose who paid.")
        if ch.payer.user_id not in household_member_ids(db, hh):
            raise HTTPException(status_code=404, detail="Member not found.")
    if ch.payment_method is not None:
        try:
            PaymentMethod(ch.payment_method)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown payment method '{ch.payment_method}'."
            ) from None
    return target


def _bill(db: Session, hh: str, bill_id: str) -> RecurringBill:
    bill = db.query(RecurringBill).filter_by(id=bill_id, household_id=hh).first()
    if bill is None:
        raise HTTPException(status_code=404, detail="Recurring item not found.")
    return bill


def _check_move_bill(
    db: Session, hh: str, select: Selection, ch: Changes, move_bill: bool, target: Bucket | None
) -> RecurringBill | None:
    if not move_bill:
        return None
    if select.bill_id is None or not ch.has_bucket:
        raise HTTPException(
            status_code=400,
            detail="Moving the item needs its payments selected by item and a bucket change.",
        )  # R9
    bill = _bill(db, hh, select.bill_id)
    if bill.direction == ItemDirection.in_.value:
        raise HTTPException(status_code=400, detail=BILL_IN_ITEM)  # R10
    if target is not None and target.kind == BucketKind.event.value:
        raise HTTPException(status_code=400, detail=BILL_EVENT_BUCKET)  # R10
    return bill


# ----------------------------------------------------------------- selection


def _selected_query(db: Session, hh: str, select: Selection) -> Query:
    """Active rows of the household matching a bill selection."""
    bill = _bill(db, hh, select.bill_id)
    return db.query(Transaction).filter(
        Transaction.household_id == hh,
        Transaction.active(),
        Transaction.recurring_bill_id == bill.id,
    )


def _load(q: Query, lock: bool) -> list[Transaction]:
    q = q.options(joinedload(Transaction.splits)).order_by(
        Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id
    )
    if lock:
        # OF transactions: a plain FOR UPDATE fails on Postgres here, because
        # joinedload's LEFT OUTER JOIN puts transaction_splits on the nullable
        # side ("FOR UPDATE cannot be applied to the nullable side of an outer
        # join"). SQLite ignores the clause; tests/test_bulk_pg.py proves it.
        q = q.with_for_update(of=Transaction)
    return q.all()


def _select_rows(db: Session, hh: str, select: Selection, *, lock: bool) -> list[Transaction]:
    if select.ids is not None:
        ids = list(dict.fromkeys(i for i in select.ids if i))
        if not ids:
            raise HTTPException(status_code=400, detail="Select at least one transaction.")
        if len(ids) > BULK_MAX_ROWS:
            raise HTTPException(
                status_code=400, detail=f"Select at most {BULK_MAX_ROWS:,} transactions."
            )
        q = db.query(Transaction).filter(
            Transaction.id.in_(ids), Transaction.household_id == hh
        )
        rows = _load(q, lock)
        if len(rows) != len(ids):  # R1: missing and foreign look the same
            raise HTTPException(status_code=404, detail="Some selected transactions were not found.")
        return rows  # own soft-deleted rows stay in; plan_row skips them (R2)
    q = _selected_query(db, hh, select)
    count = q.count()
    if count > BULK_MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"{count:,} transactions match. Narrow the filter to {BULK_MAX_ROWS:,} or fewer.",
        )
    return _load(q, lock)


def _takers(db: Session, txn_ids: list[str]) -> dict[str, str]:
    """Transaction id -> whose wallet its active linked take went to."""
    if not txn_ids:
        return {}
    return dict(
        db.query(CashMovement.transaction_id, CashMovement.user_id)
        .filter(CashMovement.transaction_id.in_(txn_ids), CashMovement.active())
        .all()
    )


def _bucket_names(db: Session, hh: str) -> dict[str, str]:
    return dict(db.query(Bucket.id, Bucket.name).filter(Bucket.household_id == hh).all())


# ------------------------------------------------------------------- preview


def _fixed_costs_spent(db: Session, hh: str, start: date, end: date) -> Decimal:
    """Bucket-less expenses paid for an item (Fixed costs) in [start, end]."""
    return quantize(
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .filter(
            Transaction.household_id == hh,
            Transaction.active(),
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.is_(None),
            Transaction.recurring_bill_id.isnot(None),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .scalar()
    )


def _bucket_effects(
    db: Session, hh: str, plans: list[tuple[Transaction, RowPlan]], today: date
) -> list[dict]:
    """Every source and target bucket of the changed expenses, with its budget
    figures before and after (the same numbers as 2a Budgets). ``None`` is
    "No bucket (Fixed costs)" this month. Rows outside a bucket's period
    are counted in ``outside_period`` and don't move its figures."""
    moved = [
        (t, t.bucket_id, p.bucket_id)
        for t, p in plans
        if t.type == TransactionType.expense and t.bucket_id != p.bucket_id
    ]
    ids = {b for _, old, new in moved for b in (old, new)}
    effects = []
    for bucket_id in sorted(ids, key=lambda b: (b is None, b or "")):
        if bucket_id is None:
            start, end = _month_range(today.year, today.month)
            name, kind, budget = NO_BUCKET_NAME, "fixed", None
            spent = _fixed_costs_spent(db, hh, start, end)
        else:
            bucket = db.get(Bucket, bucket_id)
            start, end = bucket_period(bucket, today)
            name, kind = bucket.name, bucket.kind
            budget = quantize(bucket.budget) if bucket.budget is not None else None
            spent = bucket_spent(db, bucket, today)
        moved_in = moved_out = Decimal(0)
        outside = 0
        for t, old, new in moved:
            if bucket_id not in (old, new):
                continue
            if (start and t.transaction_date < start) or (end and t.transaction_date > end):
                outside += 1
                continue
            base = to_base(t.amount, t.exchange_rate)
            if new == bucket_id:
                moved_in += base
            else:
                moved_out += base
        effects.append(
            {
                "bucket_id": bucket_id,
                "name": name,
                "kind": kind,
                "budget": budget,
                "period_start": start,
                "period_end": end,
                "spent_before": spent,
                "spent_after": quantize(spent + moved_in - moved_out),
                "moved_in": quantize(moved_in),
                "moved_out": quantize(moved_out),
                "outside_period": outside,
            }
        )
    return effects


def _total(plans, kind: TransactionType) -> Decimal:
    return quantize(
        sum((to_base(t.amount, t.exchange_rate) for t, _ in plans if t.type == kind), Decimal(0))
    )


def _summary(db: Session, hh: str, ch: Changes, n: int, moved_bill: RecurringBill | None) -> str:
    parts = []
    if ch.has_bucket:
        parts.append(f"Bucket → {_bucket_names(db, hh).get(ch.bucket_id) or 'No bucket'}")
    if ch.has_category:
        name = db.get(Category, ch.category_id).name if ch.category_id else "No category"
        parts.append(f"Category → {name}")
    if ch.payer is not None:
        who = (
            "Each their own share"
            if ch.payer.mode == OWN_SHARE
            else db.get(User, ch.payer.user_id).display_name
        )
        parts.append(f"Payer → {who}")
    if ch.payment_method is not None:
        parts.append(f"Method → {METHOD_LABELS.get(ch.payment_method, ch.payment_method)}")
    text = f"{' · '.join(parts)} · {n} {'transaction' if n == 1 else 'transactions'}"
    if moved_bill is not None:
        text += f" · {moved_bill.name} moved"
    return text[:200]


# --------------------------------------------------------------------- apply


def _apply(db: Session, batch: BulkBatch, ch: Changes, plans) -> None:
    """Write the plans and their undo rows. Does not commit."""
    occurrences = {}
    if ch.payer is not None and ch.payer.mode == SINGLE:
        ids = [t.id for t, _ in plans]
        occurrences = {
            o.transaction_id: o
            for o in db.query(BillOccurrence).filter(BillOccurrence.transaction_id.in_(ids))
        }
    for t, p in plans:
        row = BulkBatchRow(batch_id=batch.id, transaction_id=t.id)
        if ch.has_bucket:
            row.old_bucket_id, row.new_bucket_id = t.bucket_id, p.bucket_id
            t.bucket_id = p.bucket_id
        if ch.has_category:
            row.old_category_id, row.new_category_id = t.category_id, p.category_id
            t.category_id = p.category_id
        if ch.payer is not None:
            row.old_paid_by, row.new_paid_by = t.paid_by, p.paid_by
            row.old_payer_mode, row.new_payer_mode = t.payer_mode, p.payer_mode
            if p.absorb_cent:
                absorb_own_share_cent(t.amount, t.splits)  # R17; undo keeps it (U8)
            t.paid_by, t.payer_mode = p.paid_by, p.payer_mode
            occ = occurrences.get(t.id)
            if occ is not None and p.payer_mode == SINGLE:  # R18
                row.occurrence_id, row.old_occurrence_paid_by = occ.id, occ.paid_by
                occ.paid_by = p.paid_by
        if ch.payment_method is not None:
            row.old_payment_method, row.new_payment_method = t.payment_method, p.payment_method
            t.payment_method = p.payment_method
        db.add(row)
    # R12, R20: recurring_bill_id, the entry's transaction_id and match
    # suggestions are never touched.


def run_bulk(
    db: Session,
    *,
    household_id: str,
    user_id: str,
    select: Selection,
    changes: Changes,
    move_bill: bool = False,
    dry_run: bool = True,
    expected_count: int | None = None,
    today: date | None = None,
) -> dict:
    """Preview or apply ``changes`` to ``select``; the BulkResult shape."""
    hh = household_id
    today = today or local_today()
    target = _check_changes(db, hh, changes)
    bill = _check_move_bill(db, hh, select, changes, move_bill, target)
    rows = _select_rows(db, hh, select, lock=not dry_run)
    matched = len(rows)
    if expected_count is not None and select.kind != "ids" and expected_count != matched:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"The selection changed: {matched} now match. Preview again.",
        )

    ctx = RowContext(
        takers=_takers(db, [t.id for t in rows]),
        fuel_category_id=fuel_category_id(db, hh),
        target_takes_income=bool(
            target is not None and target.show_income and target.status == BucketStatus.active
        ),
    )
    plans: list[tuple[Transaction, RowPlan]] = []
    skipped: list[dict] = []
    unchanged = 0
    for t in rows:
        plan = plan_row(t, changes, ctx)
        if isinstance(plan, Skip):
            skipped.append({"id": t.id, "code": plan.code, "reason": plan.reason})
        elif plan.changed:
            plans.append((t, plan))
        else:
            unchanged += 1

    names = _bucket_names(db, hh)
    bill_moves = bill is not None and bill.bucket_id != changes.bucket_id
    total_out = _total(plans, TransactionType.expense)
    total_in = _total(plans, TransactionType.income)
    result = {
        "dry_run": dry_run,
        "batch_id": None,
        "matched": matched,
        "changed": len(plans),
        "unchanged": unchanged,
        "total_out": total_out,
        "total_in": total_in,
        "skipped": skipped,
        "buckets": _bucket_effects(db, hh, plans, today) if changes.has_bucket else [],
        "bill": None
        if bill is None
        else {
            "id": bill.id,
            "name": bill.name,
            "bucket_before": names.get(bill.bucket_id),
            "bucket_after": names.get(changes.bucket_id),
        },
        "undo_until": None,
    }
    if dry_run or not (plans or bill_moves):
        db.rollback()  # R21: nothing was written; release any locks
        return result

    now = utcnow_naive()
    batch = BulkBatch(
        household_id=hh,
        created_by=user_id,
        created_at=now,
        selection=select.kind,
        fields=",".join(changes.fields),
        summary=_summary(db, hh, changes, len(plans), bill if bill_moves else None),
        row_count=len(plans),
        total_out=total_out,
        total_in=total_in,
        bill_id=bill.id if bill is not None else None,
        bill_bucket_old=bill.bucket_id if bill is not None else None,
        bill_bucket_new=changes.bucket_id if bill is not None else None,
        bill_moved=bill_moves,
    )
    db.add(batch)
    db.flush()
    _apply(db, batch, changes, plans)
    if bill_moves:
        bill.bucket_id = changes.bucket_id  # R11: entries read the item's bucket
    db.commit()
    result.update(batch_id=batch.id, undo_until=now + UNDO_WINDOW)
    return result
```

- [ ] **Step 5: Implement `app/api/bulk.py`**

```python
"""Bulk changes to transactions (2c spec §5.3): preview and apply. Task 4
adds undo and the recent list, and Task 5 adds "Keep both" for duplicates.

app.api includes this router ahead of app.api.transactions, so the literal
/transactions/bulk is never read as /transactions/{txn_id}.
"""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api.planning_models import Money
from app.api_auth import require_api_auth
from app.core.database import get_db
from app.services.bulk import Selection, run_bulk
from app.services.bulk_rules import Changes, Payer

router = APIRouter(prefix="/transactions", tags=["transactions"])

SELECT_KEYS = ("ids", "bill_id")


class PayerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "own_share"]
    user_id: str | None = None


class ChangesIn(BaseModel):
    """A key sent as null means "none"; an absent key leaves the field."""

    model_config = ConfigDict(extra="forbid")

    bucket_id: str | None = None
    category_id: str | None = None
    payer: PayerIn | None = None
    payment_method: str | None = None

    def to_changes(self) -> Changes:
        sent = self.model_fields_set
        if "payer" in sent and self.payer is None:
            raise HTTPException(status_code=400, detail="The payer can't be cleared in bulk.")
        if "payment_method" in sent and self.payment_method is None:
            raise HTTPException(status_code=400, detail="Choose a payment method.")
        return Changes(
            has_bucket="bucket_id" in sent,
            bucket_id=self.bucket_id,
            has_category="category_id" in sent,
            category_id=self.category_id,
            payer=Payer(self.payer.mode, self.payer.user_id) if self.payer else None,
            payment_method=self.payment_method,
        )


class SelectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None
    bill_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        given = [k for k in SELECT_KEYS if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(f"select needs exactly one of: {', '.join(SELECT_KEYS)}")
        return self

    def to_selection(self) -> Selection:
        return Selection(ids=self.ids, bill_id=self.bill_id)


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    select: SelectIn
    changes: ChangesIn
    move_bill: bool = False
    dry_run: bool = True
    expected_count: int | None = Field(default=None, ge=0)


class SkippedOut(BaseModel):
    id: str
    code: str
    reason: str


class BucketEffectOut(BaseModel):
    bucket_id: str | None  # None: "No bucket (Fixed costs)" this month
    name: str
    kind: str  # monthly | event | fixed
    budget: Money | None
    period_start: date | None
    period_end: date | None
    spent_before: Money
    spent_after: Money
    moved_in: Money
    moved_out: Money
    outside_period: int


class BillMoveOut(BaseModel):
    id: str
    name: str
    bucket_before: str | None  # bucket names; None: no bucket
    bucket_after: str | None


class BulkResult(BaseModel):
    dry_run: bool
    batch_id: str | None
    matched: int
    changed: int
    unchanged: int
    total_out: Money
    total_in: Money
    skipped: list[SkippedOut]
    buckets: list[BucketEffectOut]
    bill: BillMoveOut | None
    undo_until: datetime | None


@router.post("/bulk", response_model=BulkResult)
def bulk_change(
    body: BulkIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Preview (``dry_run``, the default) or apply one change to a selection.
    Apply re-checks ``expected_count`` (409 on drift) and writes all or nothing."""
    user, hh_id = auth
    return run_bulk(
        db,
        household_id=hh_id,
        user_id=user.id,
        select=body.select.to_selection(),
        changes=body.changes.to_changes(),
        move_bill=body.move_bill,
        dry_run=body.dry_run,
        expected_count=body.expected_count,
    )
```

In `app/api/__init__.py`, add `bulk,` to the `from app.api import (...)` list (alphabetical, after `buckets`) and insert this line **directly above** `router.include_router(transactions.router)`:

```python
router.include_router(bulk.router)  # before transactions: /transactions/bulk is not a txn id
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bulk_api.py tests/test_bulk_rules.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/bulk.py app/api/bulk.py app/api/__init__.py tests/bulk_fixtures.py tests/test_bulk_api.py
git commit -m "feat(bulk): POST /transactions/bulk preview and apply by ids or by bill"
```

---

### Task 4: Undo, recent bulk changes, and bulk history events

**Stream:** B1. **Depends on:** Task 3.

**Files:**
- Modify: `app/services/bulk_rules.py` (append `UndoContext`, `undo_problem`), `app/services/bulk.py` (append `undo_batch`, `recent_batches`, `bulk_history_events`), `app/api/bulk.py` (append `UndoResult`, `RecentBatchOut`, two routes)
- Test: `tests/test_bulk_undo.py`

**Interfaces:**
- Consumes: Task 3's `_load`, `_takers`, `_bucket_names`, `can_undo`, `UNDO_WINDOW`, `run_bulk`, `Selection`, and the `env` fixture.
- Produces:
  - `app.services.bulk_rules`:
    - `@dataclass(frozen=True) class UndoContext: takers: dict[str, str]; bucket_ids: set[str]; category_ids: set[str]; member_ids: set[str]`;
    - `undo_problem(t: Transaction, row: BulkBatchRow, fields: tuple[str, ...], ctx: UndoContext) -> Skip | None`.
  - `app.services.bulk`:
    - `undo_batch(db, *, household_id, user_id, batch_id) -> {"restored": int, "skipped": list[{"id", "code", "reason"}], "bill_restored": bool}`;
    - `recent_batches(db, household_id, limit=10) -> list[dict]`;
    - `bulk_history_events(db, household_id, txn_id) -> list[{"at": datetime, "kind": "bulk_change" | "bulk_undone", "by": str | None, "text": str, "batch_id": str, "can_undo": bool}]`. Task 10 wires this into B2's history.
  - HTTP: `POST /api/v1/transactions/bulk/{batch_id}/undo` → `UndoResult`, and `GET /api/v1/transactions/bulk?limit=10` (1–50) → `list[RecentBatchOut]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_bulk_undo.py`:

```python
"""Undo of a bulk change (2c spec §5.3-5.4 U1-U8; §9 item 10), the recent
list, and the bulk events in a transaction's history."""

from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core import clock
from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    Bucket,
    BulkBatch,
    Category,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionSplit,
)
from app.services.bulk import (
    UNDO_WINDOW,
    bulk_history_events,
    can_undo,
    undo_batch,
)
from app.services.cash import FROM_BANK, link_take
from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.test_api import api  # noqa: F401


def apply(env, select, changes, **extra) -> str:  # noqa: F811
    r = env.bulk(select, changes, **extra)
    assert r.status_code == 200, r.text
    return r.json()["batch_id"]


def undo(env, batch_id):  # noqa: F811
    return env.client.post(f"{URL}/{batch_id}/undo", headers=env.headers)


def codes(body) -> dict[str, str]:
    return {s["id"]: s["code"] for s in body["skipped"]}


def test_u01_deleted_since_is_skipped(env, db):  # noqa: F811
    a, b = env.add(), env.add()
    batch = apply(env, {"ids": [a, b]}, {"bucket_id": env.bills})
    assert env.client.delete(f"/api/v1/transactions/{a}", headers=env.headers).status_code == 204
    body = undo(env, batch).json()
    assert body["restored"] == 1 and codes(body) == {a: "deleted_since"}
    assert env.row(b).bucket_id == env.day


def test_u02_changed_since_is_skipped_others_restored(env, db):  # noqa: F811
    a, b, c = env.add("10.00"), env.add("11.00"), env.add("12.00")
    batch = apply(env, {"ids": [a, b, c]}, {"bucket_id": env.bills})
    put = env.client.put(
        f"/api/v1/transactions/{a}",
        headers=env.headers,
        json={"amount": "10.00", "type": "expense", "bucket_id": env.box},
    )
    assert put.status_code == 200, put.text
    body = undo(env, batch).json()
    assert body["restored"] == 2 and codes(body) == {a: "changed_since"}
    assert env.row(a).bucket_id == env.box
    assert env.row(b).bucket_id == env.day and env.row(c).bucket_id == env.day
    db.expire_all()
    assert db.get(BulkBatch, batch).undone_at is not None  # set even with skips


def test_u03_old_target_gone_is_skipped(env, db):  # noqa: F811
    temp = Bucket(household_id=env.hid, name="Temp")
    snacks = Category(household_id=env.hid, name="Snacks")
    db.add_all([temp, snacks])
    db.commit()
    a = env.add(bucket_id=temp.id)
    b = env.add(category_id=snacks.id)
    by_bucket = apply(env, {"ids": [a]}, {"bucket_id": env.bills})
    by_category = apply(env, {"ids": [b]}, {"category_id": env.groceries})
    db.delete(db.get(Bucket, temp.id))
    db.delete(db.get(Category, snacks.id))
    db.commit()
    assert codes(undo(env, by_bucket).json()) == {a: "target_gone"}
    assert codes(undo(env, by_category).json()) == {b: "target_gone"}
    assert env.row(a).bucket_id == env.bills and env.row(b).category_id == env.groceries


def test_u04_fixed_cost_whose_item_was_deleted_is_skipped(env, db):  # noqa: F811
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)
    batch = apply(env, {"ids": [fixed]}, {"bucket_id": env.bills})
    db.delete(db.get(RecurringBill, env.cosmote))  # FK SET NULL clears recurring_bill_id
    db.commit()
    assert env.row(fixed).recurring_bill_id is None
    r = undo(env, batch)
    assert r.status_code == 200, r.text  # never an IntegrityError from the CHECK
    assert codes(r.json()) == {fixed: "needs_bucket"}
    assert env.row(fixed).bucket_id == env.bills


def test_u05_take_and_split_rules_against_old_values(env, db):  # noqa: F811
    # (a) Payer me -> Maria; since then Maria took cash for it: restoring me is refused.
    a = env.add("20.00")
    batch_a = apply(env, {"ids": [a]}, {"payer": {"mode": "single", "user_id": env.maria}})
    t = db.get(Transaction, a)
    t.payment_method = "cash"
    link_take(db, t, env.maria, FROM_BANK, "EUR")
    db.commit()
    assert codes(undo(env, batch_a).json()) == {a: "cash_take"}

    # (b) Method card -> cash; since then a take was linked: back to card is refused.
    b = env.add("15.00")
    batch_b = apply(env, {"ids": [b]}, {"payment_method": "cash"})
    link_take(db, db.get(Transaction, b), env.me, FROM_BANK, "EUR")
    db.commit()
    assert codes(undo(env, batch_b).json()) == {b: "cash_take"}

    # (c) Own share -> single; since then the shares were removed: own share is refused.
    c = env.add("100.00", paid_by=None, payer_mode="own_share")
    db.add_all(
        [
            TransactionSplit(transaction_id=c, user_id=env.me, amount=Decimal("50")),
            TransactionSplit(transaction_id=c, user_id=env.maria, amount=Decimal("50")),
        ]
    )
    db.commit()
    batch_c = apply(env, {"ids": [c]}, {"payer": {"mode": "single", "user_id": env.me}})
    db.query(TransactionSplit).filter_by(transaction_id=c).delete()
    db.commit()
    assert codes(undo(env, batch_c).json()) == {c: "no_split"}


def test_u06_restores_values_and_entry_payer(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote, paid_by=env.me)
    occ = BillOccurrence(
        bill_id=env.cosmote,
        due_date=env.today,
        status=OccurrenceStatus.paid,
        paid_by=env.me,
        paid_at=utcnow_naive(),
        transaction_id=pay,
    )
    db.add(occ)
    db.commit()
    batch = apply(
        env,
        {"ids": [pay]},
        {"payer": {"mode": "single", "user_id": env.maria}, "category_id": env.utilities},
    )
    body = undo(env, batch).json()
    assert body == {"restored": 1, "skipped": [], "bill_restored": False}
    t = env.row(pay)
    assert t.paid_by == env.me and t.category_id is None
    assert t.recurring_bill_id == env.cosmote
    assert db.get(BillOccurrence, occ.id).paid_by == env.me


def test_u07_bill_move_restored_only_if_untouched(env, db):  # noqa: F811
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    first = apply(env, {"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True)
    assert undo(env, first).json()["bill_restored"] is True
    db.expire_all()
    assert db.get(RecurringBill, env.cosmote).bucket_id == env.bills

    second = apply(env, {"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True)
    db.get(RecurringBill, env.cosmote).bucket_id = env.box  # someone moved it since
    db.commit()
    assert undo(env, second).json()["bill_restored"] is False
    db.expire_all()
    assert db.get(RecurringBill, env.cosmote).bucket_id == env.box


def test_u08_own_share_cent_is_kept(env, db):  # noqa: F811
    shared = env.add("100.00")
    db.add_all(
        [
            TransactionSplit(transaction_id=shared, user_id=env.me, amount=Decimal("33.33")),
            TransactionSplit(transaction_id=shared, user_id=env.maria, amount=Decimal("66.66")),
        ]
    )
    db.commit()
    batch = apply(env, {"ids": [shared]}, {"payer": {"mode": "own_share"}})
    assert undo(env, batch).json()["restored"] == 1
    db.expire_all()
    t = env.row(shared)
    assert t.payer_mode == "single" and t.paid_by == env.me
    assert sum(s.amount for s in t.splits) == Decimal("100.00")


def test_second_undo_is_409(env, db):  # noqa: F811
    batch = apply(env, {"ids": [env.add()]}, {"bucket_id": env.bills})
    assert undo(env, batch).status_code == 200
    again = undo(env, batch)
    assert again.status_code == 409 and again.json()["detail"] == "This change was already undone."


def test_undo_window_is_24_hours(env, db, monkeypatch):  # noqa: F811
    batch_id = apply(env, {"ids": [env.add()]}, {"bucket_id": env.bills})
    created = db.get(BulkBatch, batch_id).created_at
    assert can_undo(db.get(BulkBatch, batch_id), created + UNDO_WINDOW)
    # The service, not HTTP: a 24 h jump would also expire the access token.
    late = (created + UNDO_WINDOW + timedelta(seconds=1)).replace(tzinfo=UTC)
    monkeypatch.setattr(clock, "utcnow", lambda: late)
    with pytest.raises(HTTPException) as exc:
        undo_batch(db, household_id=env.hid, user_id=env.me, batch_id=batch_id)
    assert exc.value.status_code == 409
    assert exc.value.detail == "Changes can be undone for 24 hours."


def test_another_households_batch_is_404(env, db, make_household):  # noqa: F811
    batch_id = apply(env, {"ids": [env.add()]}, {"bucket_id": env.bills})
    other = make_household(name="Other", username="other")
    with pytest.raises(HTTPException) as exc:
        undo_batch(db, household_id=other.household_id, user_id=other.user_id, batch_id=batch_id)
    assert exc.value.status_code == 404
    assert undo(env, "no-such-batch").status_code == 404


def test_recent_list_newest_first_and_route_order(env, db):  # noqa: F811
    a = env.add()
    first = apply(env, {"ids": [a]}, {"bucket_id": env.bills})
    second = apply(env, {"ids": [a]}, {"category_id": env.groceries})
    undo(env, first)
    r = env.client.get(URL, headers=env.headers, params={"limit": 10})
    assert r.status_code == 200, r.text  # not "Transaction not found"
    rows = r.json()
    assert [x["id"] for x in rows] == [second, first]
    assert rows[0]["summary"] == "Category → Groceries · 1 transaction"
    assert rows[0]["created_by"] == env.hh.username.title() and rows[0]["can_undo"] is True
    assert rows[1]["undone_at"] is not None and rows[1]["can_undo"] is False
    assert env.client.get(URL, headers=env.headers, params={"limit": 51}).status_code == 422


def test_bulk_history_events(env, db):  # noqa: F811
    a = env.add()
    batch = apply(env, {"ids": [a]}, {"bucket_id": env.bills})
    undo(env, batch)
    events = bulk_history_events(db, env.hid, a)
    assert [e["kind"] for e in events] == ["bulk_change", "bulk_undone"]
    assert events[0]["text"] == "Bucket: Day to day → Bills"
    assert events[0]["batch_id"] == batch and events[0]["can_undo"] is False
    assert events[1]["text"] == "Change undone"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bulk_undo.py -o addopts="" -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'bulk_history_events'`.

- [ ] **Step 3: Append the undo rules to `app/services/bulk_rules.py`**

```python
# ---------------------------------------------------------------------- undo


@dataclass(frozen=True)
class UndoContext:
    takers: dict[str, str]
    bucket_ids: set[str]  # the household's buckets, archived included
    category_ids: set[str]
    member_ids: set[str]


def undo_problem(t: Transaction, row, fields: tuple[str, ...], ctx: UndoContext) -> Skip | None:
    """Why ``row`` (a BulkBatchRow) can't be restored on ``t``, if it can't.
    ``require_takes_income`` is not re-checked (U6)."""
    if t.deleted_at is not None:
        return skip("deleted_since")  # U1
    holds_new = {
        "bucket": t.bucket_id == row.new_bucket_id,
        "category": t.category_id == row.new_category_id,
        "payer": (t.paid_by, t.payer_mode) == (row.new_paid_by, row.new_payer_mode),
        "method": t.payment_method == row.new_payment_method,
    }
    if not all(holds_new[f] for f in fields):
        return skip("changed_since")  # U2
    if (
        ("bucket" in fields and row.old_bucket_id and row.old_bucket_id not in ctx.bucket_ids)
        or (
            "category" in fields
            and row.old_category_id
            and row.old_category_id not in ctx.category_ids
        )
        or ("payer" in fields and row.old_paid_by and row.old_paid_by not in ctx.member_ids)
    ):
        return skip("target_gone")  # U3
    if (
        "bucket" in fields
        and row.old_bucket_id is None
        and t.type != TransactionType.income
        and t.recurring_bill_id is None
    ):
        return skip("needs_bucket")  # U4: the item was deleted since (FK SET NULL)
    taker = ctx.takers.get(t.id)
    if taker is not None:  # U5 with R13 and R14
        if "payer" in fields and (row.old_payer_mode == OWN_SHARE or row.old_paid_by != taker):
            return skip("cash_take")
        if "method" in fields and row.old_payment_method != CASH:
            return skip("cash_take")
    if (
        "payer" in fields
        and row.old_payer_mode == OWN_SHARE
        and t.payer_mode != OWN_SHARE
        and own_share_problem(t.amount, (s.amount for s in t.splits))
    ):
        return skip("no_split")  # U5 with R17
    return None
```

- [ ] **Step 4: Append undo, recent and history to `app/services/bulk.py`**

Add `UndoContext` and `undo_problem` to the `app.services.bulk_rules` import line. Then append:

```python
# ---------------------------------------------------------------------- undo


def _restore(db: Session, t: Transaction, row: BulkBatchRow, fields: tuple[str, ...]) -> None:
    if "bucket" in fields:
        t.bucket_id = row.old_bucket_id
    if "category" in fields:
        t.category_id = row.old_category_id
    if "payer" in fields:
        t.paid_by, t.payer_mode = row.old_paid_by, row.old_payer_mode
        if row.occurrence_id is not None:
            occ = db.get(BillOccurrence, row.occurrence_id)
            if occ is not None and occ.transaction_id == t.id:
                occ.paid_by = row.old_occurrence_paid_by  # U6
    if "method" in fields:
        t.payment_method = row.old_payment_method
    # U8: the own-share cent stays where R17 put it.


def undo_batch(db: Session, *, household_id: str, user_id: str, batch_id: str) -> dict:
    """Restore every row of a batch that still holds the batch's values.
    The batch row is locked, so of two concurrent undos one gets 409."""
    hh = household_id
    batch = (
        db.query(BulkBatch)
        .filter(BulkBatch.id == batch_id, BulkBatch.household_id == hh)
        .with_for_update()
        .first()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Bulk change not found.")
    if batch.undone_at is not None:
        raise HTTPException(status_code=409, detail="This change was already undone.")
    now = utcnow_naive()
    if not can_undo(batch, now):
        raise HTTPException(status_code=409, detail="Changes can be undone for 24 hours.")

    fields = tuple(f for f in batch.fields.split(",") if f)
    rows = db.query(BulkBatchRow).filter(BulkBatchRow.batch_id == batch.id).all()
    ids = [r.transaction_id for r in rows]
    txns = {t.id: t for t in _load(db.query(Transaction).filter(Transaction.id.in_(ids)), True)}
    ctx = UndoContext(
        takers=_takers(db, ids),
        bucket_ids=set(_bucket_names(db, hh)),
        category_ids={c for (c,) in db.query(Category.id).filter(Category.household_id == hh)},
        member_ids=household_member_ids(db, hh),
    )
    restored, skipped = 0, []
    for row in rows:
        t = txns[row.transaction_id]
        problem = undo_problem(t, row, fields, ctx)
        if problem is not None:
            skipped.append({"id": t.id, "code": problem.code, "reason": problem.reason})
            continue
        _restore(db, t, row, fields)
        row.restored = True
        restored += 1

    bill_restored = False
    if batch.bill_moved and batch.bill_id is not None:  # U7
        bill = db.get(RecurringBill, batch.bill_id)
        old_exists = batch.bill_bucket_old is None or batch.bill_bucket_old in ctx.bucket_ids
        if bill is not None and bill.bucket_id == batch.bill_bucket_new and old_exists:
            bill.bucket_id = batch.bill_bucket_old
            bill_restored = True

    batch.undone_at, batch.undone_by = now, user_id  # set even when rows are skipped
    db.commit()
    return {"restored": restored, "skipped": skipped, "bill_restored": bill_restored}


# ------------------------------------------------------------- recent, history


def _user_names(db: Session, ids) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.query(User.id, User.display_name).filter(User.id.in_(ids)).all())


def recent_batches(db: Session, household_id: str, limit: int = 10) -> list[dict]:
    batches = (
        db.query(BulkBatch)
        .filter(BulkBatch.household_id == household_id)
        .order_by(BulkBatch.created_at.desc(), BulkBatch.id)
        .limit(limit)
        .all()
    )
    names = _user_names(db, (b.created_by for b in batches))
    now = utcnow_naive()
    return [
        {
            "id": b.id,
            "created_at": b.created_at,
            "created_by": names.get(b.created_by),
            "summary": b.summary,
            "row_count": b.row_count,
            "undone_at": b.undone_at,
            "can_undo": can_undo(b, now),
        }
        for b in batches
    ]


def bulk_history_events(db: Session, household_id: str, txn_id: str) -> list[dict]:
    """The bulk changes (and their undos) that touched one transaction."""
    pairs = (
        db.query(BulkBatchRow, BulkBatch)
        .join(BulkBatch, BulkBatchRow.batch_id == BulkBatch.id)
        .filter(BulkBatchRow.transaction_id == txn_id, BulkBatch.household_id == household_id)
        .order_by(BulkBatch.created_at)
        .all()
    )
    if not pairs:
        return []
    buckets = _bucket_names(db, household_id)
    categories = dict(
        db.query(Category.id, Category.name).filter(Category.household_id == household_id).all()
    )
    users = _user_names(
        db,
        {r.old_paid_by for r, _ in pairs}
        | {r.new_paid_by for r, _ in pairs}
        | {b.created_by for _, b in pairs}
        | {b.undone_by for _, b in pairs},
    )

    def bucket(v):
        return buckets.get(v, "a deleted bucket") if v else "No bucket"

    def category(v):
        return categories.get(v, "a deleted category") if v else "No category"

    def payer(user_id, mode):
        if mode == OWN_SHARE:
            return "Each their own share"
        return users.get(user_id, "a former member") if user_id else "No payer"

    now = utcnow_naive()
    events = []
    for row, batch in pairs:
        parts = []
        for field in batch.fields.split(","):
            if field == "bucket":
                parts.append(f"Bucket: {bucket(row.old_bucket_id)} → {bucket(row.new_bucket_id)}")
            elif field == "category":
                parts.append(
                    f"Category: {category(row.old_category_id)} → {category(row.new_category_id)}"
                )
            elif field == "payer":
                parts.append(
                    f"Payer: {payer(row.old_paid_by, row.old_payer_mode)} → "
                    f"{payer(row.new_paid_by, row.new_payer_mode)}"
                )
            elif field == "method":
                parts.append(
                    f"Method: {METHOD_LABELS.get(row.old_payment_method, row.old_payment_method)}"
                    f" → {METHOD_LABELS.get(row.new_payment_method, row.new_payment_method)}"
                )
        events.append(
            {
                "at": batch.created_at,
                "kind": "bulk_change",
                "by": users.get(batch.created_by),
                "text": "; ".join(parts),
                "batch_id": batch.id,
                "can_undo": can_undo(batch, now),
            }
        )
        if batch.undone_at is not None:
            events.append(
                {
                    "at": batch.undone_at,
                    "kind": "bulk_undone",
                    "by": users.get(batch.undone_by),
                    "text": "Change undone" if row.restored else "Undo left this one as it was",
                    "batch_id": batch.id,
                    "can_undo": False,
                }
            )
    return events
```

- [ ] **Step 5: Append the routes to `app/api/bulk.py`**

Add `Query` to the `fastapi` import, and `recent_batches, undo_batch` to the `app.services.bulk` import. Then append:

```python
class UndoResult(BaseModel):
    restored: int
    skipped: list[SkippedOut]
    bill_restored: bool


class RecentBatchOut(BaseModel):
    id: str
    created_at: datetime
    created_by: str | None  # display name
    summary: str
    row_count: int
    undone_at: datetime | None
    can_undo: bool


@router.get("/bulk", response_model=list[RecentBatchOut])
def recent_bulk(
    limit: int = Query(10, ge=1, le=50),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """The household's latest bulk changes, newest first ("Recent bulk changes")."""
    user, hh_id = auth
    return recent_batches(db, hh_id, limit)


@router.post("/bulk/{batch_id}/undo", response_model=UndoResult)
def undo_bulk(
    batch_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Undo a batch within 24 hours, once. Rows changed since are left as they are."""
    user, hh_id = auth
    return undo_batch(db, household_id=hh_id, user_id=user.id, batch_id=batch_id)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bulk_undo.py tests/test_bulk_api.py tests/test_bulk_rules.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/bulk_rules.py app/services/bulk.py app/api/bulk.py tests/test_bulk_undo.py
git commit -m "feat(bulk): undo within 24 hours, recent bulk changes, bulk history events"
```

---

### Task 5: Select by filter, and "Keep both" for duplicates

**Stream:** B1. **Depends on:** Task 4, and **Task 7** (B2's `app/services/transaction_filter.py`).

> **Precondition.** Bring Task 7's commit onto this branch before you start: `git cherry-pick <Task 7 sha>` (find it with `git log feat/2c-b2 --oneline -- app/services/transaction_filter.py`). The file is new and owned by B2, so the later merge of B2 into B1 is a no-op for it. **Never edit `transaction_filter.py` on this branch.** If the filter needs a change, make it in B2 and cherry-pick again.

**Files:**
- Modify: `app/services/bulk.py` (`Selection.filter`, `_selected_query`, `dismiss_duplicates`), `app/api/bulk.py` (`SelectIn.filter`, `DismissIn`, `POST /duplicates/dismiss`), `app/services/duplicates.py` (append `drop_dismissed`)
- Test: `tests/test_bulk_filter.py`

**Interfaces:**
- Consumes:
  - Task 7's `TransactionFilter` (with `is_empty() -> bool`), `StrictTransactionFilter` (same fields, `extra="forbid"`), and `apply_filter(q, f, db, household_id) -> Query` (raises 400 on bad values);
  - `find_household_duplicates(db, hh) -> list[{"amount", "transactions"}]`.
- Produces:
  - `Selection(ids=None, filter=None, bill_id=None)` with `kind` returning `"ids" | "filter" | "bill"`;
  - `dismiss_duplicates(db, *, household_id, user_id, ids: list[str]) -> None`;
  - `app.services.duplicates.drop_dismissed(db, household_id, groups) -> list[dict]` (Task 10 uses it);
  - HTTP `POST /api/v1/transactions/duplicates/dismiss` `{ids: [2..20]}` → 204.

- [ ] **Step 1: Write the failing tests**

`tests/test_bulk_filter.py`:

```python
"""Bulk by filter (2c spec §5.3 select.filter; §9 items 1 and 9) and
"Keep both" (§5.2 duplicates/dismiss)."""

from decimal import Decimal

from app.models import BulkBatch, DuplicateDismissal, Transaction, TransactionType
from app.services.duplicates import drop_dismissed, find_household_duplicates
from tests.bulk_fixtures import env  # noqa: F401
from tests.test_api import api  # noqa: F401

DISMISS = "/api/v1/transactions/duplicates/dismiss"


def test_filter_selects_what_the_feed_filter_matches(env, db):  # noqa: F811
    a = env.add("38.90", notes="Cosmote October")
    b = env.add("38.90", merchant="COSMOTE")
    other = env.add("12.00", notes="Bakery")
    body = env.bulk({"filter": {"q": "cosmote"}}, {"bucket_id": env.bills}, dry_run=True).json()
    assert body["matched"] == 2
    r = env.bulk({"filter": {"q": "cosmote"}}, {"bucket_id": env.bills}, expected_count=2)
    assert r.status_code == 200, r.text
    assert env.row(a).bucket_id == env.bills and env.row(b).bucket_id == env.bills
    assert env.row(other).bucket_id == env.day
    assert db.query(BulkBatch).one().selection == "filter"


def test_r01_filter_never_touches_another_household(env, db, make_household):  # noqa: F811
    other = make_household(name="Other", username="other")
    theirs = Transaction(
        household_id=other.household_id,
        bucket_id=other.bucket_id,
        amount=Decimal("38.90"),
        type=TransactionType.expense,
        notes="Cosmote October",
        transaction_date=env.today,
    )
    db.add(theirs)
    db.commit()
    mine = env.add("38.90", notes="Cosmote October")
    body = env.bulk({"filter": {"q": "Cosmote"}}, {"category_id": env.utilities}).json()
    assert body["matched"] == 1
    assert env.row(mine).category_id == env.utilities
    assert env.row(theirs.id).category_id is None


def test_filter_limits_and_errors(env, db):  # noqa: F811
    assert env.bulk({"filter": {}}, {"bucket_id": env.bills}).status_code == 400
    assert env.bulk({"filter": {"bucket": env.day}}, {"bucket_id": env.bills}).status_code == 422
    assert env.bulk({"filter": {"from_date": "07/10"}}, {"bucket_id": env.bills}).status_code == 400

    env.add("5.00", notes="lunch")
    drift = env.bulk({"filter": {"q": "lunch"}}, {"bucket_id": env.bills}, expected_count=3)
    assert drift.status_code == 409 and db.query(BulkBatch).count() == 0

    db.add_all(
        Transaction(
            household_id=env.hid,
            bucket_id=env.day,
            amount=Decimal("1.00"),
            type=TransactionType.expense,
            notes="bulk seed",
            transaction_date=env.today,
        )
        for _ in range(1001)
    )
    db.commit()
    big = env.bulk({"filter": {"q": "bulk seed"}}, {"bucket_id": env.bills}, dry_run=True)
    assert big.status_code == 400 and "Narrow the filter" in big.json()["detail"]


def test_dismiss_stores_every_pair_once(env, db):  # noqa: F811
    a, b, c = env.add("9.99"), env.add("9.99"), env.add("9.99")
    r = env.client.post(DISMISS, headers=env.headers, json={"ids": [c, a, b]})
    assert r.status_code == 204, r.text
    pairs = {(d.first_id, d.second_id) for d in db.query(DuplicateDismissal)}
    lo, mid, hi = sorted([a, b, c])
    assert pairs == {(lo, mid), (lo, hi), (mid, hi)}


def test_dismiss_is_idempotent(env, db):  # noqa: F811
    a, b = env.add("9.99"), env.add("9.99")
    for _ in range(2):
        assert env.client.post(DISMISS, headers=env.headers, json={"ids": [a, b]}).status_code == 204
    assert db.query(DuplicateDismissal).count() == 1


def test_dismiss_refuses_foreign_inactive_and_single_ids(env, db, make_household):  # noqa: F811
    from app.core.clock import utcnow_naive

    other = make_household(name="Other", username="other")
    theirs = Transaction(
        household_id=other.household_id,
        bucket_id=other.bucket_id,
        amount=Decimal("9.99"),
        type=TransactionType.expense,
        transaction_date=env.today,
    )
    db.add(theirs)
    db.commit()
    a = env.add("9.99")
    gone = env.add("9.99", deleted_at=utcnow_naive())

    def post(ids):
        return env.client.post(DISMISS, headers=env.headers, json={"ids": ids})

    assert post([a, theirs.id]).status_code == 404
    assert post([a, gone]).status_code == 404
    assert post([a]).status_code == 422
    assert db.query(DuplicateDismissal).count() == 0


def test_drop_dismissed_hides_a_pair_but_not_a_partly_dismissed_group(env, db):  # noqa: F811
    a, b = env.add("7.50"), env.add("7.50")
    x, y, z = env.add("4.20"), env.add("4.20"), env.add("4.20")
    env.client.post(DISMISS, headers=env.headers, json={"ids": [a, b]})
    env.client.post(DISMISS, headers=env.headers, json={"ids": [x, y]})
    groups = drop_dismissed(db, env.hid, find_household_duplicates(db, env.hid))
    assert [sorted(t.id for t in g["transactions"]) for g in groups] == [sorted([x, y, z])]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_bulk_filter.py -o addopts="" -p no:cacheprovider`
Expected: FAIL with `ImportError: cannot import name 'drop_dismissed'`.

- [ ] **Step 3: Extend `Selection` and `_selected_query` in `app/services/bulk.py`**

Add these imports: `from itertools import combinations`, `from sqlalchemy.exc import IntegrityError`, `DuplicateDismissal` (to the `app.models` list), and `from app.services.transaction_filter import TransactionFilter, apply_filter`. Then replace `Selection` and `_selected_query` with:

```python
@dataclass(frozen=True)
class Selection:
    """Exactly one of: hand-picked ids, the feed's filter, or every active
    payment of a recurring item."""

    ids: list[str] | None = None
    filter: TransactionFilter | None = None
    bill_id: str | None = None

    @property
    def kind(self) -> str:
        if self.ids is not None:
            return "ids"
        return "filter" if self.filter is not None else "bill"


def _selected_query(db: Session, hh: str, select: Selection) -> Query:
    """Active rows of the household matching a filter or bill selection."""
    q = db.query(Transaction).filter(Transaction.household_id == hh, Transaction.active())
    if select.filter is not None:
        if select.filter.is_empty():
            raise HTTPException(status_code=400, detail="Choose at least one filter.")
        return apply_filter(q, select.filter, db, hh)
    bill = _bill(db, hh, select.bill_id)
    return q.filter(Transaction.recurring_bill_id == bill.id)
```

Then append:

```python
# ---------------------------------------------------------------- duplicates


def dismiss_duplicates(db: Session, *, household_id: str, user_id: str, ids: list[str]) -> None:
    """ "Keep both": store every pair of ``ids`` (smaller id first), once, for
    the whole household. Every id must be an active transaction of it (404)."""
    wanted = sorted(set(ids))
    if len(wanted) < 2:
        raise HTTPException(status_code=400, detail="Choose at least two transactions.")
    found = {
        i
        for (i,) in db.query(Transaction.id).filter(
            Transaction.id.in_(wanted),
            Transaction.household_id == household_id,
            Transaction.active(),
        )
    }
    if len(found) != len(wanted):
        raise HTTPException(status_code=404, detail="Transaction not found")
    existing = set(
        db.query(DuplicateDismissal.first_id, DuplicateDismissal.second_id)
        .filter(DuplicateDismissal.first_id.in_(wanted), DuplicateDismissal.second_id.in_(wanted))
        .all()
    )
    for first, second in combinations(wanted, 2):
        if (first, second) not in existing:
            db.add(
                DuplicateDismissal(
                    household_id=household_id,
                    first_id=first,
                    second_id=second,
                    created_by=user_id,
                )
            )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # the other member's "Keep both" stored the same pair first
```

- [ ] **Step 4: Extend `app/api/bulk.py`**

Add `status` to the `fastapi` import, `StrictTransactionFilter` from `app.services.transaction_filter`, and `dismiss_duplicates` from `app.services.bulk`. Then change `SELECT_KEYS` and `SelectIn`:

```python
SELECT_KEYS = ("ids", "filter", "bill_id")


class SelectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None
    filter: StrictTransactionFilter | None = None
    bill_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        given = [k for k in SELECT_KEYS if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(f"select needs exactly one of: {', '.join(SELECT_KEYS)}")
        return self

    def to_selection(self) -> Selection:
        return Selection(ids=self.ids, filter=self.filter, bill_id=self.bill_id)
```

Append:

```python
class DismissIn(BaseModel):
    ids: list[str] = Field(min_length=2, max_length=20)


@router.post("/duplicates/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    body: DismissIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """ "Keep both": never show these as possible duplicates again, for anyone."""
    user, hh_id = auth
    dismiss_duplicates(db, household_id=hh_id, user_id=user.id, ids=body.ids)
```

- [ ] **Step 5: Append `drop_dismissed` to `app/services/duplicates.py`**

```python
def drop_dismissed(db: Session, household_id: str, groups: list[dict]) -> list[dict]:
    """``groups`` minus those whose every pair was dismissed ("Keep both").
    A group of three with one dismissed pair still shows."""
    from itertools import combinations

    from app.models import DuplicateDismissal

    pairs = set(
        db.query(DuplicateDismissal.first_id, DuplicateDismissal.second_id)
        .filter(DuplicateDismissal.household_id == household_id)
        .all()
    )
    return [
        g
        for g in groups
        if not all(p in pairs for p in combinations(sorted(t.id for t in g["transactions"]), 2))
    ]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_bulk_filter.py tests/test_bulk_api.py tests/test_bulk_undo.py tests/test_duplicates.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/bulk.py app/api/bulk.py app/services/duplicates.py tests/test_bulk_filter.py
git commit -m "feat(bulk): select by feed filter; Keep both for duplicate pairs"
```

---

### Task 6: Postgres proof (locks, concurrent undo, dismissal order)

**Stream:** B1. **Depends on:** Task 5.

**Files:**
- Test: `tests/test_bulk_pg.py`

**Interfaces:**
- Consumes: `tests.conftest.TEST_DATABASE_URL`, the `env` fixture, `run_bulk`, `undo_batch`.
- Produces: nothing new. This task only proves on Postgres 18 what SQLite can't (SQLite ignores `FOR UPDATE`).

- [ ] **Step 1: Write the tests**

`tests/test_bulk_pg.py`:

```python
"""Bulk changes on Postgres (2c spec §5.3): only a Postgres run proves these.

SQLite ignores FOR UPDATE, so the apply path's with_for_update(of=Transaction)
next to joinedload(Transaction.splits) and the batch lock in undo only mean
something here. Run with TEST_DATABASE_URL pointing at a disposable Postgres
(see tests/conftest.py)."""

import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models import TransactionSplit
from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.conftest import TEST_DATABASE_URL
from tests.test_api import api  # noqa: F401

pytestmark = pytest.mark.skipif(
    not (TEST_DATABASE_URL or "").startswith("postgresql"),
    reason="needs TEST_DATABASE_URL=postgresql://...",
)


def test_apply_locks_rows_with_splits_joined(env, db):  # noqa: F811
    """A plain FOR UPDATE here fails on Postgres: "FOR UPDATE cannot be applied
    to the nullable side of an outer join"."""
    shared = env.add("100.00")
    db.add_all(
        [
            TransactionSplit(transaction_id=shared, user_id=env.me, amount=Decimal("33.33")),
            TransactionSplit(transaction_id=shared, user_id=env.maria, amount=Decimal("66.66")),
        ]
    )
    db.commit()
    plain = env.add("5.00")
    r = env.bulk({"ids": [shared, plain]}, {"bucket_id": env.bills, "payer": {"mode": "own_share"}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 1 and r.json()["skipped"][0]["code"] == "no_split"
    by_filter = env.bulk({"filter": {"min_amount": "1"}}, {"category_id": env.groceries})
    assert by_filter.status_code == 200, by_filter.text


def test_concurrent_undos_one_wins(env, db):  # noqa: F811
    batch = env.bulk({"ids": [env.add(), env.add()]}, {"bucket_id": env.bills}).json()["batch_id"]
    clients = [TestClient(env.client.app), TestClient(env.client.app)]
    barrier = threading.Barrier(2)
    statuses = []

    def run(c):
        barrier.wait()
        statuses.append(c.post(f"{URL}/{batch}/undo", headers=env.headers).status_code)

    threads = [threading.Thread(target=run, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [200, 409]


def test_dismissal_order_matches_the_check(env, db):  # noqa: F811
    """Python's sorted() and Postgres' text collation must agree on "smaller
    id first", or the CHECK first_id < second_id rejects the insert."""
    ids = [env.add("3.30") for _ in range(4)]
    r = env.client.post(
        "/api/v1/transactions/duplicates/dismiss", headers=env.headers, json={"ids": ids}
    )
    assert r.status_code == 204, r.text
```

- [ ] **Step 2: Run on SQLite (skipped) and on Postgres**

Run: `.venv/bin/python -m pytest tests/test_bulk_pg.py -o addopts="" -p no:cacheprovider`
Expected: 3 skipped.

Container `pgp1` must be running: `docker start pgp1`. It publishes 55441.
Run: `TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t .venv/bin/python -m pytest tests/test_bulk_pg.py tests/test_bulk_api.py tests/test_bulk_undo.py tests/test_bulk_filter.py tests/test_bulk_migration.py -o addopts="" -p no:cacheprovider`
Expected: PASS. Postgres resets its schema per test, so don't use `-n` here.

If `test_dismissal_order_matches_the_check` fails, the database collation disagrees with Python. Fix it in `dismiss_duplicates` by ordering with the database: `select least(:a, :b), greatest(:a, :b)`. Don't relax the CHECK.

- [ ] **Step 3: Commit**

```bash
git add tests/test_bulk_pg.py
git commit -m "test(bulk): Postgres proof for row locks, concurrent undo and dismissal order"
```

---

## Stream B2: backend feed, counts, duplicates, receipt, history

### Task 7: `TransactionFilter` and `apply_filter`

**Stream:** B2. **Depends on:** nothing. **Task 5 (B1) cherry-picks this commit**, so keep it to the files listed here.

**Files:**
- Create: `app/services/transaction_filter.py`
- Test: `tests/test_activity_filter.py`

**Interfaces:**
- Consumes: `app.models` and `app.validators.parse_year_month(year, month)` (400 on bad values).
- Produces (B1 Task 5 and Task 8 use these exact names):
  - `class TransactionFilter(BaseModel)` with the fields `q, type, category_id, bucket_id, paid_by, payment_method, recurring_bill_id, from_date, to_date, min_amount, max_amount: str | None = None`, `no_bucket, missing_payer, fixed: bool = False` and `year, month: int | None = None`, plus `is_empty() -> bool`;
  - `class StrictTransactionFilter(TransactionFilter)` (`extra="forbid"`);
  - `apply_filter(q: Query, f: TransactionFilter, db: Session, household_id: str) -> Query`;
  - `maybe_number(value) -> Decimal | None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_activity_filter.py`:

```python
"""TransactionFilter (2c spec §5.1): one filter for the feed and bulk."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import (
    Bucket,
    Category,
    HouseholdMember,
    MemberRole,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.services.transaction_filter import (
    StrictTransactionFilter,
    TransactionFilter,
    apply_filter,
)

D = date(2026, 10, 6)


@pytest.fixture()
def seed(db, make_household):
    hh = make_household()
    hid = hh.household_id
    maria = User(username="maria", display_name="Maria", email="m@example.com", password_hash="x")
    db.add(maria)
    db.flush()
    db.add(HouseholdMember(household_id=hid, user_id=maria.id, role=MemberRole.member))
    outsider = make_household(name="Elsewhere", username="outsider")  # display name "Outsider"
    groceries = Category(household_id=hid, name="Groceries")
    holiday = Bucket(household_id=hid, name="Holiday")
    db.add_all([groceries, holiday])
    db.flush()

    def add(amount, **kw):
        fields = dict(
            household_id=hid,
            bucket_id=hh.bucket_id,
            amount=Decimal(amount),
            type=TransactionType.expense,
            paid_by=hh.user_id,
            payer_mode="single",
            payment_method="card",
            transaction_date=D,
        )
        fields.update(kw)
        t = Transaction(**fields)
        db.add(t)
        db.flush()
        return t.id

    ids = SimpleNamespace(
        notes=add("1.01", notes="Weekly shop"),
        merchant=add("1.02", merchant="Lidl Toumba"),
        category=add("1.03", category_id=groceries.id),
        bucket=add("1.04", bucket_id=holiday.id),
        maria=add("1.05", paid_by=maria.id),
        amount=add("42.50"),
        percent=add("1.06", notes="100% beef"),
        thousand=add("1.07", notes="1000 beef"),
        underscore=add("1.08", notes="a_b"),
        axb=add("1.09", notes="axb"),
        nobody=add("1.10", paid_by=None),
        own=add("1.11", paid_by=None, payer_mode="own_share"),
        income=add("900.00", type=TransactionType.income, bucket_id=None, paid_by=None),
        cash=add("1.12", payment_method="cash", transaction_date=date(2026, 9, 2)),
    )
    db.add(TransactionSplit(transaction_id=ids.notes, user_id=maria.id, amount=Decimal("0.50")))
    db.commit()
    return SimpleNamespace(hh=hh, hid=hid, maria=maria.id, outsider=outsider, ids=ids)


def run(db, seed, **kw) -> set[str]:
    base = db.query(Transaction).filter(
        Transaction.household_id == seed.hid, Transaction.active()
    )
    return {t.id for t in apply_filter(base, TransactionFilter(**kw), db, seed.hid)}


@pytest.mark.parametrize(
    "term,key",
    [
        ("weekly", "notes"),
        ("LIDL", "merchant"),
        ("grocer", "category"),
        ("holiday", "bucket"),
        ("maria", "maria"),
        ("42.50", "amount"),
    ],
)
def test_each_q_field_hits(db, seed, term, key):
    assert run(db, seed, q=term) == {getattr(seed.ids, key)}


def test_q_ignores_names_of_non_members(db, seed):
    assert run(db, seed, q="Outsider") == set()


def test_q_treats_like_wildcards_literally(db, seed):
    assert run(db, seed, q="100%") == {seed.ids.percent}
    assert run(db, seed, q="a_b") == {seed.ids.underscore}


def test_comma_decimals_in_q_and_amounts(db, seed):
    assert run(db, seed, q="42,50") == {seed.ids.amount}
    assert run(db, seed, min_amount="42,5", type="expense") == {seed.ids.amount}


def test_structured_filters(db, seed):
    ids = seed.ids
    assert run(db, seed, paid_by=seed.maria) == {ids.maria, ids.notes}  # payer or split holder
    assert run(db, seed, missing_payer=True) == {ids.nobody}  # own share is fully paid
    assert run(db, seed, no_bucket=True) == {ids.income}
    assert run(db, seed, payment_method="cash") == {ids.cash}
    assert run(db, seed, type="income") == {ids.income}
    assert ids.cash not in run(db, seed, from_date="2026-10-01", to_date="2026-10-31")
    assert run(db, seed, year=2026, month=9) == {ids.cash}
    assert run(db, seed, min_amount="40", max_amount="50") == {ids.amount}


@pytest.mark.parametrize(
    "kw",
    [
        {"from_date": "07/10/2026"},
        {"to_date": "2026-13-01"},
        {"from_date": "2026-10-07", "to_date": "2026-10-01"},
        {"min_amount": "abc"},
        {"max_amount": "-1"},
        {"type": "bogus"},
        {"payment_method": "cheque"},
        {"year": 2026, "month": 13},
    ],
)
def test_bad_values_are_400(db, seed, kw):
    with pytest.raises(HTTPException) as exc:
        run(db, seed, **kw)
    assert exc.value.status_code == 400


def test_is_empty_and_strict_extra():
    assert TransactionFilter().is_empty()
    assert TransactionFilter(q="  ", bucket_id="").is_empty()  # whitespace counts as blank
    assert TransactionFilter(q="").is_empty()
    assert not TransactionFilter(missing_payer=True).is_empty()
    with pytest.raises(ValueError):
        StrictTransactionFilter(bucket="x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_activity_filter.py -o addopts="" -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.transaction_filter'`.

- [ ] **Step 3: Implement `app/services/transaction_filter.py`**

```python
"""One filter for the Activity feed and for bulk-by-filter (2c spec §5.1),
so "N match" in a bulk preview is exactly the list on screen.

Dates and amounts stay strings in the model and are parsed here, so a bad
value is a 400 with a message, in a query string and a bulk body alike (a
typed Pydantic field would be FastAPI's 422).
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models import (
    Bucket,
    Category,
    HouseholdMember,
    PaymentMethod,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.validators import parse_year_month

LIKE_ESCAPE = "\\"


class TransactionFilter(BaseModel):
    """Every field optional; blank strings mean "not set"."""

    q: str | None = None
    type: str | None = None
    category_id: str | None = None
    bucket_id: str | None = None
    no_bucket: bool = False
    paid_by: str | None = None
    missing_payer: bool = False
    payment_method: str | None = None
    recurring_bill_id: str | None = None
    fixed: bool = False
    from_date: str | None = None
    to_date: str | None = None
    min_amount: str | None = None
    max_amount: str | None = None
    year: int | None = None
    month: int | None = None

    def is_empty(self) -> bool:
        return all(
            _blank(v) if not isinstance(v, bool) else not v
            for v in self.model_dump(include=set(TransactionFilter.model_fields)).values()
        )


class StrictTransactionFilter(TransactionFilter):
    """A bulk body's filter: an unknown key is a 422, never silently dropped,
    so a typo can't widen what a bulk change touches."""

    model_config = ConfigDict(extra="forbid")


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def maybe_number(value) -> Decimal | None:
    """The value as a Decimal if it reads as a finite number ("42,50" too)."""
    try:
        d = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _like(text: str) -> str:
    """A contains-pattern that matches % and _ literally."""
    for ch in (LIKE_ESCAPE, "%", "_"):
        text = text.replace(ch, LIKE_ESCAPE + ch)
    return f"%{text}%"


def _date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{label} must be a date like 2026-10-07."
        ) from None


def _amount(value: str, label: str) -> Decimal:
    d = maybe_number(value)
    if d is None or d < 0:
        raise HTTPException(status_code=400, detail=f"{label} must be a number of 0 or more.")
    return d


def apply_filter(q: Query, f: TransactionFilter, db: Session, household_id: str) -> Query:
    """``q`` narrowed by ``f``. The caller has already limited ``q`` to the
    household (and to active rows). 400 on a bad date, amount or enum value."""
    hh = household_id
    if not _blank(f.q):
        text = f.q.strip()
        term = _like(text)
        members = db.query(HouseholdMember.user_id).filter(HouseholdMember.household_id == hh)
        conditions = [
            Transaction.notes.ilike(term, escape=LIKE_ESCAPE),
            Transaction.merchant.ilike(term, escape=LIKE_ESCAPE),
            Transaction.category_id.in_(
                db.query(Category.id)
                .filter(Category.household_id == hh, Category.name.ilike(term, escape=LIKE_ESCAPE))
                .scalar_subquery()
            ),
            Transaction.bucket_id.in_(
                db.query(Bucket.id)
                .filter(Bucket.household_id == hh, Bucket.name.ilike(term, escape=LIKE_ESCAPE))
                .scalar_subquery()
            ),
            # Payer names: members of this household only.
            Transaction.paid_by.in_(
                db.query(User.id)
                .filter(
                    User.id.in_(members.scalar_subquery()),
                    User.display_name.ilike(term, escape=LIKE_ESCAPE),
                )
                .scalar_subquery()
            ),
        ]
        exact = maybe_number(text)
        if exact is not None:
            conditions.append(Transaction.amount == exact)  # "42.50" finds the amount
        q = q.filter(or_(*conditions))

    if not _blank(f.type):
        try:
            q = q.filter(Transaction.type == TransactionType(f.type))
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown transaction type '{f.type}'"
            ) from None
    if not _blank(f.payment_method):
        try:
            PaymentMethod(f.payment_method)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown payment method '{f.payment_method}'"
            ) from None
        q = q.filter(Transaction.payment_method == f.payment_method)
    if not _blank(f.category_id):
        q = q.filter(Transaction.category_id == f.category_id)
    if not _blank(f.bucket_id):
        q = q.filter(Transaction.bucket_id == f.bucket_id)
    if f.no_bucket:
        q = q.filter(Transaction.bucket_id.is_(None))
    if not _blank(f.recurring_bill_id):
        q = q.filter(Transaction.recurring_bill_id == f.recurring_bill_id)
    if f.fixed:
        # Fixed costs: expenses linked to an item, with no bucket (spec §5).
        q = q.filter(
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.is_(None),
            Transaction.recurring_bill_id.isnot(None),
        )
    if not _blank(f.paid_by):
        q = q.filter(
            or_(
                Transaction.paid_by == f.paid_by,
                Transaction.id.in_(
                    db.query(TransactionSplit.transaction_id)
                    .filter(TransactionSplit.user_id == f.paid_by)
                    .scalar_subquery()
                ),
            )
        )
    if f.missing_payer:
        # Own-share expenses have no payer by design and are fully paid.
        q = q.filter(Transaction.missing_payer(), Transaction.type == TransactionType.expense)

    start = None if _blank(f.from_date) else _date(f.from_date, "From date")
    end = None if _blank(f.to_date) else _date(f.to_date, "To date")
    if start and end and end < start:
        raise HTTPException(status_code=400, detail="The to date is before the from date.")
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)

    lo = None if _blank(f.min_amount) else _amount(f.min_amount, "Min amount")
    hi = None if _blank(f.max_amount) else _amount(f.max_amount, "Max amount")
    if lo is not None and hi is not None and hi < lo:
        raise HTTPException(status_code=400, detail="Max amount is below min amount.")
    if lo is not None:
        q = q.filter(Transaction.amount >= lo)
    if hi is not None:
        q = q.filter(Transaction.amount <= hi)

    parse_year_month(f.year, f.month)
    if f.year and f.month:
        nxt_y, nxt_m = (f.year + 1, 1) if f.month == 12 else (f.year, f.month + 1)
        q = q.filter(
            Transaction.transaction_date >= date(f.year, f.month, 1),
            Transaction.transaction_date < date(nxt_y, nxt_m, 1),
        )
    elif f.year:
        q = q.filter(
            Transaction.transaction_date >= date(f.year, 1, 1),
            Transaction.transaction_date < date(f.year + 1, 1, 1),
        )
    return q
```

`is_empty` checks only `TransactionFilter`'s own fields (the `include=` set), so Task 8's subclass with `page`/`page_size` still reads as empty when no filter is set.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_activity_filter.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit (keep this commit to these two files; B1 cherry-picks it)**

```bash
git add app/services/transaction_filter.py tests/test_activity_filter.py
git commit -m "feat(activity): TransactionFilter shared by the feed and bulk-by-filter"
```

---

### Task 8: The feed (`GET /transactions` with the filter, `day_totals` and typed rows)

**Stream:** B2. **Depends on:** Task 7.

**Files:**
- Create: `app/api/transaction_models.py`
- Modify: `app/api/transactions.py` (`list_transactions`, `get_transaction`, new helpers `_takes`, `transaction_out`, `_day_totals`)
- Test: `tests/test_activity_feed.py`

**Interfaces:**
- Consumes: Task 7's `TransactionFilter` and `apply_filter`; `app.services.money.base_amount_expr`; `app.core.money.quantize`; `app.api.planning_models.Money`.
- Produces:
  - `app.api.transaction_models`:
    - `TransactionSplitOut`;
    - `TransactionOut` (the `_txn_dict` fields plus `has_take: bool` and `missing_payer: bool`);
    - `TransactionPage {total, page, page_size, items: list[TransactionOut], day_totals: dict[str, Money]}`;
    - `CountsOut`, `DuplicateGroupOut`, `DuplicatesOut`, `HistoryEventOut` and `HistoryOut`, which Task 9 uses.
  - `app.api.transactions`:
    - `transaction_out(t: Transaction, has_take: bool) -> dict`;
    - `_takes(db, ids) -> set[str]`;
    - `FeedQuery(TransactionFilter)` with `page` and `page_size`.
  - `GET /api/v1/transactions` → `TransactionPage`, and `GET /api/v1/transactions/{txn_id}` → `TransactionOut`.

- [ ] **Step 1: Write the failing tests**

`tests/test_activity_feed.py`:

```python
"""GET /api/v1/transactions as the Activity feed (2c spec §5.1; §9 item 11)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import Transaction, TransactionType
from app.services.cash import FROM_BANK, link_take
from tests.test_api import api  # noqa: F401

URL = "/api/v1/transactions"


def add(db, hh, amount, *, days_ago=0, **kw) -> str:
    fields = dict(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=Decimal(amount),
        type=TransactionType.expense,
        paid_by=hh.user_id,
        transaction_date=local_today() - timedelta(days=days_ago),
    )
    fields.update(kw)
    t = Transaction(**fields)
    db.add(t)
    db.commit()
    return t.id


def test_rows_carry_has_take_and_missing_payer(client, db, api):  # noqa: F811
    headers, hh = api
    cash = add(db, hh, "20.00", payment_method="cash")
    link_take(db, db.get(Transaction, cash), hh.user_id, FROM_BANK, "EUR")
    db.commit()
    nobody = add(db, hh, "5.00", paid_by=None)
    body = client.get(URL, headers=headers).json()
    rows = {r["id"]: r for r in body["items"]}
    assert rows[cash]["has_take"] is True and rows[cash]["missing_payer"] is False
    assert rows[nobody]["missing_payer"] is True and rows[nobody]["has_take"] is False
    assert isinstance(rows[cash]["amount"], float) and rows[cash]["splits"] == []
    one = client.get(f"{URL}/{nobody}", headers=headers).json()
    assert one["missing_payer"] is True and one["id"] == nobody


def test_q_via_http_and_exact_amount(client, db, api):  # noqa: F811
    headers, hh = api
    hit = add(db, hh, "42.50", merchant="Cosmote")
    add(db, hh, "7.00", notes="bakery")
    assert [r["id"] for r in client.get(URL, headers=headers, params={"q": "cosmote"}).json()["items"]] == [hit]
    assert [r["id"] for r in client.get(URL, headers=headers, params={"q": "42.50"}).json()["items"]] == [hit]


def test_day_totals_are_right_across_pages(client, db, api):  # noqa: F811
    headers, hh = api
    today, yesterday = local_today(), local_today() - timedelta(days=1)
    add(db, hh, "10.00")
    add(db, hh, "5.00")
    add(db, hh, "100.00", type=TransactionType.income, bucket_id=None)
    add(db, hh, "50.00", type=TransactionType.transfer)  # transfers are excluded
    add(db, hh, "7.00", days_ago=1)
    add(db, hh, "100.00", days_ago=1, currency="USD", exchange_rate=Decimal("0.9"))

    p1 = client.get(URL, headers=headers, params={"page_size": 3, "page": 1}).json()
    p2 = client.get(URL, headers=headers, params={"page_size": 3, "page": 2}).json()
    assert p1["total"] == 6 and len(p1["items"]) == 3 and len(p2["items"]) == 3
    assert p1["day_totals"] == {today.isoformat(): 85.0}
    assert p2["day_totals"][today.isoformat()] == 85.0  # same figure on both pages
    assert p2["day_totals"][yesterday.isoformat()] == pytest.approx(-97.0)  # base currency


def test_order_and_paging_limits(client, db, api):  # noqa: F811
    headers, hh = api
    old = add(db, hh, "1.00", days_ago=3)
    new = add(db, hh, "2.00")
    ids = [r["id"] for r in client.get(URL, headers=headers).json()["items"]]
    assert ids == [new, old]
    assert client.get(URL, headers=headers, params={"page_size": 201}).status_code == 422
    assert client.get(URL, headers=headers).json()["page_size"] == 50


@pytest.mark.parametrize(
    "params",
    [
        {"from_date": "yesterday"},
        {"min_amount": "lots"},
        {"type": "bogus"},
        {"payment_method": "cheque"},
        {"year": 2026, "month": 99},
    ],
)
def test_bad_values_are_400(client, api, params):  # noqa: F811
    headers, _ = api
    assert client.get(URL, headers=headers, params=params).status_code == 400


def test_existing_drilldowns_still_work(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, occurrence=False)
    fixed = add(db, hh, "38.90", bucket_id=None, recurring_bill_id=bill.id)
    add(db, hh, "1.00")
    got = client.get(URL, headers=headers, params={"fixed": "true"}).json()["items"]
    assert [r["id"] for r in got] == [fixed]
    got = client.get(URL, headers=headers, params={"recurring_bill_id": bill.id}).json()["items"]
    assert [r["id"] for r in got] == [fixed]


def test_other_households_rows_never_show(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    add(db, other, "38.90", notes="Cosmote")
    assert client.get(URL, headers=headers, params={"q": "Cosmote"}).json()["total"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_activity_feed.py -o addopts="" -p no:cacheprovider`
Expected: FAIL. `has_take` is a KeyError, and `day_totals` is missing.

- [ ] **Step 3: Create `app/api/transaction_models.py`**

```python
"""Response models for the Activity endpoints (2c spec §5.1-5.2).

Money is a JSON number (planning_models.Money), so the generated TypeScript
types say ``number``.
"""

from datetime import date, datetime

from pydantic import BaseModel

from app.api.planning_models import Money


class TransactionSplitOut(BaseModel):
    user_id: str
    amount: Money
    is_settled: bool


class TransactionOut(BaseModel):
    id: str
    bucket_id: str | None
    household_id: str
    amount: Money
    currency: str | None
    exchange_rate: float
    type: str
    paid_by: str | None
    payer_mode: str | None
    category_id: str | None
    notes: str | None
    transaction_date: date | None
    receipt_path: str | None
    payment_method: str
    merchant: str | None
    fuel_price_per_litre: Money | None
    fuel_litres: Money | None
    exclude_from_forecast: bool
    exclude_from_settlement: bool
    recurring_bill_id: str | None
    created_at: datetime | None
    splits: list[TransactionSplitOut]
    has_take: bool  # a cash take is linked to it (swipe and bulk keep it cash)
    missing_payer: bool  # an expense with a single payer not yet recorded


class TransactionPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TransactionOut]
    # Each date on this page -> its net over the WHOLE filter (income -
    # expenses, base currency, transfers excluded), so it is right across pages.
    day_totals: dict[str, Money]


class CountsOut(BaseModel):
    no_payer: int
    duplicate_groups: int


class DuplicateGroupOut(BaseModel):
    amount: Money
    transactions: list[TransactionOut]


class DuplicatesOut(BaseModel):
    groups: list[DuplicateGroupOut]


class HistoryEventOut(BaseModel):
    at: datetime
    kind: str  # created | entry_linked | cash_taken | bulk_change | bulk_undone
    by: str | None
    text: str
    batch_id: str | None = None
    can_undo: bool = False


class HistoryOut(BaseModel):
    events: list[HistoryEventOut]
```

- [ ] **Step 4: Rewrite `list_transactions` and `get_transaction` in `app/api/transactions.py`**

Add these imports:
- `from decimal import Decimal`
- `from typing import Annotated`
- `from pydantic import Field`
- `from sqlalchemy import case, func`
- `CashMovement` and `PayerMode` (already imported) to the `app.models` list
- `from app.api.transaction_models import TransactionOut, TransactionPage`
- `from app.services.money import base_amount_expr`
- `from app.services.transaction_filter import TransactionFilter, apply_filter`

Remove the now-unused `parse_year_month` import if ruff flags it. Then add the helpers after `_txn_dict`:

```python
class FeedQuery(TransactionFilter):
    """The feed's query string: the shared filter plus paging."""

    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


def _takes(db: Session, ids: list[str]) -> set[str]:
    """Which of ``ids`` have an active linked cash take (one query)."""
    if not ids:
        return set()
    return {
        i
        for (i,) in db.query(CashMovement.transaction_id).filter(
            CashMovement.transaction_id.in_(ids), CashMovement.active()
        )
    }


def transaction_out(t: Transaction, has_take: bool) -> dict:
    d = _txn_dict(t)
    d["has_take"] = has_take
    d["missing_payer"] = (
        t.type == TransactionType.expense
        and (t.payer_mode or PayerMode.single.value) == PayerMode.single.value
        and t.paid_by is None
    )
    return d


def _day_totals(filtered, dates: list[date]) -> dict[str, Decimal]:
    """Net per date over the whole filtered set, not just this page's rows."""
    totals = {d.isoformat(): Decimal(0) for d in dates}
    if not dates:
        return totals
    signed = case(
        (Transaction.type == TransactionType.income, base_amount_expr()),
        else_=-base_amount_expr(),
    )
    rows = (
        filtered.filter(
            Transaction.type != TransactionType.transfer,
            Transaction.transaction_date.in_(dates),
        )
        .with_entities(Transaction.transaction_date, func.sum(signed))
        .group_by(Transaction.transaction_date)
        .all()
    )
    for day, total in rows:
        totals[day.isoformat()] = quantize(total)
    return totals
```

Replace `list_transactions` with this, keeping the route decorator path `""`:

```python
@router.get("", response_model=TransactionPage)
def list_transactions(
    f: Annotated[FeedQuery, Query()],
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """The Activity feed (2c spec §5.1): the shared TransactionFilter, 50 a
    page (max 200), newest first, with each shown day's net."""
    user, hh_id = auth
    filtered = apply_filter(
        db.query(Transaction).filter(Transaction.active(), Transaction.household_id == hh_id),
        f,
        db,
        hh_id,
    )
    total = filtered.count()
    items = (
        filtered.options(joinedload(Transaction.splits))
        .order_by(
            Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id
        )
        .offset((f.page - 1) * f.page_size)
        .limit(f.page_size)
        .all()
    )
    takes = _takes(db, [t.id for t in items])
    return {
        "total": total,
        "page": f.page,
        "page_size": f.page_size,
        "items": [transaction_out(t, t.id in takes) for t in items],
        "day_totals": _day_totals(filtered, sorted({t.transaction_date for t in items})),
    }
```

Change `get_transaction`'s decorator to `@router.get("/{txn_id}", response_model=TransactionOut)` and its return to `return transaction_out(txn, bool(_takes(db, [txn.id])))`.

- [ ] **Step 5: Run the tests to verify they pass, plus the existing transaction API tests**

Run: `.venv/bin/python -m pytest tests/test_activity_feed.py tests/test_activity_filter.py tests/test_api.py tests/test_transactions.py tests/test_planning_fixed_costs.py -o addopts="" -p no:cacheprovider`
Expected: PASS. The existing `test_transaction_filters_validate` still gives 400 for `type=bogus` and `month=99`.

- [ ] **Step 6: Commit**

```bash
git add app/api/transaction_models.py app/api/transactions.py tests/test_activity_feed.py
git commit -m "feat(activity): feed filter, typed rows and day totals on GET /transactions"
```

---

### Task 9: Counts, duplicates, receipt and history endpoints; regenerate types

**Stream:** B2. **Depends on:** Task 8.

**Files:**
- Create: `app/services/history.py`
- Modify: `app/api/transactions.py` (four routes; `/counts` and `/duplicates` go **above** `get_transaction`), `web/src/api/openapi.json`, `web/src/api/schema.d.ts` (generated)
- Test: `tests/test_activity_misc.py`

**Interfaces:**
- Consumes: Task 8's models, `transaction_out` and `_takes`; `find_household_duplicates(db, hh)`; `UPLOADS_DIR` in `app/api/transactions.py`.
- Produces:
  - `app.services.history.transaction_history(db, txn) -> list[dict]` (keys `at, kind, by, text, batch_id, can_undo`, newest first). Task 10 adds the bulk events.
  - HTTP:
    - `GET /api/v1/transactions/counts` → `CountsOut`;
    - `GET /api/v1/transactions/duplicates` → `DuplicatesOut`;
    - `GET /api/v1/transactions/{txn_id}/receipt` → the file;
    - `GET /api/v1/transactions/{txn_id}/history` → `HistoryOut`.
- 2c owns `GET /api/v1/transactions/{txn_id}/receipt` (API auth). 2b's receipt "View" switches to this endpoint once this task is merged.

- [ ] **Step 1: Write the failing tests**

`tests/test_activity_misc.py`:

```python
"""Counts, duplicates, receipt and history (2c spec §5.1-5.2; §9 item 11)."""

from datetime import timedelta
from decimal import Decimal

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, Transaction, TransactionType
from app.services.cash import FROM_BANK, link_take
from tests.test_api import api  # noqa: F401

URL = "/api/v1/transactions"


def add(db, hh, amount, **kw) -> str:
    fields = dict(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=Decimal(amount),
        type=TransactionType.expense,
        paid_by=hh.user_id,
        transaction_date=local_today(),
    )
    fields.update(kw)
    t = Transaction(**fields)
    db.add(t)
    db.commit()
    return t.id


def test_literal_routes_answer_before_txn_id(client, api):  # noqa: F811
    headers, _ = api
    counts = client.get(f"{URL}/counts", headers=headers)
    dups = client.get(f"{URL}/duplicates", headers=headers)
    assert counts.status_code == 200 and counts.json() == {"no_payer": 0, "duplicate_groups": 0}
    assert dups.status_code == 200 and dups.json() == {"groups": []}


def test_counts(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "5.00", paid_by=None)
    add(db, hh, "6.00", paid_by=None, payer_mode="own_share")  # fully paid by design
    add(db, hh, "7.00", paid_by=None, type=TransactionType.income, bucket_id=None)
    add(db, hh, "9.99")
    add(db, hh, "9.99", transaction_date=local_today() - timedelta(days=2))
    assert client.get(f"{URL}/counts", headers=headers).json() == {
        "no_payer": 1,
        "duplicate_groups": 1,
    }


def test_duplicates_payload(client, db, api):  # noqa: F811
    headers, hh = api
    a, b = add(db, hh, "9.99"), add(db, hh, "9.99")
    [group] = client.get(f"{URL}/duplicates", headers=headers).json()["groups"]
    assert group["amount"] == 9.99
    assert {t["id"] for t in group["transactions"]} == {a, b}
    assert {"has_take", "created_at", "merchant"} <= set(group["transactions"][0])


def test_receipt(client, db, api, make_household, tmp_path, monkeypatch):  # noqa: F811
    import app.api.transactions as module

    monkeypatch.setattr(module, "UPLOADS_DIR", str(tmp_path))
    headers, hh = api
    (tmp_path / "r1.pdf").write_bytes(b"%PDF-1.4 receipt")
    own = add(db, hh, "3.00", receipt_path="r1.pdf")
    r = client.get(f"{URL}/{own}/receipt", headers=headers)
    assert r.status_code == 200 and r.content == b"%PDF-1.4 receipt"

    other = make_household(name="Other", username="other")
    (tmp_path / "r2.pdf").write_bytes(b"%PDF-1.4 theirs")
    foreign = add(db, other, "3.00", receipt_path="r2.pdf")
    deleted = add(db, hh, "3.00", receipt_path="r1.pdf", deleted_at=utcnow_naive())
    missing = add(db, hh, "3.00", receipt_path="gone.pdf")
    none = add(db, hh, "3.00")
    for txn_id in (foreign, deleted, missing, none):
        assert client.get(f"{URL}/{txn_id}/receipt", headers=headers).status_code == 404


def test_history_created_entry_and_cash(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, occ = make_bill(hh.household_id, hh.bucket_id, name="Cosmote")
    pay = add(db, hh, "38.90", payment_method="cash", recurring_bill_id=bill.id)
    occ = db.get(BillOccurrence, occ.id)
    occ.status, occ.transaction_id = OccurrenceStatus.paid, pay
    occ.paid_at, occ.paid_by = utcnow_naive() + timedelta(seconds=1), hh.user_id
    link_take(db, db.get(Transaction, pay), hh.user_id, FROM_BANK, "EUR")
    db.commit()

    events = client.get(f"{URL}/{pay}/history", headers=headers).json()["events"]
    kinds = [e["kind"] for e in events]
    assert set(kinds) == {"created", "entry_linked", "cash_taken"}
    assert kinds[-1] == "created" and events[-1]["by"] is None  # oldest last; no "Added by"
    linked = next(e for e in events if e["kind"] == "entry_linked")
    assert linked["text"].startswith("Paid for Cosmote · ")
    assert client.get(f"{URL}/no-such/history", headers=headers).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_activity_misc.py -o addopts="" -p no:cacheprovider`
Expected: FAIL. `/counts` answers 404 "Transaction not found" until the route exists above `/{txn_id}`.

- [ ] **Step 3: Implement `app/services/history.py`**

```python
"""A transaction's history, derived from what the database already holds
(2c spec §5.2). There is no audit log and no "Added by". Task 10 adds the
bulk changes."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import BillOccurrence, CashMovement, ItemDirection, Transaction, User


def transaction_history(db: Session, txn: Transaction) -> list[dict]:
    """Events newest first: created, entry_linked, cash_taken."""
    names: dict[str, str | None] = {}

    def name(user_id):
        if not user_id:
            return None
        if user_id not in names:
            user = db.get(User, user_id)
            names[user_id] = user.display_name if user else None
        return names[user_id]

    def event(at, kind, by, text):
        return {"at": at, "kind": kind, "by": by, "text": text, "batch_id": None, "can_undo": False}

    events = [event(txn.created_at, "created", None, "Added")]
    occurrences = db.query(BillOccurrence).filter(
        BillOccurrence.transaction_id == txn.id, BillOccurrence.paid_at.isnot(None)
    )
    for occ in occurrences:
        verb = "Received for" if occ.bill.direction == ItemDirection.in_.value else "Paid for"
        text = f"{verb} {occ.bill.name} · {occ.due_date:%b %Y}"
        events.append(event(occ.paid_at, "entry_linked", name(occ.paid_by), text))
    for mv in db.query(CashMovement).filter(CashMovement.transaction_id == txn.id):
        source = "their stash" if mv.stash_owner_id else "the bank"
        text = f"Cash taken from {source}" + (" (since removed)" if mv.deleted_at else "")
        events.append(event(mv.created_at, "cash_taken", name(mv.user_id), text))
    events.sort(key=lambda e: e["at"] or datetime.min, reverse=True)
    return events
```

- [ ] **Step 4: Add the four routes to `app/api/transactions.py`**

Add these imports:
- `from fastapi.responses import FileResponse`
- `CountsOut, DuplicatesOut, HistoryOut` to the `transaction_models` import
- `from app.services.duplicates import find_household_duplicates`
- `from app.services.history import transaction_history`

Insert this block **between `create_transaction` and `get_transaction`**. The two literal GETs must come before `@router.get("/{txn_id}")`:

```python
# Literal paths: declared before /{txn_id}, or FastAPI reads "counts" as an id.


@router.get("/counts", response_model=CountsOut)
def transaction_counts(
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """The Activity chips' counts: expenses with no payer, and possible
    duplicate groups (90 days, ±3 days)."""
    user, hh_id = auth
    no_payer = (
        db.query(func.count(Transaction.id))
        .filter(
            Transaction.household_id == hh_id,
            Transaction.active(),
            Transaction.missing_payer(),
            Transaction.type == TransactionType.expense,
        )
        .scalar()
    )
    return {"no_payer": no_payer, "duplicate_groups": len(find_household_duplicates(db, hh_id))}


@router.get("/duplicates", response_model=DuplicatesOut)
def duplicate_groups(
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Possible duplicates over the last 90 days (find_household_duplicates)."""
    user, hh_id = auth
    groups = find_household_duplicates(db, hh_id)
    takes = _takes(db, [t.id for g in groups for t in g["transactions"]])
    return {
        "groups": [
            {
                "amount": g["amount"],
                "transactions": [transaction_out(t, t.id in takes) for t in g["transactions"]],
            }
            for g in groups
        ]
    }
```

Append after `upload_receipt`:

```python
@router.get("/{txn_id}/receipt", response_class=FileResponse)
def get_receipt(
    txn_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """The receipt file, with API auth (the old /transactions/files/ uses the
    old app's cookie). 404 for no receipt, deleted, another household or a
    missing file."""
    user, hh_id = auth
    txn = (
        db.query(Transaction)
        .filter(Transaction.active())
        .filter_by(id=txn_id, household_id=hh_id)
        .first()
    )
    if txn is None or not txn.receipt_path:
        raise HTTPException(status_code=404, detail="Receipt not found")
    path = Path(UPLOADS_DIR) / Path(txn.receipt_path).name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Receipt not found")
    return FileResponse(str(path))


@router.get("/{txn_id}/history", response_model=HistoryOut)
def get_history(
    txn_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    txn = (
        db.query(Transaction)
        .filter(Transaction.active())
        .filter_by(id=txn_id, household_id=hh_id)
        .first()
    )
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"events": transaction_history(db, txn)}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_activity_misc.py tests/test_activity_feed.py tests/test_duplicates.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Regenerate the web types**

Run: `cd web && npm run gen:api && npm run typecheck`
Expected: `schema.d.ts` now has `TransactionPage`, `TransactionOut`, `CountsOut`, `DuplicatesOut` and `HistoryOut`, and typecheck passes.

- [ ] **Step 7: Commit**

```bash
git add app/services/history.py app/api/transactions.py tests/test_activity_misc.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(activity): counts, duplicates, receipt and history endpoints"
```

---

## Join: B1 + B2

### Task 10: Dismissed pairs in the duplicates endpoints, and bulk events in history

**Stream:** B1, after B2 is merged into it. **Depends on:** Tasks 5–6 (B1) and Tasks 7–9 (B2).

> **Precondition.** On `feat/2c-b1`, run `git merge feat/2c-b2`. `transaction_filter.py` merges cleanly because it was cherry-picked. If `web/src/api/openapi.json` or `schema.d.ts` conflict, take either side; Step 4 regenerates them.

**Files:**
- Modify: `app/api/transactions.py` (`transaction_counts`, `duplicate_groups`), `app/services/history.py`, `web/src/api/openapi.json`, `web/src/api/schema.d.ts`
- Test: `tests/test_activity_join.py`

**Interfaces:**
- Consumes: Task 5's `drop_dismissed(db, hh, groups)`, Task 4's `bulk_history_events(db, hh, txn_id)`, and Task 9's routes and `transaction_history`.
- Produces: `GET /duplicates` and `/counts` hide dismissed groups, and history includes `bulk_change` (with `can_undo`) and `bulk_undone`. The OpenAPI types now carry every 2c endpoint, which F2 needs.

- [ ] **Step 1: Write the failing tests**

`tests/test_activity_join.py`:

```python
"""B1 x B2: Keep both hides pairs from the feed's duplicates and counts;
a transaction's history shows its bulk changes (2c spec §5.2, §9 item 11)."""

from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.test_api import api  # noqa: F401

TXNS = "/api/v1/transactions"


def test_dismissed_pair_is_hidden_but_partly_dismissed_group_shows(env):  # noqa: F811
    a, b = env.add("7.50"), env.add("7.50")
    x, y, z = env.add("4.20"), env.add("4.20"), env.add("4.20")
    get = lambda path: env.client.get(f"{TXNS}/{path}", headers=env.headers).json()  # noqa: E731
    assert get("counts")["duplicate_groups"] == 2
    env.client.post(f"{TXNS}/duplicates/dismiss", headers=env.headers, json={"ids": [a, b]})
    env.client.post(f"{TXNS}/duplicates/dismiss", headers=env.headers, json={"ids": [x, y]})
    groups = get("duplicates")["groups"]
    assert [sorted(t["id"] for t in g["transactions"]) for g in groups] == [sorted([x, y, z])]
    assert get("counts")["duplicate_groups"] == 1


def test_counts_duplicates_and_bulk_are_not_read_as_ids(env):  # noqa: F811
    for path in ("counts", "duplicates", "bulk"):
        r = env.client.get(f"{TXNS}/{path}", headers=env.headers)
        assert r.status_code == 200, (path, r.text)


def test_history_shows_bulk_change_with_undo_then_undone(env):  # noqa: F811
    a = env.add()
    batch = env.bulk({"ids": [a]}, {"bucket_id": env.bills}).json()["batch_id"]
    events = env.client.get(f"{TXNS}/{a}/history", headers=env.headers).json()["events"]
    change = next(e for e in events if e["kind"] == "bulk_change")
    assert change["batch_id"] == batch and change["can_undo"] is True
    assert change["text"] == "Bucket: Day to day → Bills"
    env.client.post(f"{URL}/{batch}/undo", headers=env.headers)
    events = env.client.get(f"{TXNS}/{a}/history", headers=env.headers).json()["events"]
    assert events[0]["kind"] == "bulk_undone"
    assert next(e for e in events if e["kind"] == "bulk_change")["can_undo"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_activity_join.py -o addopts="" -p no:cacheprovider`
Expected: FAIL. The dismissed group still shows, and history has no `bulk_change`.

- [ ] **Step 3: Wire them in**

In `app/api/transactions.py`, import `drop_dismissed` alongside `find_household_duplicates`, and in **both** `transaction_counts` and `duplicate_groups` replace `find_household_duplicates(db, hh_id)` with:

```python
drop_dismissed(db, hh_id, find_household_duplicates(db, hh_id))
```

In `app/services/history.py`, add `from app.services.bulk import bulk_history_events` and insert this line just before the `events.sort(...)` line:

```python
    events.extend(bulk_history_events(db, txn.household_id, txn.id))
```

Update the module docstring's last sentence to say the bulk changes come from `app.services.bulk`.

- [ ] **Step 4: Run the tests, then regenerate the types**

Run: `.venv/bin/python -m pytest tests/test_activity_join.py tests/test_activity_misc.py tests/test_bulk_filter.py tests/test_bulk_undo.py -o addopts="" -p no:cacheprovider`
Expected: PASS.

Run: `cd web && npm run gen:api && npm run typecheck`
Expected: `schema.d.ts` has `BulkIn`, `BulkResult`, `UndoResult`, `RecentBatchOut` and `DismissIn`, and typecheck passes.

- [ ] **Step 5: Commit**

```bash
git add app/api/transactions.py app/services/history.py tests/test_activity_join.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(activity): hide dismissed duplicate pairs; bulk changes in history"
```

---

## Stream F1: frontend feed, swipe, detail, duplicates

**Precondition for every F1 task:** 2a stream A is merged into this branch, so `web/src/ui/` (kit plus `ui.css`), `web/src/data/cachedQuery.ts`, `data/action.ts` and `data/keys.ts` exist, and Task 9's regenerated `schema.d.ts` is present (merge B2 first).

**The 2a/2b contract this stream codes against.** These are 2a's real Stream A exports (the "Stream A exports" section of `2026-10-07-phase-2a-plan-home.md`). 2a stream A is merged first, so every name below exists. This plan only adds to `data/keys.ts` (Task 12) and never renames or edits a 2a file.

```ts
// web/src/data/cachedQuery.ts
useCachedQuery<T>(key: QueryKey, fetcher: (signal: AbortSignal) => Promise<T>, opts?: { enabled?: boolean }): CachedQuery<T>
interface CachedQuery<T> { data: T | undefined; dataUpdatedAt: number; fromCache: boolean; isLoading: boolean;
  isError: boolean; offline: boolean; stale: boolean; noData: boolean; refetch(): void }
// web/src/data/action.ts
useAction<V = void, T = unknown>(spec: ActionSpec<V, T>): { run(vars: V): Promise<ActionResult<T>>; busy: boolean }
// ActionSpec<V, T> = { method: 'POST'|'PUT'|'PATCH'|'DELETE'; path: string | ((v: V) => string);
//   body?: unknown | ((v: V) => unknown); optimistic?(qc, v): void; invalidates: readonly QueryKey[];
//   pendingId?: string | ((v: V) => string | undefined); toastRejections?: boolean }
// ActionResult<T> = { status: 'done'; data: T } | { status: 'queued' } | { status: 'rejected'; code: number; detail: string }
// `run` never throws. Rollback is automatic: it restores every query under the `invalidates` prefixes,
// so `optimistic` returns nothing and must patch only inside those prefixes.
// web/src/data/http.ts: unwrap(p), class ApiError { status; detail }, detailOf(error, status?)
// web/src/data/online.ts: useOnline(), isOnline()
// web/src/data/keys.ts: keys, affects (see 2a A5; Task 12 adds to it)
// web/src/data/reads.ts: useHousehold(), useRecurringItems(), useBuckets(), useCategories(), memberName(m)
// web/src/ui: <Sheet open onClose title closeOnBackdrop? footer? initialFocus?>, <ListRow title subtitle? leading? trailing?
//   badges? onClick? muted? ariaLabel?> and <List label?>, <Badge tone? icon?>{text}</Badge>, <Money amount={number|null} currency? signed?
//   whole? estimated? tone? nullText?>, <ProgressBar value max label tone? thin?>, <Segmented label options value onChange>,
//   <QueryView result={CachedQuery<T>} noDataText>, <EmptyState>, <OfflineBanner>,
//   toast(message, { action?: {label, onClick}, durationMs?, tone? }), dismissToast(), useToast(): { show, dismiss }, <Toaster />
// web/src/test: fakeApi(routes) with "METHOD /path" keys (calls, callsTo(route), on, down, up), reply(status, body?),
//   renderWithProviders(ui, { route?, client? }), setOnline(bool), resetTestEnv(), fixtures (txn, page, bucket, category,
//   household, member, readRoutes, ...)
// web/src/features/composer/hooks.ts (2b §5.3): usePendingTransactions(): PendingTxn[]
```

### Task 11: Kit additions (Chip, SearchField, Check, SwipeRow)

**Stream:** F1. **Depends on:** 2a stream A.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** Visual source: `docs/redesign/mocks/access-home.html` §03 (`.chip`, `.check`, `.daygroup`) on `components.css`.

**Files:**
- Create: `web/src/ui/Chip.tsx`, `web/src/ui/SearchField.tsx`, `web/src/ui/Check.tsx`, `web/src/ui/SwipeRow.tsx`, `web/src/ui/ui-2c.css`
- Test: `web/src/ui/Chip.test.tsx`, `web/src/ui/SearchField.test.tsx`, `web/src/ui/SwipeRow.test.tsx`

**Interfaces:**
- Produces:
  - `Chip({label, pressed?, count?, disabled?, onClick?})`;
  - `SearchField({value, onChange, placeholder?, label?})` with `SEARCH_DEBOUNCE_MS = 250`;
  - `Check({checked})`;
  - `SwipeRow({children, onDelete?, onCopy?, onLongPress?, disabled?})` with `SWIPE_THRESHOLD = 0.4` and `LONG_PRESS_MS = 500`.
- Kit components have no data access (2a §3).

- [ ] **Step 1: Write the failing tests**

`web/src/ui/Chip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Chip } from './Chip'

describe('Chip', () => {
  it('exposes its state with aria-pressed and shows the count', async () => {
    const onClick = vi.fn()
    render(<Chip label="No payer" count={3} pressed onClick={onClick} />)
    const chip = screen.getByRole('button', { name: /no payer 3/i })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(chip)
    expect(onClick).toHaveBeenCalledOnce()
  })
})
```

If `@testing-library/user-event` isn't installed, add it: `npm i -D @testing-library/user-event`.

`web/src/ui/SearchField.test.tsx`:

```tsx
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SEARCH_DEBOUNCE_MS, SearchField } from './SearchField'

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('SearchField', () => {
  it('debounces typing by 250 ms', () => {
    const onChange = vi.fn()
    render(<SearchField value="" onChange={onChange} />)
    const input = screen.getByRole('searchbox', { name: 'Search transactions' })
    fireEvent.change(input, { target: { value: 'cosm' } })
    fireEvent.change(input, { target: { value: 'cosmote' } })
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1))
    expect(onChange).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(1))
    expect(onChange).toHaveBeenCalledExactlyOnceWith('cosmote')
  })

  it('clears at once', () => {
    const onChange = vi.fn()
    render(<SearchField value="lidl" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
    expect(onChange).toHaveBeenCalledWith('')
  })
})
```

`web/src/ui/SwipeRow.test.tsx`:

```tsx
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { LONG_PRESS_MS, SwipeRow } from './SwipeRow'

beforeAll(() => {
  // jsdom: no PointerEvent, no layout. Give rows a 300 px width.
  if (!('PointerEvent' in window)) {
    class PE extends MouseEvent {
      pointerId: number
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init)
        this.pointerId = init.pointerId ?? 1
      }
    }
    Object.assign(window, { PointerEvent: PE })
  }
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 300 })
})
afterEach(() => vi.useRealTimers())

function drag(el: HTMLElement, fromX: number, toX: number) {
  fireEvent.pointerDown(el, { clientX: fromX, clientY: 10, pointerId: 1 })
  fireEvent.pointerMove(el, { clientX: toX, clientY: 12, pointerId: 1 })
  fireEvent.pointerUp(el, { clientX: toX, clientY: 12, pointerId: 1 })
}

function setup(extra = {}) {
  const props = { onDelete: vi.fn(), onCopy: vi.fn(), onLongPress: vi.fn(), ...extra }
  render(<SwipeRow {...props}><span>Cosmote</span></SwipeRow>)
  return { props, row: screen.getByText('Cosmote').parentElement as HTMLElement }
}

describe('SwipeRow', () => {
  it('deletes past 40% to the left, copies past 40% to the right', () => {
    const { props, row } = setup()
    drag(row, 250, 100) // -150 px = 50%
    expect(props.onDelete).toHaveBeenCalledOnce()
    drag(row, 50, 200)
    expect(props.onCopy).toHaveBeenCalledOnce()
  })

  it('does nothing under the threshold', () => {
    const { props, row } = setup()
    drag(row, 250, 160) // -90 px = 30%
    expect(props.onDelete).not.toHaveBeenCalled()
  })

  it('is never the only path: Delete and Copy are real buttons', () => {
    const { props } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(props.onDelete).toHaveBeenCalledOnce()
    expect(props.onCopy).toHaveBeenCalledOnce()
  })

  it('long-press of 500 ms enters selection; moving cancels it', () => {
    vi.useFakeTimers()
    const { props, row } = setup()
    fireEvent.pointerDown(row, { clientX: 10, clientY: 10, pointerId: 1 })
    act(() => vi.advanceTimersByTime(LONG_PRESS_MS))
    expect(props.onLongPress).toHaveBeenCalledOnce()
    fireEvent.pointerUp(row)
    fireEvent.pointerDown(row, { clientX: 10, clientY: 10, pointerId: 2 })
    fireEvent.pointerMove(row, { clientX: 40, clientY: 10, pointerId: 2 })
    act(() => vi.advanceTimersByTime(LONG_PRESS_MS))
    expect(props.onLongPress).toHaveBeenCalledOnce()
  })

  it('a disabled row (queued create) has no actions', () => {
    setup({ disabled: true })
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/ui/Chip.test.tsx src/ui/SearchField.test.tsx src/ui/SwipeRow.test.tsx`
Expected: FAIL. The modules don't exist.

- [ ] **Step 3: Implement the components**

`web/src/ui/Chip.tsx`:

```tsx
import './ui-2c.css'

type Props = { label: string; pressed?: boolean; count?: number; disabled?: boolean; onClick?: () => void }

export function Chip({ label, pressed = false, count, disabled, onClick }: Props) {
  return (
    <button type="button" className={pressed ? 'chip on' : 'chip'} aria-pressed={pressed} disabled={disabled} onClick={onClick}>
      <span>{label}</span>
      {count !== undefined && <span className="count">{count}</span>}
    </button>
  )
}
```

`web/src/ui/SearchField.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react'
import './ui-2c.css'

export const SEARCH_DEBOUNCE_MS = 250

type Props = { value: string; onChange: (value: string) => void; placeholder?: string; label?: string }

export function SearchField({ value, onChange, placeholder = 'Search', label = 'Search transactions' }: Props) {
  const [text, setText] = useState(value)
  const sent = useRef(value)

  useEffect(() => {
    if (value !== sent.current) {
      sent.current = value
      setText(value)
    }
  }, [value])

  useEffect(() => {
    if (text === sent.current) return
    const t = setTimeout(() => {
      sent.current = text
      onChange(text)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [text, onChange])

  return (
    <div className="search" role="search">
      <input
        type="search"
        inputMode="search"
        enterKeyHint="search"
        autoComplete="off"
        aria-label={label}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {text && (
        <button
          type="button"
          className="search__clear"
          aria-label="Clear search"
          onClick={() => {
            sent.current = ''
            setText('')
            onChange('')
          }}
        >
          ×
        </button>
      )}
    </div>
  )
}
```

`web/src/ui/Check.tsx`:

```tsx
import './ui-2c.css'

/** The selection tick. Decorative: the row carries aria-selected. */
export function Check({ checked }: { checked: boolean }) {
  return (
    <span className={checked ? 'check on' : 'check'} aria-hidden="true">
      {checked && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M5 12l5 5 9-10" /></svg>
      )}
    </span>
  )
}
```

`web/src/ui/SwipeRow.tsx`:

```tsx
import { type PointerEvent, type ReactNode, useRef, useState } from 'react'
import './ui-2c.css'

export const SWIPE_THRESHOLD = 0.4
export const LONG_PRESS_MS = 500
const SLOP = 8 // px of movement before a press becomes a drag

type Props = {
  children: ReactNode
  onDelete?: () => void
  onCopy?: () => void
  onLongPress?: () => void
  disabled?: boolean
}

/** A ListRow wrapper: swipe left to delete, right to copy, long-press to
 * select. The revealed buttons are real, focusable buttons, so swipe is
 * never the only path (spec §7). */
export function SwipeRow({ children, onDelete, onCopy, onLongPress, disabled }: Props) {
  const content = useRef<HTMLDivElement>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const dxRef = useRef(0)
  const press = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [dx, setDx] = useState(0)

  const cancelPress = () => {
    clearTimeout(press.current)
    press.current = undefined
  }
  const reset = () => {
    cancelPress()
    start.current = null
    dxRef.current = 0
    setDx(0)
  }

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled) return
    start.current = { x: e.clientX, y: e.clientY }
    if (onLongPress) {
      press.current = setTimeout(() => {
        reset()
        onLongPress()
      }, LONG_PRESS_MS)
    }
  }
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const s = start.current
    if (!s) return
    const mx = e.clientX - s.x
    const my = e.clientY - s.y
    if (Math.abs(mx) > SLOP || Math.abs(my) > SLOP) cancelPress()
    if (Math.abs(mx) > SLOP && Math.abs(mx) > Math.abs(my)) {
      content.current?.setPointerCapture?.(e.pointerId)
      dxRef.current = mx
      setDx(mx)
    }
  }
  const up = () => {
    const moved = dxRef.current
    const width = content.current?.offsetWidth || 1
    const wasDragging = start.current !== null
    reset()
    if (!wasDragging) return
    if (moved / width <= -SWIPE_THRESHOLD) onDelete?.()
    else if (moved / width >= SWIPE_THRESHOLD) onCopy?.()
  }

  return (
    <div className="swipe">
      {!disabled && (onDelete || onCopy) && (
        <div className="swipe__actions">
          {onCopy && <button type="button" className="swipe__copy" onClick={onCopy}>Copy</button>}
          {onDelete && <button type="button" className="swipe__delete" onClick={onDelete}>Delete</button>}
        </div>
      )}
      <div
        ref={content}
        className="swipe__content"
        data-dragging={dx !== 0 || undefined}
        style={dx ? { transform: `translateX(${dx}px)` } : undefined}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={reset}
        onContextMenu={(e) => onLongPress && e.preventDefault()}
      >
        {children}
      </div>
    </div>
  )
}
```

`web/src/ui/ui-2c.css` holds only what 2a's `ui.css` lacks. If `.chip`/`.chips` are already ported from `components.css`, delete the duplicates here and keep the hit-area rule:

```css
/* 2c kit additions on tokens.css (mock: access-home.html §03). */
.chip { position: relative; min-height: 32px; }
.chip::before { content: ''; position: absolute; inset: -6px -2px; } /* 44 pt hit area */
.chip .count { font-family: var(--font-num); font-variant-numeric: tabular-nums; opacity: .7; }
.chip:disabled { opacity: .4; }

.search { position: relative; display: flex; align-items: center; }
.search input {
  flex: 1; height: 44px; padding: 0 40px 0 14px; border-radius: var(--r-md);
  border: 1px solid var(--line); background: var(--surface); color: var(--ink);
  font: 500 16px/1 var(--font-body); /* 16px: no zoom on iOS focus */
}
.search input::-webkit-search-cancel-button { display: none; }
.search__clear { position: absolute; right: 2px; width: 44px; height: 44px; border: 0; background: none; color: var(--muted); font-size: 20px; }

.check { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--line); flex: none; display: grid; place-items: center; }
.check.on { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
.check svg { width: 14px; height: 14px; stroke-width: 3; }

.swipe { position: relative; overflow: hidden; border-radius: var(--r-md); }
.swipe__actions { position: absolute; inset: 0; display: flex; justify-content: space-between; visibility: hidden; }
.swipe:focus-within .swipe__actions, .swipe__content[data-dragging] + .swipe__actions { visibility: visible; }
.swipe__content[data-dragging] { touch-action: pan-y; }
.swipe__actions button { min-width: 88px; min-height: 44px; border: 0; font-weight: 650; }
.swipe__copy { background: var(--accent-soft); color: var(--ink); }
.swipe__delete { margin-left: auto; background: var(--neg); color: #fff; }
.swipe__content { position: relative; background: var(--surface); touch-action: pan-y; -webkit-user-select: none; user-select: none; -webkit-touch-callout: none; }
.swipe__content:not([data-dragging]) { transition: transform 220ms cubic-bezier(.2, .8, .2, 1); }
@media (prefers-reduced-motion: reduce) { .swipe__content { transition: none !important; } }

.daygroup { display: flex; justify-content: space-between; font-size: 12.5px; font-weight: 600; color: var(--muted); padding: 12px 2px 6px; }
.daygroup .num { font-family: var(--font-num); font-variant-numeric: tabular-nums; }
```

The actions sit under the content. Show them whenever a drag is in progress by setting `data-dragging` on `.swipe` instead, if the sibling selector above doesn't match your DOM order. Keep the focus-within reveal either way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/ui/Chip.test.tsx src/ui/SearchField.test.tsx src/ui/SwipeRow.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui/Chip.tsx web/src/ui/SearchField.tsx web/src/ui/Check.tsx web/src/ui/SwipeRow.tsx web/src/ui/ui-2c.css web/src/ui/*.test.tsx web/package.json web/package-lock.json
git commit -m "feat(ui): Chip, SearchField, Check, SwipeRow; toast action"
```

---

### Task 12: Activity data layer (keys, URL filters, hooks, formatting)

**Stream:** F1. **Depends on:** Task 11, plus B2's generated types (Task 9).

**Files:**
- Modify: `web/src/data/keys.ts` (additions)
- Create: `web/src/features/activity/filters.ts`, `hooks.ts`, `pending.ts`, `format.ts`, `testing.tsx`
- Test: `web/src/features/activity/filters.test.ts`, `format.test.ts`, `hooks.test.ts`

**Interfaces:**
- Consumes: `api` (`web/src/api/client.ts`), `components['schemas']` from `web/src/api/schema.d.ts`, and 2a's `useCachedQuery`, `useAction`, `keys`, `affects`, `unwrap`, `ApiError`, `useOnline`, `useHousehold`, `useCategories` and `useRecurringItems` (no local copies).
- Produces (Tasks 13–20 use these exact names):
  - `filters.ts`:
    - the types `TransactionFilter` and `FeedState = {filter, dups}`;
    - `fromSearch(params, today?)`, `toSearch(state)`, `toQuery(filter)`, `isEmpty(filter)`, `monthRange(date)`, `monthLabel(filter)`, `activeFilterCount(filter)`, `toggle(filter, patch)`.
  - `hooks.ts`:
    - the types `Txn`, `TxnPage`, `Counts`, `DuplicateGroup`, `HistoryEvent`, `RefData`, `TxnPatch`;
    - `PAGE_SIZE = 50`, `OFFLINE_MESSAGE`, `ACTIVITY_WRITES`;
    - the hooks `useFeedPage(filter, page)`, `useCounts()`, `useDuplicates()`, `useTransaction(id)`, `useHistory(id)`, `useRefData()`, `useEditTransaction()`, `useDeleteTransaction()`;
    - `editBody(txn, patch)`, `receiptUrl(id)`, `uploadReceipt(id, file)`, `online(call)`. (`ApiError` and `unwrap` are 2a's, from `data/http`; `useOnline` is 2a's, from `data/online`.)
  - `pending.ts`: `usePendingTransactions(): PendingTxn[]` (2b's, or `[]` until 2b lands) and the type `PendingTxn = Txn & { pending: true }`.
  - `format.ts`: `dayLabel(iso, today?)`, `groupByDay(rows, dayTotals)`, `gapLabel(a, b)`, `rowTitle(t, ref)`, `rowSubtitle(t, ref)`, `METHOD_LABELS`.
  - `testing.tsx`: `renderActivity(ui, {route, path})` (a thin wrapper over 2a's `renderWithProviders`) and the fixtures `makeTxn`, `pageOf`, `refRoutes`, `REF`. Route stubs use 2a's `fakeApi` with "METHOD /path" keys.

- [ ] **Step 1: Write the failing tests**

`web/src/features/activity/filters.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { activeFilterCount, type FeedState, fromSearch, monthLabel, toQuery, toSearch } from './filters'

const TODAY = new Date(2026, 9, 7) // 7 Oct 2026
const OCT = { from_date: '2026-10-01', to_date: '2026-10-31' }

describe('filters', () => {
  it.each<FeedState>([
    { filter: { ...OCT }, dups: false },
    { filter: {}, dups: false }, // All time
    { filter: {}, dups: true },
    { filter: { q: 'cosmote', missing_payer: true }, dups: false },
    {
      filter: {
        type: 'expense', category_id: 'c', bucket_id: 'b', paid_by: 'u', payment_method: 'cash',
        recurring_bill_id: 'r', from_date: '2026-09-01', to_date: '2026-09-15', min_amount: '10', max_amount: '99.5',
      },
      dups: false,
    },
    { filter: { no_bucket: true, fixed: true }, dups: false },
  ])('round-trips %j through the URL', (state) => {
    expect(fromSearch(toSearch(state), TODAY)).toEqual(state)
  })

  it('opens plain /activity on this month', () => {
    expect(fromSearch(new URLSearchParams(''), TODAY)).toEqual({ filter: OCT, dups: false })
  })

  it('treats a deep link with its own filter as all time', () => {
    expect(fromSearch(new URLSearchParams('recurring_bill_id=r1'), TODAY).filter).toEqual({ recurring_bill_id: 'r1' })
  })

  it('drops unknown enum values and blanks', () => {
    expect(fromSearch(new URLSearchParams('type=bogus&q=%20&all=1'), TODAY).filter).toEqual({})
  })

  it('sends the API names, flags as true', () => {
    expect(toQuery({ q: 'x', missing_payer: true, ...OCT })).toEqual({ q: 'x', missing_payer: true, ...OCT })
  })

  it('counts Filters-sheet fields, not the month or the search', () => {
    expect(activeFilterCount({ q: 'x', ...OCT })).toBe(0)
    expect(activeFilterCount({ type: 'income', min_amount: '5', max_amount: '9', from_date: '2026-09-03' })).toBe(3)
    expect(monthLabel(OCT)).toBe('Oct 2026')
    expect(monthLabel({})).toBe('All time')
  })
})
```

`web/src/features/activity/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { dayLabel, gapLabel, groupByDay } from './format'
import type { Txn } from './hooks'

const TODAY = new Date(2026, 9, 6)
const row = (id: string, date: string, created: string) =>
  ({ id, transaction_date: date, created_at: created }) as unknown as Txn

describe('format', () => {
  it('labels days like the mock', () => {
    expect(dayLabel('2026-10-06', TODAY)).toBe('Today · Tue 6 Oct')
    expect(dayLabel('2026-10-05', TODAY)).toBe('Yesterday · Mon 5 Oct')
    expect(dayLabel('2026-10-01', TODAY)).toBe('Thu 1 Oct')
    expect(dayLabel('2025-12-24', TODAY)).toBe('Wed 24 Dec 2025')
  })

  it('groups rows by day with the server net', () => {
    const groups = groupByDay(
      [row('a', '2026-10-06', '2026-10-06T09:00:00'), row('b', '2026-10-06', '2026-10-06T08:00:00'), row('c', '2026-10-05', '2026-10-05T08:00:00')],
      { '2026-10-06': 85, '2026-10-05': -7 },
    )
    expect(groups.map((g) => [g.date, g.net, g.rows.map((r) => r.id)])).toEqual([
      ['2026-10-06', 85, ['a', 'b']],
      ['2026-10-05', -7, ['c']],
    ])
  })

  it('shows minutes for pairs created ≤10 min apart, else days', () => {
    expect(gapLabel(row('a', '2026-10-06', '2026-10-06T09:00:00'), row('b', '2026-10-06', '2026-10-06T09:02:10'))).toBe('2 min apart')
    expect(gapLabel(row('a', '2026-10-03', '2026-10-03T09:00:00'), row('b', '2026-10-06', '2026-10-06T09:00:00'))).toBe('3 days apart')
    expect(gapLabel(row('a', '2026-10-06', '2026-10-06T09:00:00'), row('b', '2026-10-06', '2026-10-06T18:00:00'))).toBe('Same day')
  })
})
```

`web/src/features/activity/hooks.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { editBody, type Txn } from './hooks'

const ROW = {
  id: 't1', bucket_id: 'b1', household_id: 'h', amount: 100, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: null, payer_mode: 'own_share', category_id: 'c1', notes: 'rent', transaction_date: '2026-10-01',
  receipt_path: null, payment_method: 'transfer', merchant: null, fuel_price_per_litre: null, fuel_litres: null,
  exclude_from_forecast: false, exclude_from_settlement: false, recurring_bill_id: null, created_at: '2026-10-01T08:00:00',
  splits: [{ user_id: 'u1', amount: 60, is_settled: false }, { user_id: 'u2', amount: 40, is_settled: false }],
  has_take: false, missing_payer: false,
} as Txn

describe('editBody', () => {
  it('copies splits and payer_mode, since a PUT without splits deletes them', () => {
    const body = editBody(ROW, { category_id: 'c2' })
    expect(body.category_id).toBe('c2')
    expect(body.payer_mode).toBe('own_share')
    expect(body.splits).toEqual([{ user_id: 'u1', amount: 60 }, { user_id: 'u2', amount: 40 }])
    expect(body).toMatchObject({ amount: 100, bucket_id: 'b1', notes: 'rent', transaction_date: '2026-10-01' })
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/activity/filters.test.ts src/features/activity/format.test.ts src/features/activity/hooks.test.ts`
Expected: FAIL (modules missing).

- [ ] **Step 3: Add the keys**

This task **adds to `web/src/data/keys.ts`**, on top of 2a's A5 file. It never renames or changes a 2a key. 2a already has `keys.transactions.{all, recent, one, forItem}`, `keys.recurring.{all, list, one, entries}`, `keys.plan.{all, budgets, pace, ...}`, `keys.home.all`, `keys.matches()`, `keys.buckets()`, `keys.categories()`, `keys.household()` and `affects`. 2a's convention is a `const` array for a prefix (`all`) and a function for a leaf. 2c needs these extra keys, in the same style:

```ts
// inside keys.transactions (next to all / recent / one / forItem)
    /** TxnPage: one page of the Activity feed for a filter */
    list: (filter: object, page: number) => ['transactions', 'list', filter, page] as const,
    /** HistoryEvent[]: GET /transactions/{id}/history */
    history: (id: string) => ['transactions', 'history', id] as const,
    /** Counts: GET /transactions/counts (the chip badges) */
    counts: () => ['transactions', 'counts'] as const,
// top level of keys
  /** DuplicateGroup[]: GET /transactions/duplicates */
  duplicates: () => ['duplicates'] as const,
  /** RecentBatch[]: GET /transactions/bulk?limit=10 */
  bulkRecent: () => ['bulk-recent'] as const,
  /** The raw GET /buckets rows. 2a's keys.buckets() holds the narrowed Bucket[] (no show_income or icon), which
   *  the bucket pickers need. It sits under the 'buckets' prefix, so invalidating keys.buckets() covers it too. */
  bucketsFull: () => ['buckets', 'full'] as const,
```

Every `transactions.*` key sits under `keys.transactions.all`, so one invalidation covers the list, a row, its history and the counts. `duplicates` and `bulkRecent` are listed in `ACTIVITY_WRITES` (Step 5) because they are not under that prefix.

- [ ] **Step 4: Implement `filters.ts`**

```ts
/** Activity filters live in the URL under the API's names (spec §3), so 2a's
 * and 2d's "See all" links can deep-link. Plain /activity opens on this
 * month; a link with its own filter, or ?all=1, is all time. */

export type TxnType = 'expense' | 'income' | 'transfer'
export type TransactionFilter = {
  q?: string
  type?: TxnType
  category_id?: string
  bucket_id?: string
  no_bucket?: boolean
  paid_by?: string
  missing_payer?: boolean
  payment_method?: string
  recurring_bill_id?: string
  fixed?: boolean
  from_date?: string
  to_date?: string
  min_amount?: string
  max_amount?: string
}
export type FeedState = { filter: TransactionFilter; dups: boolean }

const TEXT_KEYS = [
  'q', 'type', 'category_id', 'bucket_id', 'paid_by', 'payment_method',
  'recurring_bill_id', 'from_date', 'to_date', 'min_amount', 'max_amount',
] as const
const FLAG_KEYS = ['missing_payer', 'no_bucket', 'fixed'] as const
const TYPES: readonly string[] = ['expense', 'income', 'transfer']
const METHODS: readonly string[] = ['card', 'cash', 'apple_pay', 'transfer', 'other']

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

export function monthRange(d: Date): { from_date: string; to_date: string } {
  return {
    from_date: iso(new Date(d.getFullYear(), d.getMonth(), 1)),
    to_date: iso(new Date(d.getFullYear(), d.getMonth() + 1, 0)),
  }
}

export function isEmpty(f: TransactionFilter): boolean {
  return Object.values(f).every((v) => v === undefined || v === false || v === '')
}

export function fromSearch(params: URLSearchParams, today = new Date()): FeedState {
  const filter: TransactionFilter = {}
  for (const k of TEXT_KEYS) {
    const v = params.get(k)?.trim()
    if (!v) continue
    if (k === 'type' && !TYPES.includes(v)) continue
    if (k === 'payment_method' && !METHODS.includes(v)) continue
    ;(filter as Record<string, string>)[k] = v
  }
  for (const k of FLAG_KEYS) if (params.get(k) === '1') filter[k] = true
  const dups = params.get('dups') === '1'
  if (!dups && params.get('all') !== '1' && isEmpty(filter)) Object.assign(filter, monthRange(today))
  return { filter, dups }
}

export function toSearch({ filter, dups }: FeedState): URLSearchParams {
  const p = new URLSearchParams()
  for (const k of TEXT_KEYS) {
    const v = filter[k]
    if (v) p.set(k, String(v))
  }
  for (const k of FLAG_KEYS) if (filter[k]) p.set(k, '1')
  if (dups) p.set('dups', '1')
  else if (isEmpty(filter)) p.set('all', '1') // "All time" with nothing else
  return p
}

/** The query object for GET /transactions and select.filter. */
export function toQuery(filter: TransactionFilter): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {}
  for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== '' && v !== false) out[k] = v
  return out
}

export function toggle(filter: TransactionFilter, patch: TransactionFilter): TransactionFilter {
  const next: TransactionFilter = { ...filter }
  for (const [k, v] of Object.entries(patch) as [keyof TransactionFilter, unknown][]) {
    if (next[k] === v) delete next[k]
    else (next as Record<string, unknown>)[k] = v
  }
  return next
}

function isWholeMonth(f: TransactionFilter): boolean {
  if (!f.from_date || !f.to_date) return false
  const [y, m] = f.from_date.split('-').map(Number)
  const r = monthRange(new Date(y, m - 1, 1))
  return r.from_date === f.from_date && r.to_date === f.to_date
}

export function monthLabel(f: TransactionFilter): string {
  if (isWholeMonth(f)) {
    const [y, m] = f.from_date!.split('-').map(Number)
    return new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric' }).format(new Date(y, m - 1, 1))
  }
  return f.from_date || f.to_date ? 'Custom dates' : 'All time'
}

/** The Filters chip's count: fields the Filters sheet sets (not q, not a whole month). */
export function activeFilterCount(f: TransactionFilter): number {
  let n = 0
  if (f.type) n++
  if (f.category_id) n++
  if (f.bucket_id || f.no_bucket) n++
  if (f.paid_by) n++
  if (f.payment_method) n++
  if (f.recurring_bill_id || f.fixed) n++
  if (f.min_amount || f.max_amount) n++
  if ((f.from_date || f.to_date) && !isWholeMonth(f)) n++
  return n
}
```

- [ ] **Step 5: Implement `hooks.ts`**

```ts
import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { components } from '../../api/schema'
import { useAction } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { ApiError, unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import { useCategories, useHousehold } from '../../data/reads'
import type { Category, Member } from '../../data/types'
import { toQuery, type TransactionFilter } from './filters'

type S = components['schemas']
export type Txn = S['TransactionOut']
export type TxnPage = S['TransactionPage']
export type Counts = S['CountsOut']
export type DuplicateGroup = S['DuplicateGroupOut']
export type HistoryEvent = S['HistoryEventOut']
export type TxnUpdate = S['TransactionUpdate']
export type TxnPatch = Partial<
  Pick<Txn, 'category_id' | 'bucket_id' | 'paid_by' | 'payer_mode' | 'payment_method' | 'notes' | 'exclude_from_forecast'>
>
export type RefData = {
  buckets: { id: string; name: string; kind: string; status: string; show_income: boolean; icon: string | null }[]
  categories: Pick<Category, 'id' | 'name' | 'icon'>[]
  members: Pick<Member, 'user_id' | 'display_name'>[]
}

export const PAGE_SIZE = 50
export const OFFLINE_MESSAGE = "Couldn't reach the server. Nothing was changed."
/** What a delete, edit, bulk apply or undo invalidates (spec §6): 2a's `affects.entry` (plan, home, recurring,
 * matches, transactions, insights) plus the two keys this plan adds. */
export const ACTIVITY_WRITES = [...affects.entry, keys.duplicates(), keys.bulkRecent()] as const

/** Online-only calls (bulk, undo, dismiss): a network failure is never queued. `ApiError` is 2a's (data/http). */
export async function online<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call()
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError(0, OFFLINE_MESSAGE)
  }
}

export function useFeedPage(filter: TransactionFilter, page: number) {
  return useCachedQuery(keys.transactions.list(filter, page), (signal) =>
    unwrap(api.GET('/api/v1/transactions', { params: { query: { ...toQuery(filter), page, page_size: PAGE_SIZE } }, signal })),
  )
}
export function useCounts() {
  return useCachedQuery(keys.transactions.counts(), (signal) => unwrap(api.GET('/api/v1/transactions/counts', { signal })))
}
export function useDuplicates() {
  return useCachedQuery(keys.duplicates(), (signal) => unwrap(api.GET('/api/v1/transactions/duplicates', { signal })))
}
export function useTransaction(id: string) {
  return useCachedQuery(keys.transactions.one(id), (signal) =>
    unwrap(api.GET('/api/v1/transactions/{txn_id}', { params: { path: { txn_id: id } }, signal })),
  )
}
export function useHistory(id: string) {
  return useCachedQuery(keys.transactions.history(id), (signal) =>
    unwrap(api.GET('/api/v1/transactions/{txn_id}/history', { params: { path: { txn_id: id } }, signal })),
  )
}
/** Buckets (raw rows, for show_income and icon), plus 2a's categories and household reads. */
export function useRefData(): RefData | undefined {
  const buckets = useCachedQuery(keys.bucketsFull(), async (signal) =>
    (await unwrap(api.GET('/api/v1/buckets', { signal }))) as RefData['buckets'],
  )
  const categories = useCategories()
  const household = useHousehold()
  if (!buckets.data || !categories.data || !household.data) return undefined
  return { buckets: buckets.data, categories: categories.data, members: household.data.members }
}

export const receiptUrl = (id: string) => `/api/v1/transactions/${encodeURIComponent(id)}/receipt`

export async function uploadReceipt(id: string, file: File): Promise<void> {
  const form = new FormData()
  form.append('file', file)
  await online(() =>
    unwrap(api.POST('/api/v1/transactions/{txn_id}/receipt', {
      params: { path: { txn_id: id } },
      body: form as never,
      bodySerializer: (b: unknown) => b as FormData,
    })),
  )
}

/** The full PUT body from the cached row. splits and payer_mode are copied:
 * update_transaction replaces the splits, so a PUT without them deletes them. */
export function editBody(t: Txn, patch: TxnPatch): TxnUpdate {
  return {
    amount: t.amount,
    currency: t.currency ?? 'EUR',
    exchange_rate: t.exchange_rate,
    type: t.type as TxnUpdate['type'],
    bucket_id: t.bucket_id,
    paid_by: t.paid_by,
    payer_mode: t.payer_mode,
    category_id: t.category_id,
    notes: t.notes,
    transaction_date: t.transaction_date,
    payment_method: t.payment_method,
    merchant: t.merchant,
    fuel_price_per_litre: t.fuel_price_per_litre,
    exclude_from_forecast: t.exclude_from_forecast,
    exclude_from_settlement: t.exclude_from_settlement,
    splits: t.splits.map((s) => ({ user_id: s.user_id, amount: s.amount })),
    ...patch,
  } as TxnUpdate
}

/** Patch (or drop, when fn returns null) one row in every cached list and
 * single-row query. It returns nothing: useAction rolls back by restoring every
 * query under the `invalidates` prefixes, and keys.transactions.all is one of them. */
export function patchRows(qc: QueryClient, id: string, fn: (t: Txn) => Txn | null): void {
  for (const [key, data] of qc.getQueriesData({ queryKey: keys.transactions.all })) {
    if (!data || typeof data !== 'object') continue
    if ('items' in data) {
      const page = data as TxnPage
      qc.setQueryData(key, { ...page, items: page.items.flatMap((t) => (t.id === id ? (fn(t) ?? []) : [t])) })
    } else if ((data as Txn).id === id) {
      const next = fn(data as Txn)
      if (next) qc.setQueryData(key, next)
    }
  }
}

export function useEditTransaction() {
  return useAction<{ txn: Txn; patch: TxnPatch }, Txn>({
    method: 'PUT',
    path: ({ txn }) => `/api/v1/transactions/${txn.id}`,
    body: ({ txn, patch }) => editBody(txn, patch),
    optimistic: (qc, { txn, patch }) => patchRows(qc, txn.id, (row) => ({ ...row, ...patch })),
    invalidates: ACTIVITY_WRITES,
    pendingId: ({ txn }) => txn.id,
  })
}

export function useDeleteTransaction() {
  return useAction<{ id: string }>({
    method: 'DELETE',
    path: ({ id }) => `/api/v1/transactions/${id}`,
    optimistic: (qc, { id }) => patchRows(qc, id, () => null),
    invalidates: ACTIVITY_WRITES,
    pendingId: ({ id }) => id,
  })
}
```

`pending.ts`:

```ts
/** 2b's queued creates, rebuilt from the offline queue. Until 2b lands this
 * returns [] (spec §10, F1 dependency); then replace the body with
 * `export { usePendingTransactions } from '../composer/hooks'`. */
import type { Txn } from './hooks'

export type PendingTxn = Txn & { pending: true }

export function usePendingTransactions(): PendingTxn[] {
  return []
}
```

`format.ts`:

```ts
import type { RefData, Txn } from './hooks'

export const METHOD_LABELS: Record<string, string> = {
  card: 'Card', cash: 'Cash', apple_pay: 'Apple Pay', transfer: 'Transfer', other: 'Other',
}
const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
const parse = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString()

export function dayLabel(iso: string, today = new Date()): string {
  const d = parse(iso)
  const text = DAY.format(d).replace(',', '')
  if (sameDay(d, today)) return `Today · ${text}`
  const y = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  if (sameDay(d, y)) return `Yesterday · ${text}`
  return d.getFullYear() === today.getFullYear() ? text : `${text} ${d.getFullYear()}`
}

export type DayGroup = { date: string; label: string; net: number; rows: Txn[] }

export function groupByDay(rows: Txn[], dayTotals: Record<string, number>, today = new Date()): DayGroup[] {
  const groups: DayGroup[] = []
  for (const t of rows) {
    const date = t.transaction_date ?? ''
    let g = groups.at(-1)
    if (!g || g.date !== date) {
      g = { date, label: dayLabel(date, today), net: dayTotals[date] ?? 0, rows: [] }
      groups.push(g)
    }
    g.rows.push(t)
  }
  return groups
}

export function gapLabel(a: Txn, b: Txn): string {
  const minutes = Math.abs(Date.parse(b.created_at ?? '') - Date.parse(a.created_at ?? '')) / 60000
  if (minutes <= 10) return `${Math.max(1, Math.round(minutes))} min apart`
  const days = Math.round(Math.abs(parse(b.transaction_date ?? '').getTime() - parse(a.transaction_date ?? '').getTime()) / 864e5)
  if (days === 0) return 'Same day'
  return days === 1 ? '1 day apart' : `${days} days apart`
}

export function rowTitle(t: Txn, ref?: RefData): string {
  return t.merchant || t.notes || ref?.categories.find((c) => c.id === t.category_id)?.name || 'Transaction'
}

export function rowSubtitle(t: Txn, ref?: RefData): string {
  const parts: string[] = []
  const category = ref?.categories.find((c) => c.id === t.category_id)?.name
  if (category) parts.push(category)
  if (t.payer_mode === 'own_share') parts.push('each their share')
  else if (t.missing_payer) parts.push('no payer')
  else if (t.paid_by) parts.push(ref?.members.find((m) => m.user_id === t.paid_by)?.display_name ?? '')
  if (t.splits.length > 0 && t.payer_mode !== 'own_share') parts.push('split')
  return parts.filter(Boolean).join(' · ')
}
```

`testing.tsx`. The tests use 2a's test kit (`web/src/test`): `fakeApi` for the network (route keys like `'GET /api/v1/transactions'`, `fake.callsTo(route)`, `fake.down()`), `renderWithProviders` for the providers, `setOnline` for connectivity and `resetTestEnv` in `afterEach`. 2a's `fakeApi` types each reply from the OpenAPI schema. These fixtures are looser than the schema in places, so cast a reply `as never` at the handler when typecheck objects. This file only adds what Activity screens need on top: a route pattern for `:id` and a location readout.

```tsx
import type { ReactElement } from 'react'
import { Route, Routes, useLocation } from 'react-router'
import { renderWithProviders } from '../../test/render'

function Where() {
  const loc = useLocation()
  return <output data-testid="location">{loc.pathname + loc.search}</output>
}

/** 2a's renderWithProviders (query client, memory router, Toaster, signed-in identity) renders `ui` at every path.
 * This mounts it at `path` so a screen can read `:id`, and adds the location readout the tests assert on. */
export function renderActivity(ui: ReactElement, { route = '/activity', path = '/activity' } = {}) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path={path} element={ui} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}
```

- [ ] **Step 6: Run the tests, then typecheck**

Run: `cd web && npm test -- src/features/activity/filters.test.ts src/features/activity/format.test.ts src/features/activity/hooks.test.ts && npm run typecheck`
Expected: PASS. If typecheck flags an openapi-fetch generic (for example the multipart `bodySerializer`), fix the type at that call. Don't widen `Txn`.

- [ ] **Step 7: Commit**

```bash
git add web/src/data/keys.ts web/src/features/activity/
git commit -m "feat(activity): URL filters, data hooks, formatting and test helpers"
```

---

### Task 13: The feed screen (search, chips, day groups, paging, empty and offline states)

**Stream:** F1. **Depends on:** Task 12.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** Match `access-home.html` §03 "Activity feed": large title, search, a chip row that scrolls sideways, day headers with the net on the right, and rows with an icon, title, subtitle, signed amount and badges.

**Files:**
- Create: `web/src/features/activity/Activity.tsx`, `Feed.tsx`, `FeedRow.tsx`, `OptionSheet.tsx`, `activity.css`
- Modify: `web/src/screens/Activity.tsx` (one-line re-export), `web/src/features/activity/testing.tsx` (add `makeTxn` and `refRoutes`)
- Test: `web/src/features/activity/Activity.test.tsx`

**Interfaces:**
- Consumes: everything from Task 12, plus the kit (`Chip`, `SearchField`, `Badge`, `ListRow`, `Money`, `Sheet`, `Check`) and the shell `TopBar`.
- Produces:
  - `Activity()` (the screen);
  - `Feed({filter, onClear, renderRow?})`, where `renderRow` lets Tasks 15 and 18 wrap rows;
  - `FeedRow({t, refData, onOpen, pending?, selected?, selecting?})`;
  - `OptionSheet({open, title, options: {value, label, hint?}[], value, note?, onPick, onClose})`;
  - `withoutDates(filter)` exported from `Activity.tsx`.

**Chip behaviour (resolved here):**
- **No payer** clears the dates. `/counts` is all time, so "No payer 7" must list 7.
- **Month** opens an OptionSheet: this month, the previous 5 months, then "All time".
- **Duplicates** is wired in Task 17.

- [ ] **Step 1: Add the test helpers**

Append to `web/src/features/activity/testing.tsx`:

```tsx
import type { Routes as ApiRoutes } from '../../test/fakeApi'
import type { Txn, TxnPage } from './hooks'

const iso = (d: Date) => d.toISOString().slice(0, 10)
export const TODAY = iso(new Date())
export const YESTERDAY = iso(new Date(Date.now() - 864e5))

let n = 0
export function makeTxn(over: Partial<Txn> = {}): Txn {
  n += 1
  return {
    id: `t${n}`, bucket_id: 'b-day', household_id: 'h', amount: 10, currency: 'EUR', exchange_rate: 1,
    type: 'expense', paid_by: 'u-me', payer_mode: 'single', category_id: null, notes: null,
    transaction_date: TODAY, receipt_path: null, payment_method: 'card', merchant: null,
    fuel_price_per_litre: null, fuel_litres: null, exclude_from_forecast: false, exclude_from_settlement: false,
    recurring_bill_id: null, created_at: `${TODAY}T09:00:00`, splits: [], has_take: false, missing_payer: false,
    ...over,
  } as Txn
}

export const REF = {
  buckets: [
    { id: 'b-day', name: 'Day to day', kind: 'monthly', status: 'active', show_income: true, icon: '🛒' },
    { id: 'b-bills', name: 'Bills', kind: 'monthly', status: 'active', show_income: false, icon: '🧾' },
    { id: 'b-trip', name: 'Crete', kind: 'event', status: 'active', show_income: false, icon: '🏝' },
  ],
  categories: [{ id: 'c-groc', name: 'Groceries', icon: '🛒', system_key: null }],
  members: [{ user_id: 'u-me', display_name: 'Giorgos' }, { user_id: 'u-maria', display_name: 'Maria' }],
}

/** The reference reads every Activity screen makes, as 2a fakeApi routes. Spread it, then add the screen's own routes. */
export function refRoutes(counts = { no_payer: 0, duplicate_groups: 0 }): ApiRoutes {
  return {
    'GET /api/v1/buckets': () => REF.buckets as never,
    'GET /api/v1/settings/categories': () => REF.categories as never,
    'GET /api/v1/settings/household': () => ({ id: 'h', name: 'Home', default_currency: 'EUR', members: REF.members }) as never,
    'GET /api/v1/transactions/counts': () => counts as never,
    'GET /api/v1/recurring': () => [] as never,
  }
}

export function pageOf(items: Txn[], extra: Partial<{ total: number; page: number; day_totals: Record<string, number> }> = {}): TxnPage {
  return { total: items.length, page: 1, page_size: 50, items, day_totals: {}, ...extra } as TxnPage
}
```

- [ ] **Step 2: Write the failing tests**

`web/src/features/activity/Activity.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Activity } from './Activity'
import { YESTERDAY, TODAY, makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const FEED = 'GET /api/v1/transactions' as const

describe('Activity feed', () => {
  it('groups rows by day with the server net and titles rows merchant > notes > category', async () => {
    fakeApi({
      ...refRoutes(),
      [FEED]: () =>
        pageOf(
          [
            makeTxn({ merchant: 'Cosmote', amount: 38.9 }),
            makeTxn({ notes: 'Bread' }),
            makeTxn({ category_id: 'c-groc', transaction_date: YESTERDAY }),
          ],
          { day_totals: { [TODAY]: -48.9, [YESTERDAY]: -10 } },
        ),
    })
    renderActivity(<Activity />)
    const today = await screen.findByRole('region', { name: /^Today/ })
    expect(within(today).getByText('Cosmote')).toBeInTheDocument()
    expect(within(today).getByText('Bread')).toBeInTheDocument()
    const yesterday = screen.getByRole('region', { name: /^Yesterday/ })
    expect(within(yesterday).getAllByText('Groceries').length).toBeGreaterThan(0)
  })

  it('asks the API with its own names', async () => {
    const fake = fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]) })
    renderActivity(<Activity />, { route: '/activity?q=cosmote&all=1' })
    await waitFor(() => expect(fake.callsTo(FEED)).toHaveLength(1))
    const feed = fake.callsTo(FEED)[0]
    expect(feed.query.get('q')).toBe('cosmote')
    expect(feed.query.get('page_size')).toBe('50')
    expect(feed.query.get('from_date')).toBeNull()
  })

  it('hides chips at 0; No payer shows its count, toggles and clears the month', async () => {
    fakeApi({ ...refRoutes({ no_payer: 3, duplicate_groups: 0 }), [FEED]: () => pageOf([]) })
    renderActivity(<Activity />)
    const chip = await screen.findByRole('button', { name: /no payer 3/i })
    expect(screen.queryByRole('button', { name: /duplicates/i })).toBeNull()
    expect(chip).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(chip)
    const loc = screen.getByTestId('location').textContent!
    expect(loc).toContain('missing_payer=1')
    expect(loc).not.toContain('from_date')
  })

  it('shows "No matches" with Clear filters, and "Nothing here yet" on the plain list', async () => {
    fakeApi({ ...refRoutes(), [FEED]: () => pageOf([]) })
    renderActivity(<Activity />, { route: '/activity?q=zzz' })
    fireEvent.click(await screen.findByRole('button', { name: 'Clear filters' }))
    expect(screen.getByTestId('location').textContent).toMatch(/from_date=/)
    expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
  })

  it('loads more and keeps one header for a day split across pages', async () => {
    const first = Array.from({ length: 50 }, (_, i) => makeTxn({ notes: `row ${i}` }))
    const last = makeTxn({ notes: 'row 50' })
    fakeApi({
      ...refRoutes(),
      [FEED]: (req) =>
        req.query.get('page') === '2'
          ? pageOf([last], { total: 51, page: 2, day_totals: { [TODAY]: -510 } })
          : pageOf(first, { total: 51, day_totals: { [TODAY]: -510 } }),
    })
    renderActivity(<Activity />)
    fireEvent.click(await screen.findByRole('button', { name: 'Load more' }))
    expect(await screen.findByText('row 50')).toBeInTheDocument()
    expect(screen.getAllByRole('region', { name: /^Today/ })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
  })

  it('offline without a cached result offers the saved list', async () => {
    fakeApi(refRoutes()).down()
    setOnline(false)
    renderActivity(<Activity />, { route: '/activity?q=new-term' })
    expect(await screen.findByText('Search needs a connection')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show saved list' }))
    expect(screen.getByTestId('location').textContent).toMatch(/from_date=/)
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/activity/Activity.test.tsx`
Expected: FAIL (`./Activity` is missing).

- [ ] **Step 4: Implement the screen**

`web/src/features/activity/OptionSheet.tsx`:

```tsx
import { Check } from '../../ui/Check'
import { Sheet } from '../../ui/Sheet'

export type Option = { value: string; label: string; hint?: string }
type Props = {
  open: boolean
  title: string
  options: Option[]
  value: string
  note?: string
  onPick: (value: string) => void
  onClose: () => void
}

export function OptionSheet({ open, title, options, value, note, onPick, onClose }: Props) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      {note && <p className="small muted option-note">{note}</p>}
      <ul className="list" role="listbox" aria-label={title}>
        {options.map((o) => (
          <li key={o.value} role="option" aria-selected={o.value === value}>
            <button
              type="button"
              className="row option"
              onClick={() => {
                onPick(o.value)
                onClose()
              }}
            >
              <span className="main">
                <span className="t">{o.label}</span>
                {o.hint && <span className="s">{o.hint}</span>}
              </span>
              <Check checked={o.value === value} />
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  )
}
```

`web/src/features/activity/FeedRow.tsx`:

```tsx
import { Badge } from '../../ui/Badge'
import { Check } from '../../ui/Check'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { rowSubtitle, rowTitle } from './format'
import type { RefData, Txn } from './hooks'

type Props = {
  t: Txn
  refData?: RefData
  onOpen: (id: string) => void
  pending?: boolean
  selecting?: boolean
  selected?: boolean
}

export function FeedRow({ t, refData, onOpen, pending, selecting, selected }: Props) {
  const fixed = t.type === 'expense' && !!t.recurring_bill_id && !t.bucket_id
  const sign = t.type === 'income' ? 1 : t.type === 'expense' ? -1 : 0
  const icon = refData?.categories.find((c) => c.id === t.category_id)?.icon ?? '•'
  const badges = [
    t.payment_method === 'apple_pay' && <Badge key="ap">Apple Pay</Badge>,
    fixed && <Badge key="fx">Fixed</Badge>,
    pending && <Badge key="p" tone="warn">Waiting to sync</Badge>,
  ].filter(Boolean)
  return (
    <div className="feedrow" aria-selected={selecting ? !!selected : undefined} data-pending={pending || undefined}>
      {selecting && <Check checked={!!selected} />}
      <ListRow
        leading={<span aria-hidden="true">{icon}</span>}
        title={rowTitle(t, refData)}
        subtitle={rowSubtitle(t, refData)}
        trailing={<Money amount={sign === 0 ? t.amount : sign * t.amount} currency={t.currency ?? 'EUR'} signed={sign !== 0} />}
        badges={badges}
        onClick={() => onOpen(t.id)}
      />
    </div>
  )
}
```

`web/src/features/activity/Feed.tsx`:

```tsx
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { Money } from '../../ui/Money'
import { type TransactionFilter, activeFilterCount, isEmpty } from './filters'
import { groupByDay } from './format'
import { FeedRow } from './FeedRow'
import { type RefData, type Txn, type TxnPage, useFeedPage, useRefData } from './hooks'
import { type PendingTxn, usePendingTransactions } from './pending'

export type RenderRow = (t: Txn, row: ReactNode, opts: { pending: boolean }) => ReactNode

type Props = {
  filter: TransactionFilter
  onClear: () => void
  renderRow?: RenderRow
  hidden?: ReadonlySet<string>
  rowProps?: (t: Txn) => { selecting?: boolean; selected?: boolean; onOpen?: (id: string) => void }
  onLoaded?: (rows: Txn[], total: number) => void
}

export function Feed(props: Props) {
  // A new filter starts a new list: drop the pages of the old one.
  return <FeedList key={JSON.stringify(props.filter)} {...props} />
}

function PageLoader({ filter, page, onLoad }: { filter: TransactionFilter; page: number; onLoad: (p: TxnPage) => void }) {
  const q = useFeedPage(filter, page)
  useEffect(() => {
    if (q.data) onLoad(q.data)
  }, [q.data, onLoad])
  return null
}

function Empty({ title, action }: { title: string; action?: { label: string; onClick: () => void } }) {
  return (
    <div className="empty" role="status">
      <p className="h3">{title}</p>
      {action && <button type="button" className="btn ghost" onClick={action.onClick}>{action.label}</button>}
    </div>
  )
}

function FeedList({ filter, onClear, renderRow, hidden, rowProps, onLoaded }: Props) {
  const navigate = useNavigate()
  const refData: RefData | undefined = useRefData()
  const first = useFeedPage(filter, 1)
  const [more, setMore] = useState<TxnPage[]>([])
  const [extra, setExtra] = useState(0)
  const pendingAll = usePendingTransactions()
  const plain = isEmpty({ ...filter, from_date: undefined, to_date: undefined })

  const loaded = useMemo(() => (first.data ? [first.data, ...more.filter(Boolean)] : []), [first.data, more])
  const total = first.data?.total ?? 0
  const serverRows = loaded.flatMap((p) => p.items)
  const rows = serverRows.filter((t) => !hidden?.has(t.id))
  const pending: PendingTxn[] = plain ? pendingAll : []
  const dayTotals = Object.assign({}, ...loaded.map((p) => p.day_totals)) as Record<string, number>
  const groups = groupByDay(
    [...pending, ...rows].sort((a, b) => (b.transaction_date ?? '').localeCompare(a.transaction_date ?? '')),
    dayTotals,
  )
  const canLoadMore = serverRows.length < total

  useEffect(() => {
    onLoaded?.(serverRows, total)
  }, [serverRows.length, total]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = useCallback(() => setExtra((n) => n + 1), [])
  const sentinel = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const el = sentinel.current
    if (!el || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver((entries) => entries[0]?.isIntersecting && loadMore(), { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [canLoadMore, loadMore])

  if (!first.data) {
    // CachedQuery: noData means offline (or failing) with no saved copy; isLoading means it may still arrive.
    if (first.noData && first.offline) {
      return <Empty title="Search needs a connection" action={{ label: 'Show saved list', onClick: onClear }} />
    }
    if (first.noData) return <Empty title="Couldn't load activity" action={{ label: 'Try again', onClick: first.refetch }} />
    return <p className="screen__note" aria-busy="true">Loading…</p>
  }
  if (groups.length === 0) {
    return plain && activeFilterCount(filter) === 0
      ? <Empty title="Nothing here yet" />
      : <Empty title="No matches" action={{ label: 'Clear filters', onClick: onClear }} />
  }

  const open = (id: string) => navigate(`/activity/${encodeURIComponent(id)}`)
  return (
    <div className="feed">
      {Array.from({ length: extra }, (_, i) => (
        <PageLoader
          key={i}
          filter={filter}
          page={i + 2}
          onLoad={(p) => setMore((m) => { const c = [...m]; c[i] = p; return c })}
        />
      ))}
      {groups.map((g) => (
        <section key={g.date} aria-labelledby={`day-${g.date}`}>
          <h3 className="daygroup" id={`day-${g.date}`}>
            <span>{g.label}</span>
            <span className="num"><Money amount={g.net} signed /></span>
          </h3>
          <ul className="list">
            {g.rows.map((t) => {
              const isPending = 'pending' in t
              const extraProps = isPending ? {} : rowProps?.(t) ?? {}
              const row = (
                <FeedRow t={t} refData={refData} pending={isPending} onOpen={extraProps.onOpen ?? open} {...extraProps} />
              )
              return <li key={t.id}>{renderRow ? renderRow(t, row, { pending: isPending }) : row}</li>
            })}
          </ul>
        </section>
      ))}
      {canLoadMore && (
        <button ref={sentinel} type="button" className="btn ghost load-more" onClick={loadMore}>Load more</button>
      )}
    </div>
  )
}
```

`web/src/features/activity/Activity.tsx`:

```tsx
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { TopBar } from '../../shell/TopBar'
import { Chip } from '../../ui/Chip'
import { SearchField } from '../../ui/SearchField'
import { Feed } from './Feed'
import {
  type FeedState, type TransactionFilter, activeFilterCount, fromSearch, monthLabel, monthRange, toSearch, toggle,
} from './filters'
import { useCounts } from './hooks'
import { OptionSheet } from './OptionSheet'
import './activity.css'

export function withoutDates(f: TransactionFilter): TransactionFilter {
  const { from_date: _f, to_date: _t, ...rest } = f
  return rest
}

function monthOptions(today = new Date()) {
  const opts = Array.from({ length: 6 }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1)
    const r = monthRange(d)
    return { value: `${r.from_date}|${r.to_date}`, label: i === 0 ? 'This month' : monthLabel(r) }
  })
  return [...opts, { value: 'all', label: 'All time' }]
}

export function Activity() {
  const [params, setParams] = useSearchParams()
  const state = useMemo(() => fromSearch(params), [params])
  const set = useCallback((next: FeedState) => setParams(toSearch(next), { replace: true }), [setParams])
  const f = state.filter
  const setFilter = (filter: TransactionFilter) => set({ ...state, filter })
  const counts = useCounts().data
  const [sheet, setSheet] = useState<null | 'month' | 'filters'>(null)
  const clear = () => set({ filter: monthRange(new Date()), dups: false })
  const filters = activeFilterCount(f)

  return (
    <>
      <TopBar title="Activity" />
      <section className="screen activity">
        <SearchField value={f.q ?? ''} onChange={(q) => setFilter({ ...f, q: q || undefined })} />
        <div className="chips" role="toolbar" aria-label="Quick filters">
          <Chip label="Filters" count={filters || undefined} pressed={filters > 0} disabled={state.dups} onClick={() => setSheet('filters')} />
          <Chip label={monthLabel(f)} pressed={!!(f.from_date || f.to_date)} disabled={state.dups} onClick={() => setSheet('month')} />
          {!!counts?.no_payer && (
            <Chip
              label="No payer"
              count={counts.no_payer}
              pressed={!!f.missing_payer}
              disabled={state.dups}
              onClick={() => setFilter(withoutDates(toggle(f, { missing_payer: true })))}
            />
          )}
          <Chip label="Income" pressed={f.type === 'income'} disabled={state.dups} onClick={() => setFilter(toggle(f, { type: 'income' }))} />
          <Chip label="Cash" pressed={f.payment_method === 'cash'} disabled={state.dups} onClick={() => setFilter(toggle(f, { payment_method: 'cash' }))} />
        </div>
        <Feed filter={f} onClear={clear} />
      </section>
      <OptionSheet
        open={sheet === 'month'}
        title="Month"
        options={monthOptions()}
        value={f.from_date && f.to_date ? `${f.from_date}|${f.to_date}` : 'all'}
        onPick={(v) => {
          if (v === 'all') return setFilter(withoutDates(f))
          const [from_date, to_date] = v.split('|')
          setFilter({ ...f, from_date, to_date })
        }}
        onClose={() => setSheet(null)}
      />
    </>
  )
}
```

`web/src/screens/Activity.tsx` becomes:

```tsx
export { Activity } from '../features/activity/Activity'
```

`web/src/features/activity/activity.css`:

```css
.activity { display: flex; flex-direction: column; gap: 12px; padding-bottom: calc(96px + env(safe-area-inset-bottom)); }
.activity .chips { display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; margin-inline: -16px; padding-inline: 16px; overscroll-behavior-x: contain; }
.activity .chips::-webkit-scrollbar { display: none; }
.feed section + section { margin-top: 8px; }
.feedrow { display: flex; align-items: center; gap: 10px; }
.feedrow[aria-selected='true'] { background: var(--accent-soft); border-radius: var(--r-md); }
.feedrow[data-pending] { opacity: .85; }
.empty { display: grid; justify-items: center; gap: 12px; padding: 48px 16px; text-align: center; color: var(--muted); }
.load-more { width: 100%; min-height: 44px; margin-top: 12px; }
.option { width: 100%; min-height: 44px; text-align: left; }
.option-note { padding: 0 4px 8px; }
```

- [ ] **Step 5: Run the tests to verify they pass, then typecheck**

Run: `cd web && npm test -- src/features/activity/Activity.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/activity/ web/src/screens/Activity.tsx
git commit -m "feat(activity): feed with search, chips, day groups, paging and empty states"
```

---

### Task 14: Filters sheet

**Stream:** F1. **Depends on:** Task 13.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** Use native `<select>` and `<input type="date">` (the iOS wheel pickers). Inputs are at least 16 px to avoid focus zoom. The amount inputs use `inputMode="decimal"`.

**Files:**
- Create: `web/src/features/activity/FiltersSheet.tsx`
- Modify: `web/src/features/activity/Activity.tsx` (open the sheet from the Filters chip), `web/src/features/activity/hooks.ts` (add the `RecurringItem` type)
- Test: `web/src/features/activity/FiltersSheet.test.tsx`

**Interfaces:**
- Consumes: `TransactionFilter`, `RefData`, `METHOD_LABELS`, and 2a's `Sheet` and `Segmented`.
- Produces:
  - `FiltersSheet({open, filter, refData, items, onApply, onClose})`;
  - nothing new for data: the items come from 2a's `useRecurringItems()` (`data/reads.ts`, key `keys.recurring.list()`), and `FiltersSheet` takes them as `items?: RecurringItem[]` (the `RecurringItem` type, added to `hooks.ts` below).

- [ ] **Step 1: Write the failing test**

`web/src/features/activity/FiltersSheet.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { FiltersSheet } from './FiltersSheet'
import { REF } from './testing'

const ITEMS = [{ id: 'r-cosmote', name: 'Cosmote', direction: 'out' }]

function setup(filter = {}) {
  const onApply = vi.fn()
  render(<FiltersSheet open filter={filter} refData={REF} items={ITEMS} onApply={onApply} onClose={() => {}} />)
  return onApply
}

describe('FiltersSheet', () => {
  it('maps "No bucket" to no_bucket, and amounts and dates to the API names', () => {
    const onApply = setup({ q: 'x' })
    fireEvent.change(screen.getByLabelText('Bucket'), { target: { value: '__none' } })
    fireEvent.change(screen.getByLabelText('Min €'), { target: { value: '10,5' } })
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
    fireEvent.change(screen.getByLabelText('Recurring item'), { target: { value: 'r-cosmote' } })
    fireEvent.click(screen.getByRole('button', { name: 'Show results' }))
    expect(onApply).toHaveBeenCalledWith({
      q: 'x', no_bucket: true, min_amount: '10,5', from_date: '2026-09-01', recurring_bill_id: 'r-cosmote',
    })
  })

  it('Reset keeps only the search', () => {
    const onApply = setup({ q: 'x', type: 'income', bucket_id: 'b-day' })
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(onApply).toHaveBeenCalledWith({ q: 'x' })
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/activity/FiltersSheet.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Add to `hooks.ts` (2a's `useRecurringItems` already exists in `data/reads.ts`; don't add another hook):

```ts
import type { RecurringItemOut } from '../../data/types'

export type RecurringItem = Pick<RecurringItemOut, 'id' | 'name' | 'direction'>
```

`web/src/features/activity/FiltersSheet.tsx`:

```tsx
import { type FormEvent, useEffect, useState } from 'react'
import { Segmented } from '../../ui/Segmented'
import { Sheet } from '../../ui/Sheet'
import { toQuery, type TransactionFilter, type TxnType } from './filters'
import { METHOD_LABELS } from './format'
import type { RecurringItem, RefData } from './hooks'

const NONE = '__none'
type Props = {
  open: boolean
  filter: TransactionFilter
  refData?: RefData
  items?: RecurringItem[]
  onApply: (f: TransactionFilter) => void
  onClose: () => void
}

const clean = (f: TransactionFilter) => toQuery(f) as TransactionFilter

export function FiltersSheet({ open, filter, refData, items, onApply, onClose }: Props) {
  const [draft, setDraft] = useState<TransactionFilter>(filter)
  useEffect(() => {
    if (open) setDraft(filter)
  }, [open, filter])
  const set = (patch: TransactionFilter) => setDraft((d) => ({ ...d, ...patch }))
  const text = (key: keyof TransactionFilter) => ({
    value: (draft[key] as string | undefined) ?? '',
    onChange: (e: { target: { value: string } }) => set({ [key]: e.target.value || undefined }),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onApply(clean(draft))
    onClose()
  }

  return (
    <Sheet open={open} onClose={onClose} title="Filters">
      <form className="filters vstack" onSubmit={submit}>
        <Segmented
          label="Type"
          options={[
            { value: '', label: 'All' },
            { value: 'expense', label: 'Out' },
            { value: 'income', label: 'In' },
            { value: 'transfer', label: 'Transfer' },
          ]}
          value={draft.type ?? ''}
          onChange={(v: string) => set({ type: (v || undefined) as TxnType | undefined })}
        />
        <label className="field">Category
          <select {...text('category_id')}>
            <option value="">Any</option>
            {refData?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="field">Bucket
          <select
            value={draft.no_bucket ? NONE : (draft.bucket_id ?? '')}
            onChange={(e) => {
              const v = e.target.value
              set({ bucket_id: v && v !== NONE ? v : undefined, no_bucket: v === NONE || undefined })
            }}
          >
            <option value="">Any</option>
            <option value={NONE}>No bucket</option>
            {refData?.buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
        <label className="field">Paid by
          <select {...text('paid_by')}>
            <option value="">Anyone</option>
            {refData?.members.map((m) => <option key={m.user_id} value={m.user_id}>{m.display_name}</option>)}
          </select>
        </label>
        <label className="field">Method
          <select {...text('payment_method')}>
            <option value="">Any</option>
            {Object.entries(METHOD_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field">Recurring item
          <select {...text('recurring_bill_id')}>
            <option value="">Any</option>
            {items?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </label>
        <div className="grid2">
          <label className="field">From<input type="date" {...text('from_date')} /></label>
          <label className="field">To<input type="date" {...text('to_date')} /></label>
        </div>
        <div className="grid2">
          <label className="field">Min €<input inputMode="decimal" {...text('min_amount')} /></label>
          <label className="field">Max €<input inputMode="decimal" {...text('max_amount')} /></label>
        </div>
        <div className="hstack sheet-actions">
          <button type="button" className="btn ghost" onClick={() => { onApply(clean({ q: filter.q })); onClose() }}>Reset</button>
          <button type="submit" className="btn">Show results</button>
        </div>
      </form>
    </Sheet>
  )
}
```

In `Activity.tsx`, render the sheet next to the month sheet:

```tsx
<FiltersSheet
  open={sheet === 'filters'}
  filter={f}
  refData={useRefData()}
  items={items}
  onApply={setFilter}
  onClose={() => setSheet(null)}
/>
```

At the top of `Activity`, call `const refData = useRefData()` and `const items = useRecurringItems().data` (2a's hook from `../../data/reads`), and pass `refData={refData}` to the sheet instead of the inline `useRefData()` call above. Hooks must not be called conditionally.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/activity/FiltersSheet.test.tsx src/features/activity/Activity.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/activity/
git commit -m "feat(activity): Filters sheet"
```

---

### Task 15: Swipe to delete (held 5 s) and to copy

**Stream:** F1. **Depends on:** Task 14.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** The swipe follows the finger 1:1. On release it springs back, with no animation under `prefers-reduced-motion`. Vertical scrolling must keep working (`touch-action: pan-y`).

**Files:**
- Create: `web/src/features/activity/heldDeletes.ts`, `web/src/features/activity/useDeleteWithUndo.ts`
- Modify: `web/src/features/activity/Activity.tsx` (pass `renderRow` and `hidden` to `Feed`)
- Test: `web/src/features/activity/heldDeletes.test.ts`, `web/src/features/activity/swipe.test.tsx`

**Interfaces:**
- Consumes: `SwipeRow`, `useDeleteTransaction`, `useRecurringItems`, `useToast`.
- Produces:
  - `heldDeletes.ts`: `HOLD_MS = 5000`, `holdDelete(id, send, ms?)`, `undoDelete(id): boolean`, `flush(id)`, `flushAll()`, `useHeldDeletes(): ReadonlySet<string>`, `_resetHeldForTests()`;
  - `useDeleteWithUndo(): (t: Txn) => void`, which Tasks 16 and 17 reuse.

The store is module-level, not component state, so a held delete survives navigating between the feed and a detail.

- [ ] **Step 1: Write the failing tests**

`web/src/features/activity/heldDeletes.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HOLD_MS, _resetHeldForTests, holdDelete, undoDelete } from './heldDeletes'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  _resetHeldForTests()
  vi.useRealTimers()
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
})

describe('held deletes', () => {
  it('Undo sends nothing', () => {
    const send = vi.fn()
    holdDelete('a', send)
    vi.advanceTimersByTime(HOLD_MS - 1)
    expect(undoDelete('a')).toBe(true)
    vi.advanceTimersByTime(HOLD_MS * 2)
    expect(send).not.toHaveBeenCalled()
  })

  it('sends the DELETE when the 5 s toast ends', () => {
    const send = vi.fn()
    holdDelete('a', send)
    vi.advanceTimersByTime(HOLD_MS)
    expect(send).toHaveBeenCalledOnce()
  })

  it('sends at once when the page is hidden', () => {
    const send = vi.fn()
    holdDelete('a', send)
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(send).toHaveBeenCalledOnce()
    const other = vi.fn()
    holdDelete('b', other)
    window.dispatchEvent(new Event('pagehide'))
    expect(other).toHaveBeenCalledOnce()
  })
})
```

`web/src/features/activity/swipe.test.tsx`:

```tsx
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { Activity } from './Activity'
import { HOLD_MS, _resetHeldForTests } from './heldDeletes'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(async () => {
  _resetHeldForTests()
  await resetTestEnv()
})

const DELETE = 'DELETE /api/v1/transactions/{txn_id}' as const

function setup() {
  const row = makeTxn({ merchant: 'Cosmote', recurring_bill_id: 'r1', bucket_id: 'b-bills' })
  const fake = fakeApi({
    ...refRoutes(),
    'GET /api/v1/recurring': () => [{ id: 'r1', name: 'Cosmote', direction: 'out' }] as never,
    'GET /api/v1/transactions': () => pageOf([row]),
    [DELETE]: () => null,
  })
  renderActivity(<Activity />)
  return { row, fake }
}

describe('swipe delete', () => {
  it('hides the row, offers Undo, and Undo sends nothing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { fake } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(screen.queryByText('Cosmote')).toBeNull()
    expect(screen.getByText(/Cosmote .* is expected again/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Cosmote')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(HOLD_MS * 2))
    expect(fake.callsTo(DELETE)).toHaveLength(0)
  })

  it('sends the DELETE after 5 s', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { fake, row } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    act(() => vi.advanceTimersByTime(HOLD_MS))
    await waitFor(() => expect(fake.callsTo(DELETE).map((c) => c.path)).toEqual([`/api/v1/transactions/${row.id}`]))
  })

  it('Copy opens the composer with ?from=', async () => {
    const { row } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Copy' }))
    expect(screen.getByTestId('location').textContent).toBe(`/new?from=${row.id}`)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/activity/heldDeletes.test.ts src/features/activity/swipe.test.tsx`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`web/src/features/activity/heldDeletes.ts`:

```ts
/** Swipe delete is held locally for 5 s (spec §4.3; there is no restore
 * endpoint). The DELETE goes when the hold ends, or at once when the page
 * is hidden; Undo cancels it. Module-level so it survives navigation. */
import { useSyncExternalStore } from 'react'

export const HOLD_MS = 5000

type Held = { timer: ReturnType<typeof setTimeout>; send: () => void }
const held = new Map<string, Held>()
const listeners = new Set<() => void>()
let snapshot: ReadonlySet<string> = new Set()
let installed = false

function emit() {
  snapshot = new Set(held.keys())
  listeners.forEach((l) => l())
}

function installFlushOnHide() {
  if (installed) return
  installed = true
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushAll()
  })
  window.addEventListener('pagehide', flushAll)
}

export function holdDelete(id: string, send: () => void, ms = HOLD_MS) {
  const prev = held.get(id)
  if (prev) clearTimeout(prev.timer)
  held.set(id, { timer: setTimeout(() => flush(id), ms), send })
  installFlushOnHide()
  emit()
}

export function undoDelete(id: string): boolean {
  const h = held.get(id)
  if (!h) return false
  clearTimeout(h.timer)
  held.delete(id)
  emit()
  return true
}

export function flush(id: string) {
  const h = held.get(id)
  if (!h) return
  clearTimeout(h.timer)
  held.delete(id)
  emit()
  h.send()
}

export function flushAll() {
  for (const id of [...held.keys()]) flush(id)
}

export function useHeldDeletes(): ReadonlySet<string> {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => snapshot,
  )
}

export function _resetHeldForTests() {
  held.forEach((h) => clearTimeout(h.timer))
  held.clear()
  emit()
}
```

`web/src/features/activity/useDeleteWithUndo.ts`:

```ts
import { useToast } from '../../ui/Toast'
import { HOLD_MS, holdDelete, undoDelete } from './heldDeletes'
import { useRecurringItems } from '../../data/reads'
import { type Txn, useDeleteTransaction } from './hooks'

const MONTH = new Intl.DateTimeFormat('en-GB', { month: 'short' })

export function useDeleteWithUndo() {
  const del = useDeleteTransaction()
  const toast = useToast()
  const items = useRecurringItems().data
  return (t: Txn) => {
    holdDelete(t.id, () => void del.run({ id: t.id }))
    const bill = t.recurring_bill_id ? items?.find((i) => i.id === t.recurring_bill_id) : undefined
    const month = t.transaction_date ? MONTH.format(new Date(`${t.transaction_date}T12:00:00`)) : ''
    toast.show(bill ? `Deleted · ${bill.name} ${month} is expected again` : 'Deleted', {
      action: { label: 'Undo', onClick: () => undoDelete(t.id) },
      durationMs: HOLD_MS,
    })
  }
}
```

In `Activity.tsx`, wire the rows. `hidden` keeps held rows out of the list:

```tsx
const held = useHeldDeletes()
const deleteWithUndo = useDeleteWithUndo()
const navigate = useNavigate()
// ...
<Feed
  filter={f}
  onClear={clear}
  hidden={held}
  renderRow={(t, row, { pending }) => (
    <SwipeRow
      disabled={pending}
      onDelete={() => deleteWithUndo(t)}
      onCopy={() => navigate(`/new?from=${encodeURIComponent(t.id)}`)}
    >
      {row}
    </SwipeRow>
  )}
/>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/activity/heldDeletes.test.ts src/features/activity/swipe.test.tsx src/features/activity/Activity.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/activity/
git commit -m "feat(activity): swipe to delete with a 5 s undo, swipe to copy"
```

---

### Task 16: Detail (`/activity/:id`) with per-field edits

**Stream:** F1. **Depends on:** Task 15.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** Match `access-home.html` §03 "Detail":
- head: icon, title, big amount, "Tue 6 Oct · Card";
- a receipt card with a thumbnail;
- grouped field rows with chevrons;
- shares;
- linked items;
- history;
- a footer with Copy as new and Delete.

The detail is read-first: every field row is a button that opens a picker.

**Files:**
- Create: `web/src/features/activity/Detail.tsx`, `web/src/features/activity/NotesSheet.tsx`, `web/src/features/activity/pickers.ts`
- Modify: `web/src/router.tsx` (add `{ path: 'activity/:id', element: <ActivityDetail /> }` next to `activity`), `web/src/features/activity/activity.css`
- Test: `web/src/features/activity/Detail.test.tsx`, `web/src/features/activity/pickers.test.ts`

**Interfaces:**
- Consumes: `useTransaction`, `useHistory`, `useRefData`, `useEditTransaction`, `useDeleteWithUndo`, `usePendingTransactions`, `receiptUrl`, `uploadReceipt`, 2a's `useOnline`, `OptionSheet`, `dayLabel`, `METHOD_LABELS`; 2a's `EntrySheet` (opened for a linked entry, with 2a's props).
- Produces:
  - `ActivityDetail()` (route element; the module also exports it as `Detail`);
  - `pickers.ts`: `bucketOptions(t, ref) -> {options, note?}`, `payerOptions(ref)`, `payerPatch(value) -> TxnPatch`, `OWN_SHARE = '__own'`;
  - `HistoryList({id, renderAction?})`, which Task 20 uses for "Undo this change".

- [ ] **Step 1: Write the failing tests**

`web/src/features/activity/pickers.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { bucketOptions, payerPatch } from './pickers'
import { REF, makeTxn } from './testing'

const values = (r: ReturnType<typeof bucketOptions>) => r.options.map((o) => o.label)

describe('bucket picker (R7)', () => {
  it('a bucketed bill payment keeps a bucket, with the hint', () => {
    const r = bucketOptions(makeTxn({ recurring_bill_id: 'r1', bucket_id: 'b-bills' }), REF)
    expect(values(r)).not.toContain('No bucket (Fixed cost)')
    expect(r.note).toBe('Bill payments keep a bucket. Move the bill instead.')
  })

  it('a bucket-less Fixed cost may stay bucket-less', () => {
    const r = bucketOptions(makeTxn({ recurring_bill_id: 'r1', bucket_id: null }), REF)
    expect(values(r)[0]).toBe('No bucket (Fixed cost)')
  })

  it('income offers No bucket and only income-tracking buckets', () => {
    const r = bucketOptions(makeTxn({ type: 'income', bucket_id: null }), REF)
    expect(values(r)).toEqual(['No bucket', 'Day to day'])
  })

  it('maps the payer choice to paid_by and payer_mode', () => {
    expect(payerPatch('u-maria')).toEqual({ paid_by: 'u-maria', payer_mode: 'single' })
    expect(payerPatch('__own')).toEqual({ paid_by: null, payer_mode: 'own_share' })
  })
})
```

`web/src/features/activity/Detail.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Detail } from './Detail'
import { makeTxn, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const PUT = 'PUT /api/v1/transactions/{txn_id}' as const

const ROW = makeTxn({
  id: 'rent', notes: 'Rent', amount: 1100, payer_mode: 'own_share', paid_by: null, category_id: null,
  splits: [{ user_id: 'u-me', amount: 700, is_settled: false }, { user_id: 'u-maria', amount: 400, is_settled: false }],
})

function setup(row = ROW) {
  const fake = fakeApi({
    ...refRoutes(),
    'GET /api/v1/transactions/{txn_id}': () => row,
    'GET /api/v1/transactions/{txn_id}/history': () => ({ events: [] }) as never,
    'GET /api/v1/recurring/entries': () => [],
    [PUT]: (req) => ({ ...row, ...(req.body as object) }),
  })
  renderActivity(<Detail />, { route: `/activity/${row.id}`, path: '/activity/:id' })
  return fake
}

describe('Detail', () => {
  it('a field edit PUTs the full row, keeping splits and payer_mode', async () => {
    const fake = setup()
    fireEvent.click(await screen.findByRole('button', { name: /^Category/ }))
    fireEvent.click(screen.getByRole('button', { name: /Groceries/ }))
    await waitFor(() => expect(fake.callsTo(PUT)).toHaveLength(1))
    const put = fake.callsTo(PUT)[0].body as Record<string, unknown>
    expect(put.category_id).toBe('c-groc')
    expect(put.payer_mode).toBe('own_share')
    expect(put.splits).toEqual([{ user_id: 'u-me', amount: 700 }, { user_id: 'u-maria', amount: 400 }])
  })

  it('links the receipt through the API route; Add receipt needs a connection', async () => {
    setup(makeTxn({ id: 'r1', receipt_path: 'x.jpg', merchant: 'Lidl' }))
    expect(await screen.findByRole('link', { name: 'View receipt' })).toHaveAttribute('href', '/api/v1/transactions/r1/receipt')
  })

  it('Add receipt is disabled offline', async () => {
    setOnline(false)
    setup(makeTxn({ id: 'r2', merchant: 'Lidl' }))
    expect(await screen.findByRole('button', { name: /Add receipt/ })).toBeDisabled()
  })

  it('Edit opens the composer route and Copy opens /new?from=', async () => {
    setup()
    expect(await screen.findByRole('link', { name: 'Edit' })).toHaveAttribute('href', '/edit/rent')
    fireEvent.click(screen.getByRole('button', { name: 'Copy as new' }))
    expect(screen.getByTestId('location').textContent).toBe('/new?from=rent')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/activity/pickers.test.ts src/features/activity/Detail.test.tsx`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement the pickers**

`web/src/features/activity/pickers.ts`:

```ts
import type { RefData, Txn, TxnPatch } from './hooks'
import type { Option } from './OptionSheet'

export const OWN_SHARE = '__own'
const NO_BUCKET = ''

/** The Bucket picker (spec §4.4, R7): income may have no bucket and only
 * goes to buckets that track income; a bucket-less Fixed cost may stay
 * bucket-less; a bill payment that has a bucket keeps one. */
export function bucketOptions(t: Txn, ref: RefData): { options: Option[]; note?: string } {
  const active = ref.buckets.filter((b) => b.status === 'active')
  const asOption = (b: RefData['buckets'][number]): Option => ({
    value: b.id, label: b.name, hint: b.kind === 'event' ? 'Event' : undefined,
  })
  if (t.type === 'income') {
    return { options: [{ value: NO_BUCKET, label: 'No bucket' }, ...active.filter((b) => b.show_income).map(asOption)] }
  }
  const fixedCost = t.type === 'expense' && !!t.recurring_bill_id && !t.bucket_id
  return {
    options: [...(fixedCost ? [{ value: NO_BUCKET, label: 'No bucket (Fixed cost)' }] : []), ...active.map(asOption)],
    note: t.recurring_bill_id && t.bucket_id ? 'Bill payments keep a bucket. Move the bill instead.' : undefined,
  }
}

export function payerOptions(ref: RefData): Option[] {
  return [
    ...ref.members.map((m) => ({ value: m.user_id, label: m.display_name ?? 'Member' })),
    { value: OWN_SHARE, label: 'Each paid their own share' },
  ]
}

export function payerPatch(value: string): TxnPatch {
  return value === OWN_SHARE ? { paid_by: null, payer_mode: 'own_share' } : { paid_by: value, payer_mode: 'single' }
}
```

`web/src/features/activity/NotesSheet.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Sheet } from '../../ui/Sheet'

export function NotesSheet({ open, value, onSave, onClose }: { open: boolean; value: string; onSave: (v: string) => void; onClose: () => void }) {
  const [text, setText] = useState(value)
  useEffect(() => {
    if (open) setText(value)
  }, [open, value])
  return (
    <Sheet open={open} onClose={onClose} title="Notes">
      <form onSubmit={(e) => { e.preventDefault(); onSave(text.trim()); onClose() }} className="vstack">
        <textarea aria-label="Notes" rows={4} maxLength={500} value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit" className="btn">Save</button>
      </form>
    </Sheet>
  )
}
```

- [ ] **Step 4: Implement the Detail screen**

`web/src/features/activity/Detail.tsx`:

```tsx
import { type ReactNode, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useOnline } from '../../data/online'
import { TopBar } from '../../shell/TopBar'
import { Money } from '../../ui/Money'
import { useToast } from '../../ui/Toast'
import { EntrySheet } from '../plan/EntrySheet'
import { dayLabel, METHOD_LABELS, rowTitle } from './format'
import {
  type HistoryEvent, type RefData, type Txn, type TxnPatch, receiptUrl, uploadReceipt,
  useEditTransaction, useHistory, useLinkedEntry, useRefData, useTransaction,
} from './hooks'
import { NotesSheet } from './NotesSheet'
import { OptionSheet } from './OptionSheet'
import { usePendingTransactions } from './pending'
import { bucketOptions, OWN_SHARE, payerOptions, payerPatch } from './pickers'
import { useDeleteWithUndo } from './useDeleteWithUndo'
import './activity.css' // a cold deep link to /activity/:id never loads Activity.tsx

type Picker = null | 'category' | 'bucket' | 'payer' | 'method' | 'notes'

function FieldRow({ label, value, onClick, disabled }: { label: string; value: string; onClick: () => void; disabled?: boolean }) {
  return (
    <li>
      <button type="button" className="row field-row" onClick={onClick} disabled={disabled} aria-label={`${label}, ${value}`}>
        <span className="t">{label}</span>
        <span className="s">{value}</span>
        <span className="chev" aria-hidden="true">›</span>
      </button>
    </li>
  )
}

export function HistoryList({ id, renderAction }: { id: string; renderAction?: (e: HistoryEvent) => ReactNode }) {
  const events = useHistory(id).data?.events ?? []
  if (events.length === 0) return null
  const time = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  return (
    <section aria-labelledby="history-h">
      <h2 className="h3" id="history-h">History</h2>
      <ol className="list history">
        {events.map((e, i) => (
          <li key={`${e.kind}-${e.at}-${i}`} className="row">
            <span className="main">
              <span className="t">{e.text}</span>
              <span className="s">{time.format(new Date(e.at))}{e.by ? ` · ${e.by}` : ''}</span>
            </span>
            {renderAction?.(e)}
          </li>
        ))}
      </ol>
    </section>
  )
}

function names(t: Txn, ref?: RefData) {
  return {
    category: ref?.categories.find((c) => c.id === t.category_id)?.name ?? 'None',
    bucket: ref?.buckets.find((b) => b.id === t.bucket_id)?.name ?? (t.recurring_bill_id && t.type === 'expense' ? 'No bucket (Fixed cost)' : 'No bucket'),
    payer: t.payer_mode === 'own_share' ? 'Each paid their own share' : ref?.members.find((m) => m.user_id === t.paid_by)?.display_name ?? 'No payer',
  }
}

export function Detail({ historyAction }: { historyAction?: (e: HistoryEvent) => ReactNode } = {}) {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const online = useOnline()
  const toast = useToast()
  const ref = useRefData()
  const pending = usePendingTransactions().find((p) => p.id === id)
  const query = useTransaction(id)
  const edit = useEditTransaction()
  const deleteWithUndo = useDeleteWithUndo()
  const linked = useLinkedEntry(query.data)
  const [picker, setPicker] = useState<Picker>(null)
  const [entryOpen, setEntryOpen] = useState(false)
  const file = useRef<HTMLInputElement>(null)

  const t = pending ?? query.data
  if (!t) {
    return (
      <>
        <TopBar title="" back />
        <p className="screen__note">{query.isError ? 'This transaction is gone.' : 'Loading…'}</p>
      </>
    )
  }
  const readOnly = !!pending
  const n = names(t, ref)
  const save = (patch: TxnPatch) => void edit.run({ txn: t, patch })
  const sign = t.type === 'income' ? 1 : t.type === 'expense' ? -1 : 0

  return (
    <>
      <TopBar title="" back />
      <section className="screen detail">
        <header className="detail__head">
          <h1 className="h1">{rowTitle(t, ref)}</h1>
          <p className="amt-xl"><Money amount={sign ? sign * t.amount : t.amount} currency={t.currency ?? 'EUR'} signed={sign !== 0} /></p>
          <p className="muted">{dayLabel(t.transaction_date ?? '')} · {METHOD_LABELS[t.payment_method] ?? t.payment_method}</p>
          {readOnly && <p className="badge warn">Saves when you're back online</p>}
        </header>

        <div className="card receipt">
          {t.receipt_path ? (
            <>
              {/\.(jpe?g|png|gif|webp)$/i.test(t.receipt_path) && (
                <img className="receipt-thumb" src={receiptUrl(t.id)} alt="" loading="lazy" />
              )}
              <a href={receiptUrl(t.id)} target="_blank" rel="noreferrer">View receipt</a>
            </>
          ) : (
            <>
              <button type="button" className="btn ghost" disabled={!online || readOnly} onClick={() => file.current?.click()}>
                Add receipt{!online ? ' (needs a connection)' : ''}
              </button>
              <input
                ref={file}
                type="file"
                hidden
                accept="image/*,application/pdf"
                onChange={async (e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  try {
                    await uploadReceipt(t.id, f)
                    void query.refetch()
                  } catch (err) {
                    toast.show((err as Error).message, { tone: 'error' })
                  }
                }}
              />
            </>
          )}
        </div>

        <ul className="list card fields">
          <FieldRow label="Category" value={n.category} onClick={() => setPicker('category')} disabled={readOnly} />
          <FieldRow label="Bucket" value={n.bucket} onClick={() => setPicker('bucket')} disabled={readOnly} />
          <FieldRow label="Paid by" value={n.payer} onClick={() => setPicker('payer')} disabled={readOnly} />
          <FieldRow label="Method" value={METHOD_LABELS[t.payment_method] ?? t.payment_method} onClick={() => setPicker('method')} disabled={readOnly} />
          <FieldRow label="Notes" value={t.notes || 'None'} onClick={() => setPicker('notes')} disabled={readOnly} />
          <li className="row">
            <label className="between toggle-row">
              <span>Count in forecast</span>
              <input
                type="checkbox"
                role="switch"
                checked={!t.exclude_from_forecast}
                disabled={readOnly}
                onChange={(e) => save({ exclude_from_forecast: !e.target.checked })}
              />
            </label>
          </li>
        </ul>

        {!readOnly && <Link className="btn ghost" to={`/edit/${encodeURIComponent(t.id)}`}>Edit</Link>}

        {t.splits.length > 0 && (
          <section aria-labelledby="shares-h">
            <h2 className="h3" id="shares-h">Shares</h2>
            <div className="bar" role="img" aria-label={t.splits.map((s) => `${ref?.members.find((m) => m.user_id === s.user_id)?.display_name}: ${s.amount}`).join(', ')}>
              {t.splits.map((s) => <span key={s.user_id} style={{ flex: s.amount }} />)}
            </div>
            <ul className="list">
              {t.splits.map((s) => (
                <li key={s.user_id} className="row between">
                  <span>{ref?.members.find((m) => m.user_id === s.user_id)?.display_name ?? 'Member'}</span>
                  <Money amount={s.amount} currency={t.currency ?? 'EUR'} />
                </li>
              ))}
            </ul>
          </section>
        )}

        {(linked || t.has_take) && (
          <section aria-labelledby="linked-h">
            <h2 className="h3" id="linked-h">Linked</h2>
            {linked && <button type="button" className="row" onClick={() => setEntryOpen(true)}>{linked.name} · due {dayLabel(linked.due_date)}</button>}
            {t.has_take && <p className="row">Cash was taken for it</p>}
          </section>
        )}

        {!readOnly && <HistoryList id={t.id} renderAction={historyAction} />}

        {!readOnly && (
          <footer className="detail__footer hstack">
            <button type="button" className="btn ghost" onClick={() => navigate(`/new?from=${encodeURIComponent(t.id)}`)}>Copy as new</button>
            <button type="button" className="btn danger" onClick={() => { deleteWithUndo(t); navigate('/activity') }}>Delete</button>
          </footer>
        )}
      </section>

      {ref && (
        <>
          <OptionSheet open={picker === 'category'} title="Category" value={t.category_id ?? ''}
            options={[{ value: '', label: 'None' }, ...ref.categories.map((c) => ({ value: c.id, label: c.name }))]}
            onPick={(v) => save({ category_id: v || null })} onClose={() => setPicker(null)} />
          <OptionSheet open={picker === 'bucket'} title="Bucket" value={t.bucket_id ?? ''} {...bucketOptions(t, ref)}
            onPick={(v) => save({ bucket_id: v || null })} onClose={() => setPicker(null)} />
          <OptionSheet open={picker === 'payer'} title="Paid by" value={t.payer_mode === 'own_share' ? OWN_SHARE : (t.paid_by ?? '')}
            options={payerOptions(ref)} onPick={(v) => save(payerPatch(v))} onClose={() => setPicker(null)} />
          <OptionSheet open={picker === 'method'} title="Method" value={t.payment_method}
            options={Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label }))}
            onPick={(v) => save({ payment_method: v })} onClose={() => setPicker(null)} />
        </>
      )}
      <NotesSheet open={picker === 'notes'} value={t.notes ?? ''} onSave={(v) => save({ notes: v || null })} onClose={() => setPicker(null)} />
      {linked && <EntrySheet entry={linked} open={entryOpen} onClose={() => setEntryOpen(false)} />}
    </>
  )
}

export { Detail as ActivityDetail }
```

Add `useLinkedEntry` to `hooks.ts`. It finds the entry this transaction paid within ±45 days, using 2a's entries endpoint and its `keys.recurring.entries(from, to)` key:

```ts
export type LinkedEntry = S['EntryOut']
export function useLinkedEntry(t: Txn | undefined): LinkedEntry | undefined {
  const day = t?.transaction_date ?? '2000-01-01'
  const shift = (d: string, n: number) => new Date(Date.parse(d) + n * 864e5).toISOString().slice(0, 10)
  const from = shift(day, -45)
  const to = shift(day, 45)
  const q = useCachedQuery(keys.recurring.entries(from, to), (signal) =>
    unwrap(api.GET('/api/v1/recurring/entries', { params: { query: { from, to } }, signal })),
  )
  return t?.recurring_bill_id ? q.data?.find((e) => e.transaction_id === t.id) : undefined
}
```

If 2a's `EntrySheet` takes different props, adapt the one JSX line. If 2a's `TopBar` has no `back` prop, render a back link (`<Link to="/activity" aria-label="Back">‹</Link>`) in its slot.

Add to `router.tsx`, after the `activity` child route:

```tsx
{ path: 'activity/:id', element: <ActivityDetail /> },
```

with `import { ActivityDetail } from './features/activity/Detail'`.

Add to `activity.css`:

```css
.detail { display: flex; flex-direction: column; gap: 16px; padding-bottom: calc(24px + env(safe-area-inset-bottom)); }
.detail__head { text-align: center; display: grid; gap: 4px; padding-top: 8px; }
.field-row { width: 100%; min-height: 44px; display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; text-align: left; }
.field-row .s { color: var(--muted); }
.toggle-row { width: 100%; min-height: 44px; align-items: center; }
.detail__footer { justify-content: space-between; }
.detail .bar { display: flex; height: 8px; border-radius: var(--r-pill); overflow: hidden; gap: 2px; }
.detail .bar span { background: var(--accent); }
.detail .bar span + span { background: var(--c2); }
```

- [ ] **Step 5: Run the tests to verify they pass, then typecheck**

Run: `cd web && npm test -- src/features/activity/pickers.test.ts src/features/activity/Detail.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/activity/ web/src/router.tsx
git commit -m "feat(activity): read-first detail with per-field edits"
```

---

### Task 17: Duplicates mode (`dups=1`)

**Stream:** F1. **Depends on:** Task 16.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** Match `access-home.html` §03 "Possible duplicates": a card per pair, a gap badge, the two rows side by side (`.pair`), a "Will be deleted" outline on the tapped row, then Confirm or Keep both.

**Files:**
- Create: `web/src/features/activity/Duplicates.tsx`
- Modify: `web/src/features/activity/Activity.tsx` (the Duplicates chip; render `<Duplicates />` when `dups`), `web/src/features/activity/hooks.ts` (`dismissDuplicates`), `activity.css`
- Test: `web/src/features/activity/Duplicates.test.tsx`

**Interfaces:**
- Consumes: `useDuplicates`, 2a's `useOnline` and `unwrap`, `online()`, `useDeleteWithUndo`, `useHeldDeletes`, `gapLabel`, `rowTitle`.
- Produces: `Duplicates()`, and `dismissDuplicates(ids: string[]): Promise<void>` in `hooks.ts` (online only; it never queues).

- [ ] **Step 1: Write the failing test**

`web/src/features/activity/Duplicates.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Activity } from './Activity'
import { _resetHeldForTests } from './heldDeletes'
import { TODAY, makeTxn, refRoutes, renderActivity } from './testing'

afterEach(async () => {
  _resetHeldForTests()
  await resetTestEnv()
})

const DISMISS = 'POST /api/v1/transactions/duplicates/dismiss' as const

const a = makeTxn({ id: 'd1', merchant: 'Taverna', amount: 42, created_at: `${TODAY}T20:00:00` })
const b = makeTxn({ id: 'd2', merchant: 'Taverna', amount: 42, created_at: `${TODAY}T20:02:00`, paid_by: 'u-maria' })

function setup(groups = [{ amount: 42, transactions: [a, b] }]) {
  return fakeApi({
    ...refRoutes({ no_payer: 0, duplicate_groups: groups.length }),
    'GET /api/v1/transactions/duplicates': () => ({ groups }) as never,
    [DISMISS]: () => null,
    'DELETE /api/v1/transactions/{txn_id}': () => null,
  })
}

describe('Duplicates mode', () => {
  it('shows pair cards with the gap and disables the other chips', async () => {
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByText('2 min apart')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Income/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Duplicates\? 1/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('Keep both posts the pair', async () => {
    const fake = setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    fireEvent.click(await screen.findByRole('button', { name: 'Keep both' }))
    await waitFor(() => expect(fake.callsTo(DISMISS)[0]?.body).toEqual({ ids: ['d1', 'd2'] }))
  })

  it('tap a row to drop it, then confirm deletes that one (held, with Undo)', async () => {
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    fireEvent.click(await screen.findByRole('button', { name: /Taverna.*Maria/ }))
    expect(screen.getByText('Will be deleted')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete this one' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
    expect(screen.queryByText('2 min apart')).toBeNull() // the pair is resolved
  })

  it('Keep both needs a connection', async () => {
    setOnline(false)
    setup()
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByRole('button', { name: 'Keep both' })).toBeDisabled()
  })

  it('empty state', async () => {
    setup([])
    renderActivity(<Activity />, { route: '/activity?dups=1' })
    expect(await screen.findByText('No possible duplicates in the last 90 days')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/activity/Duplicates.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Add to `hooks.ts`:

```ts
export async function dismissDuplicates(ids: string[]): Promise<void> {
  await online(() => unwrap(api.POST('/api/v1/transactions/duplicates/dismiss', { body: { ids } })))
}
```

`web/src/features/activity/Duplicates.tsx`:

```tsx
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useOnline } from '../../data/online'
import { keys } from '../../data/keys'
import { Badge } from '../../ui/Badge'
import { Money } from '../../ui/Money'
import { useToast } from '../../ui/Toast'
import { gapLabel, rowTitle } from './format'
import { useHeldDeletes } from './heldDeletes'
import { type DuplicateGroup, type RefData, dismissDuplicates, useDuplicates, useRefData } from './hooks'
import { useDeleteWithUndo } from './useDeleteWithUndo'

function PairCard({ group, refData }: { group: DuplicateGroup; refData?: RefData }) {
  const qc = useQueryClient()
  const toast = useToast()
  const isOnline = useOnline()
  const deleteWithUndo = useDeleteWithUndo()
  const [drop, setDrop] = useState<string | null>(null)
  const rows = group.transactions
  const first = rows[0]
  const last = rows[rows.length - 1]
  const name = (id: string | null) => refData?.members.find((m) => m.user_id === id)?.display_name ?? ''

  const keepBoth = async () => {
    try {
      await dismissDuplicates(rows.map((t) => t.id))
      await qc.invalidateQueries({ queryKey: keys.duplicates() })
      await qc.invalidateQueries({ queryKey: keys.transactions.counts() })
    } catch (e) {
      toast.show((e as Error).message, { tone: 'error' })
    }
  }

  return (
    <article className="card vstack dup" aria-label={`Possible duplicate: ${rowTitle(first, refData)}`}>
      <div className="between">
        <span className="h3">{rowTitle(first, refData)} · <Money amount={group.amount} /></span>
        <Badge>{gapLabel(first, last)}</Badge>
      </div>
      <div className="pair">
        {rows.map((t) => (
          <button
            key={t.id}
            type="button"
            className={drop === t.id ? 'well drop' : 'well'}
            aria-pressed={drop === t.id}
            onClick={() => setDrop(drop === t.id ? null : t.id)}
          >
            <span className="t">{rowTitle(t, refData)}</span>
            <span className="s">{t.transaction_date} · {name(t.paid_by)}</span>
            {drop === t.id && <span className="badge warn">Will be deleted</span>}
          </button>
        ))}
      </div>
      <div className="hstack">
        {drop ? (
          <button type="button" className="btn danger" onClick={() => { const t = rows.find((r) => r.id === drop)!; setDrop(null); deleteWithUndo(t) }}>
            Delete this one
          </button>
        ) : (
          <button type="button" className="btn" disabled={!isOnline} onClick={keepBoth}>Keep both</button>
        )}
      </div>
      {!isOnline && !drop && <p className="xs muted">Needs a connection</p>}
    </article>
  )
}

export function Duplicates() {
  const q = useDuplicates()
  const refData = useRefData()
  const held = useHeldDeletes()
  const groups = (q.data?.groups ?? [])
    .map((g) => ({ ...g, transactions: g.transactions.filter((t) => !held.has(t.id)) }))
    .filter((g) => g.transactions.length > 1)
  if (!q.data) return <p className="screen__note" aria-busy="true">Loading…</p>
  if (groups.length === 0) return <div className="empty" role="status"><p className="h3">No possible duplicates in the last 90 days</p></div>
  return <div className="vstack">{groups.map((g) => <PairCard key={g.transactions.map((t) => t.id).join()} group={g} refData={refData} />)}</div>
}
```

In `Activity.tsx`, add the chip after "No payer". Turning it off returns to this month:

```tsx
{!!counts?.duplicate_groups && (
  <Chip
    label="Duplicates?"
    count={counts.duplicate_groups}
    pressed={state.dups}
    onClick={() => set(state.dups ? { filter: monthRange(new Date()), dups: false } : { filter: {}, dups: true })}
  />
)}
```

and render `{state.dups ? <Duplicates /> : <Feed … />}`.

Add to `activity.css`:

```css
.dup .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.dup .well { text-align: left; display: flex; flex-direction: column; gap: 2px; min-height: 44px; border: 2px solid transparent; }
.dup .well.drop { border-color: var(--neg); }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/activity/Duplicates.test.tsx src/features/activity/Activity.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the stream's checks, then commit**

Run: `cd web && npm run typecheck && npm run lint && npm test -- src/features/activity src/ui`
Expected: PASS.

```bash
git add web/src/features/activity/
git commit -m "feat(activity): duplicates mode with Keep both and delete one"
```

---

## Stream F2: frontend selection, bulk changes, undo

**Precondition for every F2 task:** branch `feat/2c-f2` from F1 (Tasks 11–17), with B1's Task 10 merged, so `schema.d.ts` has `BulkIn`, `BulkResult`, `UndoResult` and `RecentBatchOut`.

### Task 18: Selection (long-press, Select, All, Select all N) and the BulkBar

**Stream:** F2. **Depends on:** Task 17 and Task 10.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** Match `access-home.html` §03 "Select": the app bar becomes "Cancel · N selected · All". Selected rows get a tick and a tint. The `.bulkbar` floats above the tab bar, inside the safe area.

**Files:**
- Create: `web/src/features/activity/selection.ts`, `web/src/ui/BulkBar.tsx`
- Modify: `web/src/features/activity/Activity.tsx` (selection state, app bar, ⋯ menu, "Select all N", BulkBar), `web/src/ui/ui-2c.css` (`.bulkbar`), `activity.css` (`.selbar`)
- Test: `web/src/features/activity/selection.test.ts`, `web/src/ui/BulkBar.test.tsx`, `web/src/features/activity/select.test.tsx`

**Interfaces:**
- Consumes: `Feed`'s `rowProps`, `renderRow` and `onLoaded`; `toQuery`; `isEmpty`; 2a's `useOnline`.
- Produces:
  - `selection.ts`:
    - `type Selection = {kind: 'off'} | {kind: 'picked', ids: string[]} | {kind: 'filter', filter, count} | {kind: 'bill', billId, count}`;
    - `OFF`, `reduce(s, action)`, `isSelected(s, id)`, `selectedCount(s)`, `toSelect(s)`, `expectedCount(s)`.
  - `BulkBar({count, total?, disabled?, disabledReason?, actions})`.
  - `Activity` opens `BulkSheet` (Task 19) with `initial` set to the tapped action.

**Rules (spec §4.5, resolved here):**
- **All** selects *by bill* only when the recurring item is the whole filter. Otherwise it selects *by filter*, with the dates included, so "N match" is the list shown.
- Unticking a row in an "All" selection returns to hand-picked: the loaded rows minus that one.
- Queued rows can't be selected.

- [ ] **Step 1: Write the failing tests**

`web/src/features/activity/selection.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { OFF, expectedCount, isSelected, reduce, selectedCount, toSelect } from './selection'

const OCT = { from_date: '2026-10-01', to_date: '2026-10-31' }

describe('selection', () => {
  it('All → by filter → untick → hand-picked', () => {
    let s = reduce(OFF, { type: 'enter', id: 'a' })
    expect(toSelect(s)).toEqual({ ids: ['a'] })
    s = reduce(s, { type: 'all', filter: { missing_payer: true, ...OCT }, total: 120 })
    expect(s.kind).toBe('filter')
    expect(selectedCount(s)).toBe(120)
    expect(isSelected(s, 'anything')).toBe(true)
    expect(toSelect(s)).toEqual({ filter: { missing_payer: true, ...OCT } })
    expect(expectedCount(s)).toBe(120)
    s = reduce(s, { type: 'toggle', id: 'b', loadedIds: ['a', 'b', 'c'] })
    expect(s).toEqual({ kind: 'picked', ids: ['a', 'c'] })
    expect(expectedCount(s)).toBeNull()
  })

  it('All with only a bill filter selects by bill', () => {
    const s = reduce(reduce(OFF, { type: 'enter' }), { type: 'all', filter: { recurring_bill_id: 'r1' }, total: 14 })
    expect(toSelect(s)).toEqual({ bill_id: 'r1' })
    expect(expectedCount(s)).toBe(14)
  })

  it('a bill plus anything else stays by filter', () => {
    const s = reduce(OFF, { type: 'all', filter: { recurring_bill_id: 'r1', ...OCT }, total: 1 })
    expect(s.kind).toBe('filter')
  })

  it('toggling picks and unpicks; cancel leaves selection', () => {
    let s = reduce(OFF, { type: 'toggle', id: 'a', loadedIds: [] })
    s = reduce(s, { type: 'toggle', id: 'b', loadedIds: [] })
    s = reduce(s, { type: 'toggle', id: 'a', loadedIds: [] })
    expect(toSelect(s)).toEqual({ ids: ['b'] })
    expect(reduce(s, { type: 'cancel' })).toEqual(OFF)
  })
})
```

`web/src/ui/BulkBar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BulkBar } from './BulkBar'

const actions = ['Bucket', 'Category', 'Payer', 'Method'].map((label) => ({ label, onClick: vi.fn() }))

describe('BulkBar', () => {
  it('is labelled for its count', () => {
    render(<BulkBar count={3} actions={actions} />)
    expect(screen.getByRole('toolbar', { name: 'Bulk actions for 3 selected' })).toBeInTheDocument()
  })

  it('is disabled offline with the reason', () => {
    render(<BulkBar count={3} actions={actions} disabled disabledReason="Needs a connection" />)
    expect(screen.getByText('Needs a connection')).toBeInTheDocument()
    for (const name of ['Bucket', 'Category', 'Payer', 'Method']) expect(screen.getByRole('button', { name })).toBeDisabled()
  })
})
```

`web/src/features/activity/select.test.tsx`:

```tsx
import { act, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Activity } from './Activity'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const rows = [makeTxn({ notes: 'one' }), makeTxn({ notes: 'two' }), makeTxn({ notes: 'three' })]

function setup(route = '/activity') {
  fakeApi({
    ...refRoutes({ no_payer: 3, duplicate_groups: 0 }),
    'GET /api/v1/transactions': () => pageOf(rows, { total: 120 }),
  })
  renderActivity(<Activity />, { route })
}

describe('selection mode', () => {
  it('Select, tick, All (server-side count), untick back to hand-picked', async () => {
    setup()
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getByText('120 selected')).toBeInTheDocument()
    fireEvent.click(screen.getByText('two'))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    expect(screen.getByRole('toolbar', { name: 'Bulk actions for 2 selected' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('toolbar', { name: /Bulk actions/ })).toBeNull()
  })

  it('"Select all N" under the No payer chip selects by filter', async () => {
    setup('/activity?missing_payer=1')
    fireEvent.click(await screen.findByRole('button', { name: 'Select all 120' }))
    expect(screen.getByText('120 selected')).toBeInTheDocument()
  })

  it('the bar is disabled offline', async () => {
    setup()
    fireEvent.click(await screen.findByRole('button', { name: 'More' }))
    fireEvent.click(screen.getByRole('button', { name: /^Select/ }))
    fireEvent.click(await screen.findByText('one'))
    act(() => setOnline(false)) // the rows are already on screen
    expect(screen.getByRole('button', { name: 'Bucket' })).toBeDisabled()
    expect(screen.getByText('Needs a connection')).toBeInTheDocument()
  })
})
```

The offline test goes offline after the rows are on screen (`setOnline(false)` inside `act`), so it needs no cache seeding.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/activity/selection.test.ts src/ui/BulkBar.test.tsx src/features/activity/select.test.tsx`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `selection.ts`**

```ts
import { isEmpty, toQuery, type TransactionFilter } from './filters'

export type Selection =
  | { kind: 'off' }
  | { kind: 'picked'; ids: string[] }
  | { kind: 'filter'; filter: TransactionFilter; count: number }
  | { kind: 'bill'; billId: string; count: number }

export type SelectionAction =
  | { type: 'enter'; id?: string }
  | { type: 'toggle'; id: string; loadedIds: string[] }
  | { type: 'all'; filter: TransactionFilter; total: number }
  | { type: 'cancel' }

export type BulkSelect = { ids: string[] } | { filter: Record<string, string | boolean> } | { bill_id: string }

export const OFF: Selection = { kind: 'off' }

/** By bill only when the item is the whole filter; anything more could make
 * the two selections differ. */
function billOnly(f: TransactionFilter): string | null {
  const { recurring_bill_id, ...rest } = f
  return recurring_bill_id && isEmpty(rest) ? recurring_bill_id : null
}

export function reduce(s: Selection, a: SelectionAction): Selection {
  switch (a.type) {
    case 'cancel':
      return OFF
    case 'enter':
      return s.kind === 'off' ? { kind: 'picked', ids: a.id ? [a.id] : [] } : s
    case 'all': {
      const bill = billOnly(a.filter)
      return bill ? { kind: 'bill', billId: bill, count: a.total } : { kind: 'filter', filter: a.filter, count: a.total }
    }
    case 'toggle':
      if (s.kind === 'filter' || s.kind === 'bill') return { kind: 'picked', ids: a.loadedIds.filter((id) => id !== a.id) }
      if (s.kind === 'off') return { kind: 'picked', ids: [a.id] }
      return { kind: 'picked', ids: s.ids.includes(a.id) ? s.ids.filter((i) => i !== a.id) : [...s.ids, a.id] }
  }
}

export const isSelected = (s: Selection, id: string) =>
  s.kind === 'filter' || s.kind === 'bill' || (s.kind === 'picked' && s.ids.includes(id))

export const selectedCount = (s: Selection) =>
  s.kind === 'off' ? 0 : s.kind === 'picked' ? s.ids.length : s.count

export function toSelect(s: Selection): BulkSelect {
  if (s.kind === 'filter') return { filter: toQuery(s.filter) }
  if (s.kind === 'bill') return { bill_id: s.billId }
  return { ids: s.kind === 'picked' ? s.ids : [] }
}

/** Sent with apply for filter and bill selections: the server answers 409 on drift. */
export const expectedCount = (s: Selection) => (s.kind === 'filter' || s.kind === 'bill' ? s.count : null)
```

- [ ] **Step 4: Implement `BulkBar` and the selection UI**

`web/src/ui/BulkBar.tsx`:

```tsx
import type { ReactNode } from 'react'
import './ui-2c.css'

type Props = {
  count: number
  total?: ReactNode
  disabled?: boolean
  disabledReason?: string
  actions: { label: string; onClick: () => void }[]
}

export function BulkBar({ count, total, disabled, disabledReason, actions }: Props) {
  return (
    <div className="bulkbar" role="toolbar" aria-label={`Bulk actions for ${count} selected`}>
      <span className="bulkbar__sum">
        <b className="num">{count}</b>
        {total !== undefined && <> · {total}</>}
        {disabled && disabledReason && <span className="bulkbar__why">{disabledReason}</span>}
      </span>
      {actions.map((a) => (
        <button key={a.label} type="button" className="btn" disabled={disabled || count === 0} onClick={a.onClick}>
          {a.label}
        </button>
      ))}
    </div>
  )
}
```

Add to `ui-2c.css`:

```css
.bulkbar {
  position: fixed; left: 12px; right: 12px; z-index: 6;
  bottom: calc(var(--tabbar-h, 64px) + env(safe-area-inset-bottom) + 8px); /* above the tab bar */
  max-width: 456px; margin-inline: auto;
  background: var(--ink); color: var(--bg); border-radius: var(--r-lg);
  padding: 8px 8px 8px 16px; display: flex; align-items: center; gap: 6px; box-shadow: 0 12px 30px rgba(0, 0, 0, .3);
}
.bulkbar__sum { flex: 1; display: grid; font-size: 13.5px; }
.bulkbar__why { font-size: 11.5px; opacity: .75; }
.bulkbar .btn { min-height: 44px; padding: 0 10px; font-size: 13.5px; background: color-mix(in srgb, var(--bg) 16%, transparent); color: var(--bg); }
.bulkbar .btn:disabled { opacity: .45; }
```

If 2a's tab bar exposes its height under another variable name, use that name instead of `--tabbar-h`.

In `Activity.tsx`:
- Add `const [sel, dispatch] = useReducer(reduce, OFF)`, `const [loaded, setLoaded] = useState<{ ids: string[]; rows: Txn[]; total: number }>({ ids: [], rows: [], total: 0 })` and `const [bulk, setBulk] = useState<null | 'bucket' | 'category' | 'payer' | 'method'>(null)`.
- Header:
  - when `sel.kind === 'off'`: `<TopBar title="Activity" />` plus a `<button aria-label="More">⋯</button>`. It opens an `OptionSheet` titled "Activity" with the options `select` ("Select") and `recent` ("Recent bulk changes"; Task 20 handles it).
  - when selecting: a `<div className="selbar" role="toolbar" aria-label="Selection">` with `Cancel`, `<span aria-live="polite">{selectedCount(sel)} selected</span>` and `All` (`dispatch({ type: 'all', filter: f, total: loaded.total })`).
- Under the chips, when `f.missing_payer && loaded.total > 0`: `<button className="btn ghost sm">Select all {loaded.total}</button>`, which dispatches `enter`, then `all`.
- `Feed`:
  - pass `onLoaded={(rows, total) => setLoaded({ ids: rows.map((r) => r.id), rows, total })}`;
  - when selecting, pass `rowProps={(t) => ({ selecting: true, selected: isSelected(sel, t.id), onOpen: (id) => dispatch({ type: 'toggle', id, loadedIds: loaded.ids }) })}`;
  - when selecting, `renderRow` returns `row` as is (no swipe); otherwise it is the `SwipeRow` from Task 15 plus `onLongPress={() => dispatch({ type: 'enter', id: t.id })}`.
- When selecting, render `<BulkBar>`:
  - `count={selectedCount(sel)}`;
  - for a picked selection, `total` is `<Money amount={sum of the picked loaded rows' amounts} />`;
  - `disabled={!online}`, with `disabledReason="Needs a connection"`;
  - `actions` Bucket, Category, Payer and Method each call `setBulk(<that>)`.

Add to `activity.css`:

```css
.selbar { display: flex; align-items: center; justify-content: space-between; min-height: 44px; padding: env(safe-area-inset-top) 16px 0; }
.selbar button { min-height: 44px; min-width: 44px; background: none; border: 0; color: var(--accent); font-weight: 650; }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/activity/selection.test.ts src/ui/BulkBar.test.tsx src/features/activity/select.test.tsx src/features/activity/swipe.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/activity/ web/src/ui/BulkBar.tsx web/src/ui/BulkBar.test.tsx web/src/ui/ui-2c.css
git commit -m "feat(activity): selection by hand, by filter or by bill; BulkBar"
```

---

### Task 19: Bulk sheet, preview and apply

**Stream:** F2. **Depends on:** Task 18.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.** The preview writes before → after as text, not only as bars (spec §7). Use 2a's `ProgressBar` with its 80% and 100% tints. Each skipped-reason group is a native `<details>`.

**Files:**
- Create: `web/src/features/activity/BulkSheet.tsx`, `web/src/features/activity/BulkPreview.tsx`
- Modify: `web/src/features/activity/hooks.ts` (`previewBulk`, `applyBulk`, the types), `web/src/features/activity/Activity.tsx` (render `BulkSheet`; handle apply)
- Test: `web/src/features/activity/BulkSheet.test.tsx`

**Interfaces:**
- Consumes: Task 18's `Selection`, `toSelect` and `expectedCount`; `RefData`; `RecurringItem`; `online()`; 2a's `unwrap` and `ApiError`; `ACTIVITY_WRITES`.
- Produces:
  - `hooks.ts`:
    - the types `BulkChanges = S['ChangesIn']`, `BulkResult = S['BulkResult']`, `BulkReq = {select, changes, move_bill}`;
    - `previewBulk(req) -> Promise<BulkResult>` (`dry_run: true`);
    - `applyBulk(req, expected: number | null) -> Promise<BulkResult>`.
  - `BulkSheet({open, selection, rows, refData, items, initial, onApplied, onClose})`, where `onApplied(result, req)` is called on 200.
  - `BulkPreview({result})`.

**Choice rules (spec §4.5):**
- "No bucket" is offered when every selected row is income. "No bucket (Fixed cost)" is offered only when every selected row is a bucket-less Fixed cost.
  - For a filter selection, that means `filter.type === 'income'` or `filter.fixed`.
  - For a bill selection, it means an `in` item ("No bucket").
  - A selection with any bucketed bill payment never offers it.
- "Also move the bill, so future payments go here":
  - shown only *by bill* with a bucket change, and hidden for `in` items;
  - disabled for an event bucket;
  - off by default.

- [ ] **Step 1: Write the failing test**

`web/src/features/activity/BulkSheet.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi, reply, type FakeRequest } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { BulkSheet } from './BulkSheet'
import type { Selection } from './selection'
import { REF, makeTxn, renderActivity } from './testing'

afterEach(resetTestEnv)

const BULK = 'POST /api/v1/transactions/bulk' as const

const RESULT = {
  dry_run: true, batch_id: null, matched: 3, changed: 2, unchanged: 1, total_out: 90, total_in: 0,
  skipped: [], bill: null, undo_until: null,
  buckets: [{
    bucket_id: 'b-bills', name: 'Bills', kind: 'monthly', budget: 300, period_start: '2026-10-01', period_end: '2026-10-31',
    spent_before: 100, spent_after: 190, moved_in: 90, moved_out: 0, outside_period: 1,
  }],
}
const ITEMS = [{ id: 'r1', name: 'Cosmote', direction: 'out' }, { id: 'r-sal', name: 'Salary', direction: 'in' }]
const ECHO = {
  [BULK]: (req: FakeRequest) => {
    const dry = (req.body as { dry_run: boolean }).dry_run
    return { ...RESULT, dry_run: dry, batch_id: dry ? null : 'batch1' } as never
  },
}

function renderSheet(selection: Selection, rows = [makeTxn()]) {
  const onApplied = vi.fn()
  renderActivity(
    <BulkSheet open selection={selection} rows={rows} refData={REF} items={ITEMS} initial="bucket" onApplied={onApplied} onClose={() => {}} />,
  )
  return onApplied
}

const pickBucket = (value: string) => fireEvent.change(screen.getByLabelText('Bucket'), { target: { value } })

describe('BulkSheet', () => {
  it('previews with dry_run, then applies with expected_count', async () => {
    const fake = fakeApi(ECHO)
    const onApplied = renderSheet({ kind: 'filter', filter: { missing_payer: true }, count: 3 })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('Bills: €100.00 → €190.00 of €300.00')).toBeInTheDocument()
    expect(screen.getByText('+1 from other periods, not in this budget')).toBeInTheDocument()
    expect(screen.getByText('1 already set')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Apply to 2' }))
    await waitFor(() => expect(onApplied).toHaveBeenCalled())
    const [preview, apply] = fake.callsTo(BULK).map((c) => c.body as Record<string, unknown>)
    expect(preview).toMatchObject({ dry_run: true, select: { filter: { missing_payer: true } }, changes: { bucket_id: 'b-bills' } })
    expect(apply).toMatchObject({ dry_run: false, expected_count: 3 })
  })

  it('hand-picked rows apply without expected_count', async () => {
    const fake = fakeApi(ECHO)
    renderSheet({ kind: 'picked', ids: ['t1'] })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 2' }))
    await waitFor(() => expect(fake.callsTo(BULK)).toHaveLength(2))
    expect((fake.callsTo(BULK)[1].body as { expected_count: unknown }).expected_count).toBeNull()
  })

  it('a 409 on apply re-previews and shows the message', async () => {
    const bodies: { dry_run: boolean }[] = []
    fakeApi({
      [BULK]: (req) => {
        const body = req.body as { dry_run: boolean }
        bodies.push(body)
        if (!body.dry_run) return reply(409, { detail: 'The selection changed: 4 now match. Preview again.' })
        return { ...RESULT, matched: bodies.length > 1 ? 4 : 3 } as never
      },
    })
    renderSheet({ kind: 'filter', filter: { q: 'x' }, count: 3 })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply to 2' }))
    expect(await screen.findByText('The selection changed: 4 now match. Preview again.')).toBeInTheDocument()
    await waitFor(() => expect(bodies.filter((b) => b.dry_run)).toHaveLength(2))
  })

  it('a 400 stays open with the server detail; a network failure says nothing changed', async () => {
    const fake = fakeApi({ [BULK]: () => reply(400, { detail: 'That bucket is archived. Choose an active one.' }) })
    renderSheet({ kind: 'picked', ids: ['t1'] })
    pickBucket('b-bills')
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('That bucket is archived. Choose an active one.')).toBeInTheDocument()
    fake.down()
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText("Couldn't reach the server. Nothing was changed.")).toBeInTheDocument()
  })

  it('offers "Also move the bill" only by bill, off by default, disabled for an event bucket', () => {
    renderSheet({ kind: 'bill', billId: 'r1', count: 2 })
    expect(screen.queryByLabelText(/Also move the bill/)).toBeNull()
    pickBucket('b-day')
    expect((screen.getByLabelText(/Also move the bill/) as HTMLInputElement).checked).toBe(false)
    pickBucket('b-trip')
    expect(screen.getByLabelText(/Also move the bill/)).toBeDisabled()
  })

  it('hides the bill toggle for an in item and for hand-picked rows', () => {
    renderSheet({ kind: 'bill', billId: 'r-sal', count: 2 })
    pickBucket('b-day')
    expect(screen.queryByLabelText(/Also move the bill/)).toBeNull()
  })

  it('offers "No bucket (Fixed cost)" only when every row is a bucket-less Fixed cost', () => {
    const fixed = makeTxn({ bucket_id: null, recurring_bill_id: 'r1' })
    renderSheet({ kind: 'picked', ids: [fixed.id] }, [fixed])
    expect(screen.getByRole('option', { name: 'No bucket (Fixed cost)' })).toBeInTheDocument()
  })

  it('never offers it with a bucketed bill payment in the selection', () => {
    const fixed = makeTxn({ bucket_id: null, recurring_bill_id: 'r1' })
    const paid = makeTxn({ bucket_id: 'b-bills', recurring_bill_id: 'r1' })
    renderSheet({ kind: 'picked', ids: [fixed.id, paid.id] }, [fixed, paid])
    expect(screen.queryByRole('option', { name: /No bucket/ })).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/activity/BulkSheet.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Add to `hooks.ts`:

```ts
export type BulkChanges = S['ChangesIn']
export type BulkResult = S['BulkResult']
export type BulkReq = { select: import('./selection').BulkSelect; changes: BulkChanges; move_bill: boolean }

export function previewBulk(req: BulkReq): Promise<BulkResult> {
  return online(() => unwrap(api.POST('/api/v1/transactions/bulk', { body: { ...req, dry_run: true } as never })))
}
export function applyBulk(req: BulkReq, expected: number | null): Promise<BulkResult> {
  return online(() =>
    unwrap(api.POST('/api/v1/transactions/bulk', { body: { ...req, dry_run: false, expected_count: expected } as never })),
  )
}
```

`web/src/features/activity/BulkPreview.tsx`:

```tsx
import { Money } from '../../ui/Money'
import { ProgressBar } from '../../ui/ProgressBar'
import type { BulkResult } from './hooks'

const eur = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })

export function BulkPreview({ result }: { result: BulkResult }) {
  const reasons = new Map<string, string[]>()
  for (const s of result.skipped) reasons.set(s.reason, [...(reasons.get(s.reason) ?? []), s.id])
  return (
    <div className="vstack bulk-preview" aria-live="polite">
      <p>
        <b>{result.changed}</b> of {result.matched} change · out <Money amount={result.total_out} />
        {result.total_in > 0 && <> · in <Money amount={result.total_in} /></>}
      </p>
      {result.unchanged > 0 && <p className="muted">{result.unchanged} already set</p>}
      {result.buckets.map((b) => (
        <div key={b.bucket_id ?? 'none'} className="vstack">
          <p>
            {b.name}: {eur.format(b.spent_before)} → {eur.format(b.spent_after)}
            {b.budget != null ? ` of ${eur.format(b.budget)}` : ''}
          </p>
          {b.budget != null && <ProgressBar value={b.spent_after} max={b.budget} label={`${b.name} after the change`} />}
          <p className="xs muted">{b.kind === 'event' ? `${b.period_start ?? '…'} to ${b.period_end ?? '…'}` : 'This month'}</p>
          {b.outside_period > 0 && <p className="xs muted">+{b.outside_period} from other periods, not in this budget</p>}
        </div>
      ))}
      {result.bill && (
        <p>{result.bill.name} moves from {result.bill.bucket_before ?? 'no bucket'} to {result.bill.bucket_after ?? 'no bucket'}</p>
      )}
      {[...reasons].map(([reason, ids]) => (
        <details key={reason}>
          <summary>{ids.length} skipped: {reason}</summary>
          <ul>{ids.map((id) => <li key={id}><a href={`/app/activity/${id}`}>{id.slice(0, 8)}</a></li>)}</ul>
        </details>
      ))}
    </div>
  )
}
```

`web/src/features/activity/BulkSheet.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Sheet } from '../../ui/Sheet'
import { BulkPreview } from './BulkPreview'
import { METHOD_LABELS } from './format'
import { ApiError } from '../../data/http'
import { useOnline } from '../../data/online'
import { applyBulk, type BulkChanges, type BulkReq, type BulkResult, previewBulk, type RecurringItem, type RefData, type Txn } from './hooks'
import { OWN_SHARE } from './pickers'
import { expectedCount, type Selection, toSelect } from './selection'

type Field = 'bucket' | 'category' | 'payer' | 'method'
const KEEP = '__keep'
const NONE = '__none'

type Props = {
  open: boolean
  selection: Selection
  rows: Txn[] // the loaded rows (hand-picked rule checks)
  refData?: RefData
  items?: RecurringItem[]
  initial: Field
  onApplied: (result: BulkResult, req: BulkReq) => void
  onClose: () => void
}

function noBucketLabel(sel: Selection, rows: Txn[], items?: RecurringItem[]): string | null {
  if (sel.kind === 'filter') return sel.filter.type === 'income' ? 'No bucket' : sel.filter.fixed ? 'No bucket (Fixed cost)' : null
  if (sel.kind === 'bill') return items?.find((i) => i.id === sel.billId)?.direction === 'in' ? 'No bucket' : null
  if (sel.kind !== 'picked') return null
  const picked = rows.filter((r) => sel.ids.includes(r.id))
  if (picked.length !== sel.ids.length || picked.length === 0) return null
  if (picked.every((r) => r.type === 'income')) return 'No bucket'
  if (picked.every((r) => r.type === 'expense' && r.recurring_bill_id && !r.bucket_id)) return 'No bucket (Fixed cost)'
  return null
}

export function BulkSheet({ open, selection, rows, refData, items, initial, onApplied, onClose }: Props) {
  const isOnline = useOnline()
  const [values, setValues] = useState<Record<Field, string>>({ bucket: KEEP, category: KEEP, payer: KEEP, method: KEEP })
  const [moveBill, setMoveBill] = useState(false)
  const [preview, setPreview] = useState<BulkResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (open) {
      setPreview(null)
      setError(null)
      setMoveBill(false)
    }
  }, [open])

  const noBucket = noBucketLabel(selection, rows, items)
  const target = refData?.buckets.find((b) => b.id === values.bucket)
  const bill = selection.kind === 'bill' ? items?.find((i) => i.id === selection.billId) : undefined
  const showMoveBill = !!bill && bill.direction !== 'in' && values.bucket !== KEEP
  const set = (f: Field, v: string) => {
    setValues((s) => ({ ...s, [f]: v }))
    setPreview(null)
  }

  const changes = (): BulkChanges => {
    const c: Record<string, unknown> = {}
    if (values.bucket !== KEEP) c.bucket_id = values.bucket === NONE ? null : values.bucket
    if (values.category !== KEEP) c.category_id = values.category === NONE ? null : values.category
    if (values.payer !== KEEP) c.payer = values.payer === OWN_SHARE ? { mode: 'own_share' } : { mode: 'single', user_id: values.payer }
    if (values.method !== KEEP) c.payment_method = values.method
    return c as BulkChanges
  }
  const req = (): BulkReq => ({ select: toSelect(selection), changes: changes(), move_bill: showMoveBill && moveBill && target?.kind !== 'event' })

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const doPreview = () => run(async () => setPreview(await previewBulk(req())))
  const doApply = () =>
    run(async () => {
      const r = req()
      try {
        onApplied(await applyBulk(r, expectedCount(selection)), r)
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          setPreview(await previewBulk(r)) // re-preview, keep the message
        }
        throw e
      }
    })

  const nothing = preview && preview.changed === 0 && !(preview.bill && preview.bill.bucket_before !== preview.bill.bucket_after)
  const select = (f: Field, label: string, options: { value: string; label: string }[]) => (
    <label className="field">
      {label}
      <select autoFocus={f === initial} value={values[f]} onChange={(e) => set(f, e.target.value)}>
        <option value={KEEP}>Leave as is</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )

  return (
    <Sheet open={open} onClose={onClose} title="Change selected">
      <div className="vstack bulk-sheet">
        {select('bucket', 'Bucket', [
          ...(refData?.buckets.filter((b) => b.status === 'active').map((b) => ({ value: b.id, label: b.name })) ?? []),
          ...(noBucket ? [{ value: NONE, label: noBucket }] : []),
        ])}
        {showMoveBill && (
          <label className="between toggle-row">
            <span>Also move the bill, so future payments go here</span>
            <input type="checkbox" role="switch" checked={moveBill && target?.kind !== 'event'} disabled={target?.kind === 'event'} onChange={(e) => setMoveBill(e.target.checked)} />
          </label>
        )}
        {select('category', 'Category', [
          ...(refData?.categories.map((c) => ({ value: c.id, label: c.name })) ?? []),
          { value: NONE, label: 'No category' },
        ])}
        {select('payer', 'Payer', [
          ...(refData?.members.map((m) => ({ value: m.user_id, label: m.display_name ?? 'Member' })) ?? []),
          { value: OWN_SHARE, label: 'Each paid their own share' },
        ])}
        {select('method', 'Method', Object.entries(METHOD_LABELS).map(([value, label]) => ({ value, label })))}

        {error && <p className="error" role="alert">{error}</p>}
        {preview && <BulkPreview result={preview} />}

        {!preview ? (
          <button type="button" className="btn" disabled={busy || !isOnline || Object.values(values).every((v) => v === KEEP)} onClick={doPreview}>
            Preview
          </button>
        ) : (
          <button type="button" className="btn" disabled={busy || !isOnline || !!nothing} onClick={doApply}>
            {nothing ? 'Nothing to change' : `Apply to ${preview.changed}`}
          </button>
        )}
        {!isOnline && <p className="xs muted">Needs a connection</p>}
      </div>
    </Sheet>
  )
}
```

In `Activity.tsx`, render the sheet and handle a successful apply:

```tsx
const qc = useQueryClient()
const toast = useToast()
// ...
<BulkSheet
  open={bulk !== null}
  initial={bulk ?? 'bucket'}
  selection={sel}
  rows={loaded.rows}
  refData={refData}
  items={items}
  onClose={() => setBulk(null)}
  onApplied={(result, req) => {
    setBulk(null)
    dispatch({ type: 'cancel' })
    for (const key of ACTIVITY_WRITES) void qc.invalidateQueries({ queryKey: key }) // includes recurring, for "Also move the bill"
    toast.show('bucket_id' in req.changes ? `Moved ${result.changed} payments` : `Changed ${result.changed}`, {
      durationMs: 10_000,
    })
  }}
/>
```

`ACTIVITY_WRITES` includes `keys.recurring.all`, 2a's prefix that covers both the recurring list and `recurring/entries`. Task 20 adds the toast's Undo action.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/activity/BulkSheet.test.tsx src/features/activity/select.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/activity/
git commit -m "feat(activity): bulk sheet with budget preview and guarded apply"
```

---

### Task 20: Undo (toast, detail history, Recent bulk changes)

**Stream:** F2. **Depends on:** Task 19.

**Load skills frontend-design, mobile-native, apple-design before writing UI code.**

**Files:**
- Create: `web/src/features/activity/RecentBulk.tsx`, `web/src/features/activity/useUndoBulk.tsx`
- Modify: `web/src/features/activity/hooks.ts` (`undoBulk`, `useRecentBulk`), `Activity.tsx` (the toast's Undo; ⋯ › Recent bulk changes), `Detail.tsx` ("Undo this change" in history)
- Test: `web/src/features/activity/undo.test.tsx`

**Interfaces:**
- Consumes: `online`, 2a's `unwrap` and `ApiError`, `ACTIVITY_WRITES`, `HistoryList`'s `renderAction`, `useToast`, `Sheet`.
- Produces:
  - `hooks.ts`: `undoBulk(batchId) -> Promise<UndoResult>` and `useRecentBulk()` (`keys.bulkRecent()`, `GET /api/v1/transactions/bulk?limit=10`);
  - `useUndoBulk(): (batchId: string) => Promise<void>`. It shows the result toast ("Restored N · M changed since, left as they are" with a "Details" action) and toasts a 409's detail;
  - `RecentBulk({open, onClose})`.

- [ ] **Step 1: Write the failing test**

`web/src/features/activity/undo.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi, reply } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { RecentBulk } from './RecentBulk'
import { Detail } from './Detail'
import { makeTxn, refRoutes, renderActivity } from './testing'

afterEach(resetTestEnv)

const UNDO = 'POST /api/v1/transactions/bulk/{batch_id}/undo' as const

const RECENT = [
  { id: 'b2', created_at: '2026-10-07T09:00:00', created_by: 'Giorgos', summary: 'Bucket → Bills · 12 transactions', row_count: 12, undone_at: null, can_undo: true },
  { id: 'b1', created_at: '2026-10-05T09:00:00', created_by: 'Maria', summary: 'Payer → Maria · 3 transactions', row_count: 3, undone_at: '2026-10-05T10:00:00', can_undo: false },
]

describe('undo', () => {
  it('Recent bulk changes lists the last batches; Undo reports skips', async () => {
    const fake = fakeApi({
      'GET /api/v1/transactions/bulk': () => RECENT as never,
      [UNDO]: () => ({ restored: 11, skipped: [{ id: 'x', code: 'changed_since', reason: 'Changed since' }], bill_restored: false }) as never,
    })
    renderActivity(<RecentBulk open onClose={() => {}} />)
    expect(await screen.findByText('Bucket → Bills · 12 transactions')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Undo' })).toHaveLength(1) // only the one that can
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Restored 11 · 1 changed since, left as they are')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Details' })).toBeInTheDocument()
    expect(fake.callsTo(UNDO).map((c) => c.path)).toEqual(['/api/v1/transactions/bulk/b2/undo'])
  })

  it('a 409 shows the detail', async () => {
    fakeApi({
      'GET /api/v1/transactions/bulk': () => RECENT as never,
      [UNDO]: () => reply(409, { detail: 'Changes can be undone for 24 hours.' }),
    })
    renderActivity(<RecentBulk open onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Changes can be undone for 24 hours.')).toBeInTheDocument()
  })

  it('the detail history offers "Undo this change" for an undoable bulk event', async () => {
    const row = makeTxn({ id: 'h1', merchant: 'Cosmote' })
    const fake = fakeApi({
      ...refRoutes(),
      'GET /api/v1/transactions/{txn_id}': () => row,
      'GET /api/v1/recurring/entries': () => [],
      'GET /api/v1/transactions/{txn_id}/history': () =>
        ({ events: [{ at: '2026-10-07T09:00:00', kind: 'bulk_change', by: 'Giorgos', text: 'Bucket: Day to day → Bills', batch_id: 'b2', can_undo: true }] }) as never,
      [UNDO]: () => ({ restored: 1, skipped: [], bill_restored: false }) as never,
    })
    renderActivity(<Detail />, { route: '/activity/h1', path: '/activity/:id' })
    fireEvent.click(await screen.findByRole('button', { name: 'Undo this change' }))
    await waitFor(() => expect(fake.callsTo(UNDO).map((c) => c.path)).toEqual(['/api/v1/transactions/bulk/b2/undo']))
    expect(await screen.findByText('Restored 1')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/activity/undo.test.tsx`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

Add to `hooks.ts`:

```ts
export type UndoResult = S['UndoResult']
export type RecentBatch = S['RecentBatchOut']

export function undoBulk(batchId: string): Promise<UndoResult> {
  return online(() =>
    unwrap(api.POST('/api/v1/transactions/bulk/{batch_id}/undo', { params: { path: { batch_id: batchId } } })),
  )
}
export function useRecentBulk() {
  return useCachedQuery(keys.bulkRecent(), (signal) =>
    unwrap(api.GET('/api/v1/transactions/bulk', { params: { query: { limit: 10 } }, signal })),
  )
}
```

`web/src/features/activity/useUndoBulk.tsx`:

```tsx
import { useQueryClient } from '@tanstack/react-query'
import { keys } from '../../data/keys'
import { useToast } from '../../ui/Toast'
import { ACTIVITY_WRITES, undoBulk } from './hooks'

export function undoMessage(restored: number, skipped: number): string {
  return skipped ? `Restored ${restored} · ${skipped} changed since, left as they are` : `Restored ${restored}`
}

/** Undo a batch from anywhere (toast, detail history, Recent bulk changes). */
export function useUndoBulk(onDetails?: (skipped: { id: string; reason: string }[]) => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return async (batchId: string) => {
    try {
      const r = await undoBulk(batchId)
      for (const key of ACTIVITY_WRITES) void qc.invalidateQueries({ queryKey: key }) // recurring.all is in it, for a restored bill
      toast.show(undoMessage(r.restored, r.skipped.length), {
        action: r.skipped.length && onDetails ? { label: 'Details', onClick: () => onDetails(r.skipped) } : undefined,
      })
    } catch (e) {
      void qc.invalidateQueries({ queryKey: keys.bulkRecent() }) // the Undo button goes away
      toast.show((e as Error).message, { tone: 'error' })
    }
  }
}
```

`web/src/features/activity/RecentBulk.tsx`:

```tsx
import { useState } from 'react'
import { Sheet } from '../../ui/Sheet'
import { useOnline } from '../../data/online'
import { useRecentBulk } from './hooks'
import { useUndoBulk } from './useUndoBulk'

const when = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export function RecentBulk({ open, onClose }: { open: boolean; onClose: () => void }) {
  const recent = useRecentBulk().data ?? []
  const isOnline = useOnline()
  const [details, setDetails] = useState<{ id: string; reason: string }[] | null>(null)
  const undo = useUndoBulk(setDetails)
  return (
    <Sheet open={open} onClose={onClose} title="Recent bulk changes">
      {recent.length === 0 && <p className="muted">No bulk changes yet</p>}
      <ul className="list">
        {recent.map((b) => (
          <li key={b.id} className="row between">
            <span className="main">
              <span className="t">{b.summary}</span>
              <span className="s">{when.format(new Date(b.created_at))}{b.created_by ? ` · ${b.created_by}` : ''}{b.undone_at ? ' · Undone' : ''}</span>
            </span>
            {b.can_undo && <button type="button" className="btn ghost sm" disabled={!isOnline} onClick={() => void undo(b.id)}>Undo</button>}
          </li>
        ))}
      </ul>
      {details && (
        <section aria-label="Left as they are">
          <ul>{details.map((d) => <li key={d.id}><a href={`/app/activity/${d.id}`}>{d.reason}</a></li>)}</ul>
        </section>
      )}
    </Sheet>
  )
}
```

Wire it up in three places:
- **`Activity.tsx`:**
  - the apply toast from Task 19 gains `action: result.batch_id ? { label: 'Undo', onClick: () => void undo(result.batch_id!) } : undefined`, where `const undo = useUndoBulk()`;
  - ⋯ › "Recent bulk changes" opens `<RecentBulk open={…} onClose={…} />`.
- **`Detail.tsx`:** inside `Detail`, `const undo = useUndoBulk()`. Pass `HistoryList` this `renderAction`:

```tsx
(e) => e.kind === 'bulk_change' && e.can_undo && e.batch_id
  ? <button type="button" className="btn ghost sm" disabled={!online} onClick={() => void undo(e.batch_id!)}>Undo this change</button>
  : null
```

This replaces the `historyAction` prop, so remove that prop from `Detail`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/activity/undo.test.tsx src/features/activity/Detail.test.tsx src/features/activity/BulkSheet.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/activity/
git commit -m "feat(activity): undo a bulk change from the toast, the detail or Recent bulk changes"
```

---

### Task 21: 2a Item sheet gets "See payments"

**Stream:** F2. **Depends on:** Task 13, and 2a's `ItemSheet.tsx` merged (2a stream D).

**Load skills frontend-design, mobile-native, apple-design before writing UI code.**

**Files:**
- Modify: `web/src/features/plan/ItemSheet.tsx`
- Test: `web/src/features/plan/ItemSheet.test.tsx` (add one case)

**Interfaces:**
- Consumes: 2a's `ItemSheet` props (an existing item has an `id`).
- Produces: a link from an existing item to `/activity?recurring_bill_id=<id>`. That deep link is all time (Task 12's rule), and "All" there selects *by bill*.

- [ ] **Step 1: Write the failing test**

Add to `web/src/features/plan/ItemSheet.test.tsx`, using that file's existing render helper and a saved item fixture:

```tsx
it('links an existing item to its payments in Activity', async () => {
  renderItemSheet({ item: { ...existingItem, id: 'r-cosmote' } }) // the file's helper
  expect(await screen.findByRole('link', { name: 'See payments' })).toHaveAttribute(
    'href',
    '/activity?recurring_bill_id=r-cosmote',
  )
})
```

If the router basename is `/app` in that test's router, expect `'/app/activity?recurring_bill_id=r-cosmote'`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/ItemSheet.test.tsx`
Expected: FAIL (no such link).

- [ ] **Step 3: Implement**

In `ItemSheet.tsx`, for an existing item (it has an `id`), add next to the sheet's secondary actions:

```tsx
<Link className="btn ghost" to={`/activity?recurring_bill_id=${encodeURIComponent(item.id)}`}>See payments</Link>
```

with `import { Link } from 'react-router'`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/ItemSheet.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/ItemSheet.tsx web/src/features/plan/ItemSheet.test.tsx
git commit -m "feat(plan): See payments from an item opens its Activity"
```

---

## Integration

### Task 22: Full checks, Postgres run and manual pass

**Stream:** Integration. **Depends on:** every task (2d M → B2 → B1 with Task 10 → F1 → F2 merged).

**Files:** none new. Fix only what the checks find, in the file that owns it.

- [ ] **Step 1: Backend, full suite on SQLite**

Run: `.venv/bin/python -m pytest -n 8 -o addopts="" -p no:cacheprovider`
Expected: all pass, including `test_single_head`, `test_schema_matches_models` and the production-shaped upgrade test.

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: clean.

- [ ] **Step 2: Postgres 18 run of the bulk tests**

Container `pgp1` must be running (`docker start pgp1`).
Run: `TEST_DATABASE_URL=postgresql://postgres:t@localhost:55441/t .venv/bin/python -m pytest tests/test_bulk_pg.py tests/test_bulk_api.py tests/test_bulk_undo.py tests/test_bulk_filter.py tests/test_bulk_migration.py tests/test_activity_feed.py tests/test_activity_join.py tests/test_migrations.py -o addopts="" -p no:cacheprovider`
Expected: PASS, with nothing skipped in `test_bulk_pg.py`. No `-n`: each test resets the one Postgres schema.

- [ ] **Step 3: Web checks**

Run: `cd web && npm run gen:api && git diff --exit-code src/api/ && npm run typecheck && npm test && npm run lint && npm run build`
Expected: no diff in the generated types (they were committed in Task 10), and everything passes.

- [ ] **Step 4: Manual pass in Chrome at 390×844, light and dark**

Seed a local database. Start the API (`.venv/bin/uvicorn app.main:app --reload`) and `cd web && npm run dev`, then open `http://localhost:5173/app/activity` in Chrome DevTools device mode at 390×844. Do each flow once in light mode and once in dark mode:
1. **Move a bill's payments and the bill.**
   - Plan › Items › Cosmote › See payments, then Select › All. The app bar reads "N selected", by bill.
   - Bucket › Bills → Day to day, with "Also move the bill" on, then Preview. Check that both buckets show `before → after` as text with the period, plus "+N from other periods" if any.
   - Apply. The toast reads "Moved N payments · Undo" for 10 s.
   - Undo from the toast: the rows go back and so does the item's bucket (Plan › Items).
2. **Clear No payer.** Tap the "No payer N" chip, then "Select all N", then Payer › Maria. Preview, then Apply. The chip disappears once its count is 0.
3. **Resolve a duplicate.**
   - Duplicates? chip: tap one row ("Will be deleted"), then Delete this one, and wait 5 s. The other pair: Keep both.
   - Reload: the dismissed pair stays hidden, and as the partner user too.
4. **Swipe and offline.** Swipe a row left (Delete toast, Undo), then right (it opens `/new?from=`). With DevTools › Network › Offline, check that:
   - the feed shows the "Offline · updated" banner;
   - a field edit in the detail queues;
   - the BulkBar says "Needs a connection".

Take screenshots of the feed, the detail, the bulk preview and duplicates in both themes. Check for horizontal overflow, contrast, 44 pt targets, the BulkBar sitting above the tab bar, and the safe-area insets.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix(activity): integration fixes from the full checks and manual pass"
```

Before deploying, take a `pg_dump`, because migration `c9d0e1f2a3b4` runs. The user pushes to `main`.
