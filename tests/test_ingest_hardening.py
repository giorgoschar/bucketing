"""Hardening of the ingest diagnostics (polish R2): token redaction, log
injection, per-user scope, and a bounded amount parser."""

import logging
import time
from types import SimpleNamespace

import pytest

from app.models import Bucket, BucketType, IngestAttempt
from app.services import issue_personal_token, recent_ingest_attempts, record_ingest_attempt
from tests.test_household_settlement import _add_member

URL = "/api/v1/ingest/apple-pay"


@pytest.fixture()
def ingest(db, make_household):
    hh = make_household()
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    record, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    return SimpleNamespace(hh=hh, token=record, raw=raw, headers={"Authorization": f"Bearer {raw}"})


def _logged(caplog):
    return [r for r in caplog.records if r.getMessage().startswith("ingest:")]


# ------------------------------------------------------------------ redaction


def test_token_pasted_in_body_is_never_stored_or_logged(db, client, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.post(
        URL,
        json={"merchant": "Shop", "amount": "1", "notes": f"key {ingest.raw}"},
        headers=ingest.headers,
    )
    assert r.status_code == 201, r.text
    # And a rejected one (bad amount) with the token inside a field.
    client.post(URL, json={"merchant": ingest.raw, "amount": "zzz"}, headers=ingest.headers)
    rows = db.query(IngestAttempt).all()
    assert len(rows) == 2
    for row in rows:
        assert ingest.raw not in (row.payload or "")
        assert ingest.raw not in (row.detail or "")
    assert any("pat_…redacted" in (row.payload or "") for row in rows)
    for rec in caplog.records:
        assert ingest.raw not in rec.getMessage()


def test_authorization_and_token_fields_are_redacted(db, client, ingest):
    client.post(
        URL,
        json={
            "merchant": "Shop",
            "amount": "1",
            "authorization": "Bearer something-secret-123",
            "Token": "another-secret-456",
        },
        headers=ingest.headers,
    )
    payload = db.query(IngestAttempt).one().payload
    assert "something-secret-123" not in payload
    assert "another-secret-456" not in payload
    assert "Shop" in payload


def test_form_and_truncated_json_secrets_are_redacted(db, ingest):
    record_ingest_attempt(
        status=422, payload='{"amount": 1, "token": "abcdef-secret', token=ingest.token, db=db
    )
    record_ingest_attempt(status=422, payload="token=abcdef-secret&x=1", token=ingest.token, db=db)
    for row in db.query(IngestAttempt).all():
        assert "abcdef-secret" not in row.payload


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


# ------------------------------------------------------------------ redaction bypasses


def _windows(raw, size=12):
    body = raw[len("pat_") :]
    return [body[i : i + size] for i in range(len(body) - size + 1)]


def _assert_clean(db, caplog, raw):
    texts = []
    for row in db.query(IngestAttempt).all():
        texts += [row.payload or "", row.detail or "", row.content_type or ""]
    texts += [rec.getMessage() for rec in caplog.records]
    for text in texts:
        assert raw not in text
        for w in _windows(raw):
            assert w not in text, (w, text[:200])


def _uni(s):
    return "".join(f"\\u{ord(c):04x}" for c in s)


def _pct(s):
    return "".join(f"%{ord(c):02X}" for c in s)


class _Weird:
    """jsonable_encoder cannot encode it, so the repr() fallback is used."""

    __slots__ = ("raw",)

    def __init__(self, raw):
        self.raw = raw

    def __iter__(self):
        raise TypeError

    def __repr__(self):
        return f"Weird({self.raw})"


def _cases(raw):
    half = len(raw) // 2
    return {
        "unicode escape": '{"notes": "' + _uni(raw) + '"}',
        "unicode escape of the prefix only": '{"notes": "' + _uni("pat_") + raw[4:] + '"}',
        "percent encoding": "merchant=x&notes=" + _pct(raw),
        "percent encoded prefix": "notes=pat%5F" + raw[4:],
        "form body": f"merchant=x&amount=1&notes={raw}",
        "form authorization": f"authorization=Bearer%20{raw}&amount=1",
        "non-json body": f"hello {raw} there\n<html>",
        "dict": {"a": {"b": [raw]}},
        "repr": _Weird(raw),
        "truncation boundary": "x" * 1990 + raw,
        "precap boundary": "x" * 19990 + raw,
        "duplicate keys": f'{{"token": "a1", "token": "{raw}", "Authorization": "Bearer {raw}"}}',
        "bearer casing": f'{{"h": "BeArEr   {raw}"}}',
        "whitespace in value": '{"authorization": "Bearer\\n  ' + raw + '"}',
        "split by whitespace": raw[:half] + "\n " + raw[half:],
        "split by json concat": '{"a": "' + raw[:half] + '", "b": "' + raw[half:] + '"}',
        "malformed json": '{"token": "' + raw,
    }


@pytest.mark.parametrize("case", list(_cases("pat_" + "A" * 32)))
def test_token_never_survives_any_serialisation(db, ingest, caplog, case):
    caplog.set_level(logging.DEBUG)
    payload = _cases(ingest.raw)[case]
    record_ingest_attempt(
        status=422,
        detail=f"bad input {ingest.raw}",
        payload=payload,
        content_type=f"text/plain; x={ingest.raw}",
        raw_token=ingest.raw,
        token=ingest.token,
        db=db,
    )
    _assert_clean(db, caplog, ingest.raw)


@pytest.mark.parametrize("case", ["unicode escape", "percent encoding", "form body", "dict"])
def test_token_in_a_real_request_never_survives(client, db, ingest, caplog, case):
    caplog.set_level(logging.DEBUG)
    payload = _cases(ingest.raw)[case]
    if isinstance(payload, dict):
        client.post(URL, json={"merchant": "x", "amount": "zz", **payload}, headers=ingest.headers)
    else:
        client.post(
            URL,
            content=payload,
            headers={**ingest.headers, "content-type": "application/octet-stream"},
        )
    assert db.query(IngestAttempt).count() == 1
    _assert_clean(db, caplog, ingest.raw)


def test_a_payload_that_still_holds_the_token_is_withheld(db, ingest):
    half = len(ingest.raw) // 2
    record_ingest_attempt(
        status=422,
        payload=ingest.raw[:half] + "\n " + ingest.raw[half:],
        raw_token=ingest.raw,
        token=ingest.token,
        db=db,
    )
    assert db.query(IngestAttempt).one().payload == "[payload withheld: it contained the token]"


def test_ordinary_payloads_are_kept_as_they_were(db, ingest):
    record_ingest_attempt(
        status=201,
        payload='{"merchant": "Café ΣΚΛΑΒΕΝΙΤΗΣ", "amount": "12,50"}',
        raw_token=ingest.raw,
        token=ingest.token,
        db=db,
    )
    assert db.query(IngestAttempt).one().payload == (
        '{"merchant": "Café ΣΚΛΑΒΕΝΙΤΗΣ", "amount": "12,50"}'
    )
