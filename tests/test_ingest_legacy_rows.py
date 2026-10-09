"""Rows main's diagnostics wrote before the summary existed hold the raw body.
They carry no summary_version, and the readers never show them (review I-1).
The marker is a column the caller cannot influence; nothing sniffs the shape."""

import json

import pytest

from app.models import Bucket, BucketType, IngestAttempt
from app.services import issue_personal_token
from app.services.ingest import LEGACY_DETAIL, LEGACY_PAYLOAD_LINE, summary_lines
from tests.test_api import api  # noqa: F401  (fixture)

SECRET = "pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
CARD = "4111 1111 1111 1111"
# Crafted to look exactly like what the new code writes.
LOOKALIKE = json.dumps(
    {
        "merchant": {"type": "text", "value": f"{SECRET} {CARD}"},
        "unknown_keys": 0,
    }
)
SAFE = ('{"merchant":{"type":"text","value":"Lidl"},"unknown_keys":0}', "Lidl")


def _row(db, token, status, *, version=None, **kw):
    row = IngestAttempt(
        household_id=token.household_id,
        token_id=token.id,
        token_prefix=token.prefix,
        status=status,
        detail=kw.pop("detail", f"RuntimeError: boom {SECRET} {CARD}"),
        payload=kw.pop("payload", json.dumps({"merchant": "Shop", "notes": SECRET, "card": CARD})),
        content_type=kw.pop("content_type", f"text/plain; {SECRET}"),
        summary_version=version,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def mine(db, api):  # noqa: F811
    headers, hh = api
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    token, _ = issue_personal_token(db, user_id=hh.user_id, household_id=hh.household_id, name="p")
    db.commit()
    return headers, token


@pytest.mark.parametrize("status", [200, 201, 401, 409, 429, 400, 422, 500])
@pytest.mark.parametrize("payload", [None, "raw=1", LOOKALIKE, "not a JSON object (3 bytes, x)"])
def test_api_never_returns_the_payload_of_a_null_version_row(client, db, mine, status, payload):
    headers, token = mine
    fixed = status in (200, 201, 401, 409, 429)
    _row(db, token, status, payload=payload, detail="duplicate" if fixed else SECRET)
    (item,) = client.get("/api/v1/ingest/attempts", headers=headers).json()["items"]
    assert item["payload"] is None
    assert item["detail"] == ("duplicate" if fixed else LEGACY_DETAIL)
    assert SECRET not in json.dumps(item) and CARD not in json.dumps(item)


def test_a_lookalike_summary_without_the_marker_is_not_shown(client, db, mine):
    headers, token = mine
    _row(db, token, 422, payload=LOOKALIKE, detail="Amount must be a number")
    text = client.get("/api/v1/ingest/attempts", headers=headers).text
    assert SECRET not in text and CARD not in text


def test_a_version_1_row_is_shown(client, db, mine):
    headers, token = mine
    _row(db, token, 422, version=1, payload=SAFE[0], detail="Amount must be a number")
    (item,) = client.get("/api/v1/ingest/attempts", headers=headers).json()["items"]
    assert item["payload"] == SAFE[0]
    assert item["detail"] == "Amount must be a number"


def test_a_version_1_row_with_an_unusual_status_keeps_its_detail(client, db, mine):
    headers, token = mine
    _row(db, token, 500, version=1, payload=None, detail="unexpected error (ValueError)")
    (item,) = client.get("/api/v1/ingest/attempts", headers=headers).json()["items"]
    assert item["detail"] == "unexpected error (ValueError)"


def test_page_hides_null_version_rows_and_shows_version_1(client, db, authed):
    db.get(Bucket, authed.bucket_id).type = BucketType.day2day
    token, _ = issue_personal_token(
        db, user_id=authed.user_id, household_id=authed.household_id, name="p"
    )
    db.commit()
    _row(db, token, 500)
    _row(db, token, 422, detail=f"{SECRET} {CARD}", payload=LOOKALIKE)
    _row(
        db,
        token,
        422,
        version=1,
        payload=SAFE[0],
        detail="Amount must be a number",
        content_type="application/json",
    )
    text = client.get("/settings/automations").text
    assert SECRET not in text and CARD not in text and "boom" not in text
    assert LEGACY_PAYLOAD_LINE in text and LEGACY_DETAIL in text
    assert "merchant: Lidl (text)" in text


def test_new_attempts_are_written_with_version_1(client, db, authed):
    db.get(Bucket, authed.bucket_id).type = BucketType.day2day
    _, raw = issue_personal_token(
        db, user_id=authed.user_id, household_id=authed.household_id, name="p"
    )
    db.commit()
    client.post(
        "/api/v1/ingest/apple-pay",
        json={"merchant": "Shop", "amount": "2"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    client.post("/api/v1/ingest/apple-pay", content="x", headers={"Authorization": f"Bearer {raw}"})
    db.expire_all()
    rows = db.query(IngestAttempt).all()
    assert len(rows) == 2 and {r.summary_version for r in rows} == {1}


def test_summary_lines_render_a_stored_summary():
    lines = summary_lines(
        '{"merchant":{"type":"text","value":"Lidl"},"amount":{"type":"missing"},"unknown_keys":2}'
    )
    assert lines == ["merchant: Lidl (text)", "amount: missing", "other keys: 2"]
    assert summary_lines("not a JSON object (3 bytes, x)") == ["not a JSON object (3 bytes, x)"]
    assert summary_lines(None) == []
