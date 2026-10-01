"""JSON API (/api/v1) — auth flow, validation and isolation."""
import pyotp
import pytest

from app.clock import local_today, utcnow_naive
from tests.conftest import PASSWORD


@pytest.fixture()
def api(client, make_household):
    """A logged-in API client. Returns (headers, household namespace)."""
    hh = make_household()
    r = client.post("/api/v1/auth/login",
                    json={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    pending = r.json()["pending_token"]

    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": pending, "code": pyotp.TOTP(hh.secret).now()})
    assert r.status_code == 200, r.text
    hh.tokens = r.json()
    return {"Authorization": f"Bearer {hh.tokens['access_token']}"}, hh


def test_login_requires_totp_step(client, make_household):
    hh = make_household()
    r = client.post("/api/v1/auth/login",
                    json={"username": hh.username, "password": PASSWORD})
    body = r.json()
    assert "pending_token" in body
    assert "access_token" not in body


def test_pending_token_cannot_access_data(client, make_household):
    hh = make_household()
    pending = client.post("/api/v1/auth/login",
                          json={"username": hh.username, "password": PASSWORD}).json()["pending_token"]
    r = client.get("/api/v1/buckets", headers={"Authorization": f"Bearer {pending}"})
    assert r.status_code == 401


def test_bad_password_is_401(client, make_household):
    hh = make_household()
    r = client.post("/api/v1/auth/login",
                    json={"username": hh.username, "password": "wrong-password"})
    assert r.status_code == 401


def test_unauthenticated_requests_are_401(client):
    assert client.get("/api/v1/buckets").status_code == 401


@pytest.mark.parametrize("path", [
    "/api/v1/auth/me", "/api/v1/dashboard", "/api/v1/buckets", "/api/v1/bills",
    "/api/v1/transactions", "/api/v1/insights", "/api/v1/settings/profile",
    "/api/v1/settings/categories", "/api/v1/notifications",
])
def test_endpoints_respond(client, api, path):
    headers, _ = api
    assert client.get(path, headers=headers).status_code == 200


def test_refresh_rotates_and_revokes(client, api):
    _, hh = api
    old = hh.tokens["refresh_token"]
    r = client.post("/api/v1/auth/token/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    assert r.json()["refresh_token"] != old
    # The old token must no longer work.
    assert client.post("/api/v1/auth/token/refresh",
                       json={"refresh_token": old}).status_code == 401


def test_insights_payload_shape(client, api):
    headers, _ = api
    body = client.get("/api/v1/insights", headers=headers).json()
    for key in ("total_spent", "income_total", "net", "categories",
                "budget_status", "bucket_breakdown", "category_trend",
                "monthly_trend", "period_label"):
        assert key in body, f"missing {key}"
    assert "max_value" in body["category_trend"]


def test_insights_budget_status_is_serialised_explicitly(client, db, api):
    from app.models import Bucket

    headers, hh = api
    db.get(Bucket, hh.bucket_id).budget = 250
    db.commit()

    rows = client.get("/api/v1/insights", headers=headers).json()["budget_status"]
    assert rows and set(rows[0]) == {
        "bucket_id", "bucket_name", "icon", "color",
        "spent", "budget", "pct", "remaining", "over_budget",
    }


@pytest.mark.parametrize("query,expected", [
    ("type=bogus", 400),
    ("year=2026&month=99", 400),
    ("year=2026&month=6", 200),
])
def test_transaction_filters_validate(client, api, query, expected):
    headers, _ = api
    assert client.get(f"/api/v1/transactions?{query}", headers=headers).status_code == expected


def test_cannot_create_transaction_in_foreign_bucket(client, api, make_household):
    headers, _ = api
    victim = make_household(name="Victim", username="apivictim")
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": victim.bucket_id, "amount": 10, "type": "expense",
    })
    assert r.status_code == 404


def test_cannot_split_onto_foreign_user(client, api, make_household):
    headers, hh = api
    victim = make_household(name="Victim", username="apivictim2")
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": 10, "type": "expense",
        "splits": [{"user_id": victim.user_id, "amount": 10}],
    })
    assert r.status_code == 400


