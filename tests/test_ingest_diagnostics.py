"""Diagnostics around POST /api/v1/ingest/apple-pay.

Every attempt — created, duplicate, or refused — is recorded in
``ingest_attempts`` no matter which layer rejects it: the endpoint itself
(400/409/422/500), payload validation before the endpoint runs (422), the
auth dependency (401), and the rate limiter (429). The rows are shown on
Settings → Automations and logged as ``ingest:`` lines. These tests pin down
that recording, the payload coercion that feeds it, the visibility rules of
the automations page, and the pruning caps — a broken Shortcut should be
diagnosable instead of guessed at from a bare "422".
"""

import logging

import pytest

from app.core.config import settings
from app.models import (
    Bucket,
    BucketType,
    Category,
    IngestAttempt,
    Transaction,
)
from app.services import (
    issue_personal_token,
    recent_ingest_attempts,
    record_ingest_attempt,
    revoke_personal_token,
)

URL = "/api/v1/ingest/apple-pay"


@pytest.fixture()
def ingest(db, make_household):
    """A household with a day2day bucket and a personal ingest token."""
    from types import SimpleNamespace

    hh = make_household()
    db.get(Bucket, hh.bucket_id).type = BucketType.day2day
    cat = Category(household_id=hh.household_id, name="Groceries", icon="🛒")
    db.add(cat)
    db.flush()
    record, raw = issue_personal_token(
        db, user_id=hh.user_id, household_id=hh.household_id, name="iPhone"
    )
    db.commit()
    return SimpleNamespace(
        hh=hh, token=record, raw=raw, category=cat, headers={"Authorization": f"Bearer {raw}"}
    )


def _post(client, ingest, **body):
    body.setdefault("merchant", "Sklavenitis")
    body.setdefault("amount", "12,50")
    return client.post(URL, json=body, headers=ingest.headers)


def _attempts(db):
    return (
        db.query(IngestAttempt)
        .order_by(IngestAttempt.created_at.asc(), IngestAttempt.id.asc())
        .all()
    )


# ---------------------------------------------------------------- recording: endpoint paths


def test_created_records_attempt_with_payload_and_attribution(db, client, ingest):
    r = _post(client, ingest, card="Visa ••1234")
    assert r.status_code == 201, r.text

    rows = _attempts(db)
    assert len(rows) == 1
    a = rows[0]
    assert a.status == 201
    assert a.detail == "created"
    assert a.household_id == ingest.hh.household_id
    assert a.token_id == ingest.token.id
    assert a.token_prefix == ingest.token.prefix
    assert a.transaction_id == r.json()["id"]
    assert a.content_type == "application/json"
    assert "12,50" in a.payload  # the raw body, exactly as sent


def test_duplicate_replay_records_200(db, client, ingest):
    at = "2026-10-01T12:34:00Z"
    first = _post(client, ingest, occurred_at=at)
    second = _post(client, ingest, occurred_at=at)
    assert first.status_code == 201
    assert second.status_code == 200

    assert [a.status for a in _attempts(db)] == [201, 200]
    assert _attempts(db)[-1].detail.startswith("duplicate")
    assert _attempts(db)[-1].transaction_id == first.json()["id"]


def test_replay_of_deleted_expense_records_409(db, client, ingest):
    from app.core.clock import utcnow_naive

    at = "2026-10-01T12:34:00Z"
    tid = _post(client, ingest, occurred_at=at).json()["id"]
    db.get(Transaction, tid).deleted_at = utcnow_naive()
    db.commit()

    assert _post(client, ingest, occurred_at=at).status_code == 409
    a = _attempts(db)[-1]
    assert a.status == 409
    assert "deleted" in a.detail.lower()


def test_bad_amount_records_400_naming_the_field(db, client, ingest):
    r = _post(client, ingest, amount="abc")
    assert r.status_code == 400
    a = _attempts(db)[-1]
    assert a.status == 400
    assert "amount" in a.detail.lower()
    assert a.payload


def test_missing_bucket_records_422(client, db, ingest):
    db.get(Bucket, ingest.hh.bucket_id).type = BucketType.custom
    db.commit()
    r = _post(client, ingest)
    assert r.status_code == 422
    a = _attempts(db)[-1]
    assert a.status == 422
    assert "No bucket" in a.detail


# ---------------------------------------------------------------- recording: before the endpoint runs


