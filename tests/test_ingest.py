"""POST /api/v1/ingest/apple-pay — the iOS Shortcut endpoint (Phase 5)."""
from datetime import date
from decimal import Decimal

import pytest

from app.category_rules import learn_rule
from app.config import settings
from app.models import (
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    HouseholdMember,
    Notification,
    NotificationType,
    PaymentMethod,
    Transaction,
)
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member

URL = "/api/v1/ingest/apple-pay"


@pytest.fixture()
def ingest(db, make_household):
    """A household with a day2day bucket, a Groceries rule and a token."""
    from types import SimpleNamespace

    from app.services import issue_personal_token

    hh = make_household()
    bucket = db.get(Bucket, hh.bucket_id)
    bucket.type = BucketType.day2day
    cat = Category(household_id=hh.household_id, name="Groceries", icon="🛒")
    db.add(cat)
    db.flush()
    learn_rule(db, hh.household_id, "Sklavenitis", cat.id, created_by=hh.user_id)
    record, raw = issue_personal_token(db, user_id=hh.user_id,
                                       household_id=hh.household_id, name="iPhone")
    db.commit()
    return SimpleNamespace(hh=hh, token=record, raw=raw, category=cat,
                           headers={"Authorization": f"Bearer {raw}"})


def _post(client, ingest, **body):
    body.setdefault("merchant", "Sklavenitis")
    body.setdefault("amount", "12,50")
    return client.post(URL, json=body, headers=ingest.headers)


def test_happy_path_creates_apple_pay_expense(client, db, ingest):
    r = _post(client, ingest, card="Visa ••1234")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount"] == 12.5
    assert body["category"] == "Groceries"
    assert body["bucket"] == db.get(Bucket, ingest.hh.bucket_id).name
    assert "duplicate" not in body

    t = db.get(Transaction, body["id"])
    assert t.amount == Decimal("12.5")
    assert t.currency == "EUR"
    assert t.payment_method == PaymentMethod.apple_pay.value
    assert t.merchant == "Sklavenitis"
    assert t.paid_by == ingest.hh.user_id
    assert t.bucket_id == ingest.hh.bucket_id
    assert t.category_id == ingest.category.id
    assert t.notes == "Apple Pay · Visa ••1234"
    assert t.client_id and len(t.client_id) == 32


def test_numeric_amount_and_unknown_merchant(client, db, ingest):
    r = _post(client, ingest, merchant="Corner Kiosk", amount=3.2)
    assert r.status_code == 201, r.text
    t = db.get(Transaction, r.json()["id"])
    assert t.amount == Decimal("3.2")
    assert r.json()["category"] is None
    assert t.notes is None


def test_extra_notes_are_kept(client, db, ingest):
    r = _post(client, ingest, card="Visa", notes="lunch")
    t = db.get(Transaction, r.json()["id"])
    assert t.notes == "Apple Pay · Visa · lunch"


def test_currency_defaults_to_household_and_can_be_overridden(client, db, ingest):
    from app.models import Household

    db.get(Household, ingest.hh.household_id).default_currency = "GBP"
    db.commit()
    t = db.get(Transaction, _post(client, ingest).json()["id"])
    assert t.currency == "GBP"
    r = _post(client, ingest, merchant="Shop", currency="USD")
    assert db.get(Transaction, r.json()["id"]).currency == "USD"


def test_occurred_at_sets_household_local_date(client, db, ingest, monkeypatch):
    monkeypatch.setattr(settings, "app_timezone", "Europe/Athens")
    r = _post(client, ingest, occurred_at="2026-09-30T22:30:00Z")
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).transaction_date == date(2026, 10, 1)


def test_bad_amount_and_missing_merchant_are_rejected(client, db, ingest):
    assert _post(client, ingest, amount="abc").status_code == 400
    assert _post(client, ingest, amount="-3").status_code == 400
    assert client.post(URL, json={"amount": "1"}, headers=ingest.headers).status_code == 422
    assert _post(client, ingest, merchant="   ").status_code == 422
    assert db.query(Transaction).count() == 0


def test_default_bucket_is_used(client, db, ingest):
    trip = Bucket(household_id=ingest.hh.household_id, name="Trip", type=BucketType.trip)
    db.add(trip)
    db.flush()
    ingest.token.default_bucket_id = trip.id
    db.commit()
    r = _post(client, ingest)
    assert r.json()["bucket"] == "Trip"
    assert db.get(Transaction, r.json()["id"]).bucket_id == trip.id


