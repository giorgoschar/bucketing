"""
Per-person view.

"Paid out" is money fronted; "my share" is what that person is actually
responsible for. The gap between them is what settlement resolves.
"""
from datetime import date, timedelta

import pyotp
import pytest

from app.auth import hash_password
from app.models import (
    Bucket, Category, HouseholdMember, MemberRole, Transaction,
    TransactionSplit, TransactionType, User,
)
from app.services import get_person_summary
from tests.conftest import PASSWORD


@pytest.fixture()
def pair(db, authed):
    partner = User(
        username="partner", display_name="Partner", email="partner@example.com",
        password_hash=hash_password(PASSWORD),
        totp_secret=pyotp.random_base32(), totp_enabled=True, session_version=0,
    )
    db.add(partner)
    db.flush()
    db.add(HouseholdMember(household_id=authed.household_id, user_id=partner.id,
                           role=MemberRole.member))
    db.get(Bucket, authed.bucket_id).enable_settlement = True
    db.commit()
    authed.partner_id = partner.id
    return authed


def _shared(db, authed, amount, payer, shares, when=None):
    txn = Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=when or date.today(),
        paid_by=payer,
    )
    db.add(txn)
    db.flush()
    for uid, share in shares.items():
        db.add(TransactionSplit(transaction_id=txn.id, user_id=uid, amount=share))
    db.commit()
    return txn


def _solo(db, authed, amount, payer, when=None):
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=when or date.today(),
        paid_by=payer,
    ))
    db.commit()


def test_paid_out_and_share_differ_on_shared_expense(db, pair):
    """The whole point: fronting 100 on a 50/50 split is 100 out, 50 owed."""
    _shared(db, pair, 100, pair.user_id,
            {pair.user_id: 50, pair.partner_id: 50})

    mine = get_person_summary(db, pair.household_id, pair.user_id)
    assert mine["paid_out"] == 100.0
    assert mine["my_share"] == 50.0

    theirs = get_person_summary(db, pair.household_id, pair.partner_id)
    assert theirs["paid_out"] == 0.0
    assert theirs["my_share"] == 50.0


def test_solo_expense_counts_fully_to_the_payer(db, pair):
    _solo(db, pair, 40, pair.user_id)

    mine = get_person_summary(db, pair.household_id, pair.user_id)
    assert mine["paid_out"] == 40.0
    assert mine["my_share"] == 40.0

    theirs = get_person_summary(db, pair.household_id, pair.partner_id)
    assert theirs["my_share"] == 0.0


def test_net_matches_the_settlement_position(db, pair):
    _shared(db, pair, 100, pair.user_id,
            {pair.user_id: 50, pair.partner_id: 50})

    assert get_person_summary(db, pair.household_id, pair.user_id)["net"] == 50.0
    assert get_person_summary(db, pair.household_id, pair.partner_id)["net"] == -50.0


def test_shared_count(db, pair):
    _shared(db, pair, 100, pair.user_id, {pair.user_id: 50, pair.partner_id: 50})
    _shared(db, pair, 60, pair.partner_id, {pair.user_id: 30, pair.partner_id: 30})
    _solo(db, pair, 20, pair.user_id)

    assert get_person_summary(db, pair.household_id, pair.user_id)["shared_count"] == 2


def test_period_filter_limits_the_totals(db, pair):
    _solo(db, pair, 100, pair.user_id, date.today())
    _solo(db, pair, 500, pair.user_id, date.today() - timedelta(days=400))

    recent = get_person_summary(db, pair.household_id, pair.user_id,
                                date.today() - timedelta(days=30), date.today())
    assert recent["my_share"] == 100.0

    everything = get_person_summary(db, pair.household_id, pair.user_id)
    assert everything["my_share"] == 600.0


def test_net_is_all_time_regardless_of_period(db, pair):
    """Settlement position is a running balance; a period filter must not skew it."""
    _shared(db, pair, 100, pair.user_id,
            {pair.user_id: 50, pair.partner_id: 50},
            when=date.today() - timedelta(days=400))

    scoped = get_person_summary(db, pair.household_id, pair.user_id,
                                date.today() - timedelta(days=7), date.today())
    assert scoped["my_share"] == 0.0     # nothing in the window
    assert scoped["net"] == 50.0         # but still owed


def test_breakdown_by_bucket_and_category(db, pair):
    cat = Category(household_id=pair.household_id, name="Food")
    db.add(cat)
    db.flush()
    txn = Transaction(
        bucket_id=pair.bucket_id, household_id=pair.household_id,
        amount=30, currency="EUR", exchange_rate=1, category_id=cat.id,
        type=TransactionType.expense, transaction_date=date.today(),
        paid_by=pair.user_id,
    )
    db.add(txn)
    db.commit()

    s = get_person_summary(db, pair.household_id, pair.user_id)
    assert s["by_bucket"][0]["amount"] == 30.0
    assert s["by_category"][0]["name"] == "Food"


def test_currency_is_converted(db, pair):
    db.add(Transaction(
        bucket_id=pair.bucket_id, household_id=pair.household_id,
        amount=200, currency="USD", exchange_rate=0.5,
        type=TransactionType.expense, transaction_date=date.today(),
        paid_by=pair.user_id,
    ))
    db.commit()
    assert get_person_summary(db, pair.household_id, pair.user_id)["paid_out"] == 100.0


def test_empty_household_does_not_crash(db, authed):
    s = get_person_summary(db, authed.household_id, authed.user_id)
    assert s["paid_out"] == 0.0
    assert s["by_bucket"] == []


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_page_renders(client, db, pair):
    _shared(db, pair, 100, pair.user_id, {pair.user_id: 50, pair.partner_id: 50})
    r = client.get("/me")
    assert r.status_code == 200
    assert "Paid out" in r.text
    assert "My share" in r.text


def test_page_defaults_to_signed_in_user(client, pair):
    r = client.get("/me")
    assert r.status_code == 200
    assert "(you)" in r.text


def test_can_view_another_member(client, db, pair):
    _shared(db, pair, 100, pair.user_id, {pair.user_id: 50, pair.partner_id: 50})
    r = client.get(f"/me?member={pair.partner_id}")
    assert r.status_code == 200
    assert "Partner" in r.text


def test_cannot_view_someone_outside_the_household(client, pair, make_household):
    outsider = make_household(name="Other", username="peekvictim")
    r = client.get(f"/me?member={outsider.user_id}")
    assert r.status_code == 400


def test_period_presets_render(client, pair):
    for preset in ("this_month", "last_month", "this_year", "all_time"):
        assert client.get(f"/me?preset={preset}").status_code == 200


def test_page_requires_auth(client):
    assert client.get("/me").status_code == 302