def test_invalid_json_records_422_with_raw_payload(db, client, ingest):
    r = client.post(
        URL,
        content=b'{"merchant": ',
        headers={**ingest.headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 422
    a = _attempts(db)[-1]
    assert a.status == 422
    assert '{"merchant":' in (a.payload or "")
    assert a.household_id == ingest.hh.household_id  # attributed from the bearer token


def test_form_encoded_body_records_422(db, client, ingest):
    r = client.post(
        URL,
        data={"merchant": "C", "amount": "1"},
        headers={**ingest.headers, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 422
    a = _attempts(db)[-1]
    assert a.status == 422
    assert "merchant" in (a.payload or "")  # the form bytes, recorded verbatim
    assert a.household_id == ingest.hh.household_id


def test_missing_token_records_401_unattributed(client, db):
    r = client.post(URL, json={"merchant": "X", "amount": "1"})
    assert r.status_code == 401
    a = _attempts(db)[-1]
    assert a.status == 401
    assert a.household_id is None
    assert a.token_id is None
    assert a.token_prefix is None


def test_unknown_token_records_401_with_prefix_snippet(client, db):
    bad = {"Authorization": "Bearer pat_" + "A" * 32}
    r = client.post(URL, json={"merchant": "X", "amount": "1"}, headers=bad)
    assert r.status_code == 401
    a = _attempts(db)[-1]
    assert a.status == 401
    assert a.household_id is None
    assert a.token_prefix == ("pat_" + "A" * 32)[:12]


def test_revoked_token_records_401_attributed(db, client, ingest):
    _post(client, ingest)  # a good run first
    revoke_personal_token(
        db, token_id=ingest.token.id, user_id=ingest.hh.user_id, household_id=ingest.hh.household_id
    )
    db.commit()

    r = client.post(URL, json={"merchant": "X", "amount": "1"}, headers=ingest.headers)
    assert r.status_code == 401
    a = _attempts(db)[-1]
    assert a.status == 401
    assert a.household_id == ingest.hh.household_id
    assert a.token_prefix == ingest.token.prefix
    assert "revoked" in a.detail.lower()


def test_rate_limit_records_429(db, client, ingest):
    for i in range(60):
        r = _post(client, ingest, merchant=f"Shop {i}", amount="1")
        assert r.status_code == 201, (i, r.text)
    r = _post(client, ingest, merchant="Shop 60", amount="1")
    assert r.status_code == 429
    a = _attempts(db)[-1]
    assert a.status == 429
    assert a.household_id == ingest.hh.household_id  # the header still identifies the token


# ---------------------------------------------------------------- visibility & pruning


def test_other_households_do_not_see_attempts(db, client, ingest, make_household):
    _post(client, ingest)
    other = make_household()
    assert len(recent_ingest_attempts(db, ingest.hh.household_id, ingest.hh.user_id)) == 1
    assert recent_ingest_attempts(db, other.household_id, other.user_id) == []


def test_unattributed_attempt_with_matching_prefix_is_not_shown_in_app(db, ingest, make_household):
    # Polish R2c: an attempt carrying an unknown tail of our own token is
    # unattributed (the hash lookup fails). It is recorded (and logged) but
    # shown to nobody in the app, the near-owner included: a prefix is not
    # proof of ownership.
    record_ingest_attempt(
        status=401, detail="no such token", raw_token=ingest.raw + "Z" * 10, db=db
    )
    other = make_household()
    assert db.query(IngestAttempt).filter(IngestAttempt.household_id.is_(None)).count() == 1
    assert recent_ingest_attempts(db, ingest.hh.household_id, ingest.hh.user_id) == []
    assert recent_ingest_attempts(db, other.household_id, other.user_id) == []


def test_attempts_pruned_per_household(db, client, ingest, monkeypatch):
    import app.services.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "KEEP_PER_SCOPE", 5)
    for i in range(7):
        _post(client, ingest, merchant=f"Shop {i}", amount="1")

    count = db.query(IngestAttempt).filter_by(household_id=ingest.hh.household_id).count()
    assert count == 5
    # The newest are the ones kept.
    kept = db.query(IngestAttempt.detail).filter_by(household_id=ingest.hh.household_id).all()
    assert ["created"] * 5 == [k[0] for k in kept]


def test_unattributed_attempts_hard_capped(db, monkeypatch):
    import app.services.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "KEEP_UNATTRIBUTED", 3)
    for i in range(5):
        record_ingest_attempt(status=401, detail=f"try {i}", raw_token=f"pat_{i:08d}", db=db)

    count = db.query(IngestAttempt).filter(IngestAttempt.household_id.is_(None)).count()
    assert count == 3


def test_automations_page_shows_recent_attempts(client, db, authed):
    db.get(Bucket, authed.bucket_id).type = BucketType.day2day
    db.commit()
    _, raw = issue_personal_token(
        db, user_id=authed.user_id, household_id=authed.household_id, name="iPhone"
    )
    db.commit()
    headers = {"Authorization": f"Bearer {raw}"}
    r = client.post(URL, json={"merchant": "Corner", "amount": "nope"}, headers=headers)
    assert r.status_code == 400

    text = client.get("/settings/automations").text
    assert "Recent ingest attempts" in text
    # The raw payload is shown (JSON quotes are HTML-escaped on the page).
    assert "Corner" in text and "nope" in text
    assert "Amount" in text  # the reason it was refused


# ---------------------------------------------------------------- payload coercion


def test_currency_symbol_and_locale_amounts_parse(db, client, ingest):
    from decimal import Decimal

    cases = [
        ("€12,50", Decimal("12.50")),
        ("12,50 €", Decimal("12.50")),
        ("1.234,50", Decimal("1234.50")),  # German film
        ("1,234.56", Decimal("1234.56")),  # US film
    ]
    for amount, expect in cases:
        tid = _post(client, ingest, merchant="Shop", amount=amount).json()["id"]
        assert db.get(Transaction, tid).amount == expect, amount


def test_amount_wrapped_in_value_dict_parses(client, db, ingest):
    r = _post(client, ingest, merchant="Shop", amount={"value": "12,50"})
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).amount == 12.5


def test_multi_dot_thousands_are_grouped(client, db, ingest):
    r = _post(client, ingest, merchant="Shop", amount="1.234.567")
    assert r.json()["amount"] == 1234567.0


def test_single_dot_amount_keeps_decimal_reading(client, db, ingest):
    # "12.500" stays 12.5 (the app's Amount parsing), not 12500.
    r = _post(client, ingest, merchant="Shop", amount="12.500")
    assert r.json()["amount"] == 12.5


def test_whole_record_amount_is_400_with_the_keys_it_saw(db, client, ingest):
    r = _post(client, ingest, amount={"total": 1, "currency": "EUR"})
    assert r.status_code == 400
    assert "keys: total, currency" in r.json()["detail"]


def test_null_amount_is_400(db, client, ingest):
    r = _post(client, ingest, amount=None)
    assert r.status_code == 400
    assert r.json()["detail"] == "Amount is required."


def test_merchant_dict_with_name_parses(client, db, ingest):
    r = _post(client, ingest, merchant={"name": "Sklavenitis"})
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).merchant == "Sklavenitis"


