"""What an ingest attempt keeps of a request (polish): a summary built from the
parsed body, never the body; and the attempt log can never change the payment."""

import json
import logging
from types import SimpleNamespace

import pytest

from app.models import Bucket, BucketType, IngestAttempt, Transaction
from app.services import issue_personal_token, record_ingest_attempt
from app.services.ingest import KNOWN_KEYS, summarise_payload

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


def _summary(body, **kw):
    return json.loads(summarise_payload(json.dumps(body), "application/json", **kw))


# ------------------------------------------------------------------ the summary


def test_each_key_type():
    s = _summary(
        {
            "merchant": "Lidl",
            "amount": 12.5,
            "currency": None,
            "card": {"name": "Visa", "idx": 3},
            "occurred_at": ["a", "b", "c"],
            "notes": True,
        }
    )
    assert s["merchant"] == {"type": "text", "value": "Lidl"}
    assert s["amount"] == {"type": "number", "value": "12.5"}
    assert s["currency"] == {"type": "null"}
    assert s["card"] == {"type": "record", "value": "keys: name, idx"}
    assert s["occurred_at"] == {"type": "list", "value": "3 items"}
    assert s["notes"] == {"type": "text", "value": "true"}
    assert s["exchange_rate"] == {"type": "missing"}
    assert s["unknown_keys"] == 0
    assert set(KNOWN_KEYS) <= set(s)


def test_unknown_keys_are_only_counted():
    s = _summary({"merchant": "x", "secret_note": "hunter2", "other": 1, "Merchant": "y"})
    assert s["unknown_keys"] == 3
    blob = json.dumps(s)
    assert "secret_note" not in blob and "hunter2" not in blob and "other" not in blob


def test_previews_are_short_and_free_of_control_characters():
    s = _summary({"merchant": "A" * 100 + "\n2026 INFO forged\x1b[0m\r"})
    value = s["merchant"]["value"]
    assert len(value) <= 40
    assert not any(ord(c) < 32 for c in value)
    s = _summary({"merchant": "Café\n\x00ΣΚΛΑΒΕΝΙΤΗΣ"})
    assert s["merchant"]["value"] == "CaféΣΚΛΑΒΕΝΙΤΗΣ"


def test_record_key_names_are_capped_and_filtered():
    s = _summary({"card": {f"k{i}" + "x" * 30 + "\n<b>": 1 for i in range(10)}})
    names = s["card"]["value"].removeprefix("keys: ").split(", ")
    assert len(names) == 6
    assert all(len(n) <= 20 and all(c.isalnum() or c in "_ -" for c in n) for n in names)


@pytest.mark.parametrize(
    "body,ct,expected",
    [
        (
            b"merchant=x&amount=1",
            "application/x-www-form-urlencoded",
            "19 bytes, application/x-www",
        ),
        (b"[1,2,3]", "application/json", "7 bytes, application/json"),
        (b"not json at all", None, "15 bytes, no content type"),
        (b'"a string"', "text/plain", "10 bytes, text/plain"),
    ],
)
def test_a_body_that_is_not_an_object_is_only_described(body, ct, expected):
    out = summarise_payload(body, ct)
    assert out.startswith("not a JSON object (") and expected in out
    assert "merchant" not in out and "string" not in out.split("(")[0]


# ------------------------------------------------------------------ no 8+ char piece of the token


def _pieces(raw, size=8):
    # The 12-character display prefix (pat_ + 8) is shown on purpose, on the
    # Settings page and in the log, so it is not part of the secret checked.
    rest = raw[12:]
    return [rest[i : i + size] for i in range(len(rest) - size + 1)]


def _assert_clean(db, caplog, raw):
    texts = []
    for row in db.query(IngestAttempt).all():
        texts += [row.payload or "", row.detail or "", row.content_type or ""]
    # The app's own records (the test client's httpx logs its URLs; the server's
    # access log is uvicorn's, outside the app).
    own = [r for r in caplog.records if r.name.startswith("app")]
    texts += [rec.getMessage() for rec in own]
    texts += [str(rec.args) for rec in own]
    assert texts
    for text in texts:
        for piece in _pieces(raw):
            assert piece not in text, (piece, text[:300])
        assert raw not in text


@pytest.mark.parametrize("field", list(KNOWN_KEYS) + ["unknown_field"])
@pytest.mark.parametrize("form", ["plain", "bearer", "encoded", "spaced"])
def test_a_token_pasted_into_any_field_is_never_kept(client, db, ingest, caplog, field, form):
    caplog.set_level(logging.DEBUG)
    raw = ingest.raw
    value = {
        "plain": raw,
        "bearer": f"Bearer {raw}",
        "encoded": "%" + "%".join(f"{ord(c):02X}" for c in raw),
        "spaced": " ".join(raw),
    }[form]
    body = {"merchant": "Shop", "amount": "1"}
    body[field] = value
    client.post(URL, json=body, headers=ingest.headers)
    _assert_clean(db, caplog, raw)


