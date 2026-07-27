"""
Settle up.

get_bucket_settlement() derived who owes whom, but nothing recorded that a debt
had been paid, so the same balance was shown forever.
"""
from datetime import date

import pyotp
import pytest

from app.auth import hash_password
from app.models import (
    Bucket, HouseholdMember, MemberRole, Settlement, Transaction,
    TransactionSplit, TransactionType, User,
)
from app.services import (
    get_bucket_settlement,
    get_bucket_settlement_history,
    record_bucket_settlement,
)
from tests.conftest import PASSWORD


@pytest.fixture()
def shared(db, authed):
    """A settlement-enabled bucket where `authed` fronted 100, split evenly.

    Partner therefore owes 50.
    """
    partner = User(
        username="partner", display_name="Partner", email="partner@example.com",
        password_hash=hash_password(PASSWORD),
        totp_secret=pyotp.random_base32(), totp_enabled=True, session_version=0,
    )
    db.add(partner)
    db.flush()
    db.add(HouseholdMember(household_id=authed.household_id, user_id=partner.id,
                           role=MemberRole.member))

    bucket = db.get(Bucket, authed.bucket_id)
    bucket.enable_settlement = True

    txn = Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=100, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date.today(),
        paid_by=authed.user_id,
    )
    db.add(txn)
    db.flush()
    db.add_all([
        TransactionSplit(transaction_id=txn.id, user_id=authed.user_id, amount=50),
        TransactionSplit(transaction_id=txn.id, user_id=partner.id, amount=50),
    ])
    db.commit()

    authed.partner_id = partner.id
    return authed


def test_debt_is_computed_before_settling(db, shared):
    rows = get_bucket_settlement(db, shared.bucket_id)
    assert len(rows) == 1
    assert rows[0]["from_id"] == shared.partner_id
    assert rows[0]["to_id"] == shared.user_id
    assert rows[0]["amount"] == 50.0


def test_recording_a_settlement_clears_the_balance(db, shared):
    record_bucket_settlement(db, shared.bucket_id, shared.household_id,
                             created_by=shared.user_id)
    db.commit()

    assert get_bucket_settlement(db, shared.bucket_id) == []
    assert db.query(Settlement).count() == 1


def test_partial_settlement_leaves_the_remainder(db, shared):
    record_bucket_settlement(
        db, shared.bucket_id, shared.household_id,
        created_by=shared.user_id,
        from_user_id=shared.partner_id, to_user_id=shared.user_id, amount=20,
    )
    db.commit()

    rows = get_bucket_settlement(db, shared.bucket_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 30.0


def test_settling_twice_does_not_go_negative(db, shared):
    record_bucket_settlement(db, shared.bucket_id, shared.household_id)
    db.commit()
    # Second call has nothing outstanding to record.
    created = record_bucket_settlement(db, shared.bucket_id, shared.household_id)
    db.commit()

    assert created == []
    assert get_bucket_settlement(db, shared.bucket_id) == []


def test_new_expense_after_settling_creates_new_debt(db, shared):
    record_bucket_settlement(db, shared.bucket_id, shared.household_id)
    db.commit()
    assert get_bucket_settlement(db, shared.bucket_id) == []

    txn = Transaction(
        bucket_id=shared.bucket_id, household_id=shared.household_id,
        amount=60, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date.today(),
        paid_by=shared.partner_id,
    )
    db.add(txn)
    db.flush()
    db.add_all([
        TransactionSplit(transaction_id=txn.id, user_id=shared.user_id, amount=30),
        TransactionSplit(transaction_id=txn.id, user_id=shared.partner_id, amount=30),
    ])
    db.commit()

    rows = get_bucket_settlement(db, shared.bucket_id)
    assert len(rows) == 1
    # Direction flips: authed now owes partner 30.
    assert rows[0]["from_id"] == shared.user_id
    assert rows[0]["to_id"] == shared.partner_id
    assert rows[0]["amount"] == 30.0


def test_history_records_who_paid_whom(db, shared):
    record_bucket_settlement(db, shared.bucket_id, shared.household_id,
                             created_by=shared.user_id, note="cash")
    db.commit()

    history = get_bucket_settlement_history(db, shared.bucket_id)
    assert len(history) == 1
    assert history[0]["from_name"] == "Partner"
    assert history[0]["amount"] == 50.0
    assert history[0]["note"] == "cash"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_settle_endpoint_clears_balance(client, db, shared):
    r = client.post(f"/buckets/{shared.bucket_id}/settle",
                    data={}, headers=shared.headers)
    assert r.status_code == 302
    assert get_bucket_settlement(db, shared.bucket_id) == []


def test_settle_endpoint_records_partial(client, db, shared):
    r = client.post(f"/buckets/{shared.bucket_id}/settle", data={
        "from_user_id": shared.partner_id, "to_user_id": shared.user_id,
        "amount": "20",
    }, headers=shared.headers)
    assert r.status_code == 302
    assert get_bucket_settlement(db, shared.bucket_id)[0]["amount"] == 30.0


def test_settle_rejects_foreign_user(client, db, shared, make_household):
    outsider = make_household(name="Other", username="outsider")
    r = client.post(f"/buckets/{shared.bucket_id}/settle", data={
        "from_user_id": outsider.user_id, "to_user_id": shared.user_id,
        "amount": "10",
    }, headers=shared.headers)
    assert r.status_code == 400
    assert db.query(Settlement).count() == 0


def test_settle_rejects_same_payer_and_payee(client, shared):
    r = client.post(f"/buckets/{shared.bucket_id}/settle", data={
        "from_user_id": shared.user_id, "to_user_id": shared.user_id, "amount": "10",
    }, headers=shared.headers)
    assert r.status_code == 400


def test_settle_requires_settlement_enabled(client, db, authed):
    r = client.post(f"/buckets/{authed.bucket_id}/settle",
                    data={}, headers=authed.headers)
    assert r.status_code == 400


def test_settle_blocked_across_households(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    bucket = db.get(Bucket, victim.bucket_id)
    bucket.enable_settlement = True
    db.commit()

    r = client.post(f"/buckets/{victim.bucket_id}/settle",
                    data={}, headers=authed.headers)
    assert r.status_code == 404


def test_bucket_page_shows_settle_button(client, shared):
    r = client.get(f"/buckets/{shared.bucket_id}")
    assert r.status_code == 200
    assert "Settle" in r.text
