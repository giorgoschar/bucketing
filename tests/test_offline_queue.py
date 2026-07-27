"""
Offline write queue — server side.

Queued expenses are replayed when connectivity returns. A replay can happen
after the original response was lost, so the server must recognise the repeat
rather than creating a second transaction.
"""
from datetime import date

import pytest

from app.models import Transaction


def _post(client, authed, **overrides):
    data = {
        "bucket_id": authed.bucket_id,
        "transaction_date": "2026-07-20",
        "amount": "42.50",
        "type": "expense",
    }
    data.update(overrides)
    return client.post("/transactions", data=data, headers=authed.headers)


def test_replay_with_same_client_id_creates_one_transaction(client, db, authed):
    """The core guarantee: a lost response must not become a double charge."""
    for _ in range(3):
        r = _post(client, authed, client_id="offline-abc-123", notes="Dinner")
        assert r.status_code == 302

    txns = db.query(Transaction).all()
    assert len(txns) == 1
    assert txns[0].client_id == "offline-abc-123"


def test_different_client_ids_create_separate_transactions(client, db, authed):
    _post(client, authed, client_id="offline-1")
    _post(client, authed, client_id="offline-2")
    assert db.query(Transaction).count() == 2


def test_without_client_id_nothing_is_deduplicated(client, db, authed):
    """Online entry is unaffected: two identical expenses are still two."""
    _post(client, authed)
    _post(client, authed)
    assert db.query(Transaction).count() == 2


def test_client_id_is_scoped_per_household(app, client, db, authed, make_household):
    """Two households can independently generate the same client id."""
    import pyotp
    from fastapi.testclient import TestClient
    from tests.conftest import PASSWORD

    other = make_household(name="Other", username="offlineother")
    _post(client, authed, client_id="collide")

    # A second browser: signing the other user in on the same client would be
    # rejected by CSRF, since that client already holds the first user's session.
    other_client = TestClient(app, follow_redirects=False)
    other_client.post("/login", data={"username": other.username, "password": PASSWORD})
    other_client.post("/login/verify", data={"code": pyotp.TOTP(other.secret).now()})
    token = other_client.cookies.get("csrf_token")

    r = other_client.post("/transactions", data={
        "bucket_id": other.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "expense", "client_id": "collide",
    }, headers={"X-CSRF-Token": token})
    assert r.status_code == 302

    assert db.query(Transaction).count() == 2


def test_replay_still_validates_the_bucket(client, db, authed, make_household):
    """Idempotency must not become a way past ownership checks."""
    victim = make_household(name="Victim", username="offlinevictim")
    r = _post(client, authed, bucket_id=victim.bucket_id, client_id="x-1")
    assert r.status_code in (400, 403, 404)
    assert db.query(Transaction).count() == 0


def test_replay_of_a_rejected_payload_is_not_stored(client, db, authed):
    r = _post(client, authed, amount="-5", client_id="bad-1")
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0

    # Once corrected, the same client id is free to be used.
    r = _post(client, authed, amount="5", client_id="bad-1")
    assert r.status_code == 302
    assert db.query(Transaction).count() == 1


def test_stored_transaction_keeps_its_client_id(client, db, authed):
    _post(client, authed, client_id="keep-me")
    assert db.query(Transaction).one().client_id == "keep-me"


def test_blank_client_id_is_stored_as_null(client, db, authed):
    """Blank must be NULL, or the unique constraint would reject the second."""
    _post(client, authed, client_id="")
    _post(client, authed, client_id="")
    txns = db.query(Transaction).all()
    assert len(txns) == 2
    assert all(t.client_id is None for t in txns)


# ---------------------------------------------------------------------------
# Client-side contract
# ---------------------------------------------------------------------------

def test_offline_js_reads_csrf_from_cookie_not_meta():
    """The <meta> tag is frozen at page load; the cookie is refreshed
    mid-session. Reading the tag meant a queued expense flushed after a refresh
    was rejected with 403 and stuck in the queue forever."""
    js = open("static/offline.js").read()
    assert "csrf_token=" in js, "should read the cookie"
    assert 'meta[name="csrf-token"]' not in js, "must not use the stale meta tag"


def test_offline_js_generates_a_client_id():
    js = open("static/offline.js").read()
    assert "client_id" in js
    assert "randomUUID" in js


def test_base_template_exposes_queue_controls():
    html = open("templates/base.html").read()
    for hook in ("flushOfflineQueue", "refreshOfflineBadge", "offline-queue-pill"):
        assert hook in html, hook
