"""JSON API (/api/v1) — auth flow, validation and isolation."""
import pyotp
import pytest

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
    assert r.status_code == 400


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
