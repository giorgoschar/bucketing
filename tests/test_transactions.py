"""Transaction validation, CSV export and receipt handling."""
from datetime import date

import pytest

from app.models import Transaction, TransactionSplit
from app.routes.transactions import _csv_safe


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount", ["-10", "0", "-0.01"])
def test_non_positive_amounts_are_rejected(client, db, authed, amount):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": amount, "type": "expense",
    }, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_non_numeric_amount_is_rejected(client, db, authed):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "abc", "type": "expense",
    }, headers=authed.headers)
    assert r.status_code in (400, 422)
    assert db.query(Transaction).count() == 0


def test_absurd_amount_is_rejected(client, db, authed):
    """Numeric(12,4) cannot hold this; it used to raise a 500 at commit."""
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "999999999999", "type": "expense",
    }, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_bad_date_returns_400(client, authed):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "31-02-2026",
        "amount": "10", "type": "expense",
    }, headers=authed.headers)
    assert r.status_code == 400


def test_unknown_currency_is_rejected(client, authed):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "expense", "currency": "XYZ",
    }, headers=authed.headers)
    assert r.status_code == 400


def test_unknown_type_is_rejected(client, authed):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "sideways",
    }, headers=authed.headers)
    assert r.status_code == 400


def test_valid_transaction_is_stored(client, db, authed):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "42.50", "type": "expense", "notes": "Coffee",
    }, headers=authed.headers)
    assert r.status_code == 302
    txn = db.query(Transaction).one()
    assert float(txn.amount) == 42.5
    assert txn.notes == "Coffee"
    assert txn.transaction_date == date(2026, 7, 20)


def test_splits_cannot_exceed_the_total(client, db, authed):
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "50", "type": "expense", "is_shared": "on",
        f"split_{authed.user_id}": "80",
    }, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(TransactionSplit).count() == 0


def test_bad_month_returns_400_not_500(client, authed):
    r = client.get(f"/buckets/{authed.bucket_id}?year=2026&month=13")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected_prefix", [
    ('=HYPERLINK("http://evil","x")', "'="),
    ("+1+1", "'+"),
    ("-2+3", "'-"),
    ("@SUM(A1)", "'@"),
])
def test_csv_formula_injection_is_neutralised(value, expected_prefix):
    assert _csv_safe(value).startswith(expected_prefix)


@pytest.mark.parametrize("value", ["Normal note", "Coffee -3", "", None])
def test_csv_leaves_ordinary_values_alone(value):
    out = _csv_safe(value)
    assert not out.startswith("'")


def test_export_streams_without_detached_session(client, db, authed):
    """The generator used to lazy-load relationships after the session closed."""
    client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "12.34", "type": "expense", "notes": "Lunch",
    }, headers=authed.headers)

    r = client.get("/transactions/export?year=2026")
    assert r.status_code == 200
    body = r.text
    assert "Date,Bucket,Category,Type,Amount,Currency,Paid By,Notes" in body
    assert "12.34" in body
    assert "Lunch" in body


def test_export_includes_feb_29_in_a_leap_year(client, db, authed):
    """February used to be truncated at day 28, dropping Feb 29 entirely."""
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=29.99, currency="EUR", type="expense",
        transaction_date=date(2028, 2, 29), notes="LeapDay",
    ))
    db.commit()

    r = client.get("/transactions/export?year=2028&month=2")
    assert r.status_code == 200
    assert "LeapDay" in r.text


def test_export_rejects_bad_month(client, authed):
    assert client.get("/transactions/export?year=2026&month=99").status_code == 400


def test_export_only_contains_own_household(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    db.add(Transaction(
        bucket_id=victim.bucket_id, household_id=victim.household_id,
        amount=555, currency="EUR", type="expense",
        transaction_date=date(2026, 7, 20), notes="SecretExpense",
    ))
    db.commit()

    r = client.get("/transactions/export?year=2026")
    assert "SecretExpense" not in r.text