def test_negative_amount_is_rejected(client, api):
    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": -50, "type": "expense",
    })
    assert r.status_code == 422


def test_paying_an_occurrence_twice_does_not_double_charge(client, db, api, make_bill):
    from app.models import Transaction

    headers, hh = api
    bill, occ = make_bill(hh.household_id, hh.bucket_id, amount=45,
                          auto_pay=False, paid_by=hh.user_id)

    for _ in range(3):
        r = client.post(f"/api/v1/bills/occurrences/{occ.id}/pay",
                        headers=headers, json={})
        assert r.status_code == 200

    assert db.query(Transaction).count() == 1


def test_zero_interval_bill_is_clamped(client, api):
    headers, hh = api
    r = client.post("/api/v1/bills", headers=headers, json={
        "name": "Loop", "amount": 10, "start_date": "2026-01-01",
        "interval_months": 0, "total_occurrences": 5,
    })
    assert r.status_code in (201, 400)
    if r.status_code == 201:
        assert r.json()["interval_months"] >= 1


def test_bad_date_is_400_not_500(client, api):
    headers, _ = api
    r = client.post("/api/v1/bills", headers=headers, json={
        "name": "Bad", "amount": 10, "start_date": "31/02/2026",
    })
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

def test_settle_endpoint_records_and_clears(client, db, api):
    """POST /settle used to only return instructions and record nothing."""

    import pyotp

    from app.auth import hash_password
    from app.models import (
        Bucket,
        HouseholdMember,
        MemberRole,
        Settlement,
        Transaction,
        TransactionSplit,
        TransactionType,
        User,
    )

    headers, hh = api
    partner = User(username="apipartner", display_name="APIPartner",
                   email="ap@example.com", password_hash=hash_password("x"),
                   totp_secret=pyotp.random_base32(), totp_enabled=True)
    db.add(partner)
    db.flush()
    db.add(HouseholdMember(household_id=hh.household_id, user_id=partner.id,
                           role=MemberRole.member))
    db.get(Bucket, hh.bucket_id).enable_settlement = True
    txn = Transaction(bucket_id=hh.bucket_id, household_id=hh.household_id,
                      amount=80, currency="EUR", exchange_rate=1,
                      type=TransactionType.expense, transaction_date=local_today(),
                      paid_by=hh.user_id)
    db.add(txn)
    db.flush()
    db.add_all([
        TransactionSplit(transaction_id=txn.id, user_id=hh.user_id, amount=40),
        TransactionSplit(transaction_id=txn.id, user_id=partner.id, amount=40),
    ])
    db.commit()

    r = client.get(f"/api/v1/buckets/{hh.bucket_id}/settlement", headers=headers)
    assert r.status_code == 200
    assert r.json()["settlements"][0]["amount"] == 40.0

    r = client.post(f"/api/v1/buckets/{hh.bucket_id}/settle", headers=headers, json={})
    assert r.status_code == 200
    assert r.json()["settlements"] == []
    assert db.query(Settlement).count() == 1

    hist = client.get(f"/api/v1/buckets/{hh.bucket_id}/settlement", headers=headers).json()
    assert len(hist["history"]) == 1


def test_settle_requires_enabled_bucket(client, api):
    headers, hh = api
    r = client.post(f"/api/v1/buckets/{hh.bucket_id}/settle", headers=headers, json={})
    assert r.status_code == 400


