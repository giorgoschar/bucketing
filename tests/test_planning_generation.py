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


# Ruling 12: a rule change never yields two entries for one item in one
# calendar month (ISO week for weekly rules), so salaries cannot double.


def _edit(db, bill, **changes):
    for key, value in changes.items():
        setattr(bill, key, value)
    delete_future_occurrences(db, bill.id)
    generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()


def _salary_on_26th(db, hh):
    bill = _item(db, hh, start_date=date(2026, 10, 7), rule_kind="monthly_day", rule_day=26)
    generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
    return bill, db.query(BillOccurrence).filter_by(
        bill_id=bill.id, due_date=date(2026, 10, 26)
    ).one()


@pytest.mark.parametrize(
    "touch",
    [
        {"status": OccurrenceStatus.paid},
        {"status": OccurrenceStatus.skipped},
        {"amount": Decimal("1600.00")},
    ],
    ids=["done", "skipped", "amount-set"],
)
def test_day_change_skips_a_month_that_has_a_kept_entry(db, make_household, frozen_today, touch):
    hh = make_household()
    bill, october = _salary_on_26th(db, hh)
    for key, value in touch.items():
        setattr(october, key, value)
    db.commit()

    _edit(db, bill, rule_day=28)

    got = _dates(db, bill)
    october_dates = [d for d in got if (d.year, d.month) == (2026, 10)]
    assert october_dates == [date(2026, 10, 26)]
    assert date(2026, 11, 28) in got and date(2026, 11, 26) not in got
    assert len(got) == 13


def test_day_change_moves_untouched_months(db, make_household, frozen_today):
    hh = make_household()
    bill, _ = _salary_on_26th(db, hh)
    _edit(db, bill, rule_day=28)
    got = _dates(db, bill)
    assert got[0] == date(2026, 10, 28) and date(2026, 10, 26) not in got
    assert all(d.day == 28 for d in got)


def test_weekday_change_skips_an_iso_week_that_has_a_kept_entry(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(
        db,
        hh,
        start_date=date(2026, 10, 7),
        rule_kind="weekly",
        rule_weekday=0,
        rule_interval_weeks=1,
    )
    generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
    monday = db.query(BillOccurrence).filter_by(bill_id=bill.id, due_date=date(2026, 10, 12)).one()
    monday.status = OccurrenceStatus.paid
    db.commit()

    _edit(db, bill, rule_weekday=2)  # Wednesdays from now on

    got = _dates(db, bill)
    week = date(2026, 10, 12).isocalendar()[:2]
    assert [d for d in got if d.isocalendar()[:2] == week] == [date(2026, 10, 12)]
    assert date(2026, 10, 21) in got and date(2026, 10, 19) not in got


def test_generation_is_capped_at_600_rows(db, make_household, frozen_today):
    hh = make_household()
    bill = _item(db, hh, start_date=date(2000, 1, 3), rule_kind="weekly", rule_weekday=0)
    assert generate_occurrences(db, bill, past=PAST_SKIPPED) == 600


def test_two_rule_dates_in_one_month_are_both_kept(db, make_household, frozen_today):
    # The 1st, moved back off holidays: 1 Jan 2027 is a holiday, so January's
    # entry falls on 31 Dec, the same month as December's own 1 Dec.
    hh = make_household()
    bill = _item(
        db,
        hh,
        start_date=date(2026, 10, 7),
        rule_kind="monthly_day",
        rule_day=1,
        rule_adjust="previous_business_day",
    )
    generate_occurrences(db, bill, past=PAST_NONE)
    db.commit()
    december = db.query(BillOccurrence).filter_by(bill_id=bill.id, due_date=date(2026, 12, 1)).one()
    december.status = OccurrenceStatus.paid
    db.commit()

    _edit(db, bill, name="Salary (edited)")

    assert {date(2026, 12, 1), date(2026, 12, 31)} <= set(_dates(db, bill))


def test_long_lived_item_still_gets_future_entries(db, make_household, frozen_today):
    # Over 600 past dates must not use up the cap before today is reached.
    hh = make_household()
    bill = _item(db, hh, start_date=date(2000, 1, 3), rule_kind="weekly", rule_weekday=0)
    created = generate_occurrences(db, bill, past=PAST_NONE)
    got = _dates(db, bill)
    assert created == len(got) and 55 <= created <= 58
    assert got[0] == date(2026, 10, 12)
