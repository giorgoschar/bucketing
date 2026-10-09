"""
Pantry list API (spec §3.2, §3.3): the richer ``GET /stock`` row, the extra
``POST /stock`` fields with the best-effort PosoKanei snapshot, and
``GET /stock/summary``.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import event

from app.models import PriceSnapshot, Product, StockMovement
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_stock import down, fake  # noqa: F401  (fixtures)
from tests.test_stock_prices import _series

D = Decimal

NEW_KEYS = {
    "unit",
    "unit_quantity",
    "image_url",
    "need_qty",
    "runout_days",
    "advice",
    "ticked",
    "tick_id",
}


def _item(db, hh, name="Milk", qty="1", min_qty="1", **kw):
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name=name, quantity=D(qty), min_quantity=D(min_qty), **kw
    )
    db.commit()
    return item


def _uses(db, item, days_ago_amounts):
    today = stock_svc.local_today()
    for days_ago, amount in days_ago_amounts:
        db.add(
            StockMovement(
                stock_item_id=item.id,
                delta=D(str(-amount)),
                reason="use",
                created_at=datetime.combine(today, time(12)) - timedelta(days=days_ago),
            )
        )
    db.commit()


def _rows(client, headers):
    r = client.get("/api/v1/stock", headers=headers)
    assert r.status_code == 200, r.text
    return {row["name"]: row for row in r.json()}


def test_list_row_has_the_pantry_fields(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk", qty="0", min_qty="1", unit="l", unit_quantity=D("1.5"))
    _item(db, hh, "Rice", qty="5", min_qty="1")
    _series(db, milk.product_id, [1.2] * 10, retailer="ab", end=stock_svc.local_today())

    rows = _rows(client, headers)
    milk_row, rice = rows["Milk"], rows["Rice"]
    assert NEW_KEYS <= set(milk_row)
    assert milk_row["unit"] == "l" and milk_row["unit_quantity"] == 1.5
    assert milk_row["image_url"] is None
    assert milk_row["need_qty"] == 2  # max(1, ceil(2*1 - 0))
    assert milk_row["advice"] == "buy_now"  # flat series: at its 90-day low
    assert milk_row["runout_days"] is None
    assert milk_row["ticked"] is False and milk_row["tick_id"] is None
    assert rice["advice"] == "unknown" and rice["need_qty"] == 1
    assert rice["unit"] is None and rice["unit_quantity"] is None


def test_list_runout_days_is_a_whole_number(client, db, api):  # noqa: F811
    headers, hh = api
    oil = _item(db, hh, "Oil", qty="3", min_qty="0")
    # 4 used over 10 observed days -> 3 * 10 / 4 = 7.5 days
    _uses(db, oil, [(10, 2), (5, 2)])
    row = _rows(client, headers)["Oil"]
    assert row["runout_days"] == 7 and isinstance(row["runout_days"], int)


def test_list_is_not_n_plus_one(client, db, api):  # noqa: F811
    """Advice and run-out come from bulk queries: the statement count does not
    grow with the number of items."""
    headers, hh = api

    def count_for(n_items):
        for i in range(n_items):
            it = _item(db, hh, f"P{n_items}-{i}", qty="0")
            _series(db, it.product_id, [1.0, 1.1], retailer="ab", end=stock_svc.local_today())
        stmts = []

        def _count(*_a, **_k):
            stmts.append(1)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", _count)
        try:
            assert client.get("/api/v1/stock", headers=headers).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", _count)
        return len(stmts)

    few = count_for(2)
    many = count_for(6)
    assert many == few


def test_post_accepts_size_image_and_minimum(client, db, api):  # noqa: F811
    headers, _ = api
    r = client.post(
        "/api/v1/stock",
        json={
            "name": "Feta",
            "brand": "Dodoni",
            "unit": "g",
            "unit_quantity": "400",
            "image_url": "https://img.example/feta.png",
            "quantity": 1,
            "min_quantity": 2,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert NEW_KEYS <= set(body)
    assert body["unit"] == "g" and body["unit_quantity"] == 400
    assert body["image_url"] == "https://img.example/feta.png"
    assert body["min_quantity"] == 2 and body["low"] is True
    assert body["need_qty"] == 3 and body["ticked"] is False
    p = db.query(Product).one()
    assert p.unit_quantity == D("400")


def test_post_rejects_a_bad_size(client, db, api):  # noqa: F811
    headers, _ = api
    r = client.post(
        "/api/v1/stock", json={"name": "Feta", "unit_quantity": "lots"}, headers=headers
    )
    assert r.status_code == 400
    assert db.query(Product).count() == 0


def test_post_with_posokanei_id_snapshots_prices(client, db, api, fake):  # noqa: F811
    headers, _ = api
    r = client.post("/api/v1/stock", json={"name": "Milk", "posokanei_id": "p-1"}, headers=headers)
    assert r.status_code == 201, r.text
    snaps = db.query(PriceSnapshot).all()
    assert [(s.retailer, s.price) for s in snaps] == [("ab", D("1.59"))]
    # Polish S2: the snapshot runs after the reply, so the next fetch has it.
    row = client.get("/api/v1/stock", headers=headers).json()[0]
    assert row["cheapest"]["retailer"] == "ab"
    assert ("get", "p-1") in fake.calls


def test_post_with_posokanei_down_still_adds(client, db, api, down):  # noqa: F811
    headers, _ = api
    r = client.post("/api/v1/stock", json={"name": "Milk", "posokanei_id": "p-1"}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["cheapest"] is None
    assert db.query(PriceSnapshot).count() == 0
    assert db.query(Product).count() == 1


def test_summary_counts_low_items(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    _item(db, hh, "Milk", qty="0", min_qty="1")
    _item(db, hh, "Eggs", qty="1", min_qty="1")  # at the minimum is low
    _item(db, hh, "Rice", qty="5", min_qty="1")
    gone = _item(db, hh, "Old", qty="0", min_qty="1")
    stock_svc.archive_product(db, hh.household_id, gone.id)
    other = make_household(name="Other", username="other")
    _item(db, other, "Theirs", qty="0", min_qty="1")
    db.commit()

    r = client.get("/api/v1/stock/summary", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"low_count": 2, "ticked_count": 0}


def test_summary_requires_auth(client):
    assert client.get("/api/v1/stock/summary").status_code == 401


def test_new_fields_are_household_scoped(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    theirs = _item(db, other, "Theirs", qty="0", min_qty="1")
    _series(db, theirs.product_id, [1.0] * 10, retailer="ab", end=stock_svc.local_today())
    assert client.get("/api/v1/stock", headers=headers).json() == []
    assert client.get("/api/v1/stock/summary", headers=headers).json() == {
        "low_count": 0,
        "ticked_count": 0,
    }