def test_archived_default_bucket_falls_back_to_day2day(client, db, ingest):
    trip = Bucket(household_id=ingest.hh.household_id, name="Trip", type=BucketType.trip,
                  status=BucketStatus.archived)
    db.add(trip)
    db.flush()
    ingest.token.default_bucket_id = trip.id
    db.commit()
    r = _post(client, ingest)
    assert r.status_code == 201
    assert db.get(Transaction, r.json()["id"]).bucket_id == ingest.hh.bucket_id


def test_missing_bucket_is_422(client, db, ingest):
    db.get(Bucket, ingest.hh.bucket_id).type = BucketType.custom
    db.commit()
    r = _post(client, ingest)
    assert r.status_code == 422
    assert db.query(Transaction).count() == 0


def test_notification_created_once_per_transaction(client, db, ingest):
    r = _post(client, ingest)
    notes = db.query(Notification).filter_by(type=NotificationType.ingest_created).all()
    assert len(notes) == 1
    n = notes[0]
    assert n.title == "Apple Pay: €12.50 at Sklavenitis → Groceries"
    assert n.user_id == ingest.hh.user_id
    assert n.dedupe_key == f"ingest:{r.json()['id']}"
    assert r.json()["id"] in (n.link or "")


def test_notification_without_category(client, db, ingest):
    _post(client, ingest, merchant="Corner Kiosk", amount="3")
    n = db.query(Notification).filter_by(type=NotificationType.ingest_created).one()
    assert n.title == "Apple Pay: €3.00 at Corner Kiosk"


# ---------------------------------------------------------------- auth


def test_missing_or_bad_token_is_401(client, db, ingest):
    body = {"merchant": "X", "amount": "1"}
    assert client.post(URL, json=body).status_code == 401
    bad = {"Authorization": "Bearer pat_" + "A" * 32}
    assert client.post(URL, json=body, headers=bad).status_code == 401
    assert db.query(Transaction).count() == 0


def test_jwt_is_rejected(client, db, api):  # noqa: F811
    headers, _ = api
    r = client.post(URL, json={"merchant": "X", "amount": "1"}, headers=headers)
    assert r.status_code == 401
    assert db.query(Transaction).count() == 0


def test_revoked_token_is_401(client, db, ingest):
    from app.services import revoke_personal_token

    assert _post(client, ingest).status_code == 201
    revoke_personal_token(db, token_id=ingest.token.id, user_id=ingest.hh.user_id,
                          household_id=ingest.hh.household_id)
    db.commit()
    assert _post(client, ingest, merchant="Other").status_code == 401


def test_removed_member_token_is_401(client, db, ingest):
    from app.services import issue_personal_token

    bob = _add_member(db, ingest.hh.household_id, "bob")
    db.commit()
    _, raw = issue_personal_token(db, user_id=bob.id, household_id=ingest.hh.household_id,
                                  name="Bob")
    db.commit()
    headers = {"Authorization": f"Bearer {raw}"}
    r = client.post(URL, json={"merchant": "A", "amount": "1"}, headers=headers)
    assert r.status_code == 201
    assert db.get(Transaction, r.json()["id"]).paid_by == bob.id

    db.query(HouseholdMember).filter_by(user_id=bob.id).delete()
    db.commit()
    r = client.post(URL, json={"merchant": "B", "amount": "1"}, headers=headers)
    assert r.status_code == 401


def test_rate_limit_is_per_token(client, db, ingest):
    from app.services import issue_personal_token

    for i in range(60):
        r = _post(client, ingest, merchant=f"Shop {i}", amount="1")
        assert r.status_code == 201, (i, r.text)
    r = _post(client, ingest, merchant="Shop 61", amount="1")
    assert r.status_code == 429
    assert db.query(Transaction).count() == 60

    # Another token (same client IP) has its own budget.
    _, raw = issue_personal_token(db, user_id=ingest.hh.user_id,
                                  household_id=ingest.hh.household_id, name="iPad")
    db.commit()
    r = client.post(URL, json={"merchant": "Other", "amount": "1"},
                    headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 201
