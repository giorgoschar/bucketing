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
