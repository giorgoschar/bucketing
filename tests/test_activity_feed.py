"""GET /api/v1/transactions as the Activity feed (2c spec §5.1; §9 item 11)."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import Transaction, TransactionType
from app.services.cash import FROM_BANK, link_take
from tests.test_api import api  # noqa: F401

URL = "/api/v1/transactions"


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


def test_rows_carry_has_take_and_missing_payer(client, db, api):  # noqa: F811
    headers, hh = api
    cash = add(db, hh, "20.00", payment_method="cash")
    link_take(db, db.get(Transaction, cash), hh.user_id, FROM_BANK, "EUR")
    db.commit()
    nobody = add(db, hh, "5.00", paid_by=None)
    body = client.get(URL, headers=headers).json()
    rows = {r["id"]: r for r in body["items"]}
    assert rows[cash]["has_take"] is True and rows[cash]["missing_payer"] is False
    assert rows[nobody]["missing_payer"] is True and rows[nobody]["has_take"] is False
    assert isinstance(rows[cash]["amount"], float) and rows[cash]["splits"] == []
    one = client.get(f"{URL}/{nobody}", headers=headers).json()
    assert one["missing_payer"] is True and one["id"] == nobody


def test_q_via_http_and_exact_amount(client, db, api):  # noqa: F811
    headers, hh = api
    hit = add(db, hh, "42.50", merchant="Cosmote")
    add(db, hh, "7.00", notes="bakery")
    assert [
        r["id"] for r in client.get(URL, headers=headers, params={"q": "cosmote"}).json()["items"]
    ] == [hit]
    assert [
        r["id"] for r in client.get(URL, headers=headers, params={"q": "42.50"}).json()["items"]
    ] == [hit]


def test_day_totals_are_right_across_pages(client, db, api):  # noqa: F811
    headers, hh = api
    today, yesterday = local_today(), local_today() - timedelta(days=1)
    add(db, hh, "10.00")
    add(db, hh, "5.00")
    add(db, hh, "100.00", type=TransactionType.income, bucket_id=None)
    add(db, hh, "50.00", type=TransactionType.transfer)  # transfers are excluded
    add(db, hh, "7.00", days_ago=1)
    add(db, hh, "100.00", days_ago=1, currency="USD", exchange_rate=Decimal("0.9"))

    p1 = client.get(URL, headers=headers, params={"page_size": 3, "page": 1}).json()
    p2 = client.get(URL, headers=headers, params={"page_size": 3, "page": 2}).json()
    assert p1["total"] == 6 and len(p1["items"]) == 3 and len(p2["items"]) == 3
    assert p1["day_totals"] == {today.isoformat(): 85.0}
    assert p2["day_totals"][today.isoformat()] == 85.0  # same figure on both pages
    assert p2["day_totals"][yesterday.isoformat()] == pytest.approx(-97.0)  # base currency


def test_order_and_paging_limits(client, db, api):  # noqa: F811
    headers, hh = api
    old = add(db, hh, "1.00", days_ago=3)
    new = add(db, hh, "2.00")
    ids = [r["id"] for r in client.get(URL, headers=headers).json()["items"]]
    assert ids == [new, old]
    assert client.get(URL, headers=headers, params={"page_size": 201}).status_code == 422
    assert client.get(URL, headers=headers).json()["page_size"] == 50


@pytest.mark.parametrize(
    "params",
    [
        {"from_date": "yesterday"},
        {"min_amount": "lots"},
        {"type": "bogus"},
        {"payment_method": "cheque"},
        {"year": 2026, "month": 99},
    ],
)
def test_bad_values_are_400(client, api, params):  # noqa: F811
    headers, _ = api
    assert client.get(URL, headers=headers, params=params).status_code == 400


def test_existing_drilldowns_still_work(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, occurrence=False)
    fixed = add(db, hh, "38.90", bucket_id=None, recurring_bill_id=bill.id)
    add(db, hh, "1.00")
    got = client.get(URL, headers=headers, params={"fixed": "true"}).json()["items"]
    assert [r["id"] for r in got] == [fixed]
    got = client.get(URL, headers=headers, params={"recurring_bill_id": bill.id}).json()["items"]
    assert [r["id"] for r in got] == [fixed]


def test_other_households_rows_never_show(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    add(db, other, "38.90", notes="Cosmote")
    assert client.get(URL, headers=headers, params={"q": "Cosmote"}).json()["total"] == 0
