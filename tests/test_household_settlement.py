"""
Household-wide settle up.

Nets every settlement-enabled bucket together so members square up once,
instead of bucket by bucket.
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
    get_household_settlement,
    get_household_settlement_history,
    get_member_balances,
    record_household_settlement,
)
from tests.conftest import PASSWORD


def _add_member(db, household_id, username):
    user = User(
        username=username, display_name=username.title(),
        email=f"{username}@example.com", password_hash=hash_password(PASSWORD),
        totp_secret=pyotp.random_base32(), totp_enabled=True, session_version=0,
    )
    db.add(user)
    db.flush()
    db.add(HouseholdMember(household_id=household_id, user_id=user.id,
                           role=MemberRole.member))
    return user


def _shared_expense(db, bucket_id, household_id, payer, members, amount):
    """One expense fronted by `payer`, split evenly across `members`."""
    txn = Transaction(
        bucket_id=bucket_id, household_id=household_id, amount=amount,
        currency="EUR", exchange_rate=1, type=TransactionType.expense,
        transaction_date=date.today(), paid_by=payer,
    )
    db.add(txn)
    db.flush()
    share = amount / len(members)
    for uid in members:
        db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=share))
    return txn


@pytest.fixture()
def two_buckets(db, authed):
    """Two settlement-enabled buckets with debts running opposite ways.

    Bucket A: authed fronts 100 split evenly  -> partner owes authed 50
    Bucket B: partner fronts 60 split evenly  -> authed owes partner 30
    Net across the household: partner owes authed 20.
    """
    partner = _add_member(db, authed.household_id, "partner")

    a = db.get(Bucket, authed.bucket_id)
    a.enable_settlement = True
    b = Bucket(household_id=authed.household_id, name="Bucket B",
               enable_settlement=True)
    db.add(b)
    db.flush()

    both = [authed.user_id, partner.id]
    _shared_expense(db, a.id, authed.household_id, authed.user_id, both, 100)
    _shared_expense(db, b.id, authed.household_id, partner.id, both, 60)
    db.commit()

    authed.partner_id = partner.id
    authed.bucket_b_id = b.id
    return authed


def test_nets_debts_across_buckets(db, two_buckets):
    """Opposite debts in two buckets must cancel into a single transfer."""
    rows = get_household_settlement(db, two_buckets.household_id)
    assert len(rows) == 1
    assert rows[0]["from_id"] == two_buckets.partner_id
    assert rows[0]["to_id"] == two_buckets.user_id
    assert rows[0]["amount"] == 20.0


def test_member_balances_sum_to_zero(db, two_buckets):
    balances = get_member_balances(db, two_buckets.household_id)
    assert round(sum(b["net"] for b in balances), 2) == 0.0
    by_id = {b["user_id"]: b["net"] for b in balances}
    assert by_id[two_buckets.user_id] == 20.0
    assert by_id[two_buckets.partner_id] == -20.0


def test_buckets_without_settlement_are_excluded(db, two_buckets):
    """A private bucket must not drag solo spending into the shared balance."""
    private = Bucket(household_id=two_buckets.household_id, name="Private",
                     enable_settlement=False)
    db.add(private)
    db.flush()
    db.add(Transaction(
        bucket_id=private.id, household_id=two_buckets.household_id,
        amount=500, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date.today(),
        paid_by=two_buckets.user_id,
    ))
    db.commit()

    rows = get_household_settlement(db, two_buckets.household_id)
    assert rows[0]["amount"] == 20.0


def test_settling_clears_the_household_balance(db, two_buckets):
    record_household_settlement(db, two_buckets.household_id,
                                created_by=two_buckets.user_id)
    db.commit()
    assert get_household_settlement(db, two_buckets.household_id) == []


def test_partial_household_settlement(db, two_buckets):
    record_household_settlement(
        db, two_buckets.household_id,
        from_user_id=two_buckets.partner_id, to_user_id=two_buckets.user_id,
        amount=5,
    )
    db.commit()
    rows = get_household_settlement(db, two_buckets.household_id)
    assert rows[0]["amount"] == 15.0


def test_household_settlement_is_scoped_to_household(db, two_buckets):
    record_household_settlement(db, two_buckets.household_id)
    db.commit()
    row = db.query(Settlement).filter(Settlement.bucket_id.is_(None)).one()
    assert row.household_id == two_buckets.household_id
    assert row.bucket_id is None


def test_bucket_and_household_settlements_compose(db, two_buckets):
    """A per-bucket payment reduces the household total, not double-counted."""
    from app.services import record_bucket_settlement

    record_bucket_settlement(
        db, two_buckets.bucket_id, two_buckets.household_id,
        from_user_id=two_buckets.partner_id, to_user_id=two_buckets.user_id,
        amount=50,
    )
    db.commit()

    # Bucket A is now square, so only bucket B's debt remains: authed owes 30.
    rows = get_household_settlement(db, two_buckets.household_id)
    assert len(rows) == 1
    assert rows[0]["from_id"] == two_buckets.user_id
    assert rows[0]["amount"] == 30.0


def test_history_includes_bucket_and_household_payments(db, two_buckets):
    from app.services import record_bucket_settlement

    record_bucket_settlement(db, two_buckets.bucket_id, two_buckets.household_id,
                             from_user_id=two_buckets.partner_id,
                             to_user_id=two_buckets.user_id, amount=10)
    record_household_settlement(db, two_buckets.household_id,
                                from_user_id=two_buckets.partner_id,
                                to_user_id=two_buckets.user_id, amount=5)
    db.commit()

    history = get_household_settlement_history(db, two_buckets.household_id)
    assert len(history) == 2
    assert any(h["bucket_name"] for h in history)      # the bucket-scoped one
    assert any(h["bucket_name"] is None for h in history)  # the household one


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_settlement_page_renders(client, two_buckets):
    r = client.get("/settlement")
    assert r.status_code == 200
    assert "Settle up" in r.text


def test_settlement_page_without_enabled_buckets(client, authed):
    r = client.get("/settlement")
    assert r.status_code == 200
    assert "No buckets are tracking settlement" in r.text


def test_settle_endpoint_clears(client, db, two_buckets):
    r = client.post("/settlement/settle", data={}, headers=two_buckets.headers)
    assert r.status_code == 302
    assert get_household_settlement(db, two_buckets.household_id) == []


def test_settle_rejects_foreign_user(client, db, two_buckets, make_household):
    outsider = make_household(name="Other", username="outsider")
    r = client.post("/settlement/settle", data={
        "from_user_id": outsider.user_id, "to_user_id": two_buckets.user_id,
        "amount": "10",
    }, headers=two_buckets.headers)
    assert r.status_code == 400
    assert db.query(Settlement).count() == 0


def test_settle_rejects_same_payer_payee(client, two_buckets):
    r = client.post("/settlement/settle", data={
        "from_user_id": two_buckets.user_id, "to_user_id": two_buckets.user_id,
        "amount": "10",
    }, headers=two_buckets.headers)
    assert r.status_code == 400


def test_settlement_page_requires_auth(client):
    r = client.get("/settlement")
    assert r.status_code == 302
