"""
Characterization tests for the de-duplicated services (Task 2.4).

get_category_breakdown / get_bucket_budget_status / record_bucket_settlement
were near-copies of the insights / household versions. These pin the numbers
the surviving functions produce for the inputs the deleted ones used to serve
(a calendar month), so the merge cannot quietly change them.
"""
from datetime import date
from decimal import Decimal

import pytest

from app import services
from app.models import Bucket, Category, Settlement, Transaction, TransactionType


def _txn(db, ctx, amount, when, *, category_id=None, bucket_id=None, rate=1,
         excluded=False, kind=TransactionType.expense):
    db.add(Transaction(
        bucket_id=bucket_id or ctx.bucket_id, household_id=ctx.household_id,
        amount=amount, currency="EUR", exchange_rate=rate,
        type=kind, transaction_date=when, category_id=category_id,
        paid_by=ctx.user_id, exclude_from_forecast=excluded,
    ))


@pytest.fixture()
def month_data(db, authed):
    food = Category(household_id=authed.household_id, name="Food", icon="🍔", color="#f00")
    fun = Category(household_id=authed.household_id, name="Fun", icon="🎉", color="#0f0")
    db.add_all([food, fun])
    db.flush()
    _txn(db, authed, 40, date(2026, 3, 1), category_id=food.id)
    _txn(db, authed, 20.10, date(2026, 3, 31), category_id=food.id)
    _txn(db, authed, 30, date(2026, 3, 15), category_id=fun.id, rate=2)    # 60 base
    _txn(db, authed, 7.5, date(2026, 3, 16))                                # uncategorised
    _txn(db, authed, 99, date(2026, 3, 17), category_id=fun.id, excluded=True)
    _txn(db, authed, 500, date(2026, 2, 28), category_id=food.id)           # other month
    _txn(db, authed, 500, date(2026, 4, 1), category_id=food.id)            # other month
    _txn(db, authed, 1000, date(2026, 3, 10), kind=TransactionType.income)
    deleted = Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id, amount=77,
        currency="EUR", exchange_rate=1, type=TransactionType.expense,
        transaction_date=date(2026, 3, 20), category_id=food.id, paid_by=authed.user_id,
    )
    db.add(deleted)
    db.flush()
    services.delete_transaction(db, deleted)
    db.commit()
    authed.food_id, authed.fun_id = food.id, fun.id
    return authed


def test_category_breakdown_for_a_month(db, month_data):
    rows = services.get_insights_category_breakdown(
        db, month_data.household_id, date(2026, 3, 1), date(2026, 3, 31), limit=6,
    )
    assert [(r["name"], r["amount"], r["pct"]) for r in rows] == [
        # Fun includes the 99 one-off purchase: actual spend counts it.
        ("Fun", Decimal("159.00"), Decimal("70.2")),
        ("Food", Decimal("60.10"), Decimal("26.5")),
        ("Uncategorised", Decimal("7.50"), Decimal("3.3")),
    ]


def test_budget_status_for_a_month(db, month_data):
    bucket = db.get(Bucket, month_data.bucket_id)
    bucket.budget = 100
    db.commit()
    rows = services.get_insights_budget_status(
        db, month_data.household_id, date(2026, 3, 1), date(2026, 3, 31),
    )
    assert len(rows) == 1
    r = rows[0]
    # One-off (99) counts toward budget spend; the deleted (77) expense does not.
    assert (r["spent"], r["budget"], r["pct"], r["pct_actual"], r["remaining"], r["over_budget"]) == (
        Decimal("226.60"), Decimal("100.00"), 100, Decimal("226.6"), Decimal("-126.60"), True,
    )


def test_bucket_settlement_records_against_the_bucket(db, authed):
    from tests.test_household_settlement import _add_member, _shared_expense
    partner = _add_member(db, authed.household_id, "partner").id
    db.get(Bucket, authed.bucket_id).enable_settlement = True
    _shared_expense(db, authed.bucket_id, authed.household_id,
                    authed.user_id, [authed.user_id, partner], 90)
    db.commit()

    created = services.record_household_settlement(
        db, authed.household_id, bucket_id=authed.bucket_id, created_by=authed.user_id,
    )
    db.commit()
    assert [(s.bucket_id, s.from_user_id, s.to_user_id, float(s.amount)) for s in created] == [
        (authed.bucket_id, partner, authed.user_id, 45.0),
    ]
    assert db.query(Settlement).count() == 1
    assert services.get_bucket_settlement(db, authed.bucket_id) == []