def test_merchant_whole_record_is_saved_without_a_merchant(client, db, ingest):
    # Polish R4: an unreadable merchant no longer loses the purchase.
    r = _post(client, ingest, merchant={"total": 1, "currency": "EUR"})
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).merchant == "Apple Pay purchase"


def test_card_dict_with_name_goes_into_notes(client, db, ingest):
    r = _post(client, ingest, card={"name": "Visa ••1234"})
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).notes == "Apple Pay · Visa ••1234"


def test_unreadable_card_dict_is_dropped_from_notes(client, db, ingest):
    r = _post(client, ingest, card={"idx": 3})
    assert r.status_code == 201, r.text
    assert db.get(Transaction, r.json()["id"]).notes is None


def test_unreadable_currency_is_422(client, db, ingest):
    r = _post(client, ingest, currency={"foo": 1})
    assert r.status_code == 422
    assert "Currency could not be read" in r.json()["detail"]


# ---------------------------------------------------------------- logging setup


def test_configure_logging_installs_root_handler():
    from app.core.logging import configure_logging

    configure_logging()
    root = logging.getLogger()
    assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    assert root.level == getattr(logging, str(settings.log_level).upper())


def test_configure_logging_rejects_bad_level(monkeypatch):
    from app.core.logging import configure_logging

    monkeypatch.setattr(settings, "log_level", "VERBOSE")
    with pytest.raises(RuntimeError):
        configure_logging()


def test_ingest_log_line_mentions_status(monkeypatch, db, ingest, make_household):
    """The log line carry pattern a person can grep for in Coolify."""
    import app.services.ingest as ingest_mod

    lines = []
    monkeypatch.setattr(ingest_mod.logger, "log", lambda *a, **k: lines.append(a))
    record_ingest_attempt(status=422, detail="broken", payload='{"x":1}', db=db)
    assert any("ingest:" in str(line) for line in lines)
    assert any("422" in str(line) for line in lines)
