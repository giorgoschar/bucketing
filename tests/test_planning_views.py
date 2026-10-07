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
    # Oct so far: 590 in - 488.90 out (300 + 150 + 38.90); the 200 event spend is not in Net.
    assert [d["net_this_month"] for d in days] == [
        D("71.10"),
        D("1.10"),
        D("1501.10"),
        D("-30.00"),
    ]
    assert all(e.status == "expected" for d in days for e in d["entries"])
