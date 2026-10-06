# Planning Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the backend recurring items in both directions on real schedule rules (Greek business days, Orthodox Easter), a fixed lifecycle for expected entries, Fixed-cost expenses, match suggestions, monthly/event buckets and the planning figures, exposed under `/api/v1`. The old Jinja app keeps working on the same database.

**Architecture:**
- One pure date engine. `app/core/calendar_gr.py` holds the Greek calendar and `app/core/schedule.py` turns a rule into dates. `app.services.bills.generate_occurrences` is the only writer of `bill_occurrences` rows and uses that engine for the old app, the new API and the scheduler alike.
- One additive migration (spec §6.1). Stored statuses stay `unpaid`/`paid`/`skipped`; the API shows them as `expected`/`done`/`skipped`.
- Lifecycle fixes live in shared services, so the old app gets them too:
  - paused items are hidden;
  - only untouched future entries are regenerated;
  - nothing expected is created before today;
  - auto-pay has a 3-day window;
  - a soft delete reopens the entry.
- New services:
  - `app/services/matching.py`: suggestions, never auto-linked.
  - `app/services/budgets.py`: bucket kinds and pace.
  - `app/services/planning.py`: entries, month picture, Upcoming, Year.
  - `app/services/usual.py`: categories vs usual.
- New routers `recurring`, `matches` and `plan` use Pydantic response models so the TypeScript types can be generated.

**Tech Stack:** Python 3.12, FastAPI 0.115, Pydantic 2.13, SQLAlchemy 2.0, Alembic, python-dateutil (`dateutil.easter`, `relativedelta`), APScheduler, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-06-planning-redesign-design.md` (binding). Evidence: `docs/redesign/process-audit.md`. Read both before Task 1.

## Global Constraints

- **Additive only.** No column, table or constraint is dropped or renamed. `buckets.type`, `goal_amount`, `show_income`, `interval_months` and `frequency` stay and keep working (spec §6.1).
- **Stored occurrence statuses are unchanged:** `unpaid` / `paid` / `skipped`. The API maps them to `expected` / `done` / `skipped`.
- **The old app keeps working until cutover.**
  - Its bills pages, dashboard and bill reminders use `direction = 'out'` only.
  - Items with `rule_kind != 'monthly_interval'` or `direction = 'in'` are read-only there, with "Edit in the new app".
  - Its pay route keeps claim-only for bucket-less bills (spec §6.2).
- **Every existing test passes unchanged.** Run the whole suite on SQLite (`.venv/bin/python -m pytest -q`) and on Postgres 18 (`TEST_DATABASE_URL=postgresql://… .venv/bin/python -m pytest -q`).
- `.venv/bin/ruff check app tests alembic scripts` and `.venv/bin/ruff format --check app tests alembic scripts` are clean.
- **Nothing is linked without a user tap.** Matching only writes `match_suggestions` rows.
- **Projections are labelled.** Every projected figure is named as a projection in the response (`projected`, `net_projected`, `pace`, `estimated`, "≈"). Nothing is presented as money saved or money you have.
- **Money:**
  - `Decimal` throughout, using `app.core.money` (`to_decimal`, `quantize`, `percent`, `ZERO`) and `app.services.money` (`base_amount_expr`, `to_base`).
  - Transactions count in base currency (`exchange_rate` applied).
  - Recurring items have no rate, so their entries count at face value, as "Bills due" does today.
  - On the wire, money is a JSON number (the `Money` type in `app/api/planning_models.py`).
- **Household isolation on every endpoint.**
  - Every new endpoint depends on `require_api_auth` and filters by its `household_id`.
  - Any id from another household is a 404.
- **New VARCHAR "enums" are plain `String` columns** (like `payment_method`), never `SAEnum`. Postgres native enums need `ALTER TYPE` migrations (see `NotificationType`).
- **Model fields need both Python `default=` and `server_default=`.** The suite builds tables with `create_all`, and fixtures such as `make_bill` and `make_household` don't pass the new fields.

## Review Focus

1. **A Fixed-cost expense (expense, no bucket, `recurring_bill_id` set) reaching old code paths.** Expected behaviour:
   - Editing it in the old form keeps it bucket-less instead of a 400 "A bucket is required".
   - "Duplicate" copies the link instead of a 500 from the CHECK.
   - The dashboard, search and insights render it.
   - Deleting its recurring item is refused (409), not a 500 from `ON DELETE SET NULL` hitting the CHECK, even after the expense was soft-deleted.

   Pinned in Task 7.
2. **Link tapped on a stale suggestion.** The transaction was deleted, or the entry was done or skipped elsewhere (for example two Apple Pay charges suggested for one entry, and the other one was linked). Expected: 409 with a message, nothing changes, and the suggestion disappears from `/matches`. Pinned in Task 8 (service) and Task 13 (API).
3. **The old app touching new data from a stale page or bookmark.** Expected:
   - An `in` item, or an `in` item's entry, is a 404 on every old route (pay, skip, set-amount, edit, toggle, delete, history) and on old `/api/v1/bills`. Paying it there must never create an expense.
   - A new-rule `out` item is 409 on edit.

   Pinned in Task 4.
4. **A past `start_date` together with `total_occurrences`.** Expected:
   - Past dates still use up the count, so no extra entries appear.
   - Nothing before today is ever an expected entry.
   - Auto-pay never backfills anything older than 3 days.

   Pinned in Task 3 (count) and Task 4 (auto-pay window).
5. **Resuming a paused item.** Expected: its Upcoming entries appear immediately, not after the next nightly top-up. This applies to the old toggle and to `PUT /recurring/{id}` with `is_active: true`. Pinned in Task 3 (old toggle) and Task 12 (API).

---

## File Structure

New:
- `app/core/calendar_gr.py`: Greek holidays, business days, Orthodox Easter. Pure.
- `app/core/schedule.py`: `RuleKind`, `RuleAdjust`, `Rule`, `RuleError`, `validate_rule`, `iter_dates`. Pure.
- `alembic/versions/a7b8c9d0e1f2_planning_recurring_items.py`: the one additive migration.
- `app/services/matching.py`: match suggestions (find, suggest, daily pass, link, dismiss).
- `app/services/budgets.py`: bucket kinds (`bucket_period`, `bucket_spent`, `budget_rows`) and `bucket_pace`.
- `app/services/planning.py`: `Entry`, `list_entries`, `entry_for`, `month_picture`, `upcoming`, `year_outlook`.
- `app/services/usual.py`: `categories_vs_usual`.
- `app/api/planning_models.py`: Pydantic response models and the `Money` type.
- `app/api/recurring.py`, `app/api/matches.py`, `app/api/plan.py`: the new routers.
- Tests:
  - `tests/test_schedule_rules.py`
  - `tests/test_planning_migration.py`
  - `tests/test_planning_generation.py`
  - `tests/test_planning_old_app.py`
  - `tests/test_planning_lifecycle.py`
  - `tests/test_planning_income.py`
  - `tests/test_planning_fixed_costs.py`
  - `tests/test_matching.py`
  - `tests/test_bucket_kinds.py`
  - `tests/test_planning_views.py`
  - `tests/test_planning_outlook.py`
  - `tests/test_api_recurring.py`
  - `tests/test_api_plan.py`
  - `tests/test_planning_upgrade.py`

Modified:
- `app/models.py`:
  - enums `BucketKind` and `ItemDirection`, plus `kind_for_type`;
  - `RecurringBill` rule columns, `old_app_editable` and `active_filter()`;
  - `Bucket.kind` with a `type` validator;
  - `Transaction.recurring_bill_id` and the relaxed CHECK;
  - `MatchSuggestion`.
- `app/schemas.py`: `TransactionUpdate` leaves the bucket check to the service.
- `app/services/bills.py`:
  - generation on the rule engine, with horizon and past modes;
  - the lifecycle actions;
  - `receive_occurrence` and `complete_entry`;
  - `pay_occurrence` links the item.
- `app/services/transactions.py`:
  - soft delete reopens the entry;
  - the update allows Fixed costs;
  - create triggers matching.
- `app/services/dashboard.py`, `app/services/insights.py`: bills queries are `out` and active only.
- `app/scheduler.py`:
  - auto-pay window;
  - `out`-only reminders;
  - event-bucket budget warnings;
  - `planning_daily_job` (top-up and matching).
- `app/routes/bills.py`, `app/api/bills.py`, `templates/bills/list.html`: the old app shows `out` only, has read-only new rules, and uses the new generation modes.
- `app/routes/transactions.py`: duplicate keeps `recurring_bill_id`.
- `app/api/buckets.py`: `kind`.
- `app/api/insights.py`: `/categories-vs-usual`.
- `app/api/transactions.py`: `recurring_bill_id` / `fixed` filters and field.
- `app/api/__init__.py`: mount the new routers.

---

### Task 1: Greek business-day calendar and the schedule rule engine

**Files:**
- Create: `app/core/calendar_gr.py`, `app/core/schedule.py`
- Test: `tests/test_schedule_rules.py`

**Interfaces:**
- Consumes: `dateutil.easter.easter`, `EASTER_ORTHODOX`, `dateutil.relativedelta.relativedelta`.
- Produces:
  - `app.core.calendar_gr`:
    - `orthodox_easter(year: int) -> date`
    - `greek_holidays(year: int) -> frozenset[date]`
    - `is_business_day(d: date) -> bool`
    - `previous_business_day(d: date) -> date`
    - `next_business_day(d: date) -> date`
    - `adjust_date(d: date, how: str) -> date`
    - `last_business_day(year: int, month: int) -> date`
  - `app.core.schedule`:
    - `MAX_INTERVAL_MONTHS = 120`, `MAX_INTERVAL_WEEKS = 52`, `MAX_EASTER_OFFSET = 120`
    - `RuleKind(str, Enum)`: `monthly_interval`, `monthly_day`, `last_business_day`, `yearly`, `easter_offset`, `weekly`
    - `RuleAdjust(str, Enum)`: `none`, `previous_business_day`, `next_business_day`
    - `RuleError(ValueError)`, whose message is user-facing
    - `@dataclass(frozen=True) Rule(kind="monthly_interval", interval_months=1, day=None, month=None, adjust="none", days=None, weekday=None, interval_weeks=1)`
    - `validate_rule(rule: Rule) -> Rule`, which raises `RuleError`
    - `iter_dates(rule: Rule, start: date, *, end: date | None = None, total: int | None = None, until: date) -> Iterator[date]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_schedule_rules.py`. The last test proves that the frozen copy of the old loop is the generator as shipped. Task 3 deletes it, once the generator it compares against is gone. The frozen copy stays as the permanent reference.

```python
"""Greek business-day calendar and the schedule rule engine (spec §3.2, §7)."""

from datetime import date

import pytest
from dateutil.relativedelta import relativedelta

from app.core.calendar_gr import (
    greek_holidays,
    last_business_day,
    next_business_day,
    orthodox_easter,
    previous_business_day,
)
from app.core.schedule import Rule, RuleError, iter_dates

FAR = date(2040, 12, 31)


def _dates(rule, start, n=None, *, until=FAR, **limits):
    out = list(iter_dates(rule, start, until=until, **limits))
    return out[:n] if n else out


# ---------------------------------------------------------------- calendar


def test_orthodox_easter():
    assert orthodox_easter(2026) == date(2026, 4, 12)
    assert orthodox_easter(2027) == date(2027, 5, 2)


def test_holidays_2026():
    h = greek_holidays(2026)
    # Clean Monday, Good Friday, Easter Monday, Whit Monday.
    assert {date(2026, 2, 23), date(2026, 4, 10), date(2026, 4, 13), date(2026, 6, 1)} <= h
    assert {date(2026, 1, 6), date(2026, 3, 25), date(2026, 10, 28), date(2026, 12, 26)} <= h


def test_last_business_day_of_december_2026_is_thursday_31st():
    assert last_business_day(2026, 12) == date(2026, 12, 31)


def test_last_business_day_skips_good_friday():
    assert last_business_day(2027, 4) == date(2027, 4, 29)  # 30 Apr 2027 is Good Friday


def test_business_days_step_over_the_easter_weekend():
    assert previous_business_day(date(2026, 4, 13)) == date(2026, 4, 9)
    assert next_business_day(date(2026, 4, 10)) == date(2026, 4, 14)


# ------------------------------------------------------------------ rules


def test_26th_on_a_saturday_becomes_friday_25th():
    rule = Rule(kind="monthly_day", day=26, adjust="previous_business_day")
    assert _dates(rule, date(2026, 9, 1), 1) == [date(2026, 9, 25)]


def test_26th_on_a_holiday_steps_back_over_christmas():
    rule = Rule(kind="monthly_day", day=26, adjust="previous_business_day")
    # 26 Dec 2025 (Friday) and 25 Dec are both holidays.
    assert _dates(rule, date(2025, 12, 1), 1) == [date(2025, 12, 24)]


def test_day_31_clamps_to_short_months_without_drifting():
    rule = Rule(kind="monthly_day", day=31)
    assert _dates(rule, date(2026, 1, 1), 4) == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_last_business_day_rule():
    rule = Rule(kind="last_business_day")
    assert _dates(rule, date(2026, 4, 1), 3) == [
        date(2026, 4, 30),
        date(2026, 5, 29),  # 31 May 2026 is a Sunday
        date(2026, 6, 30),
    ]


def test_christmas_salary_yearly_previous_business_day():
    rule = Rule(kind="yearly", month=12, day=21, adjust="previous_business_day")
    assert _dates(rule, date(2025, 1, 1), 3) == [
        date(2025, 12, 19),  # 21 Dec 2025 is a Sunday
        date(2026, 12, 21),
        date(2027, 12, 21),
    ]


def test_easter_salary_is_holy_wednesday():
    rule = Rule(kind="easter_offset", days=-4)
    assert _dates(rule, date(2026, 1, 1), 2) == [date(2026, 4, 8), date(2027, 4, 28)]


def test_weekly_every_two_weeks():
    rule = Rule(kind="weekly", weekday=4, interval_weeks=2)
    assert _dates(rule, date(2026, 10, 6), 3) == [
        date(2026, 10, 9),
        date(2026, 10, 23),
        date(2026, 11, 6),
    ]


def test_an_adjusted_date_never_precedes_start():
    rule = Rule(kind="monthly_day", day=26, adjust="previous_business_day")
    # September's 26th moves back to the 25th, before this start: skip to October.
    assert _dates(rule, date(2026, 9, 26), 1) == [date(2026, 10, 26)]


def test_end_total_and_until_stop_a_rule():
    rule = Rule(kind="weekly", weekday=0)
    assert len(_dates(rule, date(2026, 1, 1), total=3)) == 3
    assert _dates(rule, date(2026, 1, 1), end=date(2026, 1, 12)) == [
        date(2026, 1, 5),
        date(2026, 1, 12),
    ]
    assert _dates(rule, date(2026, 1, 1), until=date(2026, 1, 11)) == [date(2026, 1, 5)]


@pytest.mark.parametrize(
    "rule",
    [
        Rule(kind="fortnightly"),
        Rule(kind="monthly_day"),
        Rule(kind="monthly_day", day=32),
        Rule(kind="yearly", day=1),
        Rule(kind="easter_offset"),
        Rule(kind="weekly"),
        Rule(kind="weekly", weekday=1, interval_weeks=0),
        Rule(adjust="sideways"),
        Rule(interval_months=0),
    ],
)
def test_impossible_rules_raise(rule):
    with pytest.raises(RuleError):
        list(iter_dates(rule, date(2026, 1, 1), until=FAR))


# ----------------------------------------------- legacy rule = old generator

TODAY = date(2026, 10, 6)
OLD_HORIZON = date(TODAY.year + 10, 12, 31)


def _old_generator_dates(start, interval_months, end_date=None, total_occurrences=None):
    """Frozen copy of the date loop of app/services/bills.py generate_occurrences
    as shipped before the planning redesign (10-year horizon, 600-row cap).
    It is the reference the legacy rule must match. Do not edit."""
    horizon = date(TODAY.year + 10, 12, 31)
    current, count, out = start, 0, []
    while count < 600:
        if total_occurrences and count >= total_occurrences:
            break
        if end_date and current > end_date:
            break
        if current > horizon:
            break
        out.append(current)
        count += 1
        current = current + relativedelta(months=interval_months)
    return out


STARTS = [
    date(2026, 1, 31),
    date(2026, 1, 29),
    date(2024, 2, 29),
    date(2025, 8, 31),
    date(2026, 3, 15),
    date(2026, 10, 6),
    date(2016, 5, 31),
]
INTERVALS = [1, 2, 3, 5, 6, 12, 120]
LIMITS = [{}, {"end_date": date(2030, 6, 30)}, {"total_occurrences": 7}, {"total_occurrences": 0}]


@pytest.mark.parametrize("start", STARTS)
@pytest.mark.parametrize("interval", INTERVALS)
@pytest.mark.parametrize("limits", LIMITS)
def test_monthly_interval_reproduces_the_old_generator(start, interval, limits):
    rule = Rule(kind="monthly_interval", interval_months=interval)
    new = list(
        iter_dates(
            rule,
            start,
            end=limits.get("end_date"),
            total=limits.get("total_occurrences"),
            until=OLD_HORIZON,
        )
    )
    assert new == _old_generator_dates(start, interval, **limits)


def test_frozen_copy_matches_the_live_generator(db, make_household, monkeypatch):
    """Proves the frozen copy above is the generator as shipped. Task 3 deletes
    this test when generate_occurrences moves onto the rule engine."""
    import app.services.bills as bills
    from app.models import BillOccurrence, RecurringBill

    monkeypatch.setattr(bills, "local_today", lambda: TODAY)
    hh = make_household()
    for i, (start, interval) in enumerate((s, n) for s in STARTS for n in (1, 3, 12)):
        bill = RecurringBill(
            household_id=hh.household_id,
            name=f"Bill {i}",
            amount=1,
            currency="EUR",
            start_date=start,
            interval_months=interval,
        )
        db.add(bill)
        db.flush()
        bills.generate_occurrences(db, bill)
        got = sorted(d for (d,) in db.query(BillOccurrence.due_date).filter_by(bill_id=bill.id))
        assert got == _old_generator_dates(start, interval)
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_schedule_rules.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.core.calendar_gr'`.

- [ ] **Step 3: Write the calendar**

Create `app/core/calendar_gr.py`:
```python
"""Greek business days: Monday to Friday, minus Greek public holidays.

Pure date arithmetic with no database access (spec §3.2). Orthodox Easter
comes from dateutil. Only the national holidays the household's pay dates
move around are listed; regional saints' days are not.
"""

import calendar
from datetime import date, timedelta
from functools import lru_cache

from dateutil.easter import EASTER_ORTHODOX, easter

# (month, day): New Year, Epiphany, 25 March, Labour Day, Assumption,
# Ochi Day, Christmas, Synaxis of the Theotokos.
FIXED_HOLIDAYS = ((1, 1), (1, 6), (3, 25), (5, 1), (8, 15), (10, 28), (12, 25), (12, 26))
# Days from Orthodox Easter Sunday: Clean Monday, Good Friday, Easter Monday,
# Whit Monday.
EASTER_HOLIDAY_OFFSETS = (-48, -2, 1, 50)

PREVIOUS_BUSINESS_DAY = "previous_business_day"
NEXT_BUSINESS_DAY = "next_business_day"


def orthodox_easter(year: int) -> date:
    """Orthodox Easter Sunday of ``year``."""
    return easter(year, EASTER_ORTHODOX)


@lru_cache(maxsize=64)
def greek_holidays(year: int) -> frozenset[date]:
    """The public holidays of ``year`` that are not business days."""
    sunday = orthodox_easter(year)
    fixed = {date(year, m, d) for m, d in FIXED_HOLIDAYS}
    moving = {sunday + timedelta(days=n) for n in EASTER_HOLIDAY_OFFSETS}
    return frozenset(fixed | moving)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in greek_holidays(d.year)


def previous_business_day(d: date) -> date:
    """``d`` if it is a business day, else the closest business day before it."""
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def next_business_day(d: date) -> date:
    """``d`` if it is a business day, else the closest business day after it."""
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def adjust_date(d: date, how: str) -> date:
    """Apply a rule's ``adjust``: "none", "previous_business_day" or "next_business_day"."""
    if how == PREVIOUS_BUSINESS_DAY:
        return previous_business_day(d)
    if how == NEXT_BUSINESS_DAY:
        return next_business_day(d)
    return d


def last_business_day(year: int, month: int) -> date:
    """The last business day of the month."""
    return previous_business_day(date(year, month, calendar.monthrange(year, month)[1]))
```

- [ ] **Step 4: Write the rule engine**

Create `app/core/schedule.py`:
```python
"""Schedule rules for recurring items (spec §3.2).

One pure function, :func:`iter_dates`, turns a rule into due dates. The old
app, the new API and the scheduler all generate entries through it (see
app.services.bills.generate_occurrences), so both UIs always agree. No
database access here.
"""

import calendar
import enum
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from app.core.calendar_gr import adjust_date, last_business_day, orthodox_easter

MAX_INTERVAL_MONTHS = 120  # 10 years between dates
MAX_INTERVAL_WEEKS = 52
MAX_EASTER_OFFSET = 120  # days either side of Easter Sunday


class RuleKind(str, enum.Enum):
    # Legacy: start_date's day every N months, no adjustment. Every bill
    # created before the redesign has this rule.
    monthly_interval = "monthly_interval"
    monthly_day = "monthly_day"
    last_business_day = "last_business_day"
    yearly = "yearly"
    easter_offset = "easter_offset"
    weekly = "weekly"


class RuleAdjust(str, enum.Enum):
    none = "none"
    previous_business_day = "previous_business_day"
    next_business_day = "next_business_day"


class RuleError(ValueError):
    """A rule whose parameters cannot produce dates. The message is user-facing."""


@dataclass(frozen=True)
class Rule:
    kind: str = RuleKind.monthly_interval.value
    interval_months: int = 1
    day: int | None = None  # monthly_day, yearly: 1-31, clamped to the month
    month: int | None = None  # yearly: 1-12
    adjust: str = RuleAdjust.none.value
    days: int | None = None  # easter_offset: days from Orthodox Easter Sunday
    weekday: int | None = None  # weekly: 0 = Monday
    interval_weeks: int = 1


def validate_rule(rule: Rule) -> Rule:
    """``rule`` with its kind normalised to a plain string; raises RuleError."""
    try:
        kind = RuleKind(rule.kind)
    except ValueError:
        raise RuleError(f"Unknown schedule '{rule.kind}'.") from None
    try:
        adjust = RuleAdjust(rule.adjust)
    except ValueError:
        raise RuleError(f"Unknown adjustment '{rule.adjust}'.") from None
    if not 1 <= (rule.interval_months or 0) <= MAX_INTERVAL_MONTHS:
        raise RuleError(f"The interval must be 1 to {MAX_INTERVAL_MONTHS} months.")
    if kind in (RuleKind.monthly_day, RuleKind.yearly) and not 1 <= (rule.day or 0) <= 31:
        raise RuleError("The day must be 1 to 31.")
    if kind == RuleKind.yearly and not 1 <= (rule.month or 0) <= 12:
        raise RuleError("The month must be 1 to 12.")
    if kind == RuleKind.easter_offset and (rule.days is None or abs(rule.days) > MAX_EASTER_OFFSET):
        raise RuleError(f"Days from Easter must be -{MAX_EASTER_OFFSET} to {MAX_EASTER_OFFSET}.")
    if kind == RuleKind.weekly:
        if rule.weekday is None or not 0 <= rule.weekday <= 6:
            raise RuleError("The weekday must be 0 (Monday) to 6 (Sunday).")
        if not 1 <= (rule.interval_weeks or 0) <= MAX_INTERVAL_WEEKS:
            raise RuleError(f"The interval must be 1 to {MAX_INTERVAL_WEEKS} weeks.")
    return replace(rule, kind=kind.value, adjust=adjust.value)


def _on_day(year: int, month: int, day: int) -> date:
    """``day`` of the month, clamped to the month's length (31 -> 30 April)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _candidates(rule: Rule, start: date) -> Iterator[date]:
    """The rule's dates from start's month (or year, or week) on, unbounded.

    An adjusted date can fall before ``start``; iter_dates drops those.
    """
    kind = rule.kind
    if kind == RuleKind.monthly_interval.value:
        # Cumulative on purpose: the old generator added N months to the
        # previous date, so a 31st becomes the 28th after February and stays
        # there. Existing bills keep exactly those dates.
        current = start
        while True:
            yield current
            current = current + relativedelta(months=rule.interval_months)
    elif kind in (RuleKind.monthly_day.value, RuleKind.last_business_day.value):
        first = date(start.year, start.month, 1)
        k = 0
        while True:
            month = first + relativedelta(months=k * rule.interval_months)
            if kind == RuleKind.monthly_day.value:
                yield adjust_date(_on_day(month.year, month.month, rule.day), rule.adjust)
            else:
                yield last_business_day(month.year, month.month)
            k += 1
    elif kind == RuleKind.yearly.value:
        year = start.year
        while True:
            yield adjust_date(_on_day(year, rule.month, rule.day), rule.adjust)
            year += 1
    elif kind == RuleKind.easter_offset.value:
        year = start.year
        while True:
            yield adjust_date(orthodox_easter(year) + timedelta(days=rule.days), rule.adjust)
            year += 1
    else:  # weekly
        current = start + timedelta(days=(rule.weekday - start.weekday()) % 7)
        while True:
            yield current
            current += timedelta(weeks=rule.interval_weeks)


def iter_dates(
    rule: Rule,
    start: date,
    *,
    end: date | None = None,
    total: int | None = None,
    until: date,
) -> Iterator[date]:
    """Due dates of ``rule`` on or after ``start``, ascending.

    Stops after ``end``, after ``total`` dates (0 or None means no limit, as
    the old generator read it) or once past ``until``, the generation
    horizon that keeps every rule finite. A date before ``start`` (an
    adjustment can move one back) or equal to the previous one is dropped.
    Raises RuleError for a rule validate_rule rejects.
    """
    rule = validate_rule(rule)
    count = 0
    previous: date | None = None
    for d in _candidates(rule, start):
        if d < start or (previous is not None and d <= previous):
            continue
        if total and count >= total:
            return
        if end is not None and d > end:
            return
        if d > until:
            return
        yield d
        count += 1
        previous = d
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_schedule_rules.py -q`
Expected: all pass (about 230 cases, most of them from the parametrised legacy comparison).

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check app/core tests/test_schedule_rules.py && .venv/bin/ruff format app/core tests/test_schedule_rules.py
git add app/core/calendar_gr.py app/core/schedule.py tests/test_schedule_rules.py
git commit -m "feat(planning): Greek business-day calendar and schedule rule engine; legacy rule proven equal to the old generator"
```

---

### Task 2: The additive migration and model fields

**Files:**
- Modify: `app/models.py`. The anchors below are as of commit `6262de5`; search for the quoted text if lines have moved:
  - imports at lines 22 and 25;
  - after `class BucketType` (line 85);
  - `class Bucket` (lines 276–300);
  - `BUCKET_UNLESS_INCOME_SQL` (line 309);
  - `class Transaction` `__table_args__` and columns (lines 312–370);
  - `class RecurringBill` (lines 458–495);
  - before `class CategoryRule` (line 518).
- Create: `alembic/versions/a7b8c9d0e1f2_planning_recurring_items.py`
- Test: `tests/test_planning_migration.py`. The existing `tests/test_migrations.py` covers single head, schema = models and the full round trip.

**Interfaces:**
- Consumes: `RuleKind`, `RuleAdjust` (Task 1).
- Produces:
  - `app.models.ItemDirection(str, Enum)` with `out = "out"` and `in_ = "in"`.
  - `app.models.BucketKind(str, Enum)` with `monthly`, `event`.
  - `app.models.kind_for_type(bucket_type) -> str` (trip → `"event"`, otherwise `"monthly"`).
  - `RuleKind` and `RuleAdjust` re-exported from `app.models`.
  - New `RecurringBill` columns:
    - `direction: str` (default `"out"`)
    - `rule_kind: str` (default `"monthly_interval"`)
    - `rule_day`, `rule_month`, `rule_days`, `rule_weekday`, `rule_interval_weeks: int | None`
    - `rule_adjust: str` (default `"none"`)
  - `RecurringBill.old_app_editable -> bool` (property) and `RecurringBill.active_filter()` (classmethod: SQL "not paused", where a NULL `is_active` counts as active).
  - `Bucket.kind: str` (default `"monthly"`), kept equal to `kind_for_type(type)` by a `@validates("type")` hook.
  - `Transaction.recurring_bill_id: str | None` (FK `fk_transactions_recurring_bill_id`, `ON DELETE SET NULL`, index `ix_transactions_recurring_bill_id`).
  - CHECK `ck_transactions_bucket_unless_income` = `bucket_id IS NOT NULL OR type = 'income' OR recurring_bill_id IS NOT NULL`.
  - `MatchSuggestion` (table `match_suggestions`) with:
    - columns `id`, `household_id`, `transaction_id`, `occurrence_id`, `dismissed: bool`, `created_at`;
    - unique constraint `uq_match_suggestion (transaction_id, occurrence_id)`;
    - relationships `.transaction` and `.occurrence`.
  - Alembic revision `a7b8c9d0e1f2`.

- [ ] **Step 1: Write the failing migration tests**

Create `tests/test_planning_migration.py`. It seeds at the revision just before this migration (read from the migration's own `down_revision`, so the test stays valid whatever that is), upgrades, and checks every backfill.

```python
"""The planning migration (spec §6.1): additive, backfilled, reversible."""

