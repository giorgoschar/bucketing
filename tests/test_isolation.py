"""
Cross-household isolation.

Ids in this app are opaque UUIDs, but that is not an access control. Every
route that accepts an id from the client must scope it to the caller's
household.
"""
from datetime import date

from app.models import Bucket, RecurringBill, Transaction, TransactionSplit


def _make_txn(client, headers, bucket_id, amount="10"):
    r = client.post("/transactions", data={
        "bucket_id": bucket_id, "transaction_date": "2026-07-20",
        "amount": amount, "type": "expense",
    }, headers=headers)
    assert r.status_code == 302, r.text[:200]


def test_cannot_read_another_households_bucket(client, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    assert client.get(f"/buckets/{victim.bucket_id}").status_code == 404


def test_cannot_create_transaction_in_foreign_bucket(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post("/transactions", data={
        "bucket_id": victim.bucket_id, "transaction_date": "2026-07-20",
        "amount": "99", "type": "expense",
    }, headers=authed.headers)
    assert r.status_code in (400, 403, 404)
    assert db.query(Transaction).filter_by(bucket_id=victim.bucket_id).count() == 0


def test_cannot_move_transaction_into_foreign_bucket(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    _make_txn(client, authed.headers, authed.bucket_id)
    txn = db.query(Transaction).one()

    r = client.post(f"/transactions/{txn.id}/edit", data={
        "bucket_id": victim.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "expense",
    }, headers=authed.headers)

    assert r.status_code in (400, 403, 404)
    db.expire_all()
    assert db.get(Transaction, txn.id).bucket_id == authed.bucket_id


def test_cannot_split_onto_a_non_member(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "50", "type": "expense", "is_shared": "on",
        f"split_{victim.user_id}": "50",
    }, headers=authed.headers)

    assert r.status_code in (400, 403, 404)
    assert db.query(TransactionSplit).filter_by(user_id=victim.user_id).count() == 0


def test_cannot_attach_bill_to_foreign_bucket(client, db, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post("/bills", data={
        "name": "Evil", "amount": "10", "start_date": "2026-01-01",
        "interval_months": "1", "frequency": "monthly",
        "bucket_id": victim.bucket_id,
    }, headers=authed.headers)

    assert r.status_code in (400, 403, 404)
    assert db.query(RecurringBill).filter_by(bucket_id=victim.bucket_id).count() == 0


def test_cannot_use_foreign_category(client, db, authed, make_household):
    from app.models import Category

    victim = make_household(name="Victim", username="victim")
    cat = Category(household_id=victim.household_id, name="Victim Cat")
    db.add(cat)
    db.commit()

    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "expense", "category_id": cat.id,
    }, headers=authed.headers)
    assert r.status_code in (400, 403, 404)


def test_cannot_set_foreign_user_as_payer(client, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post("/transactions", data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
        "amount": "10", "type": "expense", "paid_by": victim.user_id,
    }, headers=authed.headers)
    assert r.status_code in (400, 403, 404)


def test_cannot_edit_or_delete_foreign_bucket(client, authed, make_household):
    victim = make_household(name="Victim", username="victim")
    r = client.post(f"/buckets/{victim.bucket_id}/edit",
                    data={"name": "Pwned", "type": "custom"}, headers=authed.headers)
    assert r.status_code == 404
    r = client.post(f"/buckets/{victim.bucket_id}/archive", headers=authed.headers)
    assert r.status_code == 404


def test_insights_only_reports_own_household(client, db, authed, make_household):
    """A victim's spending must never leak into the attacker's totals."""
    victim = make_household(name="Victim", username="victim")
    db.add(Transaction(
        bucket_id=victim.bucket_id, household_id=victim.household_id,
        amount=9999, currency="EUR", type="expense", transaction_date=date(2026, 7, 20),
    ))
    db.commit()

    _make_txn(client, authed.headers, authed.bucket_id, amount="10")
    r = client.get("/insights?preset=all_time")
    assert r.status_code == 200
    assert "9,999" not in r.text and "9999" not in r.text


def test_non_owner_cannot_rename_household(client, db, make_household, login):
    """The HTML route used to let any member change household settings."""
    from app.models import Household, HouseholdMember, MemberRole, User
    from app.auth import hash_password
    from tests.conftest import PASSWORD
    import pyotp

    owner = make_household(name="Shared", username="owner")
    secret = pyotp.random_base32()
    member = User(username="member", display_name="Member", email="member@example.com",
                  password_hash=hash_password(PASSWORD), totp_secret=secret,
                  totp_enabled=True, session_version=0)
    db.add(member)
    db.flush()
    db.add(HouseholdMember(household_id=owner.household_id, user_id=member.id,
                           role=MemberRole.member))
    db.commit()

    headers = login("member", secret)
    r = client.post("/settings/household",
                    data={"name": "Hijacked", "default_currency": "EUR"}, headers=headers)

    assert r.status_code == 403
    db.expire_all()
    assert db.get(Household, owner.household_id).name == "Shared"
