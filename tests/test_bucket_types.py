"""
Trip and savings bucket behaviour.

BucketType.trip and BucketType.savings previously existed only as filter
labels with no behaviour attached.
"""
from datetime import date, timedelta

import pytest

from app.models import (
    Bucket, BucketType, Transaction, TransactionSplit, TransactionType,
)
from app.services import get_savings_summary, get_trip_summary


def _expense(db, bucket, household_id, amount, when=None, paid_by=None,
             currency="EUR", rate=1):
    txn = Transaction(
        bucket_id=bucket.id, household_id=household_id, amount=amount,
        currency=currency, exchange_rate=rate, type=TransactionType.expense,
        transaction_date=when or date.today(), paid_by=paid_by,
    )
    db.add(txn)
    db.flush()
    return txn


@pytest.fixture()
def trip(db, authed):
    b = db.get(Bucket, authed.bucket_id)
    b.type = BucketType.trip
    b.name = "Florence 2026"
    db.commit()
    return b


@pytest.fixture()
def savings(db, authed):
    b = db.get(Bucket, authed.bucket_id)
    b.type = BucketType.savings
    b.name = "House deposit"
    b.show_income = True
    db.commit()
    return b


# ---------------------------------------------------------------------------
# Trip
# ---------------------------------------------------------------------------

def test_non_trip_bucket_returns_nothing(db, authed):
    assert get_trip_summary(db, db.get(Bucket, authed.bucket_id)) == {}


def test_dates_fall_back_to_transactions(db, authed, trip):
    """A trip with no explicit range is still useful."""
    _expense(db, trip, authed.household_id, 100, date(2026, 5, 1))
    _expense(db, trip, authed.household_id, 50, date(2026, 5, 5))
    db.commit()

    s = get_trip_summary(db, trip)
    assert s["start"] == date(2026, 5, 1)
    assert s["end"] == date(2026, 5, 5)
    assert s["days"] == 5
    assert s["total"] == 150.0
    assert s["per_day"] == 30.0


def test_explicit_dates_win(db, authed, trip):
    trip.start_date = date(2026, 5, 1)
    trip.end_date = date(2026, 5, 10)
    _expense(db, trip, authed.household_id, 100, date(2026, 5, 3))
    db.commit()

    s = get_trip_summary(db, trip)
    assert s["days"] == 10
    assert s["per_day"] == 10.0


def test_upcoming_trip_counts_down(db, trip):
    trip.start_date = date.today() + timedelta(days=12)
    trip.end_date = date.today() + timedelta(days=19)
    db.commit()

    s = get_trip_summary(db, trip)
    assert s["status"] == "upcoming"
    assert s["days_until"] == 12


def test_active_trip_reports_days_remaining(db, trip):
    trip.start_date = date.today() - timedelta(days=2)
    trip.end_date = date.today() + timedelta(days=3)
    db.commit()

    s = get_trip_summary(db, trip)
    assert s["status"] == "active"
    assert s["days_remaining"] == 4


def test_past_trip_is_finished(db, trip):
    trip.start_date = date.today() - timedelta(days=30)
    trip.end_date = date.today() - timedelta(days=20)
    db.commit()
    assert get_trip_summary(db, trip)["status"] == "past"


def test_budget_remaining(db, authed, trip):
    trip.budget = 500
    _expense(db, trip, authed.household_id, 120)
    db.commit()

    s = get_trip_summary(db, trip)
    assert s["budget"] == 500.0
    assert s["remaining"] == 380.0


def test_over_budget_is_negative(db, authed, trip):
    trip.budget = 100
    _expense(db, trip, authed.household_id, 150)
    db.commit()
    assert get_trip_summary(db, trip)["remaining"] == -50.0


def test_per_person_uses_splits(db, authed, trip, make_household):
    txn = _expense(db, trip, authed.household_id, 100, paid_by=authed.user_id)
    other = make_household(name="X", username="tripmate")
    db.add_all([
        TransactionSplit(transaction_id=txn.id, user_id=authed.user_id, amount=70),
        TransactionSplit(transaction_id=txn.id, user_id=other.user_id, amount=30),
    ])
    db.commit()

    people = {p["user_id"]: p["amount"] for p in get_trip_summary(db, trip)["per_person"]}
    assert people[authed.user_id] == 70.0
    assert people[other.user_id] == 30.0


def test_trip_totals_are_currency_converted(db, authed, trip):
    _expense(db, trip, authed.household_id, 200, currency="USD", rate=0.5)
    db.commit()
    assert get_trip_summary(db, trip)["total"] == 100.0


def test_empty_trip_does_not_crash(db, trip):
    s = get_trip_summary(db, trip)
    assert s["total"] == 0.0
    assert s["per_day"] is None
    assert s["transaction_count"] == 0


# ---------------------------------------------------------------------------
# Savings
# ---------------------------------------------------------------------------

def _income(db, bucket, household_id, amount):
    db.add(Transaction(
        bucket_id=bucket.id, household_id=household_id, amount=amount,
        currency="EUR", exchange_rate=1, type=TransactionType.income,
        transaction_date=date.today(),
    ))


def test_non_savings_bucket_returns_nothing(db, authed):
    assert get_savings_summary(db, db.get(Bucket, authed.bucket_id)) == {}


