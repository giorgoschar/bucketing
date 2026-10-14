"""GET /api/v1/buckets/{id}/summary: the trip and savings cards of the bucket page."""

from datetime import date
from decimal import Decimal

from app.models import Bucket, BucketType, Transaction, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)


def _spend(db, hh, bucket, amount, when, **kw):
    db.add(
        Transaction(
            household_id=hh.household_id,
            bucket_id=bucket.id,
            amount=Decimal(str(amount)),
            currency="EUR",
            paid_by=hh.user_id,
            transaction_date=when,
            type=kw.get("type", TransactionType.expense),
        )
    )
    db.commit()


def test_event_bucket_gets_a_trip_summary(client, db, api):  # noqa: F811
    headers, hh = api
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
    _spend(db, hh, trip, 600, date(2026, 9, 29))
    _spend(db, hh, trip, 300, date(2026, 10, 2))
    r = client.get(f"/api/v1/buckets/{trip.id}/summary", headers=headers)
    assert r.status_code == 200, r.text
    t = r.json()["trip"]
    assert t["total"] == 900 and t["days"] == 7 and t["remaining"] == 100
    assert t["per_day"] == round(900 / 7, 2)
    assert t["status"] == "past"
    me = next(p for p in t["people"] if p["user_id"] == hh.user_id)
    assert me["share"] == 900 and me["paid"] == 900
    assert r.json()["savings"] is None


def test_plain_bucket_has_neither_card(client, api):  # noqa: F811
    headers, hh = api
    r = client.get(f"/api/v1/buckets/{hh.bucket_id}/summary", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"trip": None, "savings": None}


def test_savings_bucket_gets_progress(client, db, api):  # noqa: F811
    headers, hh = api
    s = Bucket(
        household_id=hh.household_id,
        name="Car",
        type=BucketType.savings,
        goal_amount=Decimal("1000"),
    )
    db.add(s)
    db.commit()
    _spend(db, hh, s, 250, date(2026, 10, 1), type=TransactionType.income)
    body = client.get(f"/api/v1/buckets/{s.id}/summary", headers=headers).json()
    assert body["trip"] is None
    assert body["savings"]["saved"] == 250 and body["savings"]["goal"] == 1000
    assert body["savings"]["pct"] == 25


def test_another_household_gets_404(client, db, api, make_household):  # noqa: F811
    headers, _ = api
    other = make_household(username="other")
    r = client.get(f"/api/v1/buckets/{other.bucket_id}/summary", headers=headers)
    assert r.status_code == 404
