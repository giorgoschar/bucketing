"""2d §7.3: In and Out by month for six calendar months, lens-aware; the
current month equals in_out for this_month."""

from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.core.clock import local_today
from app.models import Category, Transaction, TransactionSplit, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user


def _txn(
    db,
    hh,
    amount,
    *,
    when,
    kind=TransactionType.expense,
    paid_by=None,
    splits=None,
    category_id=None,
):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=None if kind == TransactionType.income else hh.bucket_id,
        amount=Decimal(amount),
        currency="EUR",
        type=kind,
        paid_by=paid_by or hh.user_id,
        category_id=category_id,
        transaction_date=when,
    )
    db.add(t)
    db.flush()
    for uid, share in (splits or {}).items():
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=Decimal(share)))
    db.commit()
    return t


def test_six_months_oldest_first_current_equals_in_out(client, db, api):  # noqa: F811
    headers, hh = api
    today = local_today()
    two_ago = today.replace(day=1) - relativedelta(months=2)
    _txn(db, hh, "120", when=today)
    _txn(db, hh, "2000", when=today, kind=TransactionType.income)
    _txn(db, hh, "80", when=two_ago)
    body = client.get("/api/v1/insights", headers=headers, params={"preset": "this_month"}).json()
    months = body["monthly_in_out"]
    assert len(months) == 6
    assert (months[-1]["year"], months[-1]["month"]) == (today.year, today.month)
    assert set(months[0]) == {"year", "month", "label", "in", "out", "net"}
    current = months[-1]
    assert (current["in"], current["out"], current["net"]) == (
        body["in_out"]["in"],
        body["in_out"]["out"],
        body["in_out"]["net"],
    )
    assert months[-3]["out"] == 80.0 and months[-3]["in"] == 0.0


def test_it_ignores_the_period_and_follows_the_lens(client, db, api):  # noqa: F811
    headers, hh = api
    maria, _ = _add_member_user(db, hh.household_id, "maria")
    today = local_today()
    _txn(db, hh, "100", when=today, splits={hh.user_id: "30", maria.id: "70"})
    _txn(db, hh, "500", when=today, kind=TransactionType.income, paid_by=maria.id)
    last_month = client.get(
        "/api/v1/insights", headers=headers, params={"preset": "last_month"}
    ).json()["monthly_in_out"]
    assert last_month[-1]["out"] == 100.0  # the period does not move the window
    lens = client.get(
        "/api/v1/insights", headers=headers, params={"preset": "this_month", "paid_by": maria.id}
    ).json()
    assert (lens["monthly_in_out"][-1]["out"], lens["monthly_in_out"][-1]["in"]) == (70.0, 500.0)
    assert lens["monthly_in_out"][-1]["out"] == lens["in_out"]["out"]


def test_category_rows_carry_their_id(client, db, api):  # noqa: F811
    headers, hh = api
    cat = Category(household_id=hh.household_id, name="Groceries")
    db.add(cat)
    db.commit()
    today = local_today()
    _txn(db, hh, "30", when=today, category_id=cat.id)
    _txn(db, hh, "10", when=today - timedelta(days=0))
    rows = client.get("/api/v1/insights", headers=headers).json()["categories"]
    assert {(r["name"], r["category_id"]) for r in rows} == {
        ("Groceries", cat.id),
        ("Uncategorised", None),
    }