@pytest.mark.parametrize(
    "content",
    [
        "token pasted: {raw}",
        "merchant={raw}&amount=1",
        '{{"merchant": "{raw}"',  # broken JSON
        '["{raw}"]',
        '"{raw}"',
    ],
)
def test_a_token_pasted_into_a_non_json_body_is_never_kept(client, db, ingest, caplog, content):
    caplog.set_level(logging.DEBUG)
    client.post(
        URL,
        content=content.replace("{raw}", ingest.raw),
        headers={**ingest.headers, "content-type": "text/plain"},
    )
    _assert_clean(db, caplog, ingest.raw)


def test_a_token_in_the_content_type_or_the_detail_is_never_kept(db, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    record_ingest_attempt(
        status=422,
        detail=f"bad {ingest.raw}",
        payload=b"x",
        content_type=f"text/plain; x={ingest.raw}",
        raw_token=ingest.raw,
        token=ingest.token,
    )
    record_ingest_attempt(
        status=422,
        detail="a" + ingest.raw[6:30] + "b",
        payload={"merchant": "x"},
        raw_token=ingest.raw,
    )
    _assert_clean(db, caplog, ingest.raw)


def test_a_token_in_the_classify_body_and_path_is_never_kept(client, db, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    client.post(
        f"{URL}/{ingest.raw}/classify",
        json={"category": ingest.raw, "bucket": ingest.raw},
        headers=ingest.headers,
    )
    _assert_clean(db, caplog, ingest.raw)


def test_error_details_that_echo_input_are_fixed_text(client, db, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    r = client.post(
        URL,
        json={"merchant": "x", "amount": {ingest.raw: 1, "b": 2}},
        headers=ingest.headers,
    )
    assert r.status_code == 400
    _assert_clean(db, caplog, ingest.raw)


def test_debug_level_does_not_bring_back_the_raw_body(client, db, ingest, caplog):
    caplog.set_level(logging.DEBUG)
    client.post(
        URL, json={"merchant": "DistinctiveMerchantName", "amount": "zz"}, headers=ingest.headers
    )
    lines = [r.getMessage() for r in caplog.records if "ingest:" in r.getMessage()]
    assert lines and all('{"merchant": "Distinct' not in line for line in lines)
    assert "DistinctiveMerchantName"[:30] in "".join(lines)  # the 40-char preview, as a summary


# ------------------------------------------------------------------ the log never changes the payment


def test_a_failing_attempt_log_does_not_change_the_payment(client, db, ingest, monkeypatch, caplog):
    import app.services.ingest as mod

    def boom(**kwargs):
        raise RuntimeError("database exploded with pat_secret in it")

    monkeypatch.setattr(mod, "_store_attempt", boom)
    r = client.post(URL, json={"merchant": "Shop", "amount": "3"}, headers=ingest.headers)
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]) is not None
    assert db.query(IngestAttempt).count() == 0
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [e.getMessage() for e in errors] == ["ingest: could not record an attempt"]
    assert "exploded" not in caplog.text


def test_a_rejected_request_leaves_no_partial_rows(client, db, ingest):
    r = client.post(URL, json={"merchant": "Shop", "amount": "nope"}, headers=ingest.headers)
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0
    rows = db.query(IngestAttempt).all()
    assert [a.status for a in rows] == [400]


def test_a_crash_is_rolled_back_and_logged_with_fixed_text(client, db, ingest, monkeypatch):
    import app.api.ingest as api_mod

    def crash(*a, **k):
        raise RuntimeError("secret detail pat_leak")

    monkeypatch.setattr(api_mod, "ingest_apple_pay", crash)
    with pytest.raises(RuntimeError):
        client.post(URL, json={"merchant": "Shop", "amount": "3"}, headers=ingest.headers)
    assert db.query(Transaction).count() == 0
    row = db.query(IngestAttempt).one()
    assert row.status == 500 and row.detail == "unexpected error (RuntimeError)"


def test_a_successful_request_is_committed_exactly_once(client, db, ingest):
    r = client.post(URL, json={"merchant": "Shop", "amount": "3"}, headers=ingest.headers)
    assert r.status_code == 201
    assert db.query(Transaction).count() == 1
    rows = db.query(IngestAttempt).all()
    assert [(a.status, a.transaction_id) for a in rows] == [(201, r.json()["id"])]


def test_recording_does_not_touch_the_callers_session(db, ingest):
    ingest.token.name = "renamed but not committed"
    record_ingest_attempt(status=401, detail="x", token=ingest.token)
    assert ingest.token.name == "renamed but not committed"  # still pending, not flushed or lost
    db.rollback()
    db.refresh(ingest.token)
    assert ingest.token.name == "iPhone"


def test_hostile_bodies_and_headers_do_not_break_or_stall_the_log(client, db, ingest):
    import time

    t = time.perf_counter()
    r = client.post(
        URL,
        content="[" * 100_000,
        headers={**ingest.headers, "content-type": "application/json"},
    )
    assert r.status_code == 422
    r = client.post(
        URL,
        json={"merchant": "x", "amount": "1"},
        headers={"Authorization": "Bearer pat_" + "z" * 8000},
    )
    assert r.status_code == 401
    assert time.perf_counter() - t < 5
    assert db.query(IngestAttempt).count() == 2
