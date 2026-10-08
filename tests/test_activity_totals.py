"""GET /api/v1/transactions/totals (polish C1): count, Out and In over every
row the Activity filter matches, in household currency, as one aggregate."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core.clock import local_today, utcnow_naive
from app.models import Category, Transaction, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/transactions/totals"


def add(db, hh, amount, *, days_ago=0, **kw) -> str:
    fields = dict(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=Decimal(amount),
        type=TransactionType.expense,
        paid_by=hh.user_id,
        transaction_date=local_today() - timedelta(days=days_ago),
    )
    fields.update(kw)
    t = Transaction(**fields)
    db.add(t)
    db.commit()
    return t.id


def totals(client, headers, **params):
    r = client.get(URL, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_no_filter_counts_and_sums_every_active_row(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "10.00")
    add(db, hh, "5.50", days_ago=40)
    add(db, hh, "100.00", type=TransactionType.income, bucket_id=None)
    add(db, hh, "50.00", type=TransactionType.transfer)  # counted, in neither sum
    body = totals(client, headers)
    assert body == {"count": 4, "out": 15.5, "in": 100.0}
    assert isinstance(body["out"], float) and isinstance(body["in"], float)


def test_empty_household_is_all_zero(client, api):  # noqa: F811
    headers, _ = api
    assert totals(client, headers) == {"count": 0, "out": 0.0, "in": 0.0}


def test_category_filter(client, db, api):  # noqa: F811
    headers, hh = api
    cat = Category(household_id=hh.household_id, name="Groceries")
    db.add(cat)
    db.commit()
    add(db, hh, "12.00", category_id=cat.id)
    add(db, hh, "3.00", category_id=cat.id)
    add(db, hh, "99.00")
    assert totals(client, headers, category_id=cat.id) == {"count": 2, "out": 15.0, "in": 0.0}


def test_search_text(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "42.50", merchant="Cosmote")
    add(db, hh, "7.00", notes="bakery")
    add(db, hh, "20.00", type=TransactionType.income, bucket_id=None, notes="cosmote refund")
    assert totals(client, headers, q="cosmote") == {"count": 2, "out": 42.5, "in": 20.0}


def test_date_range(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "1.00", days_ago=10)
    add(db, hh, "2.00", days_ago=5)
    add(db, hh, "4.00", days_ago=0)
    start = (local_today() - timedelta(days=6)).isoformat()
    end = (local_today() - timedelta(days=1)).isoformat()
    assert totals(client, headers, from_date=start, to_date=end) == {
        "count": 1,
        "out": 2.0,
        "in": 0.0,
    }


def test_income_and_expense_split_by_type_filter(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "30.00")
    add(db, hh, "200.00", type=TransactionType.income, bucket_id=None)
    add(db, hh, "50.00", type=TransactionType.income, bucket_id=None)
    assert totals(client, headers) == {"count": 3, "out": 30.0, "in": 250.0}
    assert totals(client, headers, type="income") == {"count": 2, "out": 0.0, "in": 250.0}
    assert totals(client, headers, type="expense") == {"count": 1, "out": 30.0, "in": 0.0}


def test_soft_deleted_rows_are_excluded(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "10.00")
    add(db, hh, "90.00", deleted_at=utcnow_naive())
    assert totals(client, headers) == {"count": 1, "out": 10.0, "in": 0.0}


def test_foreign_currency_is_converted(client, db, api):  # noqa: F811
    headers, hh = api
    add(db, hh, "100.00", currency="USD", exchange_rate=Decimal("0.9"))
    add(db, hh, "10.00")
    body = totals(client, headers)
    assert body["count"] == 2
    assert body["out"] == pytest.approx(100.0)  # 90 + 10, household currency


def test_household_isolation(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other")
    add(db, other, "500.00")
    add(db, other, "70.00", type=TransactionType.income, bucket_id=None)
    add(db, hh, "1.00")
    assert totals(client, headers) == {"count": 1, "out": 1.0, "in": 0.0}


def test_bad_filter_is_a_400_like_the_feed(client, api):  # noqa: F811
    headers, _ = api
    r = client.get(URL, headers=headers, params={"from_date": "nope"})
    assert r.status_code == 400


def test_one_aggregate_whatever_the_row_count(client, db, api):  # noqa: F811
    headers, hh = api
    for i in range(12):
        add(db, hh, f"{i + 1}.00", days_ago=i)
        add(db, hh, "3.00", type=TransactionType.income, bucket_id=None, days_ago=i)

    stmts = []

    def _count(_conn, _cursor, statement, *_a, **_k):
        stmts.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        body = totals(client, headers, q="", type="")
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert body == {"count": 24, "out": 78.0, "in": 36.0}
    assert len(stmts) <= 3, stmts
