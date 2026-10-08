"""Rows main's diagnostics wrote before the summary existed hold the raw body.
The readers must never show them (polish review I-1)."""

import json

import pytest

from app.models import Bucket, BucketType, IngestAttempt, PersonalApiToken
from app.services import issue_personal_token
from app.services.ingest import LEGACY_DETAIL, LEGACY_PAYLOAD_LINE, is_summary, summary_lines
from tests.test_api import api  # noqa: F401  (fixture)

SECRET = "pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
CARD = "4111 1111 1111 1111"


def _legacy(db, token, status, **kw):
    row = IngestAttempt(
        household_id=token.household_id,
        token_id=token.id,
        token_prefix=token.prefix,
        status=status,
        detail=kw.pop("detail", f"RuntimeError: boom {SECRET} {CARD}"),
        payload=kw.pop("payload", json.dumps({"merchant": "Shop", "notes": SECRET, "card": CARD})),
        content_type=kw.pop("content_type", f"text/plain; {SECRET}"),
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize(
    "payload,expected",
    [
        ('{"merchant":{"type":"text","value":"Lidl"},"unknown_keys":0}', True),
        ('{"category":{"type":"missing"},"bucket":{"type":"null"},"unknown_keys":1}', True),
        ("not a JSON object (13 bytes, application/json)", True),
        ("not a JSON object (unknown size, no content type)", True),
        ('{"merchant":"Lidl","amount":"12"}', False),
        (f'{{"merchant":"{SECRET}"}}', False),
        ("merchant=Lidl&card=" + CARD, False),
        (f"not a JSON object (13 bytes, {SECRET} \n x)", False),
        ('{"merchant":{"type":"text","value":"x","extra":"y"}}', False),
        ('{"other":{"type":"text"}}', False),
        ('{"merchant":{"type":"bogus"}}', False),
        ("[1]", False),
        ("", False),
    ],
)
def test_summary_shape(payload, expected):
    assert is_summary(payload) is expected


def test_page_lines_for_a_legacy_payload():
    assert summary_lines('{"merchant":"x"}') == [LEGACY_PAYLOAD_LINE]
    assert LEGACY_PAYLOAD_LINE == "[older entry: details not kept]"


@pytest.mark.parametrize("status", [200, 201, 401, 409, 429, 400, 422, 500])
def test_api_hides_legacy_rows(client, db, api, status):  # noqa: F811
    headers, hh = api
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    token, _ = issue_personal_token(db, user_id=hh.user_id, household_id=hh.household_id, name="p")
    db.commit()
    _legacy(
        db, token, status, detail="duplicate" if status in (200, 201, 401, 409, 429) else SECRET
    )
    r = client.get("/api/v1/ingest/attempts", headers=headers)
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert item["payload"] is None
    assert SECRET not in r.text and CARD not in r.text and "boom" not in r.text
    if status in (200, 201, 401, 409, 429):
        assert item["detail"] == "duplicate"
    else:
        assert item["detail"] == LEGACY_DETAIL


def test_page_hides_legacy_rows(client, db, authed):
    db.get(Bucket, authed.bucket_id).type = BucketType.day2day
    token, _ = issue_personal_token(
        db, user_id=authed.user_id, household_id=authed.household_id, name="p"
    )
    db.commit()
    _legacy(db, token, 500)
    _legacy(db, token, 422, detail=f"{SECRET} {CARD}")
    text = client.get("/settings/automations").text
    assert SECRET not in text and CARD not in text and "boom" not in text
    assert "[older entry: details not kept]" in text
    assert "[older entry]" in text


def test_new_summary_rows_are_shown_as_before(client, db, api):  # noqa: F811
    headers, hh = api
    token, _ = issue_personal_token(db, user_id=hh.user_id, household_id=hh.household_id, name="p")
    db.commit()
    db.add(
        IngestAttempt(
            household_id=hh.household_id,
            token_id=token.id,
            token_prefix=token.prefix,
            status=422,
            detail="Amount must be a number",
            payload='{"merchant":{"type":"text","value":"Lidl"},"unknown_keys":0}',
        )
    )
    db.commit()
    (item,) = client.get("/api/v1/ingest/attempts", headers=headers).json()["items"]
    assert item["payload"].startswith('{"merchant"') and item["detail"] == "Amount must be a number"
    assert PersonalApiToken  # keep the import honest