import importlib.util
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.test_migrations import ROOT, _alembic, _db_url

MIGRATION = ROOT / "alembic" / "versions" / "a7b8c9d0e1f2_planning_recurring_items.py"


def _previous_revision() -> str:
    spec = importlib.util.spec_from_file_location("planning_mig", MIGRATION)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig.down_revision


def _seed(conn) -> dict:
    ids = {k: str(uuid.uuid4()) for k in ("hh", "user", "trip", "daily", "bill", "paid", "open", "txn")}
    conn.execute(
        text("INSERT INTO households (id, name, default_currency) VALUES (:i, 'H', 'EUR')"),
        {"i": ids["hh"]},
    )
    conn.execute(
        text(
            "INSERT INTO users (id, username, display_name, password_hash, session_version, "
            "totp_enabled, email_verified) VALUES (:i, 'u', 'U', 'x', 0, false, false)"
        ),
        {"i": ids["user"]},
    )
    for key, kind in (("trip", "trip"), ("daily", "day2day")):
        conn.execute(
            text(
                "INSERT INTO buckets (id, household_id, name, type, status, show_income, "
                "enable_settlement) VALUES (:b, :h, :n, :t, 'active', true, false)"
            ),
            {"b": ids[key], "h": ids["hh"], "n": key, "t": kind},
        )
    conn.execute(
        text(
            "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
            "frequency, interval_months, start_date, is_active, is_auto_pay) "
            "VALUES (:i, :h, :b, 'Cosmote', 38.90, 'EUR', 'monthly', 1, '2026-01-05', true, false)"
        ),
        {"i": ids["bill"], "h": ids["hh"], "b": ids["daily"]},
    )
    conn.execute(
        text(
            "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, "
            "exchange_rate, type, paid_by, transaction_date, exclude_from_forecast, "
            "exclude_from_settlement) VALUES (:i, :b, :h, 38.90, 'EUR', 1, 'expense', :u, "
            "'2026-02-05', false, false)"
        ),
        {"i": ids["txn"], "b": ids["daily"], "h": ids["hh"], "u": ids["user"]},
    )
    conn.execute(
        text(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status, transaction_id) "
            "VALUES (:i, :b, '2026-02-05', 'paid', :t)"
        ),
        {"i": ids["paid"], "b": ids["bill"], "t": ids["txn"]},
    )
    conn.execute(
        text(
            "INSERT INTO bill_occurrences (id, bill_id, due_date, status) "
            "VALUES (:i, :b, '2026-03-05', 'unpaid')"
        ),
        {"i": ids["open"], "b": ids["bill"]},
    )
    return ids


def test_upgrade_backfills_and_keeps_every_row(tmp_path):
    db_url = _db_url(tmp_path, "planning.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr

    with engine.connect() as conn:
        bill = conn.execute(
            text("SELECT direction, rule_kind, rule_adjust, interval_months FROM recurring_bills")
        ).one()
        assert tuple(bill) == ("out", "monthly_interval", "none", 1)
        kinds = dict(conn.execute(text("SELECT name, kind FROM buckets")).all())
        assert kinds == {"trip": "event", "daily": "monthly"}
        linked = conn.execute(
            text("SELECT recurring_bill_id FROM transactions WHERE id = :i"), {"i": ids["txn"]}
        ).scalar()
        assert linked == ids["bill"]
        assert conn.execute(text("SELECT COUNT(*) FROM bill_occurrences")).scalar() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM match_suggestions")).scalar() == 0
    engine.dispose()


def test_check_allows_a_fixed_cost_but_not_a_bare_expense(tmp_path):
    db_url = _db_url(tmp_path, "check.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
    assert _alembic(["upgrade", "head"], db_url).returncode == 0

    insert = text(
        "INSERT INTO transactions (id, household_id, amount, currency, exchange_rate, type, "
        "transaction_date, exclude_from_forecast, exclude_from_settlement, recurring_bill_id) "
        "VALUES (:i, :h, 10, 'EUR', 1, 'expense', '2026-03-05', false, false, :r)"
    )
    with engine.begin() as conn:
        conn.execute(insert, {"i": str(uuid.uuid4()), "h": ids["hh"], "r": ids["bill"]})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"i": str(uuid.uuid4()), "h": ids["hh"], "r": None})
    engine.dispose()


