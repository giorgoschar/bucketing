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
