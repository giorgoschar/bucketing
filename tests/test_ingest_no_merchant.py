"""Polish R4: a real purchase is never lost to an empty or unreadable merchant."""

import pytest

from app.models import Bucket, BucketType, Category, IngestAttempt, Transaction
from app.services import issue_personal_token

URL = "/api/v1/ingest/apple-pay"
PLACEHOLDER = "Apple Pay purchase"
NOTE = "Merchant not received from the Shortcut"


@pytest.fixture()
def ingest(db, make_household):
    from types import SimpleNamespace

    hh = make_household()
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    db.add(Category(household_id=hh.household_id, name="Groceries", icon="x"))
    _, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    return SimpleNamespace(hh=hh, headers={"Authorization": f"Bearer {raw}"})


@pytest.mark.parametrize(
    "merchant",
    [None, "", "   ", {"total": 1}, [], {"name": ""}, True],
)
def test_missing_blank_or_unreadable_merchant_is_created(client, db, ingest, merchant):
    body = {"amount": "12,50", "card": "Visa ••1234"}
    if merchant is not None:
        body["merchant"] = merchant
    r = client.post(URL, json=body, headers=ingest.headers)
    assert r.status_code == 201, r.text
    txn = db.get(Transaction, r.json()["id"])
    assert txn.merchant == PLACEHOLDER
    assert txn.category_id is None
    assert txn.notes.startswith(NOTE)
    assert "Visa ••1234" in txn.notes
    assert float(txn.amount) == 12.5
    a = db.query(IngestAttempt).one()
    assert a.status == 201
    assert a.detail == "created without a merchant — the Shortcut sent no merchant"
    assert a.transaction_id == txn.id


def test_without_a_merchant_the_notes_are_just_the_marker(client, db, ingest):
    r = client.post(URL, json={"amount": "3"}, headers=ingest.headers)
    assert db.get(Transaction, r.json()["id"]).notes == NOTE


def test_replay_is_deduped_by_amount_and_minute(client, db, ingest):
    at = "2026-10-01T12:34:20Z"
    first = client.post(URL, json={"amount": "9", "occurred_at": at}, headers=ingest.headers)
    again = client.post(
        URL, json={"amount": "9,00", "occurred_at": "2026-10-01T12:34:50Z"}, headers=ingest.headers
    )
    other = client.post(
        URL, json={"amount": "9", "occurred_at": "2026-10-01T12:35:00Z"}, headers=ingest.headers
    )
    assert (first.status_code, again.status_code, other.status_code) == (201, 200, 201)
    assert again.json()["id"] == first.json()["id"] != other.json()["id"]
    assert db.query(Transaction).count() == 2


@pytest.mark.parametrize("amount", [None, "", "abc", {"x": 1, "y": 2}])
def test_unreadable_or_missing_amount_is_still_400(client, db, ingest, amount):
    body = {} if amount is None else {"amount": amount}
    r = client.post(URL, json=body, headers=ingest.headers)
    assert r.status_code == 400, r.text
    assert db.query(Transaction).count() == 0
    assert db.query(IngestAttempt).one().status == 400


def test_a_real_merchant_is_unchanged(client, db, ingest):
    r = client.post(URL, json={"merchant": "Lidl", "amount": "5"}, headers=ingest.headers)
    txn = db.get(Transaction, r.json()["id"])
    assert txn.merchant == "Lidl"
    assert NOTE not in (txn.notes or "")
    assert db.query(IngestAttempt).one().detail == "created"


def test_a_nul_character_in_a_text_field_does_not_lose_the_purchase(client, db, ingest):
    r = client.post(
        URL,
        json={"merchant": "a\u0000b", "amount": "1", "notes": "n\u0000"},
        headers=ingest.headers,
    )
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).merchant == "ab"
