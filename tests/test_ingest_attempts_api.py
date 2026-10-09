"""GET /api/v1/ingest/attempts: the caller's own recent ingest attempts (polish R3)."""

import pyotp

from app.models import Bucket, BucketType
from app.services import issue_personal_token, record_ingest_attempt
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member

URL = "/api/v1/ingest/apple-pay"
ATTEMPTS = "/api/v1/ingest/attempts"


def _token(db, hh, user_id=None, name="iPhone"):
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    _, raw = issue_personal_token(
        db, user_id=user_id or hh.user_id, household_id=hh.household_id, name=name
    )
    db.commit()
    return {"Authorization": f"Bearer {raw}"}


def test_shape_and_outcomes(client, db, api):  # noqa: F811
    headers, hh = api
    ingest = _token(db, hh)
    at = "2026-10-01T12:34:00Z"
    created = client.post(
        URL, json={"merchant": "Shop", "amount": "3", "occurred_at": at}, headers=ingest
    )
    client.post(URL, json={"merchant": "Shop", "amount": "3", "occurred_at": at}, headers=ingest)
    client.post(URL, json={"merchant": "Shop", "amount": "nope"}, headers=ingest)

    r = client.get(ATTEMPTS, headers=headers)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert list(r.json()) == ["items"]
    assert [i["status"] for i in items] == [400, 200, 201]  # newest first
    assert [i["outcome"] for i in items] == ["rejected", "duplicate", "created"]
    newest, dup, first = items
    assert set(newest) == {
        "id",
        "created_at",
        "status",
        "outcome",
        "detail",
        "payload",
        "token_prefix",
        "transaction_id",
    }
    assert first["transaction_id"] == created.json()["id"] == dup["transaction_id"]
    assert newest["transaction_id"] is None
    assert "nope" in newest["payload"]
    assert newest["token_prefix"].startswith("pat_")
    assert "T" in newest["created_at"]


def test_requires_a_user_token_not_an_ingest_token(client, db, api):  # noqa: F811
    headers, hh = api
    ingest = _token(db, hh)
    assert client.get(ATTEMPTS).status_code == 401
    assert client.get(ATTEMPTS, headers=ingest).status_code == 401


def test_only_the_callers_own_attempts(client, db, api):  # noqa: F811
    headers, hh = api
    mine = _token(db, hh)
    b = _add_member(db, hh.household_id, "member_b")
    b.totp_secret = pyotp.random_base32()
    theirs = _token(db, hh, user_id=b.id, name="B")
    client.post(URL, json={"merchant": "MineShop", "amount": "1"}, headers=mine)
    client.post(URL, json={"merchant": "TheirShop", "amount": "2"}, headers=theirs)
    # Unattributed: recorded, but shown to nobody.
    record_ingest_attempt(status=401, detail="no such token", raw_token="pat_unknown1234", db=db)

    items = client.get(ATTEMPTS, headers=headers).json()["items"]
    assert len(items) == 1
    assert "MineShop" in items[0]["payload"]


def test_newest_fifty_only(client, db, api):  # noqa: F811
    headers, hh = api
    _token(db, hh)
    from app.models import PersonalApiToken

    token = db.query(PersonalApiToken).filter_by(user_id=hh.user_id).one()
    for i in range(55):
        record_ingest_attempt(status=201, detail=f"n{i}", token=token, db=db)
    items = client.get(ATTEMPTS, headers=headers).json()["items"]
    assert len(items) == 50
    assert items[0]["detail"] == "n54"
    assert items[-1]["detail"] == "n5"


def test_created_at_carries_a_utc_offset(client, db, api):  # noqa: F811
    headers, hh = api
    ingest = _token(db, hh)
    client.post(URL, json={"merchant": "Shop", "amount": "3"}, headers=ingest)
    item = client.get(ATTEMPTS, headers=headers).json()["items"][0]
    assert item["created_at"].endswith(("Z", "+00:00"))
