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


def test_uncategorised_and_null_icon_fall_back(db, make_household):
    hh = make_household()
    bare = _cat(db, hh, "Bare")
    bare.icon = bare.color = None
    db.commit()
    for m in (8, 9):
        _spend(db, hh, hh.bucket_id, "10", date(2026, m, 5), category_id=bare.id)
    _spend(db, hh, hh.bucket_id, "5", date(2026, 10, 2), category_id=bare.id)
    _spend(db, hh, hh.bucket_id, "7", date(2026, 10, 3))
    rows = {r["name"]: r for r in categories_vs_usual(db, hh.household_id, 2026, 10)}
    for name in ("Bare", "Uncategorised"):
        assert rows[name]["icon"] == "📦" and rows[name]["color"] == "#9ca3af"
