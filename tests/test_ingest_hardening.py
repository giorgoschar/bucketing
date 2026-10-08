"""Hardening of the ingest diagnostics (polish R2): log injection, per-user
scope, and a bounded amount parser. What an attempt keeps of a body is in
tests/test_ingest_summary.py."""

import logging
import time
from types import SimpleNamespace

import pytest

from app.models import Bucket, BucketType, IngestAttempt
from app.services import issue_personal_token, recent_ingest_attempts, record_ingest_attempt
from tests.test_household_settlement import _add_member

URL = "/api/v1/ingest/apple-pay"


@pytest.fixture()
def ingest(app, db, make_household):
    hh = make_household()
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    record, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    return SimpleNamespace(hh=hh, token=record, raw=raw, headers={"Authorization": f"Bearer {raw}"})


def _logged(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("ingest:")]


# ------------------------------------------------------------------ log injection


def test_payload_cannot_forge_a_log_line(db, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    record_ingest_attempt(
        status=422,
        detail="bad\r\nforged detail",
        payload='{"merchant": "x\\n2026 INFO forged"}\n2026 INFO forged\x1b[31m',
        content_type="text/plain\nX: y",
        token=ingest.token,
        db=db,
    )
    lines = _logged(caplog)
    assert len(lines) == 1
    msg = lines[0].getMessage()
    for ch in "\r\n\x1b\x00":
        assert ch not in msg
    assert "forged" in msg  # escaped, still readable


def test_forged_newline_through_the_endpoint_is_one_record(client, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    client.post(
        URL,
        content='{"merchant":"a","amount":"zz\n2026 INFO forged"}',
        headers={**ingest.headers, "content-type": "application/json"},
    )
    lines = _logged(caplog)
    assert len(lines) == 1
    assert "\n" not in lines[0].getMessage()


# ------------------------------------------------------------------ scope


def test_member_b_does_not_see_member_a_attempts(db, client, ingest):
    b = _add_member(db, ingest.hh.household_id, "member_b")
    _, raw_b = issue_personal_token(
        db, user_id=b.id, household_id=ingest.hh.household_id, name="B phone"
    )
    db.commit()
    client.post(URL, json={"merchant": "A shop", "amount": "1"}, headers=ingest.headers)
    client.post(
        URL,
        json={"merchant": "B shop", "amount": "2"},
        headers={"Authorization": f"Bearer {raw_b}"},
    )
    a_rows = recent_ingest_attempts(db, ingest.hh.household_id, ingest.hh.user_id)
    b_rows = recent_ingest_attempts(db, ingest.hh.household_id, b.id)
    assert len(a_rows) == 1 and "A shop" in a_rows[0].payload
    assert len(b_rows) == 1 and "B shop" in b_rows[0].payload


def test_unattributed_attempts_are_shown_to_nobody(db, ingest):
    record_ingest_attempt(
        status=401, detail="no such token", raw_token=ingest.raw + "Z" * 10, db=db
    )
    assert db.query(IngestAttempt).filter(IngestAttempt.household_id.is_(None)).count() == 1
    assert recent_ingest_attempts(db, ingest.hh.household_id, ingest.hh.user_id) == []


def test_automations_page_hides_other_members_attempts(client, db, authed):
    db.get(Bucket, authed.bucket_id).type = BucketType.day2day
    other = _add_member(db, authed.household_id, "member_c")
    _, raw_c = issue_personal_token(
        db, user_id=other.id, household_id=authed.household_id, name="C"
    )
    db.commit()
    client.post(
        URL,
        json={"merchant": "OtherMemberShop", "amount": "nope"},
        headers={"Authorization": f"Bearer {raw_c}"},
    )
    assert "OtherMemberShop" not in client.get("/settings/automations").text


# ------------------------------------------------------------------ ReDoS / bounds


def test_overlong_amount_is_400(client, ingest):
    r = client.post(URL, json={"merchant": "Shop", "amount": "1" * 65}, headers=ingest.headers)
    assert r.status_code == 400
    assert "too long" in r.json()["detail"]


def test_amount_of_64_chars_still_parses(client, ingest):
    r = client.post(
        URL, json={"merchant": "Shop", "amount": "0" * 60 + "1,50"}, headers=ingest.headers
    )
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("filler", ["1.", "1,", " ", "€", "1.000" * 10])
def test_amount_parsing_is_linear_and_bounded(client, ingest, filler):
    from fastapi import HTTPException

    from app.services.ingest import coerce_amount

    big = (filler * (200_000 // len(filler) + 1))[:200_000]
    t = time.perf_counter()
    with pytest.raises(HTTPException) as exc:
        coerce_amount(big)
    assert exc.value.status_code == 400
    assert time.perf_counter() - t < 0.5
    t = time.perf_counter()
    r = client.post(URL, json={"merchant": "Shop", "amount": big}, headers=ingest.headers)
    assert r.status_code == 400
    assert time.perf_counter() - t < 3