def test_downgrade_refuses_while_a_fixed_cost_exists_then_round_trips(tmp_path):
    db_url = _db_url(tmp_path, "down.db")
    assert _alembic(["upgrade", _previous_revision()], db_url).returncode == 0
    engine = create_engine(db_url)
    with engine.begin() as conn:
        ids = _seed(conn)
    assert _alembic(["upgrade", "head"], db_url).returncode == 0
    fixed_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (id, household_id, amount, currency, exchange_rate, "
                "type, transaction_date, exclude_from_forecast, exclude_from_settlement, "
                "recurring_bill_id) VALUES (:i, :h, 10, 'EUR', 1, 'expense', '2026-03-05', "
                "false, false, :r)"
            ),
            {"i": fixed_id, "h": ids["hh"], "r": ids["bill"]},
        )

    down = _alembic(["downgrade", _previous_revision()], db_url)
    assert down.returncode != 0 and "Fixed-cost" in down.stderr

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET bucket_id = :b WHERE id = :i"),
            {"b": ids["daily"], "i": fixed_id},
        )
    down = _alembic(["downgrade", _previous_revision()], db_url)
    assert down.returncode == 0, down.stderr
    insp = inspect(engine)
    assert "match_suggestions" not in insp.get_table_names()
    assert "recurring_bill_id" not in {c["name"] for c in insp.get_columns("transactions")}
    assert "kind" not in {c["name"] for c in insp.get_columns("buckets")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM transactions")).scalar() == 2

    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr
    engine.dispose()
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_migration.py -q`
Expected: FAIL with `FileNotFoundError` for `a7b8c9d0e1f2_planning_recurring_items.py`.

- [ ] **Step 3: Model enums**

In `app/models.py`:
- change line 22 to `from sqlalchemy.orm import relationship, validates`;
- after `from app.core.database import Base` (line 25), add:
```python
from app.core.schedule import RuleAdjust, RuleKind  # noqa: F401  (re-exported)
```
Directly after `class BucketType` (ends line 90), add:
```python
class BucketKind(str, enum.Enum):
    """What a bucket's budget means (spec §4.1). Plain VARCHAR like PaymentMethod."""

    monthly = "monthly"  # per calendar month, resets on the 1st
    event = "event"  # a total over start_date..end_date


def kind_for_type(bucket_type) -> str:
    """The kind an old-app bucket type stands for: a trip is an event, every
    other type is monthly."""
    if BucketType(bucket_type) == BucketType.trip:
        return BucketKind.event.value
    return BucketKind.monthly.value


class ItemDirection(str, enum.Enum):
    """Which way a recurring item's money goes. Plain VARCHAR like PaymentMethod."""

    out = "out"  # bills: DEH, Cosmote, rent paid
    in_ = "in"  # salaries, rent received
```

- [ ] **Step 4: `Bucket.kind`**

In `class Bucket`, replace
```python
    goal_amount = Column(Numeric(12, 4), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
```
with
```python
    goal_amount = Column(Numeric(12, 4), nullable=True)
    # monthly or event (spec §4.1). Follows ``type`` (see kind_for_type), so
    # the old app's forms keep it right without knowing about it.
    kind = Column(
        String(8),
        default=BucketKind.monthly.value,
        server_default=BucketKind.monthly.value,
        nullable=False,
    )
    created_at = Column(DateTime, default=utcnow_naive)

    @validates("type")
    def _kind_follows_type(self, _key, value):
        self.kind = kind_for_type(value)
        return value
```

- [ ] **Step 5: `Transaction.recurring_bill_id` and the CHECK**

Replace the `BUCKET_UNLESS_INCOME_SQL` block (lines 307–309) with:
```python
# Expenses and transfers need a bucket; income may have none, and neither may
# an expense paid for a recurring item (a Fixed cost, spec §3.4). The enum is
# stored by name ('income'), on SQLite and in the Postgres enum alike.
BUCKET_UNLESS_INCOME_SQL = (
    "bucket_id IS NOT NULL OR type = 'income' OR recurring_bill_id IS NOT NULL"
)
```
In `Transaction.__table_args__`, after `Index("ix_transactions_category_id", "category_id"),`, add:
```python
        Index("ix_transactions_recurring_bill_id", "recurring_bill_id"),
```
Between `client_id = Column(String(64), nullable=True)` and `created_at`, add:
```python
    # The recurring item this expense pays or this income receives (spec
    # §3.3): set by Pay, Mark received and Link. A bucket-less expense needs it.
    recurring_bill_id = Column(
        String,
        ForeignKey(
            "recurring_bills.id", ondelete="SET NULL", name="fk_transactions_recurring_bill_id"
        ),
        nullable=True,
    )
```

- [ ] **Step 6: `RecurringBill` rule columns**

In `class RecurringBill`, replace
```python
    is_auto_pay = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)
```
with
```python
    is_auto_pay = Column(Boolean, default=False, nullable=False)
    # Planning redesign (spec §3.1-3.2): which way the money goes and the
    # schedule rule (app.core.schedule). Rows from before it are out +
    # monthly_interval, whose dates are exactly the old generator's.
    direction = Column(
        String(8),
        default=ItemDirection.out.value,
        server_default=ItemDirection.out.value,
        nullable=False,
    )
    rule_kind = Column(
        String(24),
        default=RuleKind.monthly_interval.value,
        server_default=RuleKind.monthly_interval.value,
        nullable=False,
    )
    rule_day = Column(Integer, nullable=True)  # monthly_day, yearly
    rule_month = Column(Integer, nullable=True)  # yearly
    rule_adjust = Column(
        String(24),
        default=RuleAdjust.none.value,
        server_default=RuleAdjust.none.value,
        nullable=False,
    )
    rule_days = Column(Integer, nullable=True)  # easter_offset: days from Easter Sunday
    rule_weekday = Column(Integer, nullable=True)  # weekly: 0 = Monday
    rule_interval_weeks = Column(Integer, nullable=True)  # weekly
    created_at = Column(DateTime, default=utcnow_naive)

    @property
    def old_app_editable(self) -> bool:
        """The old app edits only out items on the legacy rule (spec §6.2)."""
        return (self.direction or ItemDirection.out.value) == ItemDirection.out.value and (
            self.rule_kind or RuleKind.monthly_interval.value
        ) == RuleKind.monthly_interval.value

    @classmethod
    def active_filter(cls):
        """Filter expression: not paused (spec §3.4.1). NULL counts as active."""
        return cls.is_active.isnot(False)
```

- [ ] **Step 7: `MatchSuggestion`**

Directly before `class CategoryRule(Base):`, add:
```python
class MatchSuggestion(Base):
    """"Looks like Cosmote · Oct": a transaction that may be an expected entry
    (spec §3.5). Nothing is linked without a tap: Link marks the entry done,
    Not this sets ``dismissed`` and the pair is never suggested again."""

    __tablename__ = "match_suggestions"
    __table_args__ = (
        UniqueConstraint("transaction_id", "occurrence_id", name="uq_match_suggestion"),
        Index("ix_match_suggestions_household", "household_id", "dismissed"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    occurrence_id = Column(
        String, ForeignKey("bill_occurrences.id", ondelete="CASCADE"), nullable=False
    )
    dismissed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)

    transaction = relationship("Transaction")
    occurrence = relationship("BillOccurrence")
```

- [ ] **Step 8: The migration**

Run `.venv/bin/alembic heads`. If it prints anything other than `f0a1b2c3d4e5 (head)`, put that revision in `down_revision` and `Revises:` below. Create `alembic/versions/a7b8c9d0e1f2_planning_recurring_items.py`:
```python
"""planning redesign: recurring items, bucket kinds, Fixed costs, match suggestions

Additive only (spec §6.1); nothing is dropped or renamed, so the old app keeps
working on the same database.

- recurring_bills: direction ('out'/'in'), rule_kind, rule_day, rule_month,
  rule_adjust, rule_days, rule_weekday, rule_interval_weeks. Every existing
  row becomes out + monthly_interval, whose dates are the old generator's.
- buckets.kind ('monthly'/'event'): trip -> event, every other type -> monthly.
- transactions.recurring_bill_id (FK, SET NULL on delete, indexed), backfilled
  from the transaction of each paid bill occurrence.
- ck_transactions_bucket_unless_income also allows a bucket-less expense that
  is linked to a recurring item (a Fixed cost).
- match_suggestions, empty.

SQLite cannot alter a CHECK in place, so transactions goes through batch mode
(a table copy), as in d8e9f0a1b2c3. Downgrade refuses while a bucket-less
expense exists, since the old CHECK would reject it; give it a bucket first.

Revision ID: a7b8c9d0e1f2
Revises: f0a1b2c3d4e5
Create Date: 2026-10-06 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a7b8c9d0e1f2"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None

CHECK_NAME = "ck_transactions_bucket_unless_income"
# Enums are stored by name, on SQLite and in the Postgres enums alike.
OLD_CHECK_SQL = "bucket_id IS NOT NULL OR type = 'income'"
NEW_CHECK_SQL = "bucket_id IS NOT NULL OR type = 'income' OR recurring_bill_id IS NOT NULL"
FK_NAME = "fk_transactions_recurring_bill_id"
TXN_INDEX = "ix_transactions_recurring_bill_id"
MATCH_INDEX = "ix_match_suggestions_household"
RULE_COLUMNS = (
    "direction",
    "rule_kind",
    "rule_day",
    "rule_month",
    "rule_adjust",
    "rule_days",
    "rule_weekday",
    "rule_interval_weeks",
)


def upgrade() -> None:
    with op.batch_alter_table("recurring_bills") as batch:
        batch.add_column(sa.Column("direction", sa.String(8), nullable=False, server_default="out"))
        batch.add_column(
            sa.Column(
                "rule_kind", sa.String(24), nullable=False, server_default="monthly_interval"
            )
        )
        batch.add_column(sa.Column("rule_day", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_month", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("rule_adjust", sa.String(24), nullable=False, server_default="none")
        )
        batch.add_column(sa.Column("rule_days", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_weekday", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("rule_interval_weeks", sa.Integer(), nullable=True))

    with op.batch_alter_table("buckets") as batch:
        batch.add_column(sa.Column("kind", sa.String(8), nullable=False, server_default="monthly"))
    op.execute("UPDATE buckets SET kind = 'event' WHERE type = 'trip'")

    if op.get_bind().dialect.name == "postgresql":
        op.add_column("transactions", sa.Column("recurring_bill_id", sa.String(), nullable=True))
        op.create_foreign_key(
            FK_NAME,
            "transactions",
            "recurring_bills",
            ["recurring_bill_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_constraint(CHECK_NAME, "transactions", type_="check")
        op.create_check_constraint(CHECK_NAME, "transactions", NEW_CHECK_SQL)
    else:
        with op.batch_alter_table("transactions") as batch:
            batch.add_column(sa.Column("recurring_bill_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                FK_NAME, "recurring_bills", ["recurring_bill_id"], ["id"], ondelete="SET NULL"
            )
            batch.drop_constraint(CHECK_NAME, type_="check")
            batch.create_check_constraint(CHECK_NAME, NEW_CHECK_SQL)
    op.create_index(TXN_INDEX, "transactions", ["recurring_bill_id"])
    op.execute(
        "UPDATE transactions SET recurring_bill_id = ("
        "  SELECT o.bill_id FROM bill_occurrences o"
        "  WHERE o.transaction_id = transactions.id AND o.status = 'paid'"
        "  ORDER BY o.due_date LIMIT 1"
        ") WHERE id IN ("
        "  SELECT transaction_id FROM bill_occurrences"
        "  WHERE status = 'paid' AND transaction_id IS NOT NULL"
        ")"
    )

    op.create_table(
        "match_suggestions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "household_id",
            sa.String(),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "transaction_id",
            sa.String(),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "occurrence_id",
            sa.String(),
            sa.ForeignKey("bill_occurrences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dismissed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("transaction_id", "occurrence_id", name="uq_match_suggestion"),
    )
    op.create_index(MATCH_INDEX, "match_suggestions", ["household_id", "dismissed"])


def downgrade() -> None:
    conn = op.get_bind()
    fixed = conn.execute(
        sa.text("SELECT COUNT(*) FROM transactions WHERE bucket_id IS NULL AND type <> 'income'")
    ).scalar()
    if fixed:
        raise RuntimeError(
            f"Cannot downgrade: {fixed} Fixed-cost expense(s) have no bucket. "
            "Give them a bucket first."
        )
    op.drop_index(MATCH_INDEX, table_name="match_suggestions")
    op.drop_table("match_suggestions")

    op.drop_index(TXN_INDEX, table_name="transactions")
    if conn.dialect.name == "postgresql":
        op.drop_constraint(CHECK_NAME, "transactions", type_="check")
        op.create_check_constraint(CHECK_NAME, "transactions", OLD_CHECK_SQL)
        op.drop_constraint(FK_NAME, "transactions", type_="foreignkey")
        op.drop_column("transactions", "recurring_bill_id")
    else:
        with op.batch_alter_table("transactions") as batch:
            batch.drop_constraint(CHECK_NAME, type_="check")
            batch.create_check_constraint(CHECK_NAME, OLD_CHECK_SQL)
            batch.drop_constraint(FK_NAME, type_="foreignkey")
            batch.drop_column("recurring_bill_id")

    with op.batch_alter_table("buckets") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("recurring_bills") as batch:
        for column in reversed(RULE_COLUMNS):
            batch.drop_column(column)
```

- [ ] **Step 9: Run the migration tests on SQLite and Postgres**

Run: `.venv/bin/python -m pytest tests/test_planning_migration.py tests/test_migrations.py -q`
Then: `TEST_DATABASE_URL=postgresql://… .venv/bin/python -m pytest tests/test_planning_migration.py tests/test_migrations.py -q`
Expected: all pass on both. `test_schema_matches_models` proves that every new model column is migrated, and `test_downgrade_then_upgrade_round_trips` proves the downgrade.

- [ ] **Step 10: The rest of the suite still builds and passes**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass. The model defaults keep `make_bill` and `make_household` working, and nothing reads the new fields yet.

- [ ] **Step 11: Commit**

```bash
.venv/bin/ruff check app alembic tests && .venv/bin/ruff format app alembic tests
git add app/models.py alembic/versions/a7b8c9d0e1f2_planning_recurring_items.py tests/test_planning_migration.py
git commit -m "feat(planning): additive migration — item direction and rule, bucket kind, transactions.recurring_bill_id, relaxed CHECK, match_suggestions"
```

---

### Task 3: Expected entries on the rule engine, a 13-month horizon and the daily top-up

**Files:**
- Modify:
  - `app/services/bills.py`: lines 1–111, from the module docstring through `delete_future_occurrences`.
  - `app/routes/bills.py`: the import block (lines 26–36), `create_bill` (line 231), `edit_bill` (lines 457–459) and `toggle_bill` (line 487).
  - `app/api/bills.py`: the import block (lines 26–36), `create_bill` (line 259) and `update_bill` (line 330).
  - `app/scheduler.py`: a new section before "Job entry point" (line 666), and `start_scheduler` (after line 786).
  - `tests/test_schedule_rules.py`: delete `test_frozen_copy_matches_the_live_generator`.
- Test: `tests/test_planning_generation.py`

**Interfaces:**
- Consumes: `Rule`, `iter_dates`, `MAX_INTERVAL_MONTHS` (Task 1); the `RecurringBill` rule columns and `RecurringBill.active_filter()` (Task 2).
- Produces (in `app.services.bills`):
  - `HORIZON_MONTHS = 13`
  - `PAST_UNPAID = "unpaid"`, `PAST_SKIPPED = "skipped"`, `PAST_NONE = "none"`
  - `horizon_end(today: date) -> date`
  - `item_rule(bill: RecurringBill) -> Rule`, which raises `RuleError`
  - `generate_occurrences(db, bill, *, today: date | None = None, past: str = PAST_UNPAID) -> int` (rows created). It does not commit and raises `RuleError`.
  - `delete_future_occurrences(db, bill_id)`, which now spares rows with an amount or a transaction.
  - `normalise_interval_months` is unchanged.

  And in `app.scheduler`:
  - `_top_up_entries(db, today) -> int`
  - `_planning_stages() -> tuple` (Task 8 adds a stage)
  - `planning_daily_job() -> None`, scheduled at 00:01 and once at startup.

  The old app's forms use `PAST_SKIPPED`. The new API and the top-up use `PAST_NONE`. Direct callers keep `PAST_UNPAID`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_generation.py`:
```python
"""Expected entries on the rule engine: rolling horizon, no past entries,
edits that keep what the user touched (spec §3.3, §3.4.3-4)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import BillOccurrence, OccurrenceStatus, RecurringBill
from app.services.bills import (
    PAST_NONE,
    PAST_SKIPPED,
    delete_future_occurrences,
    generate_occurrences,
    horizon_end,
)

TODAY = date(2026, 10, 6)


@pytest.fixture()
def frozen_today(monkeypatch):
    import app.services.bills as bills

    monkeypatch.setattr(bills, "local_today", lambda: TODAY)
    return TODAY


def _item(db, hh, **kw):
    fields = {
        "household_id": hh.household_id,
        "name": "Salary",
        "amount": Decimal("1500"),
        "currency": "EUR",
        "start_date": date(2026, 10, 1),
    }
    fields.update(kw)
    bill = RecurringBill(**fields)
    db.add(bill)
    db.flush()
    return bill


def _dates(db, bill, status=None):
    q = db.query(BillOccurrence.due_date).filter_by(bill_id=bill.id)
    if status:
        q = q.filter(BillOccurrence.status == status)
    return sorted(d for (d,) in q)


def test_horizon_is_13_months():
    assert horizon_end(TODAY) == date(2027, 11, 6)


def test_new_rule_generates_up_to_the_horizon(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, rule_kind="monthly_day", rule_day=26, rule_adjust="previous_business_day")
    created = generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
    got = _dates(db, bill)
    assert created == len(got) == 13
    assert got[0] == date(2026, 10, 26) and got[-1] == date(2027, 10, 26)
    assert date(2027, 6, 25) in got  # 26 Jun 2027 is a Saturday


def test_no_expected_entry_before_today(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, start_date=date(2026, 1, 5), interval_months=1)
    generate_occurrences(db, bill, past=PAST_NONE)
    assert min(_dates(db, bill)) == date(2026, 11, 5)


def test_old_app_forms_record_past_dates_as_skipped(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, start_date=date(2026, 1, 5), total_occurrences=12)
    generate_occurrences(db, bill, past=PAST_SKIPPED)
    assert len(_dates(db, bill, OccurrenceStatus.skipped)) == 10  # 5 Jan to 5 Oct
    assert _dates(db, bill, OccurrenceStatus.unpaid) == [date(2026, 11, 5), date(2026, 12, 5)]


def test_past_dates_still_count_towards_total_occurrences(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, start_date=date(2026, 1, 5), total_occurrences=12)
    generate_occurrences(db, bill, past=PAST_NONE)
    assert _dates(db, bill) == [date(2026, 11, 5), date(2026, 12, 5)]


def test_top_up_extends_without_duplicates(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, start_date=date(2026, 10, 10))
    generate_occurrences(db, bill, past=PAST_NONE)
    later = TODAY + timedelta(days=62)
    assert generate_occurrences(db, bill, today=later, past=PAST_NONE) == 2
    assert generate_occurrences(db, bill, today=later, past=PAST_NONE) == 0
    assert _dates(db, bill)[-1] == date(2027, 12, 10)


def test_edit_keeps_done_skipped_and_set_amount_entries(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, amount=None, start_date=date(2026, 11, 1))
    generate_occurrences(db, bill, past=PAST_NONE)
    rows = {o.due_date: o for o in db.query(BillOccurrence).filter_by(bill_id=bill.id)}
    rows[date(2026, 11, 1)].status = OccurrenceStatus.paid
    rows[date(2026, 12, 1)].status = OccurrenceStatus.skipped
    rows[date(2027, 1, 1)].amount = Decimal("80.00")
    db.commit()

    bill.start_date = date(2026, 11, 3)  # edit: the 3rd from now on
    delete_future_occurrences(db, bill.id)
    generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()

    got = _dates(db, bill)
    assert {date(2026, 11, 1), date(2026, 12, 1), date(2027, 1, 1)} <= set(got)
    assert date(2027, 2, 1) not in got and date(2027, 2, 3) in got
    kept = db.query(BillOccurrence).filter_by(bill_id=bill.id, due_date=date(2027, 1, 1)).one()
    assert kept.amount == Decimal("80.00")


def test_html_create_with_past_start_makes_no_expected_past_entries(client, db, authed):
    r = client.post(
        "/bills",
        data={
            "name": "Gym",
            "amount": "30",
            "currency": "EUR",
            "start_date": "2025-01-15",
            "interval_months": "1",
            "frequency": "monthly",
            "bucket_id": authed.bucket_id,
        },
        headers=authed.headers,
    )
    assert r.status_code == 302
    bill = db.query(RecurringBill).one()
    from app.core.clock import local_today

    expected = _dates(db, bill, OccurrenceStatus.unpaid)
    assert expected and min(expected) >= local_today()


def test_resuming_in_the_old_app_fills_the_horizon_now(client, db, authed):
    bill = RecurringBill(
        household_id=authed.household_id,
        name="Gym",
        amount=Decimal("30"),
        currency="EUR",
        start_date=date(2025, 1, 15),
        is_active=False,
    )
    db.add(bill)
    db.commit()
    r = client.post(f"/bills/{bill.id}/toggle", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    from app.core.clock import local_today

    upcoming = _dates(db, bill, OccurrenceStatus.unpaid)
    assert len(upcoming) >= 12 and min(upcoming) >= local_today()


def test_daily_job_tops_up_active_items_only(db, make_household, monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    hh = make_household()
    active = _item(db, hh, name="Rent in", start_date=date(2026, 11, 1))
    paused = _item(db, hh, name="Old gym", start_date=date(2026, 11, 1), is_active=False)
    broken = _item(db, hh, name="Broken", rule_kind="monthly_day", rule_day=None)
    db.commit()

    scheduler.planning_daily_job()

    db.expire_all()
    assert len(_dates(db, active)) >= 12
    assert _dates(db, paused) == []
    assert _dates(db, broken) == []
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_generation.py -q`
Expected: collection error, `ImportError: cannot import name 'PAST_NONE' from 'app.services.bills'`.

- [ ] **Step 3: Generation on the rule engine**

In `app/services/bills.py`, replace everything from the module docstring down to (and including) `delete_future_occurrences` (lines 1–111) with the block below. Everything from `def resolve_bill_payer(` onwards stays.
```python
"""
Recurring items: generating their expected entries (BillOccurrence rows) and
paying, receiving, undoing and skipping them.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from dateutil.relativedelta import relativedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import local_today
from app.core.schedule import MAX_INTERVAL_MONTHS, Rule, iter_dates
from app.models import (
    BillOccurrence,
    HouseholdMember,
    MemberRole,
    OccurrenceStatus,
    PayerMode,
    RecurringBill,
    Transaction,
    TransactionSplit,
    TransactionType,
)

# Entries exist from start_date to this many months from today; the daily
# planning job tops the window up (spec §3.3). Rows beyond it, left by the old
# 10-year generation, are kept.
HORIZON_MONTHS = 13

# What generate_occurrences does with a rule date before today:
PAST_UNPAID = "unpaid"  # an expected entry (the old behaviour; direct callers)
PAST_SKIPPED = "skipped"  # a skipped placeholder (the old app's forms)
PAST_NONE = "none"  # nothing (the new API and the daily top-up)


def normalise_interval_months(value: int | None) -> int:
    """Clamp interval_months into a sane range.

    A value of 0 or less would leave ``current`` unchanged on every iteration of
    the generation loop, hanging the worker in an infinite loop while inserting
    rows — reachable from any authenticated user via the bill form or the API.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 1
    if value < 1:
        return 1
    return min(value, MAX_INTERVAL_MONTHS)


def horizon_end(today: date) -> date:
    """The last date the rolling horizon generates entries for."""
    return today + relativedelta(months=HORIZON_MONTHS)


def item_rule(bill: RecurringBill) -> Rule:
    """The schedule rule stored on ``bill`` (app.core.schedule)."""
    return Rule(
        kind=bill.rule_kind or "monthly_interval",
        interval_months=normalise_interval_months(bill.interval_months),
        day=bill.rule_day,
        month=bill.rule_month,
        adjust=bill.rule_adjust or "none",
        days=bill.rule_days,
        weekday=bill.rule_weekday,
        interval_weeks=bill.rule_interval_weeks or 1,
    )


def generate_occurrences(
    db: Session, bill: RecurringBill, *, today: date | None = None, past: str = PAST_UNPAID
) -> int:
    """Create the missing entries of ``bill`` from start_date to the horizon.

    Dates come from the shared rule engine, so both apps and the scheduler
    agree. end_date and total_occurrences count from start_date, whether or
    not a past date gets a row. A date that already has a row is left alone.
    ``past`` decides what a date before today becomes (PAST_UNPAID,
    PAST_SKIPPED or PAST_NONE); only PAST_UNPAID, kept for direct callers,
    creates expected entries before today. Returns the rows created.

    Does not commit — the caller owns the transaction so that a bill and its
    occurrences are persisted atomically. Raises RuleError for a bad rule.
    """
    bill.interval_months = normalise_interval_months(bill.interval_months)
    today = today or local_today()
    existing_dates = {
        row.due_date for row in db.query(BillOccurrence.due_date).filter_by(bill_id=bill.id).all()
    }
    created = 0
    for due in iter_dates(
        item_rule(bill),
        bill.start_date,
        end=bill.end_date,
        total=bill.total_occurrences,
        until=horizon_end(today),
    ):
        if due in existing_dates:
            continue
        status = OccurrenceStatus.unpaid
        if due < today:
            if past == PAST_NONE:
                continue
            if past == PAST_SKIPPED:
                status = OccurrenceStatus.skipped
        # A SAVEPOINT keeps a duplicate-date collision from rolling back the
        # caller's whole transaction — a plain db.rollback() here used to
        # discard the not-yet-committed bill these rows point at.
        try:
            with db.begin_nested():
                db.add(BillOccurrence(bill_id=bill.id, due_date=due, amount=None, status=status))
                db.flush()
            created += 1
        except IntegrityError:
            pass
        existing_dates.add(due)
    return created


def delete_future_occurrences(db: Session, bill_id: str) -> None:
    """Remove the future entries an edit may regenerate (spec §3.4.3).

    Only expected entries after today with no amount set and nothing linked:
    done and skipped entries, and entries whose amount the user set, are
    never touched. Does not commit — the caller owns the transaction.
    """
    today = local_today()
    db.query(BillOccurrence).filter(
        BillOccurrence.bill_id == bill_id,
        BillOccurrence.due_date > today,
        BillOccurrence.status == OccurrenceStatus.unpaid,
        BillOccurrence.amount.is_(None),
        BillOccurrence.transaction_id.is_(None),
    ).delete(synchronize_session=False)
```
`datetime` and `NamedTuple` stay imported because the rest of the module uses them.

- [ ] **Step 4: The old app's forms create nothing expected in the past**

In `app/routes/bills.py`, add `PAST_NONE` and `PAST_SKIPPED` to the `from app.services.bills import (...)` list.
- In `create_bill`, replace `generate_occurrences(db, bill)` with:
```python
    # Nothing before today becomes an expected entry (spec §3.4.4).
    generate_occurrences(db, bill, past=PAST_SKIPPED)
```
- In `edit_bill`, replace the two lines under `# Regenerate future occurrences` with:
```python
    # Regenerate the future entries nobody touched (spec §3.4.3-4).
    delete_future_occurrences(db, bill.id)
    generate_occurrences(db, bill, past=PAST_SKIPPED)
```
- In `toggle_bill`, replace `bill.is_active = not bill.is_active` and the `db.commit()` after it with:
```python
    bill.is_active = not bill.is_active
    if bill.is_active:
        # Resumed: fill the horizon now rather than at the next nightly run.
        generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
```
In `app/api/bills.py`, add `PAST_SKIPPED` to the `from app.services.bills import (...)` list. Then replace both `generate_occurrences(db, bill)` calls (in `create_bill` and `update_bill`) with `generate_occurrences(db, bill, past=PAST_SKIPPED)`.

Past dates become *skipped* placeholders, not nothing, for two reasons:
- `tests/test_bills.py::test_bill_survives_occurrence_generation` (unchanged) counts 12 rows for a 12-occurrence bill that started in January.
- Skipped rows never count anywhere: auto-pay, overdue, "Bills due" and payment history all ignore them.

- [ ] **Step 5: The daily top-up job**

In `app/scheduler.py`, insert this section directly before the `# Job entry point` banner:
```python
# ---------------------------------------------------------------------------
# Planning (spec §3.3)
# ---------------------------------------------------------------------------


def _top_up_entries(db, today: date) -> int:
    """Extend every active item's entries to the rolling horizon.

    Never creates an entry dated before today. A bad rule on one item is
    logged and skipped; the others still get their entries.
    """
    from app.models import RecurringBill
    from app.services.bills import PAST_NONE, generate_occurrences

    bill_ids = [
        bill_id
        for (bill_id,) in db.query(RecurringBill.id).filter(RecurringBill.active_filter())
    ]
    created = 0
    for bill_id in bill_ids:
        try:
            created += generate_occurrences(
                db, db.get(RecurringBill, bill_id), today=today, past=PAST_NONE
            )
            db.commit()
        except Exception:
            logger.exception("Could not top up entries for recurring item %s", bill_id)
            db.rollback()
    if created:
        logger.info("Created %d expected entries", created)
    return created


def _planning_stages():
    return (_top_up_entries,)


def planning_daily_job() -> None:
    """Daily planning job: top up expected entries. Each stage is isolated."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        today = today_local()
        for stage in _planning_stages():
            try:
                stage(db, today)
            except Exception:
                logger.exception("Planning job stage %s failed", stage.__name__)
                db.rollback()
    finally:
        db.close()
```
In `start_scheduler`, after the `auto_mark_paid_startup` `add_job(...)` call, add:
```python
    # Expected entries before auto-pay looks at them; a separate job so the
    # bills job (and its tests) only ever see entries that already exist.
    scheduler.add_job(
        planning_daily_job,
        CronTrigger(hour=0, minute=1, timezone=_tz()),
        id="planning_daily",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        planning_daily_job,
        id="planning_startup",
        replace_existing=True,
        max_instances=1,
    )
```
The top-up is a separate job and deliberately not a stage of `auto_mark_paid_job`. Scheduler tests such as `test_autopay_creates_one_transaction` assert `db.query(BillOccurrence).one()` after running that job, and a top-up inside it would add 12 rows.

- [ ] **Step 6: Retire the live-generator comparison**

In `tests/test_schedule_rules.py`, delete `test_frozen_copy_matches_the_live_generator` and nothing else. The frozen copy `_old_generator_dates` and the parametrised comparison stay.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_generation.py tests/test_schedule_rules.py tests/test_bills.py tests/test_scheduler.py tests/test_payer_backfill.py -q`
Expected: all pass.

- [ ] **Step 8: Full suite and commit**

Run: `.venv/bin/python -m pytest -q`. Expected: all pass.
```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/bills.py app/routes/bills.py app/api/bills.py app/scheduler.py tests/test_planning_generation.py tests/test_schedule_rules.py
git commit -m "feat(planning): entries from the shared rule engine, 13-month horizon with daily top-up; edits keep touched entries; nothing expected before today"
```

---
### Task 4: The old app and shared bill queries: paused and income hidden, new rules read-only, the auto-pay window

**Files:**
- Modify:
  - `app/services/dashboard.py`: `get_upcoming_bills` and `get_overdue_bills` (lines 56–92).
  - `app/services/insights.py`: `get_bills_due_month_total` (lines 179–201) and `get_insights_bills_due` (lines 756–797).
  - `app/scheduler.py`:
    - constants (after line 48);
    - `_auto_pay_due_bills` (filter at lines 148–156);
    - the `_notify_due_soon`, `_notify_overdue`, `_notify_contracts_expiring` and `_notify_bill_drift` filters.
  - `app/services/bills.py`: a new constant before `BILL_HAS_HISTORY_MSG`.
  - `app/routes/bills.py`: imports, new helpers before `_bill_payer`, `_render_bills`, and every handler's bill/occurrence lookup.
  - `app/api/bills.py`: imports, `_assert_bill_in_household`, `list_bills`, `update_bill`, and the `pay_occurrence`/`skip_occurrence` lookups.
  - `templates/bills/list.html`: lines 137 and 170–173.
- Test: `tests/test_planning_old_app.py`

**Interfaces:**
- Consumes:
  - `RecurringBill.active_filter()`, `RecurringBill.old_app_editable`, `ItemDirection` (Task 2);
  - `generate_occurrences(..., past=...)` (Task 3).
- Produces:
  - `app.services.bills.EDIT_IN_NEW_APP_MSG: str`
  - `app.scheduler.AUTO_PAY_WINDOW_DAYS = 3`
  - `app/routes/bills.py`: `_old_app_bill(db, bill_id, hh_id) -> RecurringBill` and `_old_app_occurrence(db, occ_id, hh_id) -> BillOccurrence`. Both raise 404 for another household's item or an `in` item.
  - `_require_old_app_editable(bill)`, which raises 409 for a new-rule item.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_old_app.py`:
```python
"""The old app and shared queries see only active out items (spec §3.4.1,
§3.4.5, §6.2): paused and income items are hidden, new rules are read-only,
auto-pay never backfills."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import BillOccurrence, Notification, OccurrenceStatus, Transaction
from app.services import (
    get_bills_due_month_total,
    get_insights_bills_due,
    get_overdue_bills,
    get_upcoming_bills,
)
from tests.test_api import api  # noqa: F401  (fixture)


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _three(db, make_bill, hh, due):
    """An active bill, a paused bill and an income item, all due on ``due``."""
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False, due=due)
    paused, _ = make_bill(
        hh.household_id, hh.bucket_id, amount=20, auto_pay=False, due=due, name="Paused"
    )
    paused.is_active = False
    salary, _ = make_bill(
        hh.household_id, None, amount=1500, auto_pay=False, due=due, name="Salary X"
    )
    salary.direction = "in"
    db.commit()
    return bill, paused, salary


def test_bill_queries_skip_paused_and_income_items(db, make_household, make_bill):
    hh = make_household()
    today = local_today()
    bill, _, _ = _three(db, make_bill, hh, today + timedelta(days=2))
    assert [o.bill_id for o in get_upcoming_bills(db, hh.household_id)] == [bill.id]
    due = today + timedelta(days=2)
    assert get_bills_due_month_total(db, hh.household_id, due.year, due.month) == Decimal("10.00")
    assert get_insights_bills_due(db, hh.household_id, due, due) == Decimal("10.00")


def test_overdue_skips_paused_and_income_items(db, make_household, make_bill):
    hh = make_household()
    bill, _, _ = _three(db, make_bill, hh, local_today() - timedelta(days=5))
    assert [o.bill_id for o in get_overdue_bills(db, hh.household_id)] == [bill.id]


def test_bills_page_lists_out_items_only(client, db, authed, make_bill):
    _three(db, make_bill, authed, local_today() + timedelta(days=2))
    page = client.get("/bills").text
    assert "Internet" in page and "Paused" in page
    assert "Salary X" not in page


def test_old_routes_404_on_income_items(client, db, authed, make_bill):
    _, _, salary = _three(db, make_bill, authed, local_today())
    occ = db.query(BillOccurrence).filter_by(bill_id=salary.id).one()
    h = authed.headers
    assert client.post(f"/bills/{salary.id}/occurrences/{occ.id}/pay", headers=h).status_code == 404
    assert (
        client.post(f"/bills/{salary.id}/occurrences/{occ.id}/skip", headers=h).status_code == 404
    )
    r = client.post(
        f"/bills/{salary.id}/occurrences/{occ.id}/set-amount", data={"amount": "5"}, headers=h
    )
    assert r.status_code == 404
    assert client.get(f"/bills/{salary.id}/edit").status_code == 404
    assert client.post(f"/bills/{salary.id}/toggle", headers=h).status_code == 404
    assert client.post(f"/bills/{salary.id}/delete", headers=h).status_code == 404
    assert client.get(f"/bills/{salary.id}/history").status_code == 404
    assert db.query(Transaction).count() == 0


def test_old_api_hides_income_items(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    _, _, salary = _three(db, make_bill, hh, local_today())
    occ = db.query(BillOccurrence).filter_by(bill_id=salary.id).one()
    names = [b["name"] for b in client.get("/api/v1/bills", headers=headers).json()["items"]]
    assert "Salary X" not in names
    assert client.get(f"/api/v1/bills/{salary.id}", headers=headers).status_code == 404
    r = client.post(f"/api/v1/bills/occurrences/{occ.id}/pay", headers=headers, json={})
    assert r.status_code == 404
    assert db.query(Transaction).count() == 0


def test_new_rule_items_are_read_only_in_the_old_app(client, db, authed, make_bill):
    bill, _ = make_bill(authed.household_id, authed.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind, bill.rule_day = "monthly_day", 26
    db.commit()
    assert "Edit in the new app" in client.get("/bills").text
    assert client.get(f"/bills/{bill.id}/edit").status_code == 409
    r = client.post(
        f"/bills/{bill.id}/edit",
        headers=authed.headers,
        data={"name": "X", "start_date": "2026-01-01", "interval_months": "1"},
    )
    assert r.status_code == 409
    db.expire_all()
    assert bill.name == "Internet"


def test_new_rule_items_are_read_only_in_the_old_api(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    bill.rule_kind = "last_business_day"
    db.commit()
    r = client.put(
        f"/api/v1/bills/{bill.id}",
        headers=headers,
        json={"name": "X", "start_date": "2026-01-01", "bucket_id": hh.bucket_id},
    )
    assert r.status_code == 409


def test_auto_pay_window_is_three_days(db, make_household, make_bill, run_job):
    hh = make_household()
    today = local_today()
    _, edge = make_bill(hh.household_id, hh.bucket_id, amount=5, due=today - timedelta(days=3))
    _, old = make_bill(
        hh.household_id, hh.bucket_id, amount=7, due=today - timedelta(days=4), name="Old"
    )
    run_job()
    db.expire_all()
    assert db.get(BillOccurrence, edge.id).status == OccurrenceStatus.paid
    assert db.get(BillOccurrence, old.id).status == OccurrenceStatus.unpaid
    assert db.query(Transaction).count() == 1


def test_income_items_get_no_bill_reminders(db, make_household, make_bill, run_job):
    hh = make_household()
    salary, _ = make_bill(
        hh.household_id,
        None,
        amount=1500,
        auto_pay=False,
        due=local_today() + timedelta(days=3),
        name="Salary X",
    )
    salary.direction = "in"
    db.commit()
    run_job()
    assert db.query(Notification).count() == 0
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_old_app.py -q`
Expected: several failures, for example:
- `test_bill_queries_skip_paused_and_income_items` sees 3 upcoming bills;
- `test_old_routes_404_on_income_items` gets 302/200;
- `test_auto_pay_window_is_three_days` pays the 4-day-old entry.

- [ ] **Step 3: Shared bill queries show only active out items**

`app/services/dashboard.py`: add `ItemDirection,` to the `from app.models import (...)` list. In **both** `get_upcoming_bills` and `get_overdue_bills`, insert after `RecurringBill.household_id == household_id,`:
```python
            # Paused items and income are not bills due (spec §3.4.1, §6.2.1).
            RecurringBill.active_filter(),
            RecurringBill.direction == ItemDirection.out.value,
```
`app/services/insights.py`: add `ItemDirection,` to the `from app.models import (...)` list. In **both** `get_bills_due_month_total` and `get_insights_bills_due`, insert after `RecurringBill.household_id == household_id,`:
```python
            RecurringBill.active_filter(),
            RecurringBill.direction == ItemDirection.out.value,
```
"Bills due" keeps counting paid entries, as `tests/test_shared_insights.py::test_bills_due_excludes_skipped_occurrences` asserts. Only paused and income items leave.

- [ ] **Step 4: Scheduler: the auto-pay window and out-only reminders**

In `app/scheduler.py`, after `DRIFT_LOOKBACK_DAYS = 35 ...`, add:
```python
# Auto-pay pays entries due today or in the last 3 days, never older ones
# (spec §3.4.5): a bill created or resumed late is not backfilled.
AUTO_PAY_WINDOW_DAYS = 3
```
In `_auto_pay_due_bills`, after `BillOccurrence.due_date <= today,`, add:
```python
            BillOccurrence.due_date >= today - timedelta(days=AUTO_PAY_WINDOW_DAYS),
```
In the same filter, after `RecurringBill.is_active.is_(True),`, and likewise in `_notify_due_soon`, `_notify_overdue` and `_notify_contracts_expiring` (each filters `RecurringBill.is_active.is_(True)`), add:
```python
            RecurringBill.direction == "out",
```
In `_notify_bill_drift`, replace `bills = db.query(RecurringBill).filter(RecurringBill.is_active.is_(True)).all()` with:
```python
    bills = (
        db.query(RecurringBill)
        .filter(RecurringBill.is_active.is_(True), RecurringBill.direction == "out")
        .all()
    )
```
The existing scheduler tests use `due=today - 3 days` only for `auto_pay=False` bills, so the window does not affect them.

- [ ] **Step 5: The old app sees only out items and cannot edit new rules**

In `app/services/bills.py`, directly above `BILL_HAS_HISTORY_MSG = (`, add:
```python
EDIT_IN_NEW_APP_MSG = (
    "This item uses a schedule the old app can't edit. Edit it in the new app."
)
```
In `app/routes/bills.py`:
- add `ItemDirection,` to the `from app.models import (...)` list;
- add `EDIT_IN_NEW_APP_MSG,` to the `from app.services.bills import (...)` list;
- directly above `def _bill_payer(`, add:
```python
def _old_app_bill(db: Session, bill_id: str, hh_id: str) -> RecurringBill:
    """The bill if the old app may see it: this household's, and an out item.

    Income items do not exist for the old app (spec §6.2.1), so a stale page
    or bookmark gets a 404 and can never pay one as an expense.
    """
    bill = db.get(RecurringBill, bill_id)
    if not bill or bill.household_id != hh_id or bill.direction != ItemDirection.out.value:
        raise HTTPException(status_code=404)
    return bill


def _old_app_occurrence(db: Session, occ_id: str, hh_id: str) -> BillOccurrence:
    occ = db.get(BillOccurrence, occ_id)
    if not occ:
        raise HTTPException(status_code=404)
    _old_app_bill(db, occ.bill_id, hh_id)
    return occ


def _require_old_app_editable(bill: RecurringBill) -> None:
    """New schedule rules are read-only here (spec §6.2.2)."""
    if not bill.old_app_editable:
        raise HTTPException(status_code=409, detail=EDIT_IN_NEW_APP_MSG)
```
Then:
- In `_render_bills`, replace the `bills_q = (...)` expression with:
```python
    bills_q = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id, direction=ItemDirection.out.value)
        .order_by(RecurringBill.created_at)
    )
```
- In `mark_paid`, `set_occurrence_amount` and `skip_occurrence`, replace the three lines
  ```python
      occ = db.get(BillOccurrence, occ_id)
      if not occ or occ.bill.household_id != hh_id:
          raise HTTPException(status_code=404)
  ```
  with `occ = _old_app_occurrence(db, occ_id, hh_id)`.
- In `edit_bill_page`, `edit_bill`, `toggle_bill`, `delete_bill` and `bill_history`, replace
  ```python
      bill = db.get(RecurringBill, bill_id)
      if not bill or bill.household_id != hh_id:
          raise HTTPException(status_code=404)
  ```
  with `bill = _old_app_bill(db, bill_id, hh_id)`.
- In `edit_bill_page` and `edit_bill`, add `_require_old_app_editable(bill)` on the next line.

In `app/api/bills.py`:
- add `ItemDirection,` to the models import and `EDIT_IN_NEW_APP_MSG,` to the `app.services.bills` import;
- replace `_assert_bill_in_household` with:
```python
def _assert_bill_in_household(bill: RecurringBill | None, hh_id: str):
    # Income items belong to /recurring; this older API only knows bills.
    if not bill or bill.household_id != hh_id or bill.direction != ItemDirection.out.value:
        raise HTTPException(status_code=404, detail="Bill not found")
```
- in `list_bills`, replace the `q = ...` line with:
```python
    q = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id, direction=ItemDirection.out.value)
        .order_by(RecurringBill.created_at)
    )
```
- in `update_bill`, after `_assert_bill_in_household(bill, hh_id)`, add:
```python
    if not bill.old_app_editable:
        raise HTTPException(status_code=409, detail=EDIT_IN_NEW_APP_MSG)
```
- in `pay_occurrence` and `skip_occurrence`, change the lookup condition to:
```python
    if not occ or occ.bill.household_id != hh_id or occ.bill.direction != ItemDirection.out.value:
```

- [ ] **Step 6: The bills list shows "Edit in the new app"**

In `templates/bills/list.html`, change line 137 (the frequency badge) to:
```jinja
              {% if not bill.old_app_editable %}New-app schedule{% elif bill.frequency.value == 'monthly' %}Monthly{% else %}Every {{ bill.interval_months }} months{% endif %}
```
Then wrap the edit link (`<a href="/bills/{{ bill.id }}/edit" … </a>`, lines 170–173) like this:
```jinja
          {% if bill.old_app_editable %}
          <a href="/bills/{{ bill.id }}/edit"
             class="p-1.5 text-gray-400 hover:text-primary-500 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors" title="Edit">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
          </a>
          {% else %}
          <span class="px-1.5 text-xs text-gray-400" title="This schedule can only be changed in the new app">Edit in the new app</span>
          {% endif %}
```
Keep the toggle `<form>` that follows on the same line exactly as it is.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_old_app.py tests/test_bills.py tests/test_bill_fixes.py tests/test_scheduler.py tests/test_alerts.py tests/test_shared_insights.py tests/test_isolation.py -q`
Expected: all pass.

- [ ] **Step 8: Full suite and commit**

Run: `.venv/bin/python -m pytest -q`. Expected: all pass.
```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/dashboard.py app/services/insights.py app/scheduler.py app/services/bills.py app/routes/bills.py app/api/bills.py templates/bills/list.html tests/test_planning_old_app.py
git commit -m "fix(bills): paused and income items leave every bill list and total; old app read-only for new rules; auto-pay never backfills past 3 days"
```

---

### Task 5: Entry lifecycle: undo, skip, set amount, the "≈" estimate, and a deleted payment reopens its entry

**Files:**
- Modify:
  - `app/services/bills.py`: a new section directly above `def effective_overrides(` (line 352 before Task 3, about line 410 after it), plus `bill_has_payment_history`.
  - `app/services/transactions.py`: the imports and `delete_transaction` (lines 82–97).
- Test: `tests/test_planning_lifecycle.py`

**Interfaces:**
- Consumes:
  - `pay_occurrence`, `claim_occurrence`, `_q`, `_dec` (existing in `app.services.bills`);
  - `app.services.transactions.delete_transaction(db, txn, uploads_dir=None)` (existing).
- Produces (in `app.services.bills`):
  - `ESTIMATE_FROM_LAST = 3`, `FIXED_COST_NEEDS_ITEM_MSG: str`
  - `class EntryStateError(Exception)`, with a user-facing message; the API maps it to 409.
  - `reopen_occurrence(occ) -> None`
  - `undo_occurrence(db, occ, *, delete_transaction: bool = False) -> None`, which commits only on the delete path.
  - `skip_entry(occ) -> None`
  - `set_entry_amount(occ, amount: Decimal) -> None`
  - `estimate_amount(db, bill_id: str) -> Decimal | None`
  - `bill_has_payment_history` is also true when any transaction, deleted ones included, has `recurring_bill_id == bill_id`.
  - `delete_transaction` puts the linked entry back to expected.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_lifecycle.py`:
```python
"""Entry lifecycle (spec §3.3): undo done or skipped, a deleted payment
reopens its entry, set amount, the "≈" estimate."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, Transaction
from app.services import delete_transaction
from app.services.bills import (
    EntryStateError,
    estimate_amount,
    pay_occurrence,
    set_entry_amount,
    skip_entry,
    undo_occurrence,
)


def _paid(db, hh, make_bill, **kw):
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=45, auto_pay=False, **kw)
    txn = pay_occurrence(db, occ, amount=45, paid_by=hh.user_id, paid_on=utcnow_naive())
    db.commit()
    return bill, occ, txn


def test_undo_done_keeps_the_expense_but_unlinks_it(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _paid(db, hh, make_bill)
    undo_occurrence(db, occ)
    db.commit()
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.unpaid and occ.transaction_id is None
    kept = db.get(Transaction, txn.id)
    assert kept.deleted_at is None and kept.recurring_bill_id is None


def test_undo_done_can_delete_the_expense(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _paid(db, hh, make_bill)
    undo_occurrence(db, occ, delete_transaction=True)
    db.expire_all()
    assert db.get(Transaction, txn.id).deleted_at is not None
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_undo_skipped_and_undo_expected(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    skip_entry(occ)
    undo_occurrence(db, occ)
    assert occ.status == OccurrenceStatus.unpaid
    with pytest.raises(EntryStateError):
        undo_occurrence(db, occ)


def test_a_done_entry_cannot_be_skipped(db, make_household, make_bill):
    hh = make_household()
    _, occ, _ = _paid(db, hh, make_bill)
    with pytest.raises(EntryStateError):
        skip_entry(occ)


def test_soft_deleting_the_payment_reopens_the_entry(db, make_household, make_bill):
    hh = make_household()
    _, occ, txn = _paid(db, hh, make_bill)
    delete_transaction(db, txn)
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.unpaid
    assert occ.transaction_id is None and occ.paid_at is None


def test_deleting_through_the_old_ui_reopens_the_entry(client, db, authed, make_bill):
    _, occ, txn = _paid(db, authed, make_bill)
    r = client.post(f"/transactions/{txn.id}/delete", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_set_amount_only_on_expected_entries(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=None, auto_pay=False)
    set_entry_amount(occ, Decimal("61.456"))
    assert occ.amount == Decimal("61.46")
    occ.status = OccurrenceStatus.skipped
    with pytest.raises(EntryStateError):
        set_entry_amount(occ, Decimal("1"))


def test_estimate_is_the_mean_of_the_last_three_done_amounts(db, make_household, make_bill):
    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=None, occurrence=False)
    assert estimate_amount(db, bill.id) is None
    today = local_today()
    for months_ago, amount in ((4, 500), (3, 60), (2, 70), (1, 80)):
        db.add(
            BillOccurrence(
                bill_id=bill.id,
                due_date=today - timedelta(days=30 * months_ago),
                amount=Decimal(amount),
                status=OccurrenceStatus.paid,
            )
        )
    db.commit()
    assert estimate_amount(db, bill.id) == Decimal("70.00")
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_lifecycle.py -q`
Expected: collection error, `ImportError: cannot import name 'EntryStateError' from 'app.services.bills'`.

- [ ] **Step 3: The lifecycle actions**

In `app/services/bills.py`, directly above `def effective_overrides(bill: RecurringBill, submitted)`, add:
```python
# ---------------------------------------------------------------------------
# Entry lifecycle (spec §3.3): undo, skip, set amount, estimate
# ---------------------------------------------------------------------------

ESTIMATE_FROM_LAST = 3  # done amounts averaged for a variable item's estimate

FIXED_COST_NEEDS_ITEM_MSG = (
    "This expense has no bucket, so it can't stay without its bill. "
    "Delete it too, or give it a bucket first."
)


class EntryStateError(Exception):
    """The entry is not in a state that allows this action (HTTP 409).

    The message is user-facing.
    """


def reopen_occurrence(occ: BillOccurrence) -> None:
    """Put an entry back to expected: not paid, nothing linked. Does not commit."""
    occ.status = OccurrenceStatus.unpaid
    occ.paid_at = None
    occ.paid_by = None
    occ.transaction_id = None


def undo_occurrence(db: Session, occ: BillOccurrence, *, delete_transaction: bool = False) -> None:
    """Done -> expected, or skipped -> expected (spec §3.3).

    A done entry's transaction is unlinked; with ``delete_transaction`` it is
    soft-deleted too (app.services.transactions.delete_transaction, which
    reopens the entry and commits). Kept, a bucket-less expense would break
    the transactions CHECK, so that raises EntryStateError. Otherwise does
    not commit.
    """
    if occ.status == OccurrenceStatus.skipped:
        reopen_occurrence(occ)
        return
    if occ.status != OccurrenceStatus.paid:
        raise EntryStateError("This entry is already expected.")
    txn = db.get(Transaction, occ.transaction_id) if occ.transaction_id else None
    if txn is None or txn.deleted_at is not None:
        reopen_occurrence(occ)
        return
    if delete_transaction:
        from app.services.transactions import delete_transaction as soft_delete

        soft_delete(db, txn)
        return
    if txn.bucket_id is None and txn.type == TransactionType.expense:
        raise EntryStateError(FIXED_COST_NEEDS_ITEM_MSG)
    txn.recurring_bill_id = None
    reopen_occurrence(occ)


def skip_entry(occ: BillOccurrence) -> None:
    """Expected -> skipped. A done entry has to be undone first. Does not commit."""
    if occ.status == OccurrenceStatus.paid:
        raise EntryStateError("This entry is done. Undo it first.")
    occ.status = OccurrenceStatus.skipped


def set_entry_amount(occ: BillOccurrence, amount: Decimal) -> None:
    """Store the real amount on an expected entry (spec §3.3). Does not commit."""
    if occ.status != OccurrenceStatus.unpaid:
        raise EntryStateError("Only an expected entry can have its amount set.")
    occ.amount = _q(amount)


def estimate_amount(db: Session, bill_id: str) -> Decimal | None:
    """The "≈" amount of a variable item: the mean of its last 3 done amounts.

    None when nothing has been done with an amount yet.
    """
    rows = [
        _dec(a)
        for (a,) in db.query(BillOccurrence.amount)
        .filter(
            BillOccurrence.bill_id == bill_id,
            BillOccurrence.status == OccurrenceStatus.paid,
            BillOccurrence.amount.isnot(None),
        )
        .order_by(BillOccurrence.due_date.desc())
        .limit(ESTIMATE_FROM_LAST)
    ]
    if not rows:
        return None
    return _q(sum(rows, Decimal(0)) / len(rows))
```

- [ ] **Step 4: Payment history includes linked transactions**

Replace `bill_has_payment_history` with:
```python
def bill_has_payment_history(db: Session, bill_id: str) -> bool:
    """True if any occurrence was paid, or skipped with an amount recorded, or
    any transaction (even a deleted one) is linked to the item.

    Deleting such a bill would cascade away the only record of those payments
    (for bucketless bills the paid occurrence *is* the payment record). A
    linked Fixed-cost expense has no bucket, so the FK's SET NULL would break
    the transactions CHECK.
    """
    if (
        db.query(Transaction.id).filter(Transaction.recurring_bill_id == bill_id).first()
        is not None
    ):
        return True
    return (
        db.query(BillOccurrence.id)
        .filter(
            BillOccurrence.bill_id == bill_id,
            (BillOccurrence.status == OccurrenceStatus.paid)
            | (
                (BillOccurrence.status == OccurrenceStatus.skipped)
                & BillOccurrence.amount.isnot(None)
            )
            | BillOccurrence.transaction_id.isnot(None),
        )
        .first()
        is not None
    )
```
Without this, deleting an item whose only linked expense was soft-deleted would hit `ON DELETE SET NULL`. A bucket-less expense would then break the transactions CHECK.

- [ ] **Step 5: A soft-deleted payment reopens its entry**

In `app/services/transactions.py`, add `BillOccurrence,` and `OccurrenceStatus,` to the `from app.models import (...)` list. In `delete_transaction`, between the `CashMovement` `update(...)` and `db.commit()`, insert:
```python
    # A deleted payment puts its entry back to expected (spec §3.3).
    db.query(BillOccurrence).filter(BillOccurrence.transaction_id == txn.id).update(
        {
            BillOccurrence.status: OccurrenceStatus.unpaid,
            BillOccurrence.paid_at: None,
            BillOccurrence.paid_by: None,
            BillOccurrence.transaction_id: None,
        },
        synchronize_session=False,
    )
```
This covers the old UI, the old API and the new app, since all of them delete through this service.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_lifecycle.py tests/test_soft_delete.py tests/test_bill_fixes.py tests/test_bills.py -q`
Expected: all pass.

- [ ] **Step 7: Full suite and commit**

Run: `.venv/bin/python -m pytest -q`. Expected: all pass.
```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/bills.py app/services/transactions.py tests/test_planning_lifecycle.py
git commit -m "feat(planning): undo done/skipped entries, skip, set amount and estimate; a deleted payment reopens its entry"
```

---

### Task 6: Income items: Mark received

**Files:**
- Modify: `app/services/bills.py`. Add `utcnow_naive` to the clock import, `ItemDirection` and `PaymentMethod` to the models import, and a new function above `def settle_occurrence(`.
- Test: `tests/test_planning_income.py`

**Interfaces:**
- Consumes: `claim_occurrence`, `resolve_bill_payer`, `_q` (existing); `ItemDirection` (Task 2); `undo_occurrence` (Task 5).
- Produces: `app.services.bills.receive_occurrence(db, occ, *, amount, received_by: str | None, paid_on: datetime, fallback_user_id: str | None = None) -> Transaction | None`. It does not commit. It raises `ValueError` for an out item and returns None when the claim is lost.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_income.py`. The second test pins spec §5.5's per-person lens: the existing `get_insights_income(..., paid_by=)` already filters by recipient.
```python
"""Income items: Mark received creates and links an income (spec §3.1, §3.3, §5.5)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today, utcnow_naive
from app.models import BillOccurrence, OccurrenceStatus, Transaction, TransactionType
from app.services import delete_transaction, get_insights_income
from app.services.bills import receive_occurrence, undo_occurrence
from tests.test_household_settlement import _add_member


def _salary(db, make_bill, hh, **kw):
    bill, occ = make_bill(hh.household_id, None, amount=1500, auto_pay=False, name="Salary", **kw)
    bill.direction = "in"
    db.commit()
    return bill, occ


def test_mark_received_creates_linked_bucketless_income(db, make_household, make_bill):
    hh = make_household()
    partner = _add_member(db, hh.household_id, "partner")
    bill, occ = _salary(db, make_bill, hh, paid_by=partner.id)

    txn = receive_occurrence(
        db, occ, amount=Decimal("1500"), received_by=None, paid_on=utcnow_naive()
    )
    db.commit()

    assert txn.type == TransactionType.income and txn.bucket_id is None
    assert txn.recurring_bill_id == bill.id and txn.paid_by == partner.id
    assert txn.transaction_date == occ.due_date
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.status == OccurrenceStatus.paid and occ.transaction_id == txn.id


def test_received_income_counts_for_the_person_who_received_it(db, make_household, make_bill):
    hh = make_household()
    partner = _add_member(db, hh.household_id, "partner")
    _, occ = _salary(db, make_bill, hh)
    receive_occurrence(db, occ, amount=1500, received_by=partner.id, paid_on=utcnow_naive())
    db.commit()
    day = occ.due_date
    assert get_insights_income(db, hh.household_id, day, day, paid_by=partner.id) == Decimal(
        "1500.00"
    )
    assert get_insights_income(db, hh.household_id, day, day, paid_by=hh.user_id) == Decimal("0.00")


def test_receiving_twice_creates_one_income(db, make_household, make_bill):
    hh = make_household()
    _, occ = _salary(db, make_bill, hh)
    assert receive_occurrence(db, occ, amount=1500, received_by=None, paid_on=utcnow_naive())
    db.commit()
    assert (
        receive_occurrence(db, occ, amount=1500, received_by=None, paid_on=utcnow_naive()) is None
    )
    assert db.query(Transaction).count() == 1


def test_an_out_item_cannot_be_received(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    with pytest.raises(ValueError):
        receive_occurrence(db, occ, amount=45, received_by=None, paid_on=utcnow_naive())


def test_undo_and_delete_reopen_an_income_entry(db, make_household, make_bill):
    hh = make_household()
    _, occ = _salary(db, make_bill, hh, due=local_today() - timedelta(days=1))
    txn = receive_occurrence(db, occ, amount=1500, received_by=None, paid_on=utcnow_naive())
    db.commit()
    undo_occurrence(db, occ)  # keeps the income, unlinked
    db.commit()
    db.expire_all()
    assert db.get(Transaction, txn.id).recurring_bill_id is None
    occ = db.get(BillOccurrence, occ.id)
    txn2 = receive_occurrence(db, occ, amount=1400, received_by=None, paid_on=utcnow_naive())
    db.commit()
    delete_transaction(db, txn2)
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_income.py -q`
Expected: `ImportError: cannot import name 'receive_occurrence'`.

- [ ] **Step 3: Implement**

In `app/services/bills.py`:
- change `from app.core.clock import local_today` to `from app.core.clock import local_today, utcnow_naive`;
- add `ItemDirection,` and `PaymentMethod,` to the `from app.models import (...)` list;
- directly above `def settle_occurrence(`, add:
```python
def receive_occurrence(
    db: Session,
    occ: BillOccurrence,
    *,
    amount,
    received_by: str | None,
    paid_on: datetime,
    fallback_user_id: str | None = None,
) -> Transaction | None:
    """Mark received: create the entry's income and link it (spec §3.3).

    Income has no bucket and is dated on the due date. The recipient is
    ``received_by``, else the item's "received by" (``paid_by_default``) while
    still a member, then ``fallback_user_id``, then the owner (as for bill
    payers, :func:`resolve_bill_payer`). Returns None when the atomic claim
    fails (already done). Raises ValueError for an out item. Does not commit.
    """
    bill = occ.bill
    if bill.direction != ItemDirection.in_.value:
        raise ValueError("Only an income item can be marked received.")
    amount = _q(amount)
    person = received_by or resolve_bill_payer(db, bill, fallback_user_id)
    if not claim_occurrence(db, occ, paid_by=person, paid_on=paid_on):
        return None
    txn = Transaction(
        bucket_id=None,
        household_id=bill.household_id,
        amount=amount,
        currency=bill.currency,
        type=TransactionType.income,
        paid_by=person,
        category_id=bill.category_id,
        notes=f"Income: {bill.name}",
        payment_method=PaymentMethod.transfer.value,
        transaction_date=occ.due_date,
        recurring_bill_id=bill.id,
    )
    db.add(txn)
    db.flush()
    db.query(BillOccurrence).filter(BillOccurrence.id == occ.id).update(
        {BillOccurrence.transaction_id: txn.id}, synchronize_session=False
    )
    occ.transaction_id = txn.id
    return txn
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_income.py tests/test_planning_lifecycle.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/bills.py tests/test_planning_income.py
git commit -m "feat(planning): Mark received creates and links a bucket-less income for in items"
```

---

### Task 7: Fixed costs: a bucket-less out item is paid with a linked expense

**Files:**
- Modify:
  - `app/services/bills.py`:
    - `pay_occurrence` (the docstring at lines 286–297 and the `Transaction(...)` at lines 316–328);
    - a new `complete_entry` above `def settle_occurrence(`.
  - `app/schemas.py`: `class TransactionUpdate` (line 331). Override the bucket check.
  - `app/services/transactions.py`: `update_transaction` (lines 365–367).
  - `app/routes/transactions.py`: `duplicate_transaction` (the `Transaction(...)` at lines 461–477).
- Test: `tests/test_planning_fixed_costs.py`

**Interfaces:**
- Consumes:
  - `EntryStateError`, `undo_occurrence` (Task 5);
  - `receive_occurrence` (Task 6);
  - `resolve_bill_payment`, `pay_occurrence` (existing);
  - the relaxed CHECK (Task 2).
- Produces:
  - `pay_occurrence` now sets `recurring_bill_id=bill.id` on every expense it creates, and works with no bucket.
  - `app.services.bills.complete_entry(db, occ, *, user_id: str, amount=None, person: str | None = None, payment_method: str = "card") -> Transaction`. It does not commit, raises `EntryStateError` when the entry is not expected, and raises `ValueError` when it has no amount.
  - `TransactionUpdate` no longer rejects a blank bucket; `update_transaction` decides, allowing it for income and for Fixed costs.

The old app's `settle_occurrence` is unchanged: a bucket-less bill paid there is still a bare claim (spec §6.2.4).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_fixed_costs.py`. Review Focus #1 is pinned here: the old edit form, Duplicate, the old pages, and refusing to delete the item.
```python
"""Fixed costs: an out item with no bucket is paid with a bucket-less expense
linked to the item (spec §3.4.2, §6.2.4), and old code paths cope with it."""

from decimal import Decimal

import pytest

from app.models import BillOccurrence, OccurrenceStatus, Transaction, TransactionType
from app.schemas import TransactionUpdate
from app.services.bills import EntryStateError, complete_entry, undo_occurrence


def _fixed(db, hh, make_bill, **kw):
    bill, occ = make_bill(hh.household_id, None, amount=38.90, auto_pay=False, name="Cosmote", **kw)
    txn = complete_entry(db, occ, user_id=hh.user_id)
    db.commit()
    return bill, occ, txn


def test_pay_without_bucket_creates_a_fixed_cost(db, make_household, make_bill):
    hh = make_household()
    bill, occ, txn = _fixed(db, hh, make_bill)
    assert txn.type == TransactionType.expense and txn.bucket_id is None
    assert txn.recurring_bill_id == bill.id and txn.amount == Decimal("38.90")
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).transaction_id == txn.id


def test_pay_with_a_bucket_links_the_item_too(db, make_household, make_bill):
    hh = make_household()
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=10, auto_pay=False)
    txn = complete_entry(db, occ, user_id=hh.user_id)
    assert txn.bucket_id == hh.bucket_id and txn.recurring_bill_id == bill.id


def test_complete_entry_needs_an_expected_entry_and_an_amount(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, None, amount=None, auto_pay=False)
    with pytest.raises(ValueError):
        complete_entry(db, occ, user_id=hh.user_id)
    complete_entry(db, occ, user_id=hh.user_id, amount=Decimal("61.20"))
    assert occ.amount == Decimal("61.20")  # stored for the estimate
    with pytest.raises(EntryStateError):
        complete_entry(db, occ, user_id=hh.user_id, amount=1)


def test_the_old_pay_route_still_only_claims_bucketless_bills(client, db, authed, make_bill):
    bill, occ = make_bill(authed.household_id, None, amount=20, auto_pay=False)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay", headers=authed.headers)
    assert r.status_code == 302
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid
    assert db.query(Transaction).count() == 0


def test_undo_keeping_a_fixed_cost_is_refused(db, make_household, make_bill):
    hh = make_household()
    _, occ, _ = _fixed(db, hh, make_bill)
    with pytest.raises(EntryStateError):
        undo_occurrence(db, occ)


def test_old_pages_render_a_fixed_cost(client, db, authed, make_bill):
    _, _, txn = _fixed(db, authed, make_bill)
    for url in ("/dashboard", "/transactions/search", f"/transactions/{txn.id}/edit", "/insights"):
        assert client.get(url).status_code == 200, url


def test_update_schema_leaves_the_bucket_check_to_the_service():
    assert TransactionUpdate(amount="5").bucket_id is None


def test_old_edit_form_keeps_a_fixed_cost_bucketless(client, db, authed, make_bill):
    _, _, txn = _fixed(db, authed, make_bill)
    r = client.post(
        f"/transactions/{txn.id}/edit",
        headers=authed.headers,
        data={
            "bucket_id": "",
            "transaction_date": txn.transaction_date.isoformat(),
            "amount": "40",
            "type": "expense",
        },
    )
    assert r.status_code == 302
    db.expire_all()
    edited = db.get(Transaction, txn.id)
    assert edited.bucket_id is None and edited.amount == Decimal("40")


def test_duplicating_a_fixed_cost_keeps_the_link(client, db, authed, make_bill):
    bill, _, txn = _fixed(db, authed, make_bill)
    r = client.post(f"/transactions/{txn.id}/duplicate", headers=authed.headers)
    assert r.status_code == 302
    copy = db.query(Transaction).filter(Transaction.id != txn.id).one()
    assert copy.bucket_id is None and copy.recurring_bill_id == bill.id


def test_an_item_with_a_deleted_fixed_cost_cannot_be_deleted(client, db, authed, make_bill):
    bill, occ, _ = _fixed(db, authed, make_bill)
    undo_occurrence(db, occ, delete_transaction=True)
    r = client.post(f"/bills/{bill.id}/delete", headers=authed.headers)
    assert r.status_code == 409
    db.expire_all()
    assert db.query(Transaction).count() == 1
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_fixed_costs.py -q`
Expected: `ImportError: cannot import name 'complete_entry'`.

- [ ] **Step 3: `pay_occurrence` links the item**

In `pay_occurrence`, replace the docstring sentence "Bills without a bucket have no transaction — use settle_occurrence." with:
```python
    its splits succeed or fail together with the caller's commit. The expense
    is linked to the item (``recurring_bill_id``); with no bucket it is a
    Fixed cost (spec §3.4.2). The old app still goes through
    settle_occurrence, which only claims bucket-less bills (spec §6.2.4).
```
In its `Transaction(...)` call, after `transaction_date=occ.due_date,`, add:
```python
        recurring_bill_id=bill.id,
```

- [ ] **Step 4: `complete_entry`**

Directly above `def settle_occurrence(`, add:
```python
def complete_entry(
    db: Session,
    occ: BillOccurrence,
    *,
    user_id: str,
    amount=None,
    person: str | None = None,
    payment_method: str = PaymentMethod.card.value,
) -> Transaction:
    """Done, from the new app (spec §3.3): Pay for an out entry, which always
    creates an expense (a Fixed cost when the item has no bucket), Mark
    received for an in entry.

    ``amount`` defaults to the entry's set amount, then the item's. ``person``
    is the payer or recipient; None uses the item's default (then
    ``user_id``). A variable item's amount, or an explicit one, is stored on
    the entry so estimates and drift alerts see it. Raises EntryStateError
    when the entry is not expected and ValueError when no amount is known or
    the payment cannot be recorded. Does not commit.
    """
    if occ.status != OccurrenceStatus.unpaid:
        raise EntryStateError("This entry is already done or skipped.")
    bill = occ.bill
    explicit = amount is not None
    value = amount if explicit else (occ.amount if occ.amount is not None else bill.amount)
    if value is None:
        raise ValueError("Set the amount first: this item's amount varies.")
    if bill.direction == ItemDirection.in_.value:
        txn = receive_occurrence(
            db,
            occ,
            amount=value,
            received_by=person,
            paid_on=utcnow_naive(),
            fallback_user_id=user_id,
        )
    else:
        payer, mode = resolve_bill_payment(db, bill, paid_by=person, fallback_user_id=user_id)
        txn = pay_occurrence(
            db,
            occ,
            amount=value,
            paid_by=payer,
            payer_mode=mode,
            paid_on=utcnow_naive(),
            payment_method=payment_method,
        )
    if txn is None:
        raise EntryStateError("This entry is already done.")
    if explicit or bill.amount is None:
        occ.amount = _q(value)
    return txn
```

- [ ] **Step 5: Editing and duplicating a Fixed cost**

In `app/schemas.py`, inside `class TransactionUpdate`, after `payer_mode: str | None = None`, add:
```python
    @model_validator(mode="after")
    def _bucket_unless_income(self) -> "TransactionUpdate":
        """Checked by update_transaction instead, which knows the stored row:
        a Fixed-cost expense (linked to a recurring item) stays bucket-less."""
        return self
```
Pydantic replaces a parent's validator when a subclass defines one with the same name. `TransactionCreate` keeps its check, so `tests/test_income_no_bucket.py::test_schema_requires_bucket_unless_income` still holds.

In `app/services/transactions.py` `update_transaction`, replace
```python
    # Only income may go without a bucket.
    if not data.bucket_id and data.type != TransactionType.income:
        raise HTTPException(status_code=400, detail=BUCKET_REQUIRED)
```
with
```python
    # Only income, and an expense paid for a recurring item (a Fixed cost,
    # spec §3.4.2), may go without a bucket.
    fixed_cost = txn.recurring_bill_id is not None and data.type == TransactionType.expense
    if not data.bucket_id and data.type != TransactionType.income and not fixed_cost:
        raise HTTPException(status_code=400, detail=BUCKET_REQUIRED)
```
An ordinary expense with a blank bucket is still a 400, as `test_edit_income_to_no_bucket_and_expense_cannot` asserts.

In `app/routes/transactions.py` `duplicate_transaction`, after `exclude_from_settlement=src.exclude_from_settlement,` inside `Transaction(...)`, add:
```python
        # A Fixed cost has no bucket; the copy stays a Fixed cost of the
        # same item rather than breaking the bucket CHECK.
        recurring_bill_id=src.recurring_bill_id if src.bucket_id is None else None,
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_fixed_costs.py tests/test_income_no_bucket.py tests/test_transaction_edit_validation.py tests/test_bills.py tests/test_payer_mode.py -q`
Expected: all pass.

- [ ] **Step 7: Full suite and commit**

Run: `.venv/bin/python -m pytest -q`. Expected: all pass.
```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/bills.py app/schemas.py app/services/transactions.py app/routes/transactions.py tests/test_planning_fixed_costs.py
git commit -m "feat(planning): Fixed costs — paying a bucket-less item records a linked expense; edit and duplicate keep it valid"
```

---

### Task 8: Match suggestions

**Files:**
- Create: `app/services/matching.py`
- Modify:
  - `app/services/transactions.py`: the end of `create_transaction` (lines 326–327) and a new `_suggest_match`.
  - `app/scheduler.py`: `_planning_stages` and the `planning_daily_job` docstring (both from Task 3).
- Test: `tests/test_matching.py`

**Interfaces:**
- Consumes:
  - `MatchSuggestion`, `RecurringBill.active_filter()` (Task 2);
  - `EntryStateError`, `estimate_amount` (Task 5);
  - `claim_occurrence` (existing);
  - `delete_transaction` (Task 5 behaviour).
- Produces (in `app.services.matching`):
  - `EARLY_DAYS = 3`, `LATE_DAYS = 7`, `FIXED_TOLERANCE = Decimal("0.15")`, `VARIABLE_TOLERANCE = Decimal("0.50")`, `RECENT_DAYS = 14`
  - `normalise_text(value) -> str`
  - `names_similar(item_name, txn) -> bool`
  - `find_match(db, txn) -> BillOccurrence | None`
  - `suggest_for_transaction(db, txn) -> MatchSuggestion | None`, which does not commit
  - `suggest_recent(db, today, *, household_id=None) -> int`, which commits
  - `open_suggestions(db, household_id) -> list[MatchSuggestion]`
  - `link_suggestion(db, suggestion) -> BillOccurrence`, which raises `EntryStateError` and does not commit
  - `dismiss_suggestion(suggestion) -> None`

  And in `app.scheduler`: `_suggest_recent_matches(db, today) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_matching.py`. Review Focus #2 (stale links) is pinned in `test_stale_suggestions_refuse_to_link_and_drop_out`.
```python
"""Match suggestions (spec §3.5): window edges, tolerance, Greek names,
dismissal, every source, and never a link without a tap."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import (
    BillOccurrence,
    MatchSuggestion,
    OccurrenceStatus,
    Transaction,
    TransactionType,
)
from app.services import delete_transaction
from app.services.bills import EntryStateError
from app.services.matching import (
    dismiss_suggestion,
    find_match,
    link_suggestion,
    names_similar,
    open_suggestions,
    suggest_for_transaction,
    suggest_recent,
)
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_ingest import ingest  # noqa: F401  (fixture)

DUE = date(2026, 10, 10)


def _txn(db, hh, amount, when, *, kind=TransactionType.expense, merchant=None, bucket=True):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id if bucket else None,
        amount=Decimal(str(amount)),
        currency="EUR",
        type=kind,
        paid_by=hh.user_id,
        transaction_date=when,
        merchant=merchant,
    )
    db.add(t)
    db.commit()
    return t


def _bill(make_bill, hh, amount=38.90, name="Cosmote", due=DUE, **kw):
    return make_bill(
        hh.household_id, hh.bucket_id, amount=amount, auto_pay=False, due=due, name=name, **kw
    )


@pytest.mark.parametrize(
    "offset,matches", [(-4, False), (-3, True), (0, True), (7, True), (8, False)]
)
def test_window_is_three_days_early_to_seven_days_late(
    db, make_household, make_bill, offset, matches
):
    hh = make_household()
    _, occ = _bill(make_bill, hh)
    t = _txn(db, hh, "38.90", DUE + timedelta(days=offset))
    assert (find_match(db, t) == occ) is matches


@pytest.mark.parametrize("amount,matches", [("44.73", True), ("33.07", True), ("44.80", False)])
def test_fixed_amount_within_15_percent(db, make_household, make_bill, amount, matches):
    hh = make_household()
    _bill(make_bill, hh, name="Phone")
    t = _txn(db, hh, amount, DUE)
    assert (find_match(db, t) is not None) is matches


def test_variable_amount_within_50_percent_of_the_estimate(db, make_household, make_bill):
    hh = make_household()
    bill, _ = _bill(make_bill, hh, amount=None, name="Power")
    for months, amount in ((3, 60), (2, 70), (1, 80)):
        db.add(
            BillOccurrence(
                bill_id=bill.id,
                due_date=DUE - timedelta(days=30 * months),
                amount=Decimal(amount),
                status=OccurrenceStatus.paid,
            )
        )
    db.commit()
    assert find_match(db, _txn(db, hh, "104", DUE)) is not None
    assert find_match(db, _txn(db, hh, "106", DUE)) is None


def test_greek_names_match_without_accents_or_case():
    t = Transaction(merchant="ΔΕΉ ONLINE ΠΛΗΡΩΜΉ", notes=None)
    assert names_similar("Δεη", t)
    assert names_similar("ΔΕΗ πληρωμη", Transaction(merchant="δεη", notes=None))
    assert not names_similar("Ύδρευση", t)


def test_a_similar_name_matches_whatever_the_amount(db, make_household, make_bill):
    hh = make_household()
    _, occ = _bill(make_bill, hh, name="Cosmote")
    t = _txn(db, hh, "120", DUE, merchant="COSMOTE E-SHOP")
    assert find_match(db, t) == occ


def test_income_matches_in_entries_only(db, make_household, make_bill):
    hh = make_household()
    _bill(make_bill, hh, amount=1500, name="Rent paid")
    salary, s_occ = make_bill(
        hh.household_id, None, amount=1500, auto_pay=False, due=DUE, name="Pay"
    )
    salary.direction = "in"
    db.commit()
    t = _txn(db, hh, "1500", DUE, kind=TransactionType.income, bucket=False)
    assert find_match(db, t) == s_occ


def test_paused_items_and_done_entries_are_never_suggested(db, make_household, make_bill):
    hh = make_household()
    bill, occ = _bill(make_bill, hh)
    bill.is_active = False
    db.commit()
    assert find_match(db, _txn(db, hh, "38.90", DUE)) is None
    bill.is_active = True
    occ.status = OccurrenceStatus.paid
    db.commit()
    assert find_match(db, _txn(db, hh, "38.90", DUE)) is None


def test_dismissal_persists_through_the_daily_pass(db, make_household, make_bill):
    hh = make_household()
    _bill(make_bill, hh)
    t = _txn(db, hh, "38.90", DUE)
    s = suggest_for_transaction(db, t)
    dismiss_suggestion(s)
    db.commit()
    assert suggest_recent(db, DUE) == 0
    assert open_suggestions(db, hh.household_id) == []
    assert db.query(MatchSuggestion).count() == 1


def test_link_marks_done_and_links_the_transaction(db, make_household, make_bill):
    hh = make_household()
    bill, occ = _bill(make_bill, hh)
    t = _txn(db, hh, "38.90", DUE)
    s = suggest_for_transaction(db, t)
    link_suggestion(db, s)
    db.commit()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid
    assert db.get(BillOccurrence, occ.id).transaction_id == t.id
    assert db.get(Transaction, t.id).recurring_bill_id == bill.id
    assert open_suggestions(db, hh.household_id) == []


def test_stale_suggestions_refuse_to_link_and_drop_out(db, make_household, make_bill):
    hh = make_household()
    _, occ = _bill(make_bill, hh)
    first = suggest_for_transaction(db, _txn(db, hh, "38.90", DUE))
    second = suggest_for_transaction(db, _txn(db, hh, "38.90", DUE + timedelta(days=1)))
    db.commit()
    link_suggestion(db, first)
    db.commit()
    with pytest.raises(EntryStateError):
        link_suggestion(db, second)
    db.rollback()
    assert open_suggestions(db, hh.household_id) == []

    _, occ2 = _bill(make_bill, hh, name="Water", amount=20, due=DUE + timedelta(days=20))
    t = _txn(db, hh, "20", DUE + timedelta(days=20))
    s = suggest_for_transaction(db, t)
    db.commit()
    delete_transaction(db, t)
    with pytest.raises(EntryStateError):
        link_suggestion(db, s)


def test_api_create_suggests_but_never_links(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    today = local_today()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=38.90, auto_pay=False, due=today)
    body = {"amount": "38.90", "bucket_id": hh.bucket_id, "client_id": "offline-1"}
    assert client.post("/api/v1/transactions", headers=headers, json=body).status_code == 201
    assert client.post("/api/v1/transactions", headers=headers, json=body).status_code == 200
    assert db.query(MatchSuggestion).count() == 1
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid
    assert db.query(Transaction).one().recurring_bill_id is None


def test_apple_pay_ingest_suggests(client, db, ingest, make_bill):  # noqa: F811
    hh = ingest.hh
    make_bill(hh.household_id, hh.bucket_id, amount=12.50, auto_pay=False, due=local_today())
    r = client.post(
        "/api/v1/ingest/apple-pay",
        json={"merchant": "Sklavenitis", "amount": "12,50"},
        headers=ingest.headers,
    )
    assert r.status_code == 201, r.text
    assert db.query(MatchSuggestion).count() == 1


def test_daily_job_suggests_for_the_last_14_days(
    db, make_household, make_bill, monkeypatch, SessionLocal
):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    hh = make_household()
    today = local_today()
    make_bill(
        hh.household_id, hh.bucket_id, amount=30, auto_pay=False, due=today - timedelta(days=2)
    )
    _txn(db, hh, "30", today - timedelta(days=1))
    scheduler.planning_daily_job()
    assert db.query(MatchSuggestion).count() == 1
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_matching.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.matching'`.

- [ ] **Step 3: The matching service**

Create `app/services/matching.py`:
```python
"""Match suggestions (spec §3.5): an expense or income that looks like an
expected entry of a recurring item.

Suggestions only: nothing is linked until someone taps Link. A suggestion
needs the same direction (expense <-> out, income <-> in), a transaction
date from 3 days before to 7 days after the due date, and either an amount
within 15% of a known amount (50% of a variable item's estimate) or a
merchant/description that contains the item's name (case- and
accent-insensitive). One open suggestion per transaction: the closest entry.
"""

import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.clock import utcnow_naive
from app.core.money import quantize, to_decimal
from app.models import (
    BillOccurrence,
    ItemDirection,
    MatchSuggestion,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionType,
)
from app.services.bills import EntryStateError, claim_occurrence, estimate_amount
from app.services.money import to_base

EARLY_DAYS = 3  # paid up to 3 days before the due date
LATE_DAYS = 7  # ... or up to 7 days after it
FIXED_TOLERANCE = Decimal("0.15")
VARIABLE_TOLERANCE = Decimal("0.50")
RECENT_DAYS = 14  # the daily pass looks this far back
MIN_NAME_LENGTH = 3  # shorter names match too much


def normalise_text(value: str | None) -> str:
    """Case- and accent-insensitive form: "ΔΕΉ Online" -> "δεη online"."""
    decomposed = unicodedata.normalize("NFD", value or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(stripped.casefold().split())


def names_similar(item_name: str, txn: Transaction) -> bool:
    """The item's name appears in the merchant or notes, or the merchant in the name."""
    name = normalise_text(item_name)
    if len(name) < MIN_NAME_LENGTH:
        return False
    merchant = normalise_text(txn.merchant)
    text = normalise_text(f"{txn.merchant or ''} {txn.notes or ''}")
    return name in text or (len(merchant) >= MIN_NAME_LENGTH and merchant in name)


def _expected(db: Session, occ: BillOccurrence, estimates: dict) -> tuple[Decimal | None, Decimal]:
    """(amount the entry expects, tolerance) — the set amount, the item's, or the estimate."""
    if occ.amount is not None:
        return to_decimal(occ.amount), FIXED_TOLERANCE
    if occ.bill.amount is not None:
        return to_decimal(occ.bill.amount), FIXED_TOLERANCE
    if occ.bill_id not in estimates:
        estimates[occ.bill_id] = estimate_amount(db, occ.bill_id)
    return estimates[occ.bill_id], VARIABLE_TOLERANCE


def _is_linked(db: Session, txn: Transaction) -> bool:
    return (
        txn.recurring_bill_id is not None
        or db.query(BillOccurrence.id).filter(BillOccurrence.transaction_id == txn.id).first()
        is not None
    )


def find_match(db: Session, txn: Transaction) -> BillOccurrence | None:
    """The expected entry ``txn`` most likely pays or receives, or None.

    None too when ``txn`` is deleted, already linked, or already has an open
    suggestion. Pairs suggested before (dismissed or not) are not offered
    again. The closest due date wins, then the closest amount.
    """
    if txn.deleted_at is not None or txn.type not in (
        TransactionType.expense,
        TransactionType.income,
    ):
        return None
    if _is_linked(db, txn):
        return None
    tried = {
        occ_id: dismissed
        for occ_id, dismissed in db.query(
            MatchSuggestion.occurrence_id, MatchSuggestion.dismissed
        ).filter(MatchSuggestion.transaction_id == txn.id)
    }
    if not all(tried.values()):
        return None  # an open suggestion is already waiting for a tap
    direction = (
        ItemDirection.in_.value if txn.type == TransactionType.income else ItemDirection.out.value
    )
    candidates = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == txn.household_id,
            RecurringBill.active_filter(),
            RecurringBill.direction == direction,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.transaction_id.is_(None),
            BillOccurrence.due_date >= txn.transaction_date - timedelta(days=LATE_DAYS),
            BillOccurrence.due_date <= txn.transaction_date + timedelta(days=EARLY_DAYS),
        )
        .all()
    )
    actual = to_base(txn.amount, txn.exchange_rate)
    estimates: dict = {}
    scored = []
    for occ in candidates:
        if occ.id in tried:
            continue
        expected, tolerance = _expected(db, occ, estimates)
        amount_ok = (
            expected is not None and expected > 0 and abs(actual - expected) <= expected * tolerance
        )
        if not (amount_ok or names_similar(occ.bill.name, txn)):
            continue
        gap = abs((txn.transaction_date - occ.due_date).days)
        miss = abs(actual - expected) if expected is not None else actual
        scored.append((gap, miss, occ.due_date, occ.id, occ))
    return min(scored)[-1] if scored else None


def suggest_for_transaction(db: Session, txn: Transaction) -> MatchSuggestion | None:
    """Record a suggestion for ``txn`` when an expected entry fits. Does not commit."""
    occ = find_match(db, txn)
    if occ is None:
        return None
    suggestion = MatchSuggestion(
        household_id=txn.household_id, transaction_id=txn.id, occurrence_id=occ.id
    )
    try:
        with db.begin_nested():
            db.add(suggestion)
            db.flush()
    except IntegrityError:
        return None
    return suggestion


def suggest_recent(db: Session, today: date, *, household_id: str | None = None) -> int:
    """The daily pass over the last 14 days of unlinked transactions. Commits."""
    q = db.query(Transaction).filter(
        Transaction.active(),
        Transaction.type.in_([TransactionType.expense, TransactionType.income]),
        Transaction.recurring_bill_id.is_(None),
        Transaction.transaction_date >= today - timedelta(days=RECENT_DAYS),
    )
    if household_id:
        q = q.filter(Transaction.household_id == household_id)
    made = sum(suggest_for_transaction(db, txn) is not None for txn in q.all())
    db.commit()
    return made


def open_suggestions(db: Session, household_id: str) -> list[MatchSuggestion]:
    """Suggestions still waiting for a tap: not dismissed, the transaction
    still there and unlinked, the entry still expected on an active item."""
    return (
        db.query(MatchSuggestion)
        .join(Transaction, Transaction.id == MatchSuggestion.transaction_id)
        .join(BillOccurrence, BillOccurrence.id == MatchSuggestion.occurrence_id)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(
            joinedload(MatchSuggestion.transaction),
            joinedload(MatchSuggestion.occurrence).joinedload(BillOccurrence.bill),
        )
        .filter(
            MatchSuggestion.household_id == household_id,
            MatchSuggestion.dismissed.is_(False),
            Transaction.active(),
            Transaction.recurring_bill_id.is_(None),
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.transaction_id.is_(None),
            RecurringBill.active_filter(),
        )
        .order_by(BillOccurrence.due_date, MatchSuggestion.created_at)
        .all()
    )


def link_suggestion(db: Session, suggestion: MatchSuggestion) -> BillOccurrence:
    """Link (spec §3.5): the entry becomes done with this transaction, which
    gets ``recurring_bill_id``. A variable item's entry takes the amount.

    Raises EntryStateError when either side has moved on (dismissed, deleted,
    linked elsewhere, done or skipped). Does not commit.
    """
    txn, occ = suggestion.transaction, suggestion.occurrence
    if suggestion.dismissed:
        raise EntryStateError("This suggestion was dismissed.")
    if txn.deleted_at is not None:
        raise EntryStateError("That transaction was deleted.")
    if _is_linked(db, txn):
        raise EntryStateError("That transaction is already linked to a recurring item.")
    if not claim_occurrence(db, occ, paid_by=txn.paid_by, paid_on=utcnow_naive()):
        raise EntryStateError("That entry is already done or skipped.")
    db.query(BillOccurrence).filter(BillOccurrence.id == occ.id).update(
        {BillOccurrence.transaction_id: txn.id}, synchronize_session=False
    )
    occ.transaction_id = txn.id
    txn.recurring_bill_id = occ.bill_id
    if occ.amount is None and occ.bill.amount is None:
        occ.amount = quantize(to_base(txn.amount, txn.exchange_rate))
    return occ


def dismiss_suggestion(suggestion: MatchSuggestion) -> None:
    """Not this: the pair is never suggested again. Does not commit."""
    suggestion.dismissed = True
```

- [ ] **Step 4: Every new transaction is checked**

In `app/services/transactions.py`, at the end of `create_transaction`, replace
```python
    db.refresh(txn)
    return txn
```
with
```python
    db.refresh(txn)
    _suggest_match(db, txn)
    return txn


def _suggest_match(db: Session, txn: Transaction) -> None:
    """Look for an expected entry this new transaction may pay (spec §3.5).

    Every source creates through create_transaction (forms, API, Apple Pay
    ingest, offline replay, cash), so this is the one hook. A failure here
    never fails the save.
    """
    from app.services.matching import suggest_for_transaction

    try:
        if suggest_for_transaction(db, txn) is not None:
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Match suggestion for transaction %s failed", txn.id)
```
Every source of a new expense or income goes through `create_transaction`: the HTML forms, `POST /api/v1/transactions` (including offline replay), Apple Pay ingest (`ingest_apple_pay`), income and cash `withdraw_and_spend`. `duplicate_transaction` bypasses it; the daily pass picks those up within a day.

- [ ] **Step 5: The daily pass**

In `app/scheduler.py`, replace `_planning_stages` with:
```python
def _suggest_recent_matches(db, today: date) -> int:
    """Match suggestions for the last 14 days of transactions (spec §3.5)."""
    from app.services.matching import suggest_recent

    return suggest_recent(db, today)


def _planning_stages():
    return (_top_up_entries, _suggest_recent_matches)
```
Then change `planning_daily_job`'s docstring to:
```python
    """Daily planning job: top up expected entries, then suggest matches.

    Each stage is isolated so a failure in one does not discard the other.
    """
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_matching.py tests/test_ingest.py tests/test_transactions.py tests/test_offline_queue.py -q`
Expected: all pass.

- [ ] **Step 7: Full suite and commit**

Run: `.venv/bin/python -m pytest -q`. Expected: all pass.
```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/matching.py app/services/transactions.py app/scheduler.py tests/test_matching.py
git commit -m "feat(planning): match suggestions on every new transaction and daily; link and dismiss, never automatic"
```

---

### Task 9: Monthly and event buckets

**Files:**
- Create: `app/services/budgets.py`. This task writes the kind functions; Task 11 appends `bucket_pace`.
- Modify:
  - `app/scheduler.py`: `_notify_budget_thresholds` (lines 409–475).
  - `app/api/buckets.py`: imports, `BucketIn`, new `_apply_dates` and `_type_for`, `_bucket_dict`, `create_bucket`, `update_bucket`.
- Test: `tests/test_bucket_kinds.py`

**Interfaces:**
- Consumes: `Bucket.kind`, `BucketKind`, `kind_for_type` (Task 2); `app.services.insights._month_range` (existing).
- Produces:
  - In `app.services.budgets`:
    - `bucket_period(bucket, today) -> tuple[date | None, date | None]`
    - `bucket_spent(db, bucket, today) -> Decimal`
    - `@dataclass(frozen=True) BudgetRow(bucket_id, name, kind, budget, spent, pct, period_start, period_end, days_left, archive_suggested)`
    - `budget_rows(db, household_id, today) -> list[BudgetRow]`
  - `/api/v1/buckets` responses gain `kind`, `start_date` and `end_date`. The request body accepts `kind` (`"monthly"`/`"event"`; it sets `type` to match: event ↔ trip) and `start_date`/`end_date`. On update, dates that are left out are kept.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bucket_kinds.py`:
```python
"""Monthly and event buckets (spec §4.1)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import Bucket, BucketType, Notification, NotificationType, Transaction
from app.services.budgets import bucket_spent, budget_rows
from tests.test_api import api  # noqa: F401  (fixture)

TODAY = date(2026, 10, 6)


def _spend(db, hh, bucket_id, amount, when):
    db.add(
        Transaction(
            household_id=hh.household_id,
            bucket_id=bucket_id,
            amount=Decimal(str(amount)),
            currency="EUR",
            paid_by=hh.user_id,
            transaction_date=when,
        )
    )
    db.commit()


def test_kind_follows_the_old_type(db, make_household):
    hh = make_household()
    b = db.get(Bucket, hh.bucket_id)
    assert b.kind == "monthly"
    b.type = BucketType.trip
    assert b.kind == "event"
    b.type = BucketType.savings
    assert b.kind == "monthly"


def test_monthly_spend_is_this_calendar_month(db, make_household):
    hh = make_household()
    b = db.get(Bucket, hh.bucket_id)
    _spend(db, hh, b.id, 100, date(2026, 9, 30))
    _spend(db, hh, b.id, 40, date(2026, 10, 1))
    assert bucket_spent(db, b, TODAY) == Decimal("40.00")


def test_event_spend_is_the_total_over_its_dates(db, make_household):
    hh = make_household()
    trip = Bucket(
        household_id=hh.household_id,
        name="Crete",
        type=BucketType.trip,
        budget=Decimal("1000"),
        start_date=date(2026, 9, 28),
        end_date=date(2026, 10, 4),
    )
    db.add(trip)
    db.commit()
    _spend(db, hh, trip.id, 600, date(2026, 9, 29))
    _spend(db, hh, trip.id, 300, date(2026, 10, 2))
    _spend(db, hh, trip.id, 50, date(2026, 10, 5))  # after the trip
    assert bucket_spent(db, trip, TODAY) == Decimal("900.00")
    row = next(r for r in budget_rows(db, hh.household_id, TODAY) if r.bucket_id == trip.id)
    assert row.kind == "event" and row.pct == Decimal("90.0")
    assert row.days_left == 0 and row.archive_suggested


def test_open_ended_event_counts_from_its_start(db, make_household):
    hh = make_household()
    ev = Bucket(household_id=hh.household_id, name="Renovation", type=BucketType.trip)
    ev.start_date = date(2026, 8, 1)
    db.add(ev)
    db.commit()
    _spend(db, hh, ev.id, 70, date(2026, 7, 31))
    _spend(db, hh, ev.id, 30, date(2026, 8, 1))
    _spend(db, hh, ev.id, 20, date(2026, 10, 6))
    row = next(r for r in budget_rows(db, hh.household_id, TODAY) if r.bucket_id == ev.id)
    assert row.spent == Decimal("50.00") and row.days_left is None
    assert not row.archive_suggested


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def test_event_budget_warning_counts_the_whole_event(db, make_household, run_job):
    hh = make_household()
    today = local_today()
    trip = Bucket(
        household_id=hh.household_id,
        name="Trip",
        type=BucketType.trip,
        budget=Decimal("1000"),
        start_date=today - timedelta(days=40),
        end_date=today + timedelta(days=5),
    )
    db.add(trip)
    db.commit()
    _spend(db, hh, trip.id, 600, today - timedelta(days=35))  # an earlier month
    _spend(db, hh, trip.id, 250, today)
    run_job()
    run_job()
    notes = (
        db.query(Notification).filter(Notification.type == NotificationType.budget_warning).all()
    )
    assert len(notes) == 1
    assert "85%" in notes[0].title and "this month" not in notes[0].body
    assert notes[0].dedupe_key == f"budget:{trip.id}:event:80"


def test_api_bucket_kind_sets_the_type_and_dates(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post(
        "/api/v1/buckets",
        headers=headers,
        json={
            "name": "Crete",
            "kind": "event",
            "start_date": "2027-07-01",
            "end_date": "2027-07-10",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["kind"], body["type"], body["end_date"]) == ("event", "trip", "2027-07-10")
    r = client.put(
        f"/api/v1/buckets/{body['id']}", headers=headers, json={"name": "Crete", "kind": "monthly"}
    )
    assert (r.json()["kind"], r.json()["type"], r.json()["start_date"]) == (
        "monthly",
        "custom",
        "2027-07-01",
    )
    bad = client.post("/api/v1/buckets", headers=headers, json={"name": "X", "kind": "weekly"})
    assert bad.status_code == 400
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_bucket_kinds.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.budgets'`.

- [ ] **Step 3: The kind functions**

Create `app/services/budgets.py`:
```python
"""Bucket budgets by kind (spec §4.1).

A monthly bucket's budget is per calendar month (household timezone) and
resets on the 1st. An event bucket's budget is a total over its start_date to
end_date; either end may be open. Every new screen and the budget warnings use
these, so one bucket means one thing everywhere.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.money import percent, quantize
from app.models import Bucket, BucketKind, BucketStatus, Transaction, TransactionType
from app.services.insights import _month_range
from app.services.money import base_amount_expr


def bucket_period(bucket: Bucket, today: date) -> tuple[date | None, date | None]:
    """The dates a bucket's budget covers: this calendar month, or the event's dates."""
    if bucket.kind == BucketKind.event.value:
        return bucket.start_date, bucket.end_date
    return _month_range(today.year, today.month)


def bucket_spent(db: Session, bucket: Bucket, today: date) -> Decimal:
    """Expenses in the bucket over its budget period, in base currency."""
    start, end = bucket_period(bucket, today)
    q = db.query(func.coalesce(func.sum(base_amount_expr()), 0)).filter(
        Transaction.active(),
        Transaction.bucket_id == bucket.id,
        Transaction.type == TransactionType.expense,
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    return quantize(q.scalar())


@dataclass(frozen=True)
class BudgetRow:
    bucket_id: str
    name: str
    kind: str
    budget: Decimal | None
    spent: Decimal
    pct: Decimal | None  # spent / budget x 100, one decimal; None without a budget
    period_start: date | None
    period_end: date | None
    days_left: int | None  # event buckets with an end date, today included
    archive_suggested: bool  # an event whose end date has passed


def budget_rows(db: Session, household_id: str, today: date) -> list[BudgetRow]:
    """Every active bucket's spend against its budget, by kind."""
    buckets = (
        db.query(Bucket)
        .filter(Bucket.household_id == household_id, Bucket.status == BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )
    rows = []
    for b in buckets:
        start, end = bucket_period(b, today)
        spent = bucket_spent(db, b, today)
        budget = quantize(b.budget) if b.budget is not None else None
        event = b.kind == BucketKind.event.value
        rows.append(
            BudgetRow(
                bucket_id=b.id,
                name=b.name,
                kind=b.kind,
                budget=budget,
                spent=spent,
                pct=percent(spent, budget) if budget else None,
                period_start=start,
                period_end=end,
                days_left=max((end - today).days + 1, 0) if event and end else None,
                archive_suggested=bool(event and end and end < today),
            )
        )
    return rows
```

- [ ] **Step 4: Budget warnings use the kind**

In `app/scheduler.py` `_notify_budget_thresholds`:
- change the models import to `from app.models import Bucket, BucketKind, BucketStatus, NotificationType`;
- add `from app.services.budgets import bucket_spent`;
- replace `spent = spend_by_hh.get(bucket.household_id, {}).get(bucket.id, ZERO)` with:
```python
        # An event's budget is a total over its dates (spec §4.1).
        event = bucket.kind == BucketKind.event.value
        if event:
            spent = bucket_spent(db, bucket, today)
        else:
            spent = spend_by_hh.get(bucket.household_id, {}).get(bucket.id, ZERO)
```
- in the 80% body, replace `f"{_money(budget - spent, currency)} left this month."` with:
```python
                f"{_money(budget - spent, currency)} left"
                f"{'.' if event else ' this month.'}"
```
- replace `dedupe_key=f"budget:{bucket.id}:{period}:{crossed}",` with:
```python
            dedupe_key=(
                f"budget:{bucket.id}:event:{crossed}"
                if event
                else f"budget:{bucket.id}:{period}:{crossed}"
            ),
```
Monthly buckets behave exactly as before, so `tests/test_alerts.py` is unchanged.

- [ ] **Step 5: `kind` on `/api/v1/buckets`**

In `app/api/buckets.py`:
- add `from datetime import date`, and `BucketKind,` to the models import;
- add these fields at the end of `class BucketIn`:
```python
    # "monthly" or "event" (spec §4.1). Given, it sets the old type to match
    # (event <-> trip), so both apps keep reading the bucket the same way.
    kind: str | None = None
    # An event's dates. Left out of an update, the stored dates stay.
    start_date: date | None = None
    end_date: date | None = None
```
- after the class, add:
```python
def _apply_dates(bucket: Bucket, body: BucketIn) -> None:
    if "start_date" in body.model_fields_set:
        bucket.start_date = body.start_date
    if "end_date" in body.model_fields_set:
        bucket.end_date = body.end_date
    if bucket.start_date and bucket.end_date and bucket.end_date < bucket.start_date:
        raise HTTPException(status_code=400, detail="The end date is before the start date.")


def _type_for(body: BucketIn) -> BucketType:
    try:
        bucket_type = BucketType(body.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown bucket type '{body.type}'") from None
    if body.kind is None:
        return bucket_type
    try:
        kind = BucketKind(body.kind)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown bucket kind '{body.kind}'") from None
    if kind == BucketKind.event:
        return BucketType.trip
    return BucketType.custom if bucket_type == BucketType.trip else bucket_type
```
- in `_bucket_dict`, after `"type": b.type.value,`, add:
```python
        "kind": b.kind,
        "start_date": b.start_date.isoformat() if b.start_date else None,
        "end_date": b.end_date.isoformat() if b.end_date else None,
```
- in `create_bucket`, use `type=_type_for(body),` and call `_apply_dates(bucket, body)` before `db.add(bucket)`;
- in `update_bucket`, use `bucket.type = _type_for(body)` and call `_apply_dates(bucket, body)` before `db.commit()`.

`Bucket`'s `type` validator (Task 2) then sets `kind`.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_bucket_kinds.py tests/test_alerts.py tests/test_bucket_types.py tests/test_api.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/budgets.py app/scheduler.py app/api/buckets.py tests/test_bucket_kinds.py
git commit -m "feat(planning): monthly and event bucket semantics; event budget warnings over the event; kind on /api/v1/buckets"
```

---

### Task 10: Entries, the month picture and Upcoming

**Files:**
- Create: `app/services/planning.py`. This task writes everything except `year_outlook`, which Task 11 appends.
- Test: `tests/test_planning_views.py`

**Interfaces:**
- Consumes:
  - `estimate_amount` (Task 5);
  - `complete_entry` (Task 7);
  - `claim_occurrence` (existing);
  - `cash_spending`, `cash_scope` (existing, `app.services.cash`);
  - `_month_range` (existing, `app.services.insights`);
  - `RecurringBill.active_filter()`, `BucketKind` (Task 2).
- Produces (in `app.services.planning`):
  - `STATUS_NAMES`
  - `@dataclass(frozen=True) Entry(id, item_id, name, direction, due_date, status, amount, estimated, currency, bucket_id, category_id, transaction_id, overdue, infrequent)`
  - `list_entries(db, household_id, start, end, *, today=None) -> list[Entry]`
  - `entry_for(db, occ, *, today=None) -> Entry`
  - `month_picture(db, household_id, year, month, *, today=None) -> dict` with keys:
    - `month`;
    - `income`, `fixed`, each `{so_far, still_to_come, projected}`;
    - `buckets` (the same three plus `rows: [{bucket_id, name, budget, so_far, still_to_come, projected}]`);
    - `net_projected`, `events_spent`, `cash`, `estimated`.
  - `upcoming(db, household_id, *, today=None, days=30) -> list[{"date", "entries": list[Entry], "net_this_month"}]`
  - Private helpers `_total`, `_transactions_sum`, `_row` (Task 11 uses `_total`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_views.py`. The fixture covers every row of §5.1:
- a USD income with a rate (base currency);
- a Fixed cost paid in the new app, and one claimed in the old app;
- a variable item with an estimate;
- a paused item;
- a bucket over budget;
- an event bucket.

```python
"""Month picture and Upcoming (spec §5.1, §5.2)."""

from datetime import date
from decimal import Decimal

import pytest

from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    Bucket,
    BucketType,
    OccurrenceStatus,
    Transaction,
    TransactionType,
)
from app.services.bills import claim_occurrence, complete_entry
from app.services.planning import list_entries, month_picture, upcoming

TODAY = date(2026, 10, 6)
D = Decimal


def _txn(db, hh, amount, when, *, bucket_id=None, kind=TransactionType.expense, rate="1"):
    db.add(
        Transaction(
            household_id=hh.household_id,
            bucket_id=bucket_id,
            amount=D(str(amount)),
            currency="EUR" if rate == "1" else "USD",
            exchange_rate=D(rate),
            type=kind,
            paid_by=hh.user_id,
            transaction_date=when,
        )
    )
    db.commit()


@pytest.fixture()
def month(db, make_household, make_bill):
    """October 2026, seen on the 6th."""
    hh = make_household()
    daily = db.get(Bucket, hh.bucket_id)
    daily.budget = D("1200")
    over = Bucket(household_id=hh.household_id, name="Treats", budget=D("100"))
    trip = Bucket(household_id=hh.household_id, name="Crete", type=BucketType.trip)
    db.add_all([over, trip])
    db.commit()
    _txn(db, hh, 300, date(2026, 10, 2), bucket_id=daily.id)
    _txn(db, hh, 150, date(2026, 10, 2), bucket_id=over.id)
    _txn(db, hh, 200, date(2026, 10, 2), bucket_id=trip.id)
    _txn(db, hh, 500, date(2026, 10, 1), kind=TransactionType.income)  # rent in, logged by hand
    _txn(db, hh, 100, date(2026, 10, 1), kind=TransactionType.income, rate="0.9")  # USD

    salary, _ = make_bill(
        hh.household_id, None, amount=1500, auto_pay=False, due=date(2026, 10, 26), name="Salary"
    )
    salary.direction = "in"
    _, cosmote = make_bill(
        hh.household_id, None, amount=38.90, auto_pay=False, due=date(2026, 10, 5), name="Cosmote"
    )
    complete_entry(db, cosmote, user_id=hh.user_id)  # a Fixed-cost expense
    _, gym = make_bill(
        hh.household_id, None, amount=25, auto_pay=False, due=date(2026, 10, 3), name="Gym"
    )
    claim_occurrence(db, gym, paid_by=hh.user_id, paid_on=utcnow_naive())  # old app, claim only
    internet, _ = make_bill(
        hh.household_id, None, amount=30, auto_pay=False, due=date(2026, 10, 15), name="Internet"
    )
    db.add(
        BillOccurrence(
            bill_id=internet.id, due_date=date(2026, 11, 2), status=OccurrenceStatus.unpaid
        )
    )
    deh, _ = make_bill(
        hh.household_id, None, amount=None, auto_pay=False, due=date(2026, 10, 20), name="DEH"
    )
    for m, amount in ((7, 60), (8, 70), (9, 80)):
        db.add(
            BillOccurrence(
                bill_id=deh.id,
                due_date=date(2026, m, 20),
                amount=D(amount),
                status=OccurrenceStatus.paid,
            )
        )
    paused, _ = make_bill(
        hh.household_id, None, amount=999, auto_pay=False, due=date(2026, 10, 21), name="Old gym"
    )
    paused.is_active = False
    db.commit()
    return hh


def test_entries_show_statuses_estimates_and_hide_paused_items(db, month):
    entries = list_entries(
        db, month.household_id, date(2026, 10, 1), date(2026, 10, 31), today=TODAY
    )
    by_name = {e.name: e for e in entries}
    assert "Old gym" not in by_name
    assert by_name["Cosmote"].status == "done" and by_name["Cosmote"].amount == D("38.90")
    assert by_name["DEH"].amount == D("70.00") and by_name["DEH"].estimated
    assert by_name["Salary"].direction == "in" and not by_name["Salary"].overdue


def test_month_picture(db, month):
    pic = month_picture(db, month.household_id, 2026, 10, today=TODAY)
    assert pic["income"] == {
        "so_far": D("590.00"),
        "still_to_come": D("1500.00"),
        "projected": D("2090.00"),
    }
    assert pic["fixed"] == {
        "so_far": D("63.90"),
        "still_to_come": D("100.00"),
        "projected": D("163.90"),
    }
    rows = {r["name"]: r for r in pic["buckets"]["rows"]}
    assert rows["Test Household Bucket"]["still_to_come"] == D("900.00")
    assert rows["Treats"]["projected"] == D("150.00")  # max(budget, spent)
    assert rows["Treats"]["still_to_come"] == D("0.00")
    assert "Crete" not in rows
    assert pic["buckets"]["projected"] == D("1350.00")
    assert pic["events_spent"] == D("200.00")
    assert pic["net_projected"] == D("576.10")  # 2090 - 163.90 - 1350; events not in it
    assert pic["estimated"] is True


def test_a_bucket_without_budget_projects_its_bills(db, make_household, make_bill):
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45, auto_pay=False, due=date(2026, 10, 20))
    _txn(db, hh, 10, date(2026, 10, 2), bucket_id=hh.bucket_id)
    pic = month_picture(db, hh.household_id, 2026, 10, today=TODAY)
    assert pic["buckets"]["rows"][0]["projected"] == D("55.00")
    assert pic["fixed"]["still_to_come"] == D("0.00")


def test_upcoming_runs_a_net_that_restarts_each_month(db, month):
    days = upcoming(db, month.household_id, today=TODAY)
    assert [d["date"] for d in days] == [
        date(2026, 10, 15),
        date(2026, 10, 20),
        date(2026, 10, 26),
        date(2026, 11, 2),
    ]
    # Oct so far: 590 in - 688.90 out (300 + 150 + 200 + 38.90).
    assert [d["net_this_month"] for d in days] == [
        D("-128.90"),
        D("-198.90"),
        D("1301.10"),
        D("-30.00"),
    ]
    assert all(e.status == "expected" for d in days for e in d["entries"])
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_views.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.services.planning'`.

- [ ] **Step 3: Implement**

Create `app/services/planning.py`:
```python
"""Planning figures (spec §5): expected entries, the month picture, Upcoming.

All household-wide. Transactions count in base currency (exchange_rate
applied). Recurring items have no exchange rate, so entries count at face
value, as the old "Bills due" figure does. Anything not yet real is named as
a projection (``still_to_come``, ``projected``, ``net_projected``) and
``estimated`` marks a "≈" amount. Nothing here is a balance.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.clock import local_today
from app.core.money import ZERO, quantize
from app.models import (
    BillOccurrence,
    Bucket,
    BucketKind,
    BucketStatus,
    ItemDirection,
    OccurrenceStatus,
    RecurringBill,
    RuleKind,
    Transaction,
    TransactionType,
)
from app.services.bills import estimate_amount
from app.services.cash import cash_scope, cash_spending
from app.services.insights import _month_range
from app.services.money import base_amount_expr, to_base

# Stored status -> what people see (spec §3.3). Stored values never change.
STATUS_NAMES = {
    OccurrenceStatus.unpaid: "expected",
    OccurrenceStatus.paid: "done",
    OccurrenceStatus.skipped: "skipped",
}
YEARLY_KINDS = (RuleKind.yearly.value, RuleKind.easter_offset.value)


@dataclass(frozen=True)
class Entry:
    id: str
    item_id: str
    name: str
    direction: str  # "out" | "in"
    due_date: date
    status: str  # "expected" | "done" | "skipped"
    amount: Decimal | None  # done: what was paid; else set, item's, or estimate
    estimated: bool  # amount is the "≈" estimate
    currency: str
    bucket_id: str | None
    category_id: str | None
    transaction_id: str | None
    overdue: bool  # expected and due before today
    infrequent: bool  # the item recurs less than monthly (§5.3)


def _infrequent(bill: RecurringBill) -> bool:
    if bill.rule_kind in YEARLY_KINDS:
        return True
    return bill.rule_kind != RuleKind.weekly.value and (bill.interval_months or 1) > 1


def _entry(db: Session, occ: BillOccurrence, today: date, estimates: dict) -> Entry:
    bill, txn = occ.bill, occ.transaction
    estimated = False
    if occ.status == OccurrenceStatus.paid and txn is not None and txn.deleted_at is None:
        amount = quantize(to_base(txn.amount, txn.exchange_rate))
    elif occ.amount is not None:
        amount = quantize(occ.amount)
    elif bill.amount is not None:
        amount = quantize(bill.amount)
    else:
        if bill.id not in estimates:
            estimates[bill.id] = estimate_amount(db, bill.id)
        amount = estimates[bill.id]
        estimated = amount is not None
    status = STATUS_NAMES[occ.status]
    return Entry(
        id=occ.id,
        item_id=bill.id,
        name=bill.name,
        direction=bill.direction,
        due_date=occ.due_date,
        status=status,
        amount=amount,
        estimated=estimated,
        currency=bill.currency or "EUR",
        bucket_id=bill.bucket_id,
        category_id=bill.category_id,
        transaction_id=occ.transaction_id,
        overdue=status == "expected" and occ.due_date < today,
        infrequent=_infrequent(bill),
    )


def list_entries(
    db: Session, household_id: str, start: date, end: date, *, today: date | None = None
) -> list[Entry]:
    """Entries of active items due in [start, end], by date then name.

    A paused item's entries are hidden (spec §3.4.1); they stay stored.
    """
    today = today or local_today()
    occs = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill), joinedload(BillOccurrence.transaction))
        .filter(
            RecurringBill.household_id == household_id,
            RecurringBill.active_filter(),
            BillOccurrence.due_date >= start,
            BillOccurrence.due_date <= end,
        )
        .order_by(BillOccurrence.due_date, RecurringBill.name, BillOccurrence.id)
        .all()
    )
    estimates: dict = {}
    return [_entry(db, o, today, estimates) for o in occs]


def entry_for(db: Session, occ: BillOccurrence, *, today: date | None = None) -> Entry:
    """One entry, as list_entries shows it."""
    return _entry(db, occ, today or local_today(), {})


def _total(entries) -> Decimal:
    return quantize(sum((e.amount or ZERO for e in entries), ZERO))


def _transactions_sum(db: Session, *filters) -> Decimal:
    return quantize(
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .filter(Transaction.active(), *filters)
        .scalar()
    )


def _row(so_far: Decimal, still_to_come: Decimal) -> dict:
    return {
        "so_far": quantize(so_far),
        "still_to_come": quantize(still_to_come),
        "projected": quantize(so_far + still_to_come),
    }


def month_picture(
    db: Session, household_id: str, year: int, month: int, *, today: date | None = None
) -> dict:
    """Home's month picture (spec §5.1).

    - income: income this month; ``in`` entries still expected this month.
    - fixed: expenses linked to items with no bucket (plus the old app's
      claim-only payments of such items); ``out`` entries with no bucket
      still expected.
    - buckets: per monthly bucket, spent so far; still to come is budget
      minus spent, floored at 0; projected is max(budget, spent). A bucket
      without a budget projects its spend plus its items' expected entries.
    - net_projected: income projected minus fixed and buckets projected.
    - events_spent and cash: shown apart, not in the net.
    """
    today = today or local_today()
    start, end = _month_range(year, month)
    in_month = (
        Transaction.household_id == household_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    )
    entries = list_entries(db, household_id, start, end, today=today)
    expected = [e for e in entries if e.status == "expected"]
    out, inc = ItemDirection.out.value, ItemDirection.in_.value

    income = _row(
        _transactions_sum(db, *in_month, Transaction.type == TransactionType.income),
        _total(e for e in expected if e.direction == inc),
    )
    fixed_paid = _transactions_sum(
        db,
        *in_month,
        Transaction.type == TransactionType.expense,
        Transaction.bucket_id.is_(None),
        Transaction.recurring_bill_id.isnot(None),
    )
    claimed = _total(
        e
        for e in entries
        if e.direction == out
        and e.status == "done"
        and e.transaction_id is None
        and e.bucket_id is None
    )
    fixed = _row(
        fixed_paid + claimed,
        _total(e for e in expected if e.direction == out and e.bucket_id is None),
    )

    spent_by_bucket = dict(
        db.query(Transaction.bucket_id, func.sum(base_amount_expr()))
        .filter(
            Transaction.active(),
            *in_month,
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.isnot(None),
        )
        .group_by(Transaction.bucket_id)
        .all()
    )
    expected_by_bucket: dict = defaultdict(Decimal)
    for e in expected:
        if e.direction == out and e.bucket_id:
            expected_by_bucket[e.bucket_id] += e.amount or ZERO
    rows, events_spent = [], ZERO
    totals = {"so_far": ZERO, "still_to_come": ZERO, "projected": ZERO}
    for b in (
        db.query(Bucket).filter(Bucket.household_id == household_id).order_by(Bucket.created_at)
    ):
        spent = quantize(spent_by_bucket.get(b.id) or 0)
        if b.kind == BucketKind.event.value:
            events_spent += spent
            continue
        if b.status == BucketStatus.active and b.budget is not None:
            budget = quantize(b.budget)
            to_come = max(budget - spent, ZERO)
            projected = max(budget, spent)
        else:
            budget = None
            to_come = quantize(expected_by_bucket[b.id])
            projected = spent + to_come
        if not (spent or budget or to_come):
            continue
        rows.append(
            {
                "bucket_id": b.id,
                "name": b.name,
                "budget": budget,
                "so_far": spent,
                "still_to_come": to_come,
                "projected": projected,
            }
        )
        totals["so_far"] += spent
        totals["still_to_come"] += to_come
        totals["projected"] += projected
    buckets = {k: quantize(v) for k, v in totals.items()} | {"rows": rows}

    cash = cash_spending(db, household_id, start, end, cash_scope(db, household_id, None))
    return {
        "month": f"{year:04d}-{month:02d}",
        "income": income,
        "fixed": fixed,
        "buckets": buckets,
        "net_projected": quantize(income["projected"] - fixed["projected"] - buckets["projected"]),
        "events_spent": quantize(events_spent),
        "cash": cash.total,
        "estimated": any(e.estimated for e in expected),
    }


def upcoming(
    db: Session, household_id: str, *, today: date | None = None, days: int = 30
) -> list[dict]:
    """Plan › Upcoming (spec §5.2): the next ``days`` days of expected entries,
    day by day, with a running "net this month".

    The running net starts from this month's income minus expenses so far and
    adds each expected entry up to that day (in plus, out minus). It restarts
    at zero when the list crosses into the next month. It is a projection.
    """
    today = today or local_today()
    entries = [
        e
        for e in list_entries(db, household_id, today, today + timedelta(days=days), today=today)
        if e.status == "expected"
    ]
    start, _ = _month_range(today.year, today.month)
    so_far = (
        Transaction.household_id == household_id,
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= today,
    )
    running = {
        (today.year, today.month): _transactions_sum(
            db, *so_far, Transaction.type == TransactionType.income
        )
        - _transactions_sum(db, *so_far, Transaction.type == TransactionType.expense)
    }
    out_days: list[dict] = []
    for e in entries:
        key = (e.due_date.year, e.due_date.month)
        sign = 1 if e.direction == ItemDirection.in_.value else -1
        running[key] = running.get(key, ZERO) + sign * (e.amount or ZERO)
        if not out_days or out_days[-1]["date"] != e.due_date:
            out_days.append({"date": e.due_date, "entries": [], "net_this_month": ZERO})
        out_days[-1]["entries"].append(e)
        out_days[-1]["net_this_month"] = quantize(running[key])
    return out_days
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_views.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/planning.py tests/test_planning_views.py
git commit -m "feat(planning): expected entries, the month picture (so far / still to come / projected) and Upcoming with a running net"
```

---

### Task 11: The Year, bucket pace and categories against their usual

**Files:**
- Modify:
  - `app/services/planning.py`: add `from dateutil.relativedelta import relativedelta` and append `year_outlook`.
  - `app/services/budgets.py`: append `PACE_FROM_DAY` and `bucket_pace`.
- Create: `app/services/usual.py`
- Test: `tests/test_planning_outlook.py`

**Interfaces:**
- Consumes:
  - `list_entries`, `Entry.infrequent`, `_total` (Task 10);
  - `generate_occurrences`, `PAST_NONE` (Task 3);
  - `bucket_period` machinery and imports (Task 9).
- Produces:
  - `app.services.planning.year_outlook(db, household_id, *, today=None) -> {"months": [{"month", "income", "out", "estimated"}] x 12, "infrequent_monthly_average", "estimated"}`
  - `app.services.budgets.PACE_FROM_DAY = 7`
  - `app.services.budgets.bucket_pace(db, household_id, *, today: date) -> list[{"bucket_id", "name", "budget", "spent", "pct", "pace", "over_pace"}]`
  - `app.services.usual.categories_vs_usual(db, household_id, year, month) -> list[{"category_id", "name", "icon", "color", "this_month", "usual", "flagged"}]`, plus the constants `USUAL_MONTHS = 3`, `MIN_MONTHS_WITH_DATA = 2`, `FLAG_RATIO = Decimal("1.2")` and `FLAG_MIN_ABOVE = Decimal("20")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_planning_outlook.py`:
```python
"""Plan › Year, bucket pace and categories vs usual (spec §4.2, §5.3-5.5)."""

from datetime import date
from decimal import Decimal

import pytest

from app.models import (
    BillOccurrence,
    Bucket,
    Category,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
)
from app.services.bills import PAST_NONE, generate_occurrences
from app.services.budgets import bucket_pace
from app.services.planning import year_outlook
from app.services.usual import categories_vs_usual

TODAY = date(2026, 10, 6)
D = Decimal


@pytest.fixture()
def frozen_today(monkeypatch):
    import app.services.bills as bills

    monkeypatch.setattr(bills, "local_today", lambda: TODAY)


def _item(db, hh, name, amount, **kw):
    bill = RecurringBill(
        household_id=hh.household_id, name=name, amount=amount, currency="EUR", **kw
    )
    db.add(bill)
    db.flush()
    generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
    return bill


def test_year_outlook(db, make_household, frozen_today):
    hh = make_household()
    _item(
        db,
        hh,
        "Salary",
        D("1500"),
        direction="in",
        rule_kind="monthly_day",
        rule_day=26,
        rule_adjust="previous_business_day",
        start_date=date(2026, 10, 1),
    )
    _item(
        db,
        hh,
        "Christmas salary",
        D("1500"),
        direction="in",
        rule_kind="yearly",
        rule_month=12,
        rule_day=21,
        rule_adjust="previous_business_day",
        start_date=date(2026, 1, 1),
    )
    _item(db, hh, "Rent", D("800"), start_date=date(2026, 11, 1))
    _item(
        db,
        hh,
        "Insurance",
        D("600"),
        rule_kind="yearly",
        rule_month=3,
        rule_day=1,
        start_date=date(2026, 1, 1),
    )
    _item(db, hh, "Water", D("90"), interval_months=3, start_date=date(2026, 11, 15))
    power = _item(db, hh, "DEH", None, start_date=date(2026, 10, 20))
    db.add(
        BillOccurrence(
            bill_id=power.id,
            due_date=date(2026, 9, 20),
            amount=D("66"),
            status=OccurrenceStatus.paid,
        )
    )
    db.commit()

    out = year_outlook(db, hh.household_id, today=TODAY)
    months = {m["month"]: m for m in out["months"]}
    assert list(months)[0] == "2026-10" and list(months)[-1] == "2027-09"
    assert months["2026-10"] == {
        "month": "2026-10",
        "income": D("1500.00"),
        "out": D("66.00"),
        "estimated": True,
    }
    assert months["2026-12"]["income"] == D("3000.00")  # salary + Christmas salary
    assert months["2027-03"]["out"] == D("1466.00")  # rent + insurance + DEH
    # Insurance 600 + water 4 x 90 over the 12 months, / 12.
    assert out["infrequent_monthly_average"] == D("80.00")


def _spend(db, hh, bucket_id, amount, when, **kw):
    db.add(
        Transaction(
            household_id=hh.household_id,
            bucket_id=bucket_id,
            amount=D(amount),
            currency="EUR",
            paid_by=hh.user_id,
            transaction_date=when,
            **kw,
        )
    )
    db.commit()


def test_bucket_pace_extrapolates_only_unlinked_spend(db, make_household, make_bill):
    hh = make_household()
    b = db.get(Bucket, hh.bucket_id)
    b.budget = D("1200")
    bill, _ = make_bill(hh.household_id, hh.bucket_id, occurrence=False)
    db.commit()
    _spend(db, hh, b.id, "300", date(2026, 10, 3))
    _spend(db, hh, b.id, "100", date(2026, 10, 1), recurring_bill_id=bill.id)
    _spend(db, hh, b.id, "50", date(2026, 10, 2), exclude_from_forecast=True)
    [row] = bucket_pace(db, hh.household_id, today=date(2026, 10, 10))
    assert row["spent"] == D("450.00")
    assert row["pace"] == D("1080.00")  # 300 / 10 x 31 + 100 + 50
    assert not row["over_pace"]
    [early] = bucket_pace(db, hh.household_id, today=date(2026, 10, 6))
    assert early["pace"] is None


def test_event_buckets_have_no_pace(db, make_household):
    hh = make_household()
    b = db.get(Bucket, hh.bucket_id)
    b.budget, b.type = D("500"), "trip"
    db.commit()
    assert bucket_pace(db, hh.household_id, today=date(2026, 10, 10)) == []


def _cat(db, hh, name):
    c = Category(household_id=hh.household_id, name=name)
    db.add(c)
    db.commit()
    return c


def test_category_flagged_only_20_percent_and_20_euro_above_usual(db, make_household):
    hh = make_household()
    food, fun = _cat(db, hh, "Food"), _cat(db, hh, "Fun")
    for m, f, u in ((7, "100", "10"), (8, "200", "0"), (9, "150", "10")):
        _spend(db, hh, hh.bucket_id, f, date(2026, m, 5), category_id=food.id)
        if u != "0":
            _spend(db, hh, hh.bucket_id, u, date(2026, m, 6), category_id=fun.id)
    _spend(db, hh, hh.bucket_id, "185", date(2026, 10, 2), category_id=food.id)  # usual 150
    _spend(db, hh, hh.bucket_id, "25", date(2026, 10, 2), category_id=fun.id)  # usual 10
    rows = {r["name"]: r for r in categories_vs_usual(db, hh.household_id, 2026, 10)}
    assert rows["Food"]["usual"] == D("150.00") and rows["Food"]["flagged"]
    assert rows["Fun"]["usual"] == D("10.00") and not rows["Fun"]["flagged"]  # only €15 above


def test_fewer_than_two_months_of_data_means_no_flag(db, make_household):
    hh = make_household()
    food = _cat(db, hh, "Food")
    _spend(db, hh, hh.bucket_id, "50", date(2026, 9, 5), category_id=food.id)
    _spend(db, hh, hh.bucket_id, "500", date(2026, 10, 2), category_id=food.id)
    [row] = categories_vs_usual(db, hh.household_id, 2026, 10)
    assert row["usual"] is None and not row["flagged"]


def test_months_with_data_but_no_spend_count_as_zero(db, make_household):
    hh = make_household()
    food, rent = _cat(db, hh, "Food"), _cat(db, hh, "Rent")
    for m in (7, 8, 9):
        _spend(db, hh, hh.bucket_id, "800", date(2026, m, 1), category_id=rent.id)
    _spend(db, hh, hh.bucket_id, "40", date(2026, 9, 5), category_id=food.id)
    _spend(db, hh, hh.bucket_id, "30", date(2026, 10, 2), category_id=food.id)
    rows = {r["name"]: r for r in categories_vs_usual(db, hh.household_id, 2026, 10)}
    assert rows["Food"]["usual"] == D("0.00") and rows["Food"]["flagged"]
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_planning_outlook.py -q`
Expected: `ImportError: cannot import name 'bucket_pace' from 'app.services.budgets'`.

- [ ] **Step 3: The Year**

In `app/services/planning.py`, add `from dateutil.relativedelta import relativedelta` after `from decimal import Decimal`, and append:
```python
def year_outlook(db: Session, household_id: str, *, today: date | None = None) -> dict:
    """Plan › Year (spec §5.3): expected In and Out per month for this month
    and the 11 after it, from recurring items only. Variable amounts use
    their estimate (``estimated``). ``infrequent_monthly_average`` is the
    sum of out entries of items that recur less than monthly, divided by 12:
    for information only.
    """
    today = today or local_today()
    first = date(today.year, today.month, 1)
    months = [first + relativedelta(months=k) for k in range(12)]
    last = _month_range(months[-1].year, months[-1].month)[1]
    entries = [
        e for e in list_entries(db, household_id, first, last, today=today) if e.status != "skipped"
    ]
    rows = []
    for m in months:
        in_month = [e for e in entries if (e.due_date.year, e.due_date.month) == (m.year, m.month)]
        rows.append(
            {
                "month": f"{m.year:04d}-{m.month:02d}",
                "income": _total(e for e in in_month if e.direction == ItemDirection.in_.value),
                "out": _total(e for e in in_month if e.direction == ItemDirection.out.value),
                "estimated": any(e.estimated for e in in_month),
            }
        )
    infrequent = _total(
        e for e in entries if e.direction == ItemDirection.out.value and e.infrequent
    )
    return {
        "months": rows,
        "infrequent_monthly_average": quantize(infrequent / 12),
        "estimated": any(e.estimated for e in entries),
    }
```

- [ ] **Step 4: Bucket pace**

Append to `app/services/budgets.py`:
```python
PACE_FROM_DAY = 7  # before the 7th a month's pace says too little


def bucket_pace(db: Session, household_id: str, *, today: date) -> list[dict]:
    """Pace for each active monthly bucket with a budget (spec §5.4):
    "€904 of €1,200 · on pace for €1,310".

    Only spend not linked to a recurring item is extrapolated: (that spend /
    days elapsed x days in month) + the bucket's recurring-linked spend. One-off
    purchases (``exclude_from_forecast``) are added as they are too, never
    extrapolated. ``pace`` is None before the 7th. It is a projection.
    """
    start, end = _month_range(today.year, today.month)
    buckets = (
        db.query(Bucket)
        .filter(
            Bucket.household_id == household_id,
            Bucket.status == BucketStatus.active,
            Bucket.kind == BucketKind.monthly.value,
            Bucket.budget.isnot(None),
        )
        .order_by(Bucket.created_at)
        .all()
    )
    rows = []
    for b in buckets:
        base = (
            Transaction.active(),
            Transaction.bucket_id == b.id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        flat_filter = (Transaction.recurring_bill_id.isnot(None)) | (
            Transaction.exclude_from_forecast.is_(True)
        )
        total = func.coalesce(func.sum(base_amount_expr()), 0)
        flat = quantize(db.query(total).filter(*base, flat_filter).scalar())
        free = quantize(db.query(total).filter(*base, ~flat_filter).scalar())
        budget = quantize(b.budget)
        pace = None
        if today.day >= PACE_FROM_DAY:
            pace = quantize(free / today.day * end.day + flat)
        rows.append(
            {
                "bucket_id": b.id,
                "name": b.name,
                "budget": budget,
                "spent": quantize(flat + free),
                "pct": percent(flat + free, budget),
                "pace": pace,
                "over_pace": pace is not None and pace > budget,
            }
        )
    return rows
```

- [ ] **Step 5: Categories against their usual**

Create `app/services/usual.py`:
```python
"""Categories against their usual (spec §4.2, §5.5).

A category's usual is the median of its spend over the last 3 full months,
counting months with zero spend, but only months the household has any data
for. Fewer than 2 such months: no usual and no flag. A category is flagged
when this month is at least 20% and at least €20 above its usual. There are
no category budgets.
"""

from collections import defaultdict
from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from app.core.money import ZERO, quantize
from app.models import Category, Transaction, TransactionType
from app.services.insights import _month_range
from app.services.money import to_base

USUAL_MONTHS = 3
MIN_MONTHS_WITH_DATA = 2
FLAG_RATIO = Decimal("1.2")
FLAG_MIN_ABOVE = Decimal("20")


def _months_before(year: int, month: int, n: int) -> list[tuple[int, int]]:
    out = []
    for _ in range(n):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        out.append((year, month))
    return list(reversed(out))


def categories_vs_usual(db: Session, household_id: str, year: int, month: int) -> list[dict]:
    """Each category with spend this month or in the 3 months before it:
    this month, its usual and whether it is flagged. Flagged first, then by
    this month's spend."""
    past = _months_before(year, month, USUAL_MONTHS)
    window_start = _month_range(*past[0])[0]
    month_end = _month_range(year, month)[1]
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.transaction_date >= window_start,
            Transaction.transaction_date <= month_end,
        )
        .all()
    )
    with_data = set()
    spend: dict = defaultdict(lambda: defaultdict(Decimal))
    for t in rows:
        key = (t.transaction_date.year, t.transaction_date.month)
        with_data.add(key)
        if t.type == TransactionType.expense:
            spend[key][t.category_id] += to_base(t.amount, t.exchange_rate)
    data_months = [m for m in past if m in with_data]
    this = spend[(year, month)]
    category_ids = set(this) | {c for m in data_months for c in spend[m]}
    cats = {
        c.id: c for c in db.query(Category).filter(Category.id.in_([c for c in category_ids if c]))
    }
    result = []
    for cid in category_ids:
        now = quantize(this.get(cid, ZERO))
        usual = None
        flagged = False
        if len(data_months) >= MIN_MONTHS_WITH_DATA:
            usual = quantize(median([spend[m].get(cid, ZERO) for m in data_months]))
            flagged = now >= usual * FLAG_RATIO and now - usual >= FLAG_MIN_ABOVE
        cat = cats.get(cid)
        result.append(
            {
                "category_id": cid,
                "name": cat.name if cat else "Uncategorised",
                "icon": cat.icon if cat else "📦",
                "color": cat.color if cat else "#9ca3af",
                "this_month": now,
                "usual": usual,
                "flagged": flagged,
            }
        )
    result.sort(key=lambda r: (not r["flagged"], -r["this_month"], r["name"]))
    return result
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_planning_outlook.py tests/test_planning_views.py tests/test_bucket_kinds.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/services/planning.py app/services/budgets.py app/services/usual.py tests/test_planning_outlook.py
git commit -m "feat(planning): 12-month outlook with the yearly/quarterly average, bucket pace, categories vs their usual"
```

---

### Task 12: `/api/v1/recurring`: items and entry actions

**Files:**
- Create: `app/api/planning_models.py`, `app/api/recurring.py`
- Modify: `app/api/__init__.py` (import `recurring` and include its router)
- Test: `tests/test_api_recurring.py`

**Interfaces:**
- Consumes:
  - `validate_rule`, `RuleError` (Task 1);
  - `item_rule`, `generate_occurrences`, `PAST_NONE`, `horizon_end`, `delete_future_occurrences` (Task 3);
  - `EntryStateError`, `undo_occurrence`, `skip_entry`, `set_entry_amount`, `bill_has_payment_history` (Task 5);
  - `complete_entry` (Task 7);
  - `list_entries`, `entry_for` (Task 10).
- Produces:
  - `app.api.planning_models`:
    - `Money` (a Decimal that is a JSON number)
    - `EntryOut`, `SplitOut`, `RecurringItemOut`, `MatchOut`
    - `MonthRowOut`, `BucketMonthRowOut`, `BucketsMonthOut`, `MonthPictureOut`
    - `UpcomingDayOut`, `YearMonthOut`, `YearOut`, `BudgetRowOut`, `PaceOut`, `CategoryUsualOut`
  - Endpoints:
    - `GET/POST /api/v1/recurring`
    - `GET/PUT/DELETE /api/v1/recurring/{item_id}`
    - `GET /api/v1/recurring/entries?from&to`
    - `POST /api/v1/recurring/entries/{entry_id}/done|undo|skip|amount`

  Status codes:
  - 400 for invalid input;
  - 404 for another household's id;
  - 409 for `EntryStateError` and for deleting an item with history.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_recurring.py`. Review Focus #5 (resume) is pinned in `test_resuming_fills_the_horizon_at_once`.
```python
"""/api/v1/recurring (spec §6.3): items in both directions on rules, their
entries and the entry actions; household isolation."""

from datetime import timedelta
from decimal import Decimal

from app.core.clock import local_today
from app.models import BillOccurrence, Bucket, BucketType, OccurrenceStatus, Transaction
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring"


def _salary(**over):
    body = {
        "name": "Salary",
        "direction": "in",
        "amount": "1500",
        "rule_kind": "monthly_day",
        "rule_day": 26,
        "rule_adjust": "previous_business_day",
        "start_date": (local_today() - timedelta(days=90)).isoformat(),
    }
    body.update(over)
    return body


def test_create_income_item_has_no_past_entries(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post(URL, headers=headers, json=_salary())
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["direction"] == "in" and item["next_entry"]["status"] == "expected"
    assert item["next_entry"]["amount"] == 1500.0
    dates = [d for (d,) in db.query(BillOccurrence.due_date).filter_by(bill_id=item["id"])]
    assert dates and min(dates) >= local_today() and len(dates) >= 12


def test_list_shows_paused_items_without_a_next_entry(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary(is_active=False)).json()
    [listed] = client.get(URL, headers=headers).json()
    assert listed["id"] == item["id"] and listed["is_active"] is False
    assert listed["next_entry"] is None


def test_resuming_fills_the_horizon_at_once(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary(is_active=False)).json()
    r = client.put(f"{URL}/{item['id']}", headers=headers, json=_salary(is_active=True))
    assert r.status_code == 200 and r.json()["next_entry"] is not None


def test_rule_and_reference_validation(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    bad_rule = client.post(URL, headers=headers, json=_salary(rule_day=None))
    assert bad_rule.status_code == 400
    in_bucket = client.post(URL, headers=headers, json=_salary(bucket_id=hh.bucket_id))
    assert in_bucket.status_code == 400
    trip = Bucket(household_id=hh.household_id, name="Trip", type=BucketType.trip)
    db.add(trip)
    db.commit()
    out_in_event = client.post(
        URL, headers=headers, json=_salary(direction="out", bucket_id=trip.id)
    )
    assert out_in_event.status_code == 400
    other = make_household(name="Other", username="other")
    foreign = client.post(
        URL, headers=headers, json=_salary(direction="out", bucket_id=other.bucket_id)
    )
    assert foreign.status_code in (400, 404)


def test_entries_range(client, db, api):  # noqa: F811
    headers, hh = api
    client.post(URL, headers=headers, json=_salary())
    today = local_today()
    r = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": today.isoformat(), "to": (today + timedelta(days=62)).isoformat()},
    )
    assert r.status_code == 200 and 2 <= len(r.json()) <= 3
    too_long = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": today.isoformat(), "to": (today + timedelta(days=500)).isoformat()},
    )
    assert too_long.status_code == 400


def _first_entry(client, headers):
    today = local_today()
    return client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": today.isoformat(), "to": (today + timedelta(days=60)).isoformat()},
    ).json()[0]


def test_done_undo_skip_amount_round_trip(client, db, api):  # noqa: F811
    headers, hh = api
    client.post(
        URL,
        headers=headers,
        json=_salary(direction="out", name="Cosmote", amount=None, rule_adjust="none"),
    )
    entry = _first_entry(client, headers)
    eid = entry["id"]
    assert client.post(f"{URL}/entries/{eid}/done", headers=headers, json={}).status_code == 400
    r = client.post(f"{URL}/entries/{eid}/amount", headers=headers, json={"amount": "38.90"})
    assert r.json()["amount"] == 38.9
    r = client.post(f"{URL}/entries/{eid}/done", headers=headers, json={})
    assert r.status_code == 200 and r.json()["status"] == "done"
    txn = db.query(Transaction).one()
    assert txn.bucket_id is None and txn.amount == Decimal("38.90")  # a Fixed cost
    again = client.post(f"{URL}/entries/{eid}/done", headers=headers, json={})
    assert again.status_code == 409
    keep = client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={})
    assert keep.status_code == 409  # a Fixed cost can't stay without its item
    r = client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={"delete_transaction": True})
    assert r.status_code == 200 and r.json()["status"] == "expected"
    assert client.post(f"{URL}/entries/{eid}/skip", headers=headers).json()["status"] == "skipped"
    assert client.post(f"{URL}/entries/{eid}/undo", headers=headers, json={}).status_code == 200


def test_mark_received_creates_income(client, db, api):  # noqa: F811
    headers, hh = api
    client.post(URL, headers=headers, json=_salary())
    entry = _first_entry(client, headers)
    r = client.post(f"{URL}/entries/{entry['id']}/done", headers=headers, json={"amount": "1520"})
    assert r.status_code == 200
    txn = db.query(Transaction).one()
    assert txn.type.value == "income" and txn.amount == Decimal("1520.00")
    assert txn.paid_by == hh.user_id


def test_delete_item_without_history(client, db, api):  # noqa: F811
    headers, hh = api
    item = client.post(URL, headers=headers, json=_salary()).json()
    assert client.delete(f"{URL}/{item['id']}", headers=headers).status_code == 204
    assert db.query(BillOccurrence).count() == 0


def test_another_household_gets_404_everywhere(client, db, api, make_household, make_bill):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    bill, occ = make_bill(other.household_id, other.bucket_id, auto_pay=False)
    assert client.get(f"{URL}/{bill.id}", headers=headers).status_code == 404
    assert client.put(f"{URL}/{bill.id}", headers=headers, json=_salary()).status_code == 404
    assert client.delete(f"{URL}/{bill.id}", headers=headers).status_code == 404
    for action, body in (("done", {}), ("undo", {}), ("amount", {"amount": "1"})):
        r = client.post(f"{URL}/entries/{occ.id}/{action}", headers=headers, json=body)
        assert r.status_code == 404, action
    assert client.post(f"{URL}/entries/{occ.id}/skip", headers=headers).status_code == 404
    assert client.get(URL, headers=headers).json() == []
    today = local_today()
    listed = client.get(
        f"{URL}/entries",
        headers=headers,
        params={"from": (today - timedelta(days=5)).isoformat(), "to": today.isoformat()},
    ).json()
    assert listed == []
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid


def test_requires_auth(client):
    assert client.get(URL).status_code == 401
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_api_recurring.py -q`
Expected: failures with 404 (the router is not mounted yet).

- [ ] **Step 3: Response models**

Create `app/api/planning_models.py`:
```python
"""Response models for the planning endpoints (spec §6.3).

The services keep money as Decimal; on the wire it is a JSON number, as the
older dict endpoints already send it, so the generated TypeScript types say
``number``. Projections carry their name (``still_to_come``, ``projected``,
``net_projected``, ``pace``) and ``estimated`` marks a "≈" amount.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_id: str
    name: str
    direction: str
    due_date: date
    status: str  # expected | done | skipped
    amount: Money | None
    estimated: bool
    currency: str
    bucket_id: str | None
    category_id: str | None
    transaction_id: str | None
    overdue: bool
    infrequent: bool


class SplitOut(BaseModel):
    user_id: str
    amount: Money


class RecurringItemOut(BaseModel):
    id: str
    name: str
    direction: str
    amount: Money | None
    currency: str
    category_id: str | None
    bucket_id: str | None
    rule_kind: str
    interval_months: int
    rule_day: int | None
    rule_month: int | None
    rule_adjust: str
    rule_days: int | None
    rule_weekday: int | None
    rule_interval_weeks: int | None
    start_date: date
    end_date: date | None
    total_occurrences: int | None
    contract_end_date: date | None
    paid_by_default: str | None
    payer_mode: str
    is_auto_pay: bool
    is_active: bool
    notes: str | None
    splits: list[SplitOut]
    next_entry: EntryOut | None


class MatchOut(BaseModel):
    id: str
    label: str  # "Looks like Cosmote · Oct · €38.90"
    transaction_id: str
    transaction_date: date
    transaction_amount: Money
    merchant: str | None
    notes: str | None
    entry: EntryOut


class MonthRowOut(BaseModel):
    so_far: Money
    still_to_come: Money
    projected: Money


class BucketMonthRowOut(MonthRowOut):
    bucket_id: str
    name: str
    budget: Money | None


class BucketsMonthOut(MonthRowOut):
    rows: list[BucketMonthRowOut]


class MonthPictureOut(BaseModel):
    month: str
    income: MonthRowOut
    fixed: MonthRowOut
    buckets: BucketsMonthOut
    net_projected: Money
    events_spent: Money
    cash: Money
    estimated: bool


class UpcomingDayOut(BaseModel):
    date: date
    entries: list[EntryOut]
    net_this_month: Money


class YearMonthOut(BaseModel):
    month: str
    income: Money
    out: Money
    estimated: bool


class YearOut(BaseModel):
    months: list[YearMonthOut]
    infrequent_monthly_average: Money
    estimated: bool


class BudgetRowOut(BaseModel):
    bucket_id: str
    name: str
    kind: str  # monthly | event
    budget: Money | None
    spent: Money
    pct: Money | None
    period_start: date | None
    period_end: date | None
    days_left: int | None
    archive_suggested: bool


class PaceOut(BaseModel):
    bucket_id: str
    name: str
    budget: Money
    spent: Money
    pct: Money
    pace: Money | None
    over_pace: bool


class CategoryUsualOut(BaseModel):
    category_id: str | None
    name: str
    icon: str
    color: str
    this_month: Money
    usual: Money | None
    flagged: bool
```

- [ ] **Step 4: The router**

Create `app/api/recurring.py`. The `/entries` routes are declared before `/{item_id}`, or FastAPI would read `entries` as an id.
```python
"""
/api/v1/recurring — recurring items (in and out) on schedule rules, and their
expected entries (spec §3, §6.3). The new app's only way to change them.
"""

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.planning_models import EntryOut, RecurringItemOut
from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.core.schedule import RuleError, validate_rule
from app.models import (
    BillOccurrence,
    BucketKind,
    ItemDirection,
    PayerMode,
    PaymentMethod,
    RecurringBill,
    RecurringBillSplit,
)
from app.schemas import parse_payer_mode, parse_payment_method
from app.services.bills import (
    BILL_HAS_HISTORY_MSG,
    PAST_NONE,
    EntryStateError,
    bill_has_payment_history,
    complete_entry,
    delete_future_occurrences,
    generate_occurrences,
    horizon_end,
    item_rule,
    set_entry_amount,
    skip_entry,
    undo_occurrence,
)
from app.services.planning import entry_for, list_entries
from app.validators import (
    parse_amount,
    require_bucket,
    require_category,
    require_member,
    validate_currency,
    validate_split_users,
)

router = APIRouter(prefix="/recurring", tags=["recurring"])

MAX_RANGE_DAYS = 400


class SplitIn(BaseModel):
    user_id: str
    amount: Decimal


class RecurringItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    direction: str = ItemDirection.out.value
    amount: Decimal | None = None  # None: variable
    currency: str = "EUR"
    category_id: str | None = None
    bucket_id: str | None = None  # out items only; a monthly bucket
    rule_kind: str = "monthly_day"
    interval_months: int = 1
    rule_day: int | None = None
    rule_month: int | None = None
    rule_adjust: str = "none"
    rule_days: int | None = None
    rule_weekday: int | None = None
    rule_interval_weeks: int | None = None
    start_date: date
    end_date: date | None = None
    total_occurrences: int | None = Field(default=None, ge=1)
    contract_end_date: date | None = None
    paid_by_default: str | None = None  # in items: received by
    payer_mode: str = PayerMode.single.value
    is_auto_pay: bool = False
    is_active: bool = True
    notes: str | None = None
    splits: list[SplitIn] = []

    @field_validator("payer_mode", mode="before")
    @classmethod
    def _payer_mode(cls, v):
        return parse_payer_mode(v)


class EntryDoneIn(BaseModel):
    amount: Decimal | None = None
    person: str | None = None  # payer (out) or recipient (in); None: the item's default
    payment_method: str = PaymentMethod.card.value

    @field_validator("payment_method", mode="before")
    @classmethod
    def _payment_method(cls, v):
        return parse_payment_method(v)


class EntryUndoIn(BaseModel):
    delete_transaction: bool = False


class EntryAmountIn(BaseModel):
    amount: Decimal


def _apply(db: Session, item: RecurringBill, body: RecurringItemIn, hh_id: str) -> None:
    """Validate ``body`` against the household and copy it onto ``item``."""
    try:
        direction = ItemDirection(body.direction).value
    except ValueError:
        raise HTTPException(status_code=400, detail="direction must be 'out' or 'in'.") from None
    income = direction == ItemDirection.in_.value
    if income and (body.bucket_id or body.is_auto_pay or body.splits):
        raise HTTPException(status_code=400, detail="Income has no bucket, auto-pay or shares.")
    if income and body.payer_mode != PayerMode.single.value:
        raise HTTPException(status_code=400, detail="Income has one recipient.")
    bucket = require_bucket(db, body.bucket_id, hh_id, optional=True)
    if bucket is not None and bucket.kind != BucketKind.monthly.value:
        raise HTTPException(
            status_code=400, detail="A recurring item can use a monthly bucket only."
        )
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="The end date is before the start date.")
    if body.splits:
        validate_split_users([s.user_id for s in body.splits], hh_id, db)
    if body.payer_mode == PayerMode.own_share.value and not body.splits:
        raise HTTPException(
            status_code=400, detail="payer_mode own_share needs splits (each member's share)."
        )
    item.direction = direction
    item.name = body.name.strip()
    item.amount = parse_amount(body.amount, field="Amount", allow_blank=True)
    item.currency = validate_currency(body.currency)
    item.category_id = require_category(db, body.category_id, hh_id)
    item.bucket_id = bucket.id if bucket else None
    item.rule_kind = body.rule_kind
    item.interval_months = body.interval_months
    item.rule_day = body.rule_day
    item.rule_month = body.rule_month
    item.rule_adjust = body.rule_adjust
    item.rule_days = body.rule_days
    item.rule_weekday = body.rule_weekday
    item.rule_interval_weeks = body.rule_interval_weeks
    try:
        validate_rule(item_rule(item))
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    item.start_date = body.start_date
    item.end_date = body.end_date
    item.total_occurrences = body.total_occurrences
    item.contract_end_date = body.contract_end_date
    item.payer_mode = body.payer_mode
    item.paid_by_default = (
        None
        if body.payer_mode == PayerMode.own_share.value
        else require_member(db, body.paid_by_default, hh_id)
    )
    item.is_auto_pay = body.is_auto_pay
    item.is_active = body.is_active
    item.notes = (body.notes or "").strip() or None


def _replace_splits(db: Session, item: RecurringBill, body: RecurringItemIn) -> None:
    db.query(RecurringBillSplit).filter_by(bill_id=item.id).delete(synchronize_session=False)
    db.expire(item, ["splits"])
    for s in body.splits:
        db.add(RecurringBillSplit(bill_id=item.id, user_id=s.user_id, amount=s.amount))


def _item_out(item: RecurringBill, next_entry) -> RecurringItemOut:
    return RecurringItemOut(
        id=item.id,
        name=item.name,
        direction=item.direction,
        amount=item.amount,
        currency=item.currency or "EUR",
        category_id=item.category_id,
        bucket_id=item.bucket_id,
        rule_kind=item.rule_kind,
        interval_months=item.interval_months or 1,
        rule_day=item.rule_day,
        rule_month=item.rule_month,
        rule_adjust=item.rule_adjust,
        rule_days=item.rule_days,
        rule_weekday=item.rule_weekday,
        rule_interval_weeks=item.rule_interval_weeks,
        start_date=item.start_date,
        end_date=item.end_date,
        total_occurrences=item.total_occurrences,
        contract_end_date=item.contract_end_date,
        paid_by_default=item.paid_by_default,
        payer_mode=item.payer_mode,
        is_auto_pay=item.is_auto_pay,
        is_active=item.is_active is not False,
        notes=item.notes,
        splits=[{"user_id": s.user_id, "amount": s.amount} for s in item.splits],
        next_entry=next_entry,
    )


def _next_entries(db: Session, hh_id: str) -> dict:
    """item id -> its first expected entry from today (active items only)."""
    today = local_today()
    first: dict = {}
    for e in list_entries(db, hh_id, today, horizon_end(today), today=today):
        if e.status == "expected":
            first.setdefault(e.item_id, e)
    return first


def _item_or_404(db: Session, item_id: str, hh_id: str) -> RecurringBill:
    item = db.get(RecurringBill, item_id)
    if not item or item.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return item


def _entry_or_404(db: Session, entry_id: str, hh_id: str) -> BillOccurrence:
    occ = db.get(BillOccurrence, entry_id)
    if not occ or occ.bill.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    return occ


# --------------------------------------------------------------- entries
# Declared before /{item_id}, or FastAPI would read "entries" as an item id.


@router.get("/entries", response_model=list[EntryOut])
def entries(
    from_: date = Query(alias="from"),
    to: date = Query(),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Entries of active items due in [from, to] (Upcoming, Year, history)."""
    user, hh_id = auth
    if to < from_ or (to - from_) > timedelta(days=MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=400, detail=f"'to' must be 0 to {MAX_RANGE_DAYS} days after 'from'."
        )
    return list_entries(db, hh_id, from_, to)


@router.post("/entries/{entry_id}/done", response_model=EntryOut)
def entry_done(
    entry_id: str,
    body: EntryDoneIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Pay (out: always an expense, a Fixed cost without a bucket) or Mark
    received (in: an income). Either creates and links the transaction."""
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    amount = parse_amount(body.amount, allow_blank=True)
    try:
        complete_entry(
            db,
            occ,
            user_id=user.id,
            amount=amount,
            person=require_member(db, body.person, hh_id),
            payment_method=body.payment_method,
        )
    except EntryStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/entries/{entry_id}/undo", response_model=EntryOut)
def entry_undo(
    entry_id: str,
    body: EntryUndoIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Done -> expected (unlinks; ``delete_transaction`` deletes it too), or
    skipped -> expected."""
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    try:
        undo_occurrence(db, occ, delete_transaction=body.delete_transaction)
    except EntryStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/entries/{entry_id}/skip", response_model=EntryOut)
def entry_skip(entry_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    try:
        skip_entry(occ)
    except EntryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/entries/{entry_id}/amount", response_model=EntryOut)
def entry_amount(
    entry_id: str,
    body: EntryAmountIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    occ = _entry_or_404(db, entry_id, hh_id)
    try:
        set_entry_amount(occ, parse_amount(body.amount))
    except EntryStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


# ----------------------------------------------------------------- items


@router.get("", response_model=list[RecurringItemOut])
def list_items(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Every item, paused ones included, each with its next expected entry."""
    user, hh_id = auth
    items = (
        db.query(RecurringBill)
        .filter_by(household_id=hh_id)
        .order_by(RecurringBill.direction, RecurringBill.name)
        .all()
    )
    nxt = _next_entries(db, hh_id)
    return [_item_out(i, nxt.get(i.id)) for i in items]


@router.post("", response_model=RecurringItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    body: RecurringItemIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    """Create an item. Nothing is created before today (spec §3.4.4)."""
    user, hh_id = auth
    item = RecurringBill(household_id=hh_id)
    _apply(db, item, body, hh_id)
    db.add(item)
    db.flush()
    _replace_splits(db, item, body)
    generate_occurrences(db, item, past=PAST_NONE)
    db.commit()
    db.refresh(item)
    return _item_out(item, _next_entries(db, hh_id).get(item.id))


@router.get("/{item_id}", response_model=RecurringItemOut)
def get_item(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    item = _item_or_404(db, item_id, hh_id)
    return _item_out(item, _next_entries(db, hh_id).get(item.id))


@router.put("/{item_id}", response_model=RecurringItemOut)
def update_item(
    item_id: str,
    body: RecurringItemIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Edit an item. Only future expected entries with no amount set are
    regenerated (spec §3.4.3); resuming fills the horizon at once."""
    user, hh_id = auth
    item = _item_or_404(db, item_id, hh_id)
    _apply(db, item, body, hh_id)
    _replace_splits(db, item, body)
    delete_future_occurrences(db, item.id)
    generate_occurrences(db, item, past=PAST_NONE)
    db.commit()
    db.refresh(item)
    return _item_out(item, _next_entries(db, hh_id).get(item.id))


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    item = _item_or_404(db, item_id, hh_id)
    if bill_has_payment_history(db, item.id):
        raise HTTPException(status_code=409, detail=BILL_HAS_HISTORY_MSG)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 5: Mount it**

In `app/api/__init__.py`, add `recurring,` to the `from app.api import (...)` list in alphabetical order, and append:
```python
# Planning (spec §6.3)
router.include_router(recurring.router)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_recurring.py tests/test_api.py -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/api/planning_models.py app/api/recurring.py app/api/__init__.py tests/test_api_recurring.py
git commit -m "feat(api): /recurring — items in and out on schedule rules, entries, done/undo/skip/amount"
```

---

### Task 13: `/api/v1/matches`, `/plan/*` (including budgets), `/insights/categories-vs-usual` and the drill-down filters

**Files:**
- Create: `app/api/matches.py`, `app/api/plan.py`
- Modify:
  - `app/api/__init__.py`: import `matches` and `plan`, and include them.
  - `app/api/insights.py`: imports and a new route at the end.
  - `app/api/transactions.py`: `_txn_dict` and `list_transactions`.
- Test: `tests/test_api_plan.py`

**Interfaces:**
- Consumes:
  - `open_suggestions`, `link_suggestion`, `dismiss_suggestion` (Task 8);
  - `budget_rows` (Task 9) and `bucket_pace` (Task 11);
  - `month_picture`, `upcoming`, `year_outlook`, `entry_for` (Tasks 10–11);
  - `categories_vs_usual` (Task 11);
  - the models from Task 12;
  - `app.templates.format_currency` (existing).
- Produces:
  - `app.api.plan.parse_month(value: str | None) -> tuple[int, int]`
  - Endpoints:
    - `GET /api/v1/matches`, `POST /api/v1/matches/{id}/link` (→ `EntryOut`; 409 when stale), `POST /api/v1/matches/{id}/dismiss` (204)
    - `GET /api/v1/plan/month?month=YYYY-MM`, `GET /api/v1/plan/upcoming?days=30`, `GET /api/v1/plan/year`, `GET /api/v1/plan/pace`
    - `GET /api/v1/plan/budgets` (→ `list[BudgetRowOut]`): every active bucket against its budget by kind, for bucket detail and the ≥80% line of Needs attention
    - `GET /api/v1/insights/categories-vs-usual?month=YYYY-MM`
  - `GET /api/v1/transactions` accepts `recurring_bill_id=` and `fixed=true`, and each item carries `recurring_bill_id`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_plan.py`:
```python
"""/api/v1/matches, /plan/*, /insights/categories-vs-usual, /buckets kind and
the transaction drill-down filters (spec §6.3); household isolation."""

from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import MatchSuggestion, Transaction
from tests.test_api import api  # noqa: F401  (fixture)


def _expense(client, headers, hh, amount="38.90"):
    r = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={"amount": amount, "bucket_id": hh.bucket_id, "merchant": "COSMOTE"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_match_list_link_and_refuse_a_stale_link(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=38.90,
        auto_pay=False,
        due=local_today(),
        name="Cosmote",
    )
    txn = _expense(client, headers, hh)
    [m] = client.get("/api/v1/matches", headers=headers).json()
    assert m["label"].startswith("Looks like Cosmote · ") and m["transaction_id"] == txn["id"]
    assert m["entry"]["status"] == "expected"

    assert client.post(f"/api/v1/matches/{m['id']}/link", headers={}).status_code == 401
    r = client.post(f"/api/v1/matches/{m['id']}/link", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.get("/api/v1/matches", headers=headers).json() == []
    again = client.post(f"/api/v1/matches/{m['id']}/link", headers=headers)
    assert again.status_code == 409
    assert db.get(Transaction, txn["id"]).recurring_bill_id == bill.id


def test_dismiss_and_foreign_suggestion(client, db, api, make_household, make_bill):  # noqa: F811
    headers, hh = api
    make_bill(hh.household_id, hh.bucket_id, amount=38.90, auto_pay=False, due=local_today())
    _expense(client, headers, hh)
    [m] = client.get("/api/v1/matches", headers=headers).json()
    assert client.post(f"/api/v1/matches/{m['id']}/dismiss", headers=headers).status_code == 204
    assert client.get("/api/v1/matches", headers=headers).json() == []
    assert db.query(MatchSuggestion).one().dismissed is True

    other = make_household(name="Other", username="other")
    s = db.query(MatchSuggestion).one()
    s.household_id = other.household_id
    db.commit()
    assert client.post(f"/api/v1/matches/{s.id}/link", headers=headers).status_code == 404
    assert client.post(f"/api/v1/matches/{s.id}/dismiss", headers=headers).status_code == 404


def test_plan_endpoints_shape_and_numbers_are_json_numbers(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    make_bill(hh.household_id, None, amount=30, auto_pay=False, due=local_today(), name="Net")
    month = client.get("/api/v1/plan/month", headers=headers)
    assert month.status_code == 200, month.text
    body = month.json()
    assert body["fixed"]["still_to_come"] == 30.0 and "net_projected" in body
    assert client.get("/api/v1/plan/month?month=2026-13", headers=headers).status_code == 400
    up = client.get("/api/v1/plan/upcoming", headers=headers).json()
    assert up[0]["entries"][0]["name"] == "Net"
    year = client.get("/api/v1/plan/year", headers=headers).json()
    assert len(year["months"]) == 12
    assert client.get("/api/v1/plan/pace", headers=headers).status_code == 200
    [budget] = client.get("/api/v1/plan/budgets", headers=headers).json()
    assert budget["bucket_id"] == hh.bucket_id and budget["kind"] == "monthly"
    usual = client.get("/api/v1/insights/categories-vs-usual", headers=headers)
    assert usual.status_code == 200


def test_plan_figures_ignore_other_households(client, db, api, make_household, make_bill):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    make_bill(other.household_id, None, amount=999, auto_pay=False, due=local_today())
    body = client.get("/api/v1/plan/month", headers=headers).json()
    assert body["fixed"]["still_to_come"] == 0.0
    assert client.get("/api/v1/plan/upcoming", headers=headers).json() == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/matches",
        "/api/v1/plan/month",
        "/api/v1/plan/upcoming",
        "/api/v1/plan/year",
        "/api/v1/plan/pace",
        "/api/v1/plan/budgets",
        "/api/v1/insights/categories-vs-usual",
    ],
)
def test_planning_endpoints_require_auth(client, path):
    assert client.get(path).status_code == 401


def test_transaction_drill_down_filters(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, occ = make_bill(hh.household_id, None, amount=20, auto_pay=False)
    r = client.post(f"/api/v1/recurring/entries/{occ.id}/done", headers=headers, json={})
    assert r.status_code == 200, r.text
    _expense(client, headers, hh, amount="5")
    fixed = client.get("/api/v1/transactions", headers=headers, params={"fixed": "true"}).json()
    assert [t["amount"] for t in fixed["items"]] == [20.0]
    assert fixed["items"][0]["recurring_bill_id"] == bill.id
    by_item = client.get(
        "/api/v1/transactions", headers=headers, params={"recurring_bill_id": bill.id}
    ).json()
    assert by_item["total"] == 1
    assert Decimal(str(fixed["items"][0]["amount"])) == Decimal("20")
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_api_plan.py -q`
Expected: failures with 404 (no routes yet).

- [ ] **Step 3: Matches router**

Create `app/api/matches.py`:
```python
"""
/api/v1/matches — "Looks like Cosmote · Oct · €38.90" (spec §3.5). Link marks
the entry done with that transaction; Not this dismisses it for good. Nothing
is ever linked without one of these taps.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.planning_models import EntryOut, MatchOut
from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.money import quantize
from app.models import MatchSuggestion
from app.services.bills import EntryStateError
from app.services.matching import dismiss_suggestion, link_suggestion, open_suggestions
from app.services.money import to_base
from app.services.planning import entry_for
from app.templates import format_currency

router = APIRouter(prefix="/matches", tags=["matches"])


def _match_out(db: Session, s: MatchSuggestion) -> MatchOut:
    txn, occ = s.transaction, s.occurrence
    amount = quantize(to_base(txn.amount, txn.exchange_rate))
    label = (
        f"Looks like {occ.bill.name} · {occ.due_date.strftime('%b')} · "
        f"{format_currency(txn.amount, txn.currency)}"
    )
    return MatchOut(
        id=s.id,
        label=label,
        transaction_id=txn.id,
        transaction_date=txn.transaction_date,
        transaction_amount=amount,
        merchant=txn.merchant,
        notes=txn.notes,
        entry=entry_for(db, occ),
    )


def _suggestion_or_404(db: Session, match_id: str, hh_id: str) -> MatchSuggestion:
    s = db.get(MatchSuggestion, match_id)
    if not s or s.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return s


@router.get("", response_model=list[MatchOut])
def list_matches(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Open suggestions, for Needs attention."""
    user, hh_id = auth
    return [_match_out(db, s) for s in open_suggestions(db, hh_id)]


@router.post("/{match_id}/link", response_model=EntryOut)
def link(match_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    s = _suggestion_or_404(db, match_id, hh_id)
    try:
        occ = link_suggestion(db, s)
    except EntryStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/{match_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(match_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    dismiss_suggestion(_suggestion_or_404(db, match_id, hh_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Plan router**

Create `app/api/plan.py`:
```python
"""
/api/v1/plan — the planning figures (spec §5): the month picture, Upcoming,
the Year, budgets by bucket kind and bucket pace. Every projected figure is
named as one.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.planning_models import (
    BudgetRowOut,
    MonthPictureOut,
    PaceOut,
    UpcomingDayOut,
    YearOut,
)
from app.api_auth import require_api_auth
from app.core.clock import local_today
from app.core.database import get_db
from app.services.budgets import bucket_pace, budget_rows
from app.services.planning import month_picture, upcoming, year_outlook

router = APIRouter(prefix="/plan", tags=["plan"])

_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value: str | None) -> tuple[int, int]:
    """'YYYY-MM' -> (year, month); blank is this month. HTTP 400 otherwise."""
    if not value:
        today = local_today()
        return today.year, today.month
    m = _MONTH.match(value.strip())
    if not m or not 1 <= int(m.group(2)) <= 12 or not 1970 <= int(m.group(1)) <= 2200:
        raise HTTPException(status_code=400, detail="month must be YYYY-MM.")
    return int(m.group(1)), int(m.group(2))


@router.get("/month", response_model=MonthPictureOut)
def month(
    month: str | None = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    year, mon = parse_month(month)
    return month_picture(db, hh_id, year, mon)


@router.get("/upcoming", response_model=list[UpcomingDayOut])
def upcoming_days(
    days: int = Query(default=30, ge=1, le=90),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    return upcoming(db, hh_id, days=days)


@router.get("/year", response_model=YearOut)
def year(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return year_outlook(db, hh_id)


@router.get("/pace", response_model=list[PaceOut])
def pace(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return bucket_pace(db, hh_id, today=local_today())


@router.get("/budgets", response_model=list[BudgetRowOut])
def budgets(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Every active bucket against its budget: monthly per calendar month,
    events over their dates with days left (spec §4.1)."""
    user, hh_id = auth
    return budget_rows(db, hh_id, local_today())
```

- [ ] **Step 5: Mount, categories vs usual and drill-down filters**

In `app/api/__init__.py`, add `matches,` and `plan,` to the import list and two more lines under `# Planning (spec §6.3)`:
```python
router.include_router(matches.router)
router.include_router(plan.router)
```
In `app/api/insights.py`, add the imports
```python
from app.api.plan import parse_month
from app.api.planning_models import CategoryUsualOut
from app.services.usual import categories_vs_usual
```
and append:
```python
@router.get("/categories-vs-usual", response_model=list[CategoryUsualOut])
def categories_usual(
    month: str | None = Query(default=None),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Each category this month against its usual (spec §4.2); flagged ones first."""
    user, hh_id = auth
    year, mon = parse_month(month)
    return categories_vs_usual(db, hh_id, year, mon)
```
In `app/api/transactions.py`:
- in `_txn_dict`, after `"exclude_from_settlement": t.exclude_from_settlement,`, add `"recurring_bill_id": t.recurring_bill_id,`;
- in `list_transactions`, after the `month` parameter, add the parameters
```python
    recurring_bill_id: str = Query(default=""),
    fixed: bool = Query(default=False),
```
- directly after `q = db.query(Transaction).filter(...)`, add:
```python
    # Drill-downs from the planning figures (spec §5): one item's payments,
    # or the Fixed costs (expenses linked to an item, with no bucket).
    if recurring_bill_id:
        q = q.filter(Transaction.recurring_bill_id == recurring_bill_id)
    if fixed:
        q = q.filter(
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.is_(None),
            Transaction.recurring_bill_id.isnot(None),
        )
```

- [ ] **Step 6: Run the tests and check the OpenAPI schema**

Run: `.venv/bin/python -m pytest tests/test_api_plan.py tests/test_api_recurring.py tests/test_api.py -q`
Expected: all pass.

Then run `.venv/bin/python scripts/export_openapi.py` (from Phase 1) and check that `components.schemas` contains `MonthPictureOut`, `EntryOut`, `MatchOut` and `RecurringItemOut`, with money fields typed `number`. If Phase 1's script is not merged yet, run `DEBUG=true APP_SECRET_KEY=x-32-chars-minimum-xxxxxxxxxxxxxx .venv/bin/python -c "from app.main import app; import json; print(json.dumps(app.openapi()['components']['schemas']['MonthPictureOut'], indent=1))"`.

- [ ] **Step 7: Full suite and commit**

Run: `.venv/bin/python -m pytest -q`. Expected: all pass.
```bash
.venv/bin/ruff check app tests && .venv/bin/ruff format app tests
git add app/api/matches.py app/api/plan.py app/api/__init__.py app/api/insights.py app/api/transactions.py tests/test_api_plan.py
git commit -m "feat(api): /matches, /plan/month|upcoming|year|pace, /insights/categories-vs-usual, transaction drill-down filters"
```

---

### Task 14: Compatibility proof: the full suite on both databases and a production-shaped upgrade

**Files:**
- Test: `tests/test_planning_upgrade.py`
- Modify: `docs/DEPLOY-COOLIFY.md`. Add a "Planning redesign upgrade" checklist after section 0.

**Interfaces:**
- Consumes:
  - Alembic revision `b3c4d5e6f7a8`, the head at commit `6cc20e8` (production);
  - `_alembic` and `_db_url` (in `tests/test_migrations.py`);
  - `PASSWORD` and `form_csrf` (in `tests/conftest.py`);
  - everything above.
- Produces: an automated production-shaped upgrade test and a manual procedure for a real dump.

- [ ] **Step 1: Write the automated upgrade test**

Create `tests/test_planning_upgrade.py`. It builds the schema production runs, seeds it the way production data looks (with a TOTP user, buckets, a bill with a paid and an unpaid occurrence, and income), upgrades to head, and then drives the old app and the new API against it.
```python
"""Production-shaped upgrade (spec §7): the schema production runs (commit
6cc20e8, alembic head b3c4d5e6f7a8) with real-looking data, upgraded to head,
then the old app used as a person would: TOTP login, dashboard, bills (pay
one), insights, a trip bucket, search; and the new API on the same data."""

import uuid
from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.core.clock import local_today
from tests.conftest import PASSWORD, form_csrf
from tests.test_migrations import _alembic, _db_url

PROD_REVISION = "b3c4d5e6f7a8"  # alembic head at commit 6cc20e8


def _seed(conn) -> dict:
    today = local_today()
    ids = {
        k: str(uuid.uuid4())
        for k in ("hh", "user", "daily", "trip", "bill", "paid", "due", "txn", "inc")
    }
    ids["secret"] = pyotp.random_base32()
    q = lambda sql, **p: conn.execute(text(sql), p)  # noqa: E731
    q("INSERT INTO households (id, name, default_currency) VALUES (:i, 'Home', 'EUR')", i=ids["hh"])
    q(
        "INSERT INTO users (id, username, display_name, password_hash, session_version, "
        "totp_enabled, totp_secret, email_verified) VALUES (:i, 'giorgos', 'Giorgos', :p, 0, "
        "true, :s, false)",
        i=ids["user"],
        p=hash_password(PASSWORD),
        s=ids["secret"],
    )
    q(
        "INSERT INTO household_members (id, household_id, user_id, role) "
        "VALUES (:i, :h, :u, 'owner')",
        i=str(uuid.uuid4()),
        h=ids["hh"],
        u=ids["user"],
    )
    for key, kind, budget in (("daily", "day2day", 1200), ("trip", "trip", 900)):
        q(
            "INSERT INTO buckets (id, household_id, name, type, status, budget, show_income, "
            "enable_settlement) VALUES (:b, :h, :n, :t, 'active', :g, true, false)",
            b=ids[key],
            h=ids["hh"],
            n=key.title(),
            t=kind,
            g=budget,
        )
    q(
        "INSERT INTO recurring_bills (id, household_id, bucket_id, name, amount, currency, "
        "frequency, interval_months, start_date, is_active, is_auto_pay) VALUES (:i, :h, :b, "
        "'Cosmote', 38.90, 'EUR', 'monthly', 1, :s, true, false)",
        i=ids["bill"],
        h=ids["hh"],
        b=ids["daily"],
        s=today - timedelta(days=40),
    )
    q(
        "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, exchange_rate, "
        "type, paid_by, transaction_date, exclude_from_forecast, exclude_from_settlement) "
        "VALUES (:i, :b, :h, 38.90, 'EUR', 1, 'expense', :u, :d, false, false)",
        i=ids["txn"],
        b=ids["daily"],
        h=ids["hh"],
        u=ids["user"],
        d=today - timedelta(days=40),
    )
    q(
        "INSERT INTO transactions (id, bucket_id, household_id, amount, currency, exchange_rate, "
        "type, paid_by, transaction_date, exclude_from_forecast, exclude_from_settlement) "
        "VALUES (:i, :b, :h, 1500, 'EUR', 1, 'income', :u, :d, false, false)",
        i=ids["inc"],
        b=ids["daily"],
        h=ids["hh"],
        u=ids["user"],
        d=today,
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status, transaction_id) "
        "VALUES (:i, :b, :d, 'paid', :t)",
        i=ids["paid"],
        b=ids["bill"],
        d=today - timedelta(days=40),
        t=ids["txn"],
    )
    q(
        "INSERT INTO bill_occurrences (id, bill_id, due_date, status) VALUES (:i, :b, :d, 'unpaid')",
        i=ids["due"],
        b=ids["bill"],
        d=today - timedelta(days=10),
    )
    return ids


@pytest.fixture()
def upgraded(tmp_path, monkeypatch):
    db_url = _db_url(tmp_path, "prod.db")
    assert _alembic(["upgrade", PROD_REVISION], db_url).returncode == 0
    engine = create_engine(db_url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as conn:
        ids = _seed(conn)
    up = _alembic(["upgrade", "head"], db_url)
    assert up.returncode == 0, up.stderr

    import app.core.database as database
    from app.main import app as fastapi_app

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine, raising=False)
    monkeypatch.setattr(database, "SessionLocal", Session, raising=False)

    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[database.get_db] = _get_db
    yield TestClient(fastapi_app, follow_redirects=False), Session, ids
    fastapi_app.dependency_overrides.clear()
    engine.dispose()


def test_old_app_works_after_the_upgrade(upgraded):
    client, Session, ids = upgraded
    r = client.post(
        "/login", data={"username": "giorgos", "password": PASSWORD, **form_csrf(client, "/login")}
    )
    assert r.status_code == 302
    r = client.post(
        "/login/verify",
        data={"code": pyotp.TOTP(ids["secret"]).now(), **form_csrf(client, "/login/verify")},
    )
    assert r.status_code == 302
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}

    for url in (
        "/dashboard",
        "/bills",
        "/insights",
        f"/buckets/{ids['trip']}",
        "/transactions/search",
    ):
        assert client.get(url).status_code == 200, url
    assert "Cosmote" in client.get("/bills").text

    r = client.post(f"/bills/{ids['bill']}/occurrences/{ids['due']}/pay", headers=headers)
    assert r.status_code == 302
    with Session() as db:
        row = db.execute(
            text(
                "SELECT o.status, t.recurring_bill_id FROM bill_occurrences o "
                "JOIN transactions t ON t.id = o.transaction_id WHERE o.id = :i"
            ),
            {"i": ids["due"]},
        ).one()
        assert tuple(row) == ("paid", ids["bill"])
        backfilled = db.execute(
            text("SELECT recurring_bill_id FROM transactions WHERE id = :i"), {"i": ids["txn"]}
        ).scalar()
        assert backfilled == ids["bill"]


def test_new_api_reads_the_upgraded_data(upgraded):
    client, Session, ids = upgraded
    r = client.post("/api/v1/auth/login", json={"username": "giorgos", "password": PASSWORD})
    pending = r.json()["pending_token"]
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": pending, "code": pyotp.TOTP(ids["secret"]).now()},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    month = client.get("/api/v1/plan/month", headers=headers)
    assert month.status_code == 200, month.text
    assert month.json()["income"]["so_far"] == 1500.0
    buckets = {b["name"]: b["kind"] for b in client.get("/api/v1/buckets", headers=headers).json()}
    assert buckets == {"Daily": "monthly", "Trip": "event"}
    [item] = client.get("/api/v1/recurring", headers=headers).json()
    assert (item["direction"], item["rule_kind"]) == ("out", "monthly_interval")
```

- [ ] **Step 2: Run it on SQLite and on Postgres 18**

Run: `.venv/bin/python -m pytest tests/test_planning_upgrade.py -q`
Then: `TEST_DATABASE_URL=postgresql://… .venv/bin/python -m pytest tests/test_planning_upgrade.py -q`
Expected: 2 passed on each.

- [ ] **Step 3: The full suite on both databases, unchanged**

Run:
```bash
git diff --stat main -- tests/ | grep -v "test_planning\|test_schedule_rules\|test_matching\|test_bucket_kinds\|test_api_recurring\|test_api_plan"
.venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql://… .venv/bin/python -m pytest -q
.venv/bin/ruff check app tests alembic scripts
.venv/bin/ruff format --check app tests alembic scripts
```
Expected:
- the `git diff` lists no existing test file;
- both suites pass;
- ruff is clean.

- [ ] **Step 4: Manual check against a real production dump**

Add this checklist to `docs/DEPLOY-COOLIFY.md`, after section 0, as "Planning redesign upgrade". Run it once before deploying.
```markdown
## Planning redesign upgrade (migration a7b8c9d0e1f2)

1. Dump production (the usual pre-migrate safety net; rollback = restore it):
   `pg_dump "$DATABASE_URL" | gzip > expenses-pre-planning.sql.gz`
2. Restore it into a scratch database on a Postgres 18 you control:
   `createdb expenses_upgrade_check && gunzip -c expenses-pre-planning.sql.gz | psql expenses_upgrade_check`
   No dump at hand? Build production's schema from the deployed code instead:
   `git worktree add /tmp/expenses-6cc20e8 6cc20e8 && (cd /tmp/expenses-6cc20e8 && DATABASE_URL=postgresql://localhost/expenses_upgrade_check APP_SECRET_KEY=$(openssl rand -hex 32) DEBUG=true <repo>/.venv/bin/alembic upgrade head)`
3. Upgrade with this branch:
   `DATABASE_URL=postgresql://localhost/expenses_upgrade_check .venv/bin/alembic upgrade head`
4. Check the backfill:
   `psql expenses_upgrade_check -c "SELECT direction, rule_kind, count(*) FROM recurring_bills GROUP BY 1,2"` → only `out | monthly_interval`
   `psql expenses_upgrade_check -c "SELECT type, kind, count(*) FROM buckets GROUP BY 1,2"` → trip = event, the rest monthly
   `psql expenses_upgrade_check -c "SELECT count(*) FROM bill_occurrences o JOIN transactions t ON t.id = o.transaction_id WHERE o.status = 'paid' AND t.recurring_bill_id IS DISTINCT FROM o.bill_id"` → 0
5. Old-app smoke test on the upgraded copy:
   `DATABASE_URL=postgresql://localhost/expenses_upgrade_check APP_SECRET_KEY=<prod key> FIELD_ENCRYPTION_KEY=<prod key> DEBUG=true ENABLE_SCHEDULER=false .venv/bin/uvicorn app.main:app --port 8001`
   Log in with password + TOTP. Open the dashboard (same month totals as production), Bills (same list, pay one occurrence), Insights, a trip bucket and Search.
6. Round trip: `.venv/bin/alembic downgrade f0a1b2c3d4e5 && .venv/bin/alembic upgrade head` (use the revision this migration revises).
7. Drop the scratch database.
```
Then run steps 1–7 against the latest production dump and note the date and result in the PR description.

- [ ] **Step 5: Commit**

```bash
.venv/bin/ruff check tests && .venv/bin/ruff format tests
git add tests/test_planning_upgrade.py docs/DEPLOY-COOLIFY.md
git commit -m "test(planning): production-shaped upgrade from 6cc20e8's schema; upgrade checklist for a real dump"
```

---

## Out of scope for this plan

- The Home and Plan screens that consume these endpoints: Phase 2 and Phase 3.
- The "Already paid up to today?" question for a past `start_date`. It is a form concern: the API never creates past entries, whatever the answer.
- Archiving an ended event bucket needs no new backend: `/plan/budgets` reports `archive_suggested`, and the existing `POST /api/v1/buckets/{id}/archive` sets `status = archived`.
- A default payment method and bulk edits on recurring items (`docs/redesign/backlog.md`).
- Cleaning up `buckets.type`, `goal_amount`, `show_income`, `interval_months` and `frequency`. That happens at cutover, after a CSV export, in the migration that drops settlements.
