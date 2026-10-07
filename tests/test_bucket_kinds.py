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


def test_old_bucket_form_creating_a_trip_gets_kind_event(client, db, authed):
    r = client.post(
        "/buckets",
        data={"name": "Rome", "type": "trip", "start_date": "2027-01-01", "end_date": "2027-01-05"},
        headers=authed.headers,
    )
    assert r.status_code in (200, 302)
    b = db.query(Bucket).filter_by(name="Rome").one()
    assert b.kind == "event"
    r = client.post(
        f"/buckets/{b.id}/edit", data={"name": "Rome", "type": "custom"}, headers=authed.headers
    )
    db.expire_all()
    assert db.get(Bucket, b.id).kind == "monthly"


def test_old_api_type_trip_gets_kind_event(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/buckets", headers=headers, json={"name": "Old", "type": "trip"})
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "event"


def test_bucket_with_active_bills_cannot_become_an_event(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, hh.bucket_id)
    r = client.put(
        f"/api/v1/buckets/{hh.bucket_id}",
        headers=headers,
        json={"name": "Main", "kind": "event"},
    )
    assert r.status_code == 409, r.text
    assert "recurring bills" in r.json()["detail"]
    assert db.get(Bucket, hh.bucket_id).kind == "monthly"
    bill.is_active = False
    db.commit()
    r = client.put(
        f"/api/v1/buckets/{hh.bucket_id}",
        headers=headers,
        json={"name": "Main", "kind": "event"},
    )
    assert r.status_code == 200, r.text
