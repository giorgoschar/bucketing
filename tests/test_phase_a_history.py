"""Phase A S3 (spec §3.5-3.6): GET /recurring/{id}/history and GET /insights/bills."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import event

from app.core.clock import local_today
from app.models import BillOccurrence, OccurrenceStatus, RecurringBill
from tests.test_api import api  # noqa: F401  (fixture)

D = Decimal


def _item(db, household_id, name="Electricity", **over):
    fields = dict(
        household_id=household_id,
        name=name,
        amount=None,
        currency="EUR",
        start_date=date(2020, 1, 1),
        interval_months=1,
        is_active=True,
        usage_unit="kWh",
    )
    fields.update(over)
    item = RecurringBill(**fields)
    db.add(item)
    db.flush()
    return item


def _done(db, item, due, amount, usage=None, status=OccurrenceStatus.paid):
    occ = BillOccurrence(bill_id=item.id, due_date=due, amount=amount, usage=usage, status=status)
    db.add(occ)
    db.flush()
    return occ


def _months_back(n, day=14):
    """The date ``n`` calendar months before this month, on ``day``."""
    t = local_today()
    m = t.year * 12 + t.month - 1 - n
    return date(m // 12, m % 12 + 1, day)


def _recent_series(db, item, amounts, usages=None):
    """Monthly done entries ending this month (or the last one); returns the entries."""
    n = len(amounts)
    out = []
    for i, a in enumerate(amounts):
        due = _months_back(n - 1 - i)
        if due > local_today():  # this month's 14th is still ahead: use today
            due = local_today()
        out.append(_done(db, item, due, a, None if usages is None else usages[i]))
    return out


# ------------------------------------------------------------------ history


def test_history_shape_order_and_unit_price(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id, category_id=None)
    _done(db, item, date(2026, 3, 14), 90, 300)
    _done(db, item, date(2026, 1, 14), 60, 200)
    _done(db, item, date(2026, 2, 14), 70, 0)
    _done(db, item, date(2026, 4, 14), 75)
    _done(db, item, date(2026, 5, 14), 99, status=OccurrenceStatus.unpaid)
    _done(db, item, date(2026, 6, 14), 99, status=OccurrenceStatus.skipped)
    db.commit()
    r = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"] == {
        "id": item.id,
        "name": "Electricity",
        "direction": "out",
        "currency": "EUR",
        "usage_unit": "kWh",
        "category_id": None,
        "is_active": True,
    }
    pts = body["points"]
    assert [p["due_date"] for p in pts] == ["2026-01-14", "2026-02-14", "2026-03-14", "2026-04-14"]
    assert [p["amount"] for p in pts] == [60.0, 70.0, 90.0, 75.0]
    assert [p["usage"] for p in pts] == [200.0, 0.0, 300.0, None]
    assert [p["unit_price"] for p in pts] == [0.3, None, 0.3, None]
    assert set(pts[0]) == {
        "entry_id",
        "due_date",
        "amount",
        "usage",
        "unit_price",
        "transaction_id",
    }
    assert body["change"] is None


def test_unit_price_has_four_places(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    _done(db, item, date(2026, 1, 14), 84, 412)
    db.commit()
    [p] = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers).json()["points"]
    assert p["unit_price"] == 0.2039


def test_history_is_capped_at_the_most_recent_240(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id, rule_kind="weekly", rule_weekday=1)
    start = date(2020, 1, 6)
    for i in range(250):
        _done(db, item, start + timedelta(days=7 * i), 10 + i)
    db.commit()
    pts = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers).json()["points"]
    assert len(pts) == 240
    assert pts[0]["due_date"] == (start + timedelta(days=7 * 10)).isoformat()
    assert pts[-1]["due_date"] == (start + timedelta(days=7 * 249)).isoformat()


def test_history_carries_the_change_of_the_latest_entry(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    entries = _recent_series(db, item, [60, 60, 60, 84], [300, 300, 300, 300])
    db.commit()
    ch = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers).json()["change"]
    assert ch == {
        "entry_id": entries[-1].id,
        "amount": 84.0,
        "usual": 60.0,
        "basis": "recent",
        "delta": 24.0,
        "pct": 40,
        "direction": "up",
        "reason": "price",
        "reason_pct": 40,
    }


def test_history_of_an_item_with_nothing_done(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    db.commit()
    body = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers).json()
    assert body["points"] == [] and body["change"] is None


def test_history_isolation_and_auth(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    foreign = _item(db, other.household_id)
    _done(db, foreign, date(2026, 1, 14), 10)
    db.commit()
    r = client.get(f"/api/v1/recurring/{foreign.id}/history", headers=headers)
    assert r.status_code == 404
    assert client.get("/api/v1/recurring/nope/history", headers=headers).status_code == 404
    assert client.get(f"/api/v1/recurring/{foreign.id}/history").status_code == 401


def test_history_of_an_income_item_has_no_change(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id, name="Salary", direction="in", usage_unit=None)
    _recent_series(db, item, [1000, 1000, 1000, 2000])
    db.commit()
    body = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers).json()
    assert len(body["points"]) == 4 and body["change"] is None


# --------------------------------------------------------------- Bills list

URL = "/api/v1/insights/bills"


def test_bills_list_row_shape(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    entries = _recent_series(db, item, [61, 58.5, 70.2, 84], [300, 290, 330, 400])
    db.commit()
    [row] = client.get(URL, headers=headers).json()
    assert set(row) == {
        "item_id", "name", "category_id", "usage_unit", "is_active", "last", "recent",
        "total_12m", "average_12m", "change",
    }  # fmt: skip
    assert row["item_id"] == item.id and row["usage_unit"] == "kWh" and row["is_active"] is True
    assert row["last"] == {
        "entry_id": entries[-1].id,
        "due_date": entries[-1].due_date.isoformat(),
        "amount": 84.0,
    }
    assert row["recent"] == [61.0, 58.5, 70.2, 84.0]
    assert row["total_12m"] == 273.7 and row["average_12m"] == 68.43
    assert row["change"]["pct"] == 38 and row["change"]["direction"] == "up"


def test_bills_list_recent_is_the_last_twelve(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    _recent_series(db, item, list(range(10, 25)))  # 15 entries
    db.commit()
    [row] = client.get(URL, headers=headers).json()
    assert row["recent"] == [float(x) for x in range(13, 25)]


def test_totals_cover_the_twelve_calendar_months_ending_this_month(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    _done(db, item, _months_back(12), 1000)  # outside
    _done(db, item, _months_back(11, day=1), 10)  # the first day of the window
    _done(db, item, _months_back(0, day=1), 30)
    db.commit()
    [row] = client.get(URL, headers=headers).json()
    assert row["total_12m"] == 40.0 and row["average_12m"] == 20.0
    assert row["recent"] == [1000.0, 10.0, 30.0]


def test_an_item_with_only_old_entries_has_null_totals(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    _done(db, item, _months_back(20), 50)
    db.commit()
    [row] = client.get(URL, headers=headers).json()
    assert row["total_12m"] is None and row["average_12m"] is None and row["last"]["amount"] == 50.0


def test_which_items_are_listed(client, db, api):  # noqa: F811
    headers, hh = api
    active_empty = _item(db, hh.household_id, name="Active, nothing yet")
    paused_with_history = _item(db, hh.household_id, name="Paused with history", is_active=False)
    _done(db, paused_with_history, _months_back(2), 20)
    _item(db, hh.household_id, name="Paused, nothing", is_active=False)
    income = _item(db, hh.household_id, name="Salary", direction="in", usage_unit=None)
    _done(db, income, _months_back(1), 1500)
    unpaid_only = _item(db, hh.household_id, name="Only expected", is_active=False)
    _done(db, unpaid_only, _months_back(1), 5, status=OccurrenceStatus.unpaid)
    db.commit()
    rows = client.get(URL, headers=headers).json()
    names = {r["name"]: r for r in rows}
    assert set(names) == {"Active, nothing yet", "Paused with history"}
    assert names["Active, nothing yet"]["last"] is None
    assert names["Active, nothing yet"]["recent"] == []
    assert names["Paused with history"]["is_active"] is False
    assert active_empty.id == names["Active, nothing yet"]["item_id"]


def test_change_only_within_35_days_of_the_latest_entry(client, db, api):  # noqa: F811
    headers, hh = api
    today = local_today()
    fresh = _item(db, hh.household_id, name="Fresh")
    stale = _item(db, hh.household_id, name="Stale")
    edge = _item(db, hh.household_id, name="Edge")
    just_out = _item(db, hh.household_id, name="Just out")
    for item, age in ((fresh, 2), (stale, 120), (edge, 35), (just_out, 36)):
        for k, a in enumerate((50, 50, 50, 90)):
            _done(db, item, today - timedelta(days=age + 30 * (3 - k)), a)
    db.commit()
    rows = {r["name"]: r for r in client.get(URL, headers=headers).json()}
    assert rows["Fresh"]["change"] is not None
    assert rows["Edge"]["change"] is not None
    assert rows["Stale"]["change"] is None and rows["Just out"]["change"] is None


def test_order_changed_first_then_total_then_name(client, db, api):  # noqa: F811
    headers, hh = api
    spike = _item(db, hh.household_id, name="Zed spike")
    _recent_series(db, spike, [10, 10, 10, 40])  # total 70
    big = _item(db, hh.household_id, name="Big steady")
    _recent_series(db, big, [500, 500, 500, 500])  # total 2000
    b = _item(db, hh.household_id, name="B small")
    _recent_series(db, b, [20, 20, 20, 20])  # total 80
    a = _item(db, hh.household_id, name="A small")
    _recent_series(db, a, [20, 20, 20, 20])  # total 80, ties on name
    empty = _item(db, hh.household_id, name="Empty")
    db.commit()
    names = [r["name"] for r in client.get(URL, headers=headers).json()]
    assert names == ["Zed spike", "Big steady", "A small", "B small", "Empty"]
    assert empty


def test_bills_list_isolation(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    foreign = _item(db, other.household_id, name="Theirs")
    _recent_series(db, foreign, [10, 10, 10, 10])
    mine = _item(db, hh.household_id, name="Mine")
    _recent_series(db, mine, [10, 10, 10, 10])
    db.commit()
    assert [r["name"] for r in client.get(URL, headers=headers).json()] == ["Mine"]
    assert client.get(URL).status_code == 401


def test_bills_list_does_not_shadow_category_detail(client, api):  # noqa: F811
    headers, _ = api
    assert client.get(URL, headers=headers).status_code == 200
    assert (
        client.get("/api/v1/insights/categories/uncategorised", headers=headers).status_code == 200
    )


def _count_queries(db, fn):
    statements = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        fn()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    return len(statements)


def test_query_count_does_not_grow_with_the_number_of_items(client, db, api):  # noqa: F811
    headers, hh = api

    def add_items(first, last):
        for n in range(first, last):
            item = _item(db, hh.household_id, name=f"Bill {n}")
            _recent_series(db, item, [50, 50, 50, 90 + n], [100, 100, 100, 100])
        db.commit()

    add_items(0, 2)
    client.get(URL, headers=headers)  # warm the auth path
    few = _count_queries(db, lambda: client.get(URL, headers=headers))
    add_items(2, 12)
    many = _count_queries(db, lambda: client.get(URL, headers=headers))
    assert len(client.get(URL, headers=headers).json()) == 12
    assert many == few


def test_totals_stop_at_the_end_of_this_month(client, db, api):  # noqa: F811
    headers, hh = api
    item = _item(db, hh.household_id)
    _done(db, item, _months_back(0, day=1), 30)
    _done(db, item, _months_back(-1, day=1), 500)  # paid ahead, due next month
    db.commit()
    [row] = client.get(URL, headers=headers).json()
    assert row["total_12m"] == 30.0 and row["average_12m"] == 30.0


def test_history_point_of_a_deleted_transaction_has_no_link(client, db, api):  # noqa: F811
    from app.core.clock import utcnow_naive
    from app.models import Transaction, TransactionType

    headers, hh = api
    item = _item(db, hh.household_id)
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=D("80"),
        currency="EUR",
        type=TransactionType.expense,
        paid_by=hh.user_id,
        transaction_date=date(2026, 1, 14),
        deleted_at=utcnow_naive(),
    )
    db.add(t)
    db.flush()
    occ = _done(db, item, date(2026, 1, 14), 80)
    occ.transaction_id = t.id
    db.commit()
    [p] = client.get(f"/api/v1/recurring/{item.id}/history", headers=headers).json()["points"]
    assert p["transaction_id"] is None