def test_no_goal_reports_saved_only(db, authed, savings):
    _income(db, savings, authed.household_id, 500)
    db.commit()

    s = get_savings_summary(db, savings)
    assert s["saved"] == 500.0
    assert s["goal"] is None
    assert s["pct"] is None


def test_progress_toward_goal(db, authed, savings):
    savings.goal_amount = 10000
    _income(db, savings, authed.household_id, 2500)
    db.commit()

    s = get_savings_summary(db, savings)
    assert s["saved"] == 2500.0
    assert s["pct"] == 25.0
    assert s["remaining"] == 7500.0
    assert s["reached"] is False


def test_withdrawals_reduce_progress(db, authed, savings):
    savings.goal_amount = 1000
    _income(db, savings, authed.household_id, 800)
    _expense(db, savings, authed.household_id, 300)
    db.commit()
    assert get_savings_summary(db, savings)["saved"] == 500.0


def test_goal_reached(db, authed, savings):
    savings.goal_amount = 1000
    _income(db, savings, authed.household_id, 1200)
    db.commit()

    s = get_savings_summary(db, savings)
    assert s["reached"] is True
    assert s["pct"] == 100          # bar is clamped
    assert s["pct_actual"] == 120.0  # true figure


def test_monthly_contribution_required(db, authed, savings):
    savings.goal_amount = 1200
    today = date.today()
    month = today.month + 6
    year = today.year + (month - 1) // 12
    savings.end_date = date(year, (month - 1) % 12 + 1, 1)
    _income(db, savings, authed.household_id, 600)
    db.commit()

    s = get_savings_summary(db, savings)
    assert s["months_left"] == 6
    assert s["per_month"] == 100.0


def test_no_target_date_has_no_monthly_figure(db, authed, savings):
    savings.goal_amount = 1000
    _income(db, savings, authed.household_id, 100)
    db.commit()

    s = get_savings_summary(db, savings)
    assert s["per_month"] is None
    assert s["on_track"] is None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_trip_page_renders(client, db, authed, trip):
    trip.start_date = date(2026, 5, 1)
    trip.end_date = date(2026, 5, 8)
    _expense(db, trip, authed.household_id, 250, date(2026, 5, 2))
    db.commit()

    r = client.get(f"/buckets/{trip.id}")
    assert r.status_code == 200
    assert "Trip" in r.text
    assert "Per day" in r.text


def test_savings_page_renders(client, db, authed, savings):
    savings.goal_amount = 5000
    _income(db, savings, authed.household_id, 1000)
    db.commit()

    r = client.get(f"/buckets/{savings.id}")
    assert r.status_code == 200
    assert "Savings goal" in r.text


def test_editing_a_bucket_saves_trip_dates(client, db, authed, trip):
    r = client.post(f"/buckets/{trip.id}/edit", data={
        "name": "Florence 2026", "type": "trip",
        "start_date": "2026-09-01", "end_date": "2026-09-09",
    }, headers=authed.headers)
    assert r.status_code == 302

    db.expire_all()
    b = db.get(Bucket, trip.id)
    assert b.start_date == date(2026, 9, 1)
    assert b.end_date == date(2026, 9, 9)


def test_editing_a_bucket_saves_goal(client, db, authed, savings):
    r = client.post(f"/buckets/{savings.id}/edit", data={
        "name": "House deposit", "type": "savings",
        "goal_amount": "25000", "end_date": "2027-01-01",
    }, headers=authed.headers)
    assert r.status_code == 302

    db.expire_all()
    b = db.get(Bucket, savings.id)
    assert float(b.goal_amount) == 25000.0
    assert b.end_date == date(2027, 1, 1)


def test_invalid_date_is_rejected(client, authed, trip):
    r = client.post(f"/buckets/{trip.id}/edit", data={
        "name": "Trip", "type": "trip", "start_date": "not-a-date",
    }, headers=authed.headers)
    assert r.status_code == 400


def test_trip_end_date_survives_a_save(client, db, authed, trip):
    """Regression: two inputs named end_date meant the hidden savings field
    (empty) overwrote the trip value, because FastAPI takes the last duplicate
    and x-show does not stop a field submitting."""
    r = client.post(f"/buckets/{trip.id}/edit", data={
        "name": "Florence 2026", "type": "trip",
        "start_date": "2026-08-07", "end_date": "2026-08-15",
    }, headers=authed.headers)
    assert r.status_code == 302

    db.expire_all()
    b = db.get(Bucket, trip.id)
    assert b.start_date == date(2026, 8, 7)
    assert b.end_date == date(2026, 8, 15), "trip end date was not saved"


def test_trip_reports_days_and_nights(db, trip):
    trip.start_date = date(2026, 8, 7)
    trip.end_date = date(2026, 8, 15)
    db.commit()

    s = get_trip_summary(db, trip)
    assert s["days"] == 9      # inclusive
    assert s["nights"] == 8


def test_single_day_trip(db, trip):
    trip.start_date = trip.end_date = date(2026, 8, 7)
    db.commit()
    s = get_trip_summary(db, trip)
    assert s["days"] == 1
    assert s["nights"] == 0