def test_household_settlement_api(client, db, api):
    """Household-wide settle nets buckets together and records the payment."""

    import pyotp

    from app.auth import hash_password
    from app.models import (
        Bucket,
        HouseholdMember,
        MemberRole,
        Settlement,
        Transaction,
        TransactionSplit,
        TransactionType,
        User,
    )

    headers, hh = api
    partner = User(username="hhpartner", display_name="HHPartner",
                   email="hp@example.com", password_hash=hash_password("x"),
                   totp_secret=pyotp.random_base32(), totp_enabled=True)
    db.add(partner)
    db.flush()
    db.add(HouseholdMember(household_id=hh.household_id, user_id=partner.id,
                           role=MemberRole.member))
    db.get(Bucket, hh.bucket_id).enable_settlement = True
    txn = Transaction(bucket_id=hh.bucket_id, household_id=hh.household_id,
                      amount=100, currency="EUR", exchange_rate=1,
                      type=TransactionType.expense, transaction_date=local_today(),
                      paid_by=hh.user_id)
    db.add(txn)
    db.flush()
    db.add_all([
        TransactionSplit(transaction_id=txn.id, user_id=hh.user_id, amount=50),
        TransactionSplit(transaction_id=txn.id, user_id=partner.id, amount=50),
    ])
    db.commit()

    r = client.get("/api/v1/settlement", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["settlements"][0]["amount"] == 50.0
    assert round(sum(b["net"] for b in body["balances"]), 2) == 0.0

    r = client.post("/api/v1/settlement/settle", headers=headers, json={})
    assert r.status_code == 200
    assert r.json()["settlements"] == []

    assert db.query(Settlement).filter(Settlement.bucket_id.is_(None)).count() == 1
    assert len(client.get("/api/v1/settlement", headers=headers).json()["history"]) == 1


# ---------------------------------------------------------------------------
# C2/M1: API auth rate limits and per-account lockout
# ---------------------------------------------------------------------------

def test_api_login_is_rate_limited(client, make_household):
    hh = make_household()
    codes = [client.post("/api/v1/auth/login",
                         json={"username": hh.username, "password": "wrong"}).status_code
             for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_api_totp_verify_is_rate_limited(client, make_household):
    make_household()
    codes = []
    for _ in range(11):
        r = client.post("/api/v1/auth/totp/verify",
                        json={"pending_token": "x", "code": "000000"})
        codes.append(r.status_code)
    assert codes[10] == 429


def test_api_refresh_is_rate_limited(client):
    codes = [client.post("/api/v1/auth/token/refresh",
                         json={"refresh_token": "nope"}).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def _reset_limits():
    from app.ratelimit import limiter
    limiter.reset()


def test_ten_wrong_passwords_lock_the_account(client, make_household):
    hh = make_household()
    for _ in range(10):
        _reset_limits()  # isolate the account lockout from the per-IP limit
        r = client.post("/api/v1/auth/login",
                        json={"username": hh.username, "password": "wrong"})
        assert r.status_code == 401
    _reset_limits()
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 429
    assert r.json()["detail"] == "Invalid credentials"


def test_lockout_expires_and_success_clears_counter(client, db, make_household):
    from datetime import timedelta

    from app.models import User

    hh = make_household()
    user = db.get(User, hh.user_id)
    user.failed_logins = 9
    user.locked_until = utcnow_naive() - timedelta(minutes=1)
    db.commit()

    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 200
    db.expire_all()
    # A correct password alone must not reset the counter (it guards 2FA too).
    assert db.get(User, hh.user_id).failed_logins == 9
    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": r.json()["pending_token"],
                          "code": pyotp.TOTP(hh.secret).now()})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(User, hh.user_id).failed_logins == 0


def test_wrong_totp_codes_count_towards_lockout(client, db, make_household):
    from app.models import User

    hh = make_household()
    pending = client.post("/api/v1/auth/login",
                          json={"username": hh.username, "password": PASSWORD}).json()["pending_token"]
    for _ in range(10):
        _reset_limits()
        r = client.post("/api/v1/auth/totp/verify", json={"pending_token": pending, "code": "000000"})
        assert r.status_code == 401
    _reset_limits()
    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": pending, "code": pyotp.TOTP(hh.secret).now()})
    assert r.status_code == 429
    db.expire_all()
    assert db.get(User, hh.user_id).locked_until is not None


def test_api_invite_creation_is_rate_limited(client, api):
    headers, _ = api
    codes = [client.post("/api/v1/settings/household/invite", headers=headers).status_code
             for _ in range(6)]
    assert codes[:5] == [200] * 5
    assert codes[5] == 429


# ---------------------------------------------------------------------------
# Shared create_transaction service
# ---------------------------------------------------------------------------

def test_api_splits_exceeding_total_are_422(client, db, api):
    from app.models import Transaction

    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": 10, "type": "expense",
        "splits": [{"user_id": hh.user_id, "amount": 6},
                   {"user_id": hh.user_id, "amount": 6}],
    })
    assert r.status_code == 422
    assert db.query(Transaction).count() == 0


