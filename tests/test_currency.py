"""
Multi-currency aggregation.

Transaction.amount is denominated in Transaction.currency; exchange_rate
converts it to the household's default currency. The rate was stored but never
applied, so totals added raw amounts across currencies.
"""
from datetime import date

import pytest

from app.models import Transaction, TransactionSplit, TransactionType
from app.services import (
    get_bucket_balance,
    get_bucket_settlement,
    get_insights_category_breakdown,
    get_insights_summary,
    get_month_summary,
    get_monthly_trend,
    to_base,
)


@pytest.fixture()
def mixed(db, authed):
    """EUR 100 plus USD 100 at rate 0.5 => 150 in household currency."""
    today = date.today()
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=100, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=today,
        paid_by=authed.user_id,
    ))
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=100, currency="USD", exchange_rate=0.5,
        type=TransactionType.expense, transaction_date=today,
        paid_by=authed.user_id,
    ))
    db.commit()
    return authed


def test_to_base_applies_the_rate():
    assert to_base(100, 0.5) == 50.0
    assert to_base(100, 1) == 100.0
    assert to_base(100, None) == 100.0   # missing rate is a no-op, not a crash
    assert to_base(None, 2) == 0.0


def test_month_summary_converts(db, mixed):
    today = date.today()
    s = get_month_summary(db, mixed.household_id, today.year, today.month)
    assert s["total_spent"] == 150.0


def test_insights_summary_converts(db, mixed):
    s = get_insights_summary(db, mixed.household_id, None, None)
    assert s["total_spent"] == 150.0


def test_paid_by_breakdown_converts(db, mixed):
    s = get_insights_summary(db, mixed.household_id, None, None)
    assert s["paid_by"][mixed.user_id]["amount"] == 150.0


def test_bucket_balance_converts(db, mixed):
    b = get_bucket_balance(db, mixed.bucket_id)
    assert b["expenses"] == 150.0


def test_monthly_trend_converts(db, mixed):
    trend = get_monthly_trend(db, mixed.household_id, n_months=1)
    assert trend[-1]["total"] == 150.0


def test_category_breakdown_converts(db, mixed):
    rows = get_insights_category_breakdown(db, mixed.household_id, None, None)
    assert round(sum(r["amount"] for r in rows), 2) == 150.0


def test_income_converts(db, authed):
    from app.services import get_insights_income

    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=200, currency="USD", exchange_rate=0.5,
        type=TransactionType.income, transaction_date=date.today(),
    ))
    db.commit()
    assert get_insights_income(db, authed.household_id, None, None) == 100.0


def test_settlement_converts(db, authed, make_household):
    """A foreign-currency expense must not distort who owes whom."""
    from app.models import Bucket, HouseholdMember, MemberRole, User
    from app.auth import hash_password
    import pyotp

    partner = User(username="partner", display_name="Partner",
                   email="p@example.com", password_hash=hash_password("x"),
                   totp_secret=pyotp.random_base32(), totp_enabled=True)
    db.add(partner)
    db.flush()
    db.add(HouseholdMember(household_id=authed.household_id, user_id=partner.id,
                           role=MemberRole.member))
    bucket = db.get(Bucket, authed.bucket_id)
    bucket.enable_settlement = True

    # authed fronts USD 100 (= 50 base) split evenly: partner owes 25.
    txn = Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=100, currency="USD", exchange_rate=0.5,
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

    settlements = get_bucket_settlement(db, authed.bucket_id)
    assert len(settlements) == 1
    # 25 in base currency, not the unconverted 50.
    assert settlements[0]["amount"] == 25.0


def test_dashboard_totals_reflect_conversion(client, mixed):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "150" in r.text
