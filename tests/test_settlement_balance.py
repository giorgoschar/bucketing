"""
Settlement arithmetic must balance.

Every expense has to be fully attributed to somebody. When it is not, the
per-member nets stop summing to zero, balances get inflated, and the suggested
transfers become nonsense — which is exactly what was reported.
"""
from datetime import date

import pyotp
import pytest

from app.auth import hash_password
from app.models import (
    Bucket, HouseholdMember, MemberRole, Transaction, TransactionSplit,
    TransactionType, User,
)
from app.services import (
    compute_bucket_net, get_bucket_settlement, get_member_balances,
    get_person_summary, shares_for,
)
from tests.conftest import PASSWORD


@pytest.fixture()
def pair(db, authed):
    partner = User(
        username="partner", display_name="Partner", email="p@example.com",
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


def _expense(db, ctx, amount, payer, splits=(), bucket_id=None):
    t = Transaction(
        bucket_id=bucket_id or ctx.bucket_id, household_id=ctx.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date.today(), paid_by=payer,
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


# ---------------------------------------------------------------------------
# shares_for
# ---------------------------------------------------------------------------

def test_partial_splits_leave_the_remainder_with_the_payer(db, pair):
    """"You owe me 50 of this 100" logged as one 50 split.

    The other 50 used to be attributed to nobody.
    """
    t = _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])
    shares = shares_for(t)
    assert shares[pair.partner_id] == 50.0
    assert shares[pair.user_id] == 50.0
    assert round(sum(shares.values()), 2) == 100.0


def test_full_splits_are_untouched(db, pair):
    t = _expense(db, pair, 100, pair.user_id,
                 [(pair.user_id, 40), (pair.partner_id, 60)])
    shares = shares_for(t)
    assert shares[pair.user_id] == 40.0
    assert shares[pair.partner_id] == 60.0


def test_unsplit_expense_falls_to_the_payer(db, pair):
    t = _expense(db, pair, 80, pair.user_id)
    assert shares_for(t) == {pair.user_id: 80.0}


def test_unsplit_expense_divides_among_members_when_asked(db, pair):
    t = _expense(db, pair, 80, pair.user_id)
    shares = shares_for(t, {pair.user_id, pair.partner_id})
    assert shares[pair.user_id] == 40.0
    assert shares[pair.partner_id] == 40.0


def test_shares_always_sum_to_the_total(db, pair):
    for amount, splits in [
        (100, [(None, 50)]),          # partial
        (100, [(None, 100)]),         # full, other person only
        (100, []),                    # none
        (99.99, [(None, 33.33)]),     # awkward remainder
    ]:
        resolved = [(pair.partner_id if uid is None else uid, amt) for uid, amt in splits]
        t = _expense(db, pair, amount, pair.user_id, resolved)
        assert round(sum(shares_for(t).values()), 2) == round(amount, 2)


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------

def test_nets_sum_to_zero_with_partial_splits(db, pair):
    """The invariant the reported bug violated."""
    _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])
    net = compute_bucket_net(db, pair.bucket_id)
    assert round(sum(net.values()), 2) == 0.0
    assert net[pair.user_id] == 50.0
    assert net[pair.partner_id] == -50.0


def test_nets_sum_to_zero_across_mixed_expenses(db, pair):
    _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])          # partial
    _expense(db, pair, 60, pair.partner_id,
             [(pair.user_id, 30), (pair.partner_id, 30)])                    # full
    _expense(db, pair, 40, pair.user_id)                                     # unsplit
    net = compute_bucket_net(db, pair.bucket_id)
    assert round(sum(net.values()), 2) == 0.0


def test_household_balances_sum_to_zero(db, pair):
    _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])
    balances = get_member_balances(db, pair.household_id)
    assert round(sum(b["net"] for b in balances), 2) == 0.0


def test_suggested_transfer_matches_the_real_debt(db, pair):
    _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])
    rows = get_bucket_settlement(db, pair.bucket_id)
    assert len(rows) == 1
    assert rows[0]["from_id"] == pair.partner_id
    assert rows[0]["to_id"] == pair.user_id
    assert rows[0]["amount"] == 50.0


def test_person_share_agrees_with_settlement(db, pair):
    """"My share" and the settlement position must tell the same story."""
    _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])

    mine = get_person_summary(db, pair.household_id, pair.user_id)
    theirs = get_person_summary(db, pair.household_id, pair.partner_id)

    assert mine["paid_out"] == 100.0
    assert mine["my_share"] == 50.0     # not 0, despite having no split row
    assert theirs["my_share"] == 50.0
    assert round(mine["my_share"] + theirs["my_share"], 2) == 100.0
    assert mine["net"] == 50.0
    assert theirs["net"] == -50.0


def test_splits_exceeding_the_total_still_balance(db, pair):
    """Bad legacy data must not break the books."""
    _expense(db, pair, 100, pair.user_id,
             [(pair.user_id, 80), (pair.partner_id, 80)])
    net = compute_bucket_net(db, pair.bucket_id)
    assert round(sum(net.values()), 2) == 0.0


def test_trip_per_person_sums_to_the_trip_total(db, pair):
    from app.models import BucketType
    from app.services import get_trip_summary

    bucket = db.get(Bucket, pair.bucket_id)
    bucket.type = BucketType.trip
    db.commit()
    _expense(db, pair, 100, pair.user_id, [(pair.partner_id, 50)])
    _expense(db, pair, 40, pair.partner_id)

    trip = get_trip_summary(db, bucket)
    assert round(sum(p["amount"] for p in trip["per_person"]), 2) == trip["total"]