def test_api_client_id_is_idempotent(client, db, api):
    from app.models import Transaction

    headers, hh = api
    body = {"bucket_id": hh.bucket_id, "amount": 10, "type": "expense",
            "client_id": "api-offline-1"}
    first = client.post("/api/v1/transactions", headers=headers, json=body)
    second = client.post("/api/v1/transactions", headers=headers, json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert db.query(Transaction).count() == 1


def test_api_client_id_of_deleted_transaction_is_409(client, db, api):
    headers, hh = api
    body = {"bucket_id": hh.bucket_id, "amount": 10, "type": "expense",
            "client_id": "api-offline-2"}
    tid = client.post("/api/v1/transactions", headers=headers, json=body).json()["id"]
    assert client.delete(f"/api/v1/transactions/{tid}", headers=headers).status_code == 204
    assert client.post("/api/v1/transactions", headers=headers, json=body).status_code == 409


def test_api_client_id_race_returns_existing_row(client, db, api, monkeypatch):
    """Two creates both pass the lookup; the loser must get the idempotent reply."""
    from app.models import Transaction
    from app.services import transactions as services

    headers, hh = api
    body = {"bucket_id": hh.bucket_id, "amount": 10, "type": "expense",
            "client_id": "api-race-1"}
    first = client.post("/api/v1/transactions", headers=headers, json=body)
    assert first.status_code == 201

    real = services._find_by_client_id
    calls = []

    def blind_once(*a, **kw):
        calls.append(1)
        return None if len(calls) == 1 else real(*a, **kw)

    monkeypatch.setattr(services, "_find_by_client_id", blind_once)
    second = client.post("/api/v1/transactions", headers=headers, json=body)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert db.query(Transaction).count() == 1


def test_api_unknown_currency_is_422(client, api):
    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": 10, "type": "expense", "currency": "XX",
    })
    assert r.status_code == 422


def test_insights_money_fields_stay_json_numbers(client, db, api):
    """Services return Decimal now; the API must still emit JSON numbers (floats)."""
    from app.clock import local_today
    from app.models import Bucket, Transaction, TransactionType

    headers, hh = api
    db.get(Bucket, hh.bucket_id).budget = 100
    for amount in (0.10, 0.15):
        db.add(Transaction(
            bucket_id=hh.bucket_id, household_id=hh.household_id, amount=amount,
            currency="EUR", exchange_rate=1, type=TransactionType.expense,
            transaction_date=local_today(), paid_by=hh.user_id,
        ))
    db.commit()

    body = client.get("/api/v1/insights", headers=headers).json()
    assert body["total_spent"] == 0.25 and isinstance(body["total_spent"], float)
    assert isinstance(body["net"], float)
    assert body["kpis"]["avg_per_txn"] == 0.13          # 0.125 rounded half up
    row = body["budget_status"][0]
    assert all(isinstance(row[k], float) for k in ("spent", "budget", "remaining"))
    assert isinstance(body["categories"][0]["amount"], float)
