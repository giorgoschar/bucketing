"""TransactionFilter (2c spec §5.1): one filter for the feed and bulk."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import (
    Bucket,
    Category,
    HouseholdMember,
    MemberRole,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.services.transaction_filter import (
    StrictTransactionFilter,
    TransactionFilter,
    apply_filter,
)

D = date(2026, 10, 6)


@pytest.fixture()
def seed(db, make_household):
    hh = make_household()
    hid = hh.household_id
    maria = User(username="maria", display_name="Maria", email="m@example.com", password_hash="x")
    db.add(maria)
    db.flush()
    db.add(HouseholdMember(household_id=hid, user_id=maria.id, role=MemberRole.member))
    outsider = make_household(name="Elsewhere", username="outsider")  # display name "Outsider"
    groceries = Category(household_id=hid, name="Groceries")
    holiday = Bucket(household_id=hid, name="Holiday")
    db.add_all([groceries, holiday])
    db.flush()

    def add(amount, **kw):
        fields = dict(
            household_id=hid,
            bucket_id=hh.bucket_id,
            amount=Decimal(amount),
            type=TransactionType.expense,
            paid_by=hh.user_id,
            payer_mode="single",
            payment_method="card",
            transaction_date=D,
        )
        fields.update(kw)
        t = Transaction(**fields)
        db.add(t)
        db.flush()
        return t.id

    ids = SimpleNamespace(
        notes=add("1.01", notes="Weekly shop"),
        merchant=add("1.02", merchant="Lidl Toumba"),
        category=add("1.03", category_id=groceries.id),
        bucket=add("1.04", bucket_id=holiday.id),
        maria=add("1.05", paid_by=maria.id),
        amount=add("42.50"),
        percent=add("1.06", notes="100% beef"),
        thousand=add("1.07", notes="1000 beef"),
        underscore=add("1.08", notes="a_b"),
        axb=add("1.09", notes="axb"),
        nobody=add("1.10", paid_by=None),
        own=add("1.11", paid_by=None, payer_mode="own_share"),
        income=add("900.00", type=TransactionType.income, bucket_id=None, paid_by=None),
        cash=add("1.12", payment_method="cash", transaction_date=date(2026, 9, 2)),
    )
    db.add(TransactionSplit(transaction_id=ids.notes, user_id=maria.id, amount=Decimal("0.50")))
    db.commit()
    return SimpleNamespace(hh=hh, hid=hid, maria=maria.id, outsider=outsider, ids=ids)


def run(db, seed, **kw) -> set[str]:
    base = db.query(Transaction).filter(Transaction.household_id == seed.hid, Transaction.active())
    return {t.id for t in apply_filter(base, TransactionFilter(**kw), db, seed.hid)}


@pytest.mark.parametrize(
    "term,key",
    [
        ("weekly", "notes"),
        ("LIDL", "merchant"),
        ("grocer", "category"),
        ("holiday", "bucket"),
        ("maria", "maria"),
        ("42.50", "amount"),
    ],
)
def test_each_q_field_hits(db, seed, term, key):
    assert run(db, seed, q=term) == {getattr(seed.ids, key)}


def test_q_ignores_names_of_non_members(db, seed):
    assert run(db, seed, q="Outsider") == set()


def test_q_treats_like_wildcards_literally(db, seed):
    assert run(db, seed, q="100%") == {seed.ids.percent}
    assert run(db, seed, q="a_b") == {seed.ids.underscore}


def test_comma_decimals_in_q_and_amounts(db, seed):
    assert run(db, seed, q="42,50") == {seed.ids.amount}
    assert run(db, seed, min_amount="42,5", type="expense") == {seed.ids.amount}


def test_structured_filters(db, seed):
    ids = seed.ids
    assert run(db, seed, paid_by=seed.maria) == {ids.maria, ids.notes}  # payer or split holder
    assert run(db, seed, missing_payer=True) == {ids.nobody}  # own share is fully paid
    assert run(db, seed, no_bucket=True) == {ids.income}
    assert run(db, seed, payment_method="cash") == {ids.cash}
    assert run(db, seed, type="income") == {ids.income}
    assert ids.cash not in run(db, seed, from_date="2026-10-01", to_date="2026-10-31")
    assert run(db, seed, year=2026, month=9) == {ids.cash}
    assert run(db, seed, min_amount="40", max_amount="50") == {ids.amount}


@pytest.mark.parametrize(
    "kw",
    [
        {"from_date": "07/10/2026"},
        {"to_date": "2026-13-01"},
        {"from_date": "2026-10-07", "to_date": "2026-10-01"},
        {"min_amount": "abc"},
        {"max_amount": "-1"},
        {"max_amount": "1e999999"},
        {"min_amount": "1000000000001"},
        {"type": "bogus"},
        {"payment_method": "cheque"},
        {"year": 2026, "month": 13},
    ],
)
def test_bad_values_are_400(db, seed, kw):
    with pytest.raises(HTTPException) as exc:
        run(db, seed, **kw)
    assert exc.value.status_code == 400


def test_is_empty_and_strict_extra():
    assert TransactionFilter().is_empty()
    assert TransactionFilter(q="  ", bucket_id="").is_empty()  # whitespace counts as blank
    assert TransactionFilter(q="").is_empty()
    assert not TransactionFilter(missing_payer=True).is_empty()
    with pytest.raises(ValueError):
        StrictTransactionFilter(bucket="x")


@pytest.mark.parametrize("term", ["1e999999", "1e13", "-1e999999", "1e-999999", "0.123456"])
def test_q_with_a_huge_or_tiny_number_matches_nothing_and_does_not_fail(db, seed, term):
    assert run(db, seed, q=term) == set()
    assert run(db, seed, min_amount="1e-999999") >= set()  # tiny amounts quantise to 0


def test_amount_at_the_cap_is_accepted(db, seed):
    assert run(db, seed, max_amount="1e12") >= set()
