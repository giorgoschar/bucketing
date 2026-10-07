"""
Wire shape of the stock API as it was before Pantry gave it Pydantic response
models (written and run against the untouched code first).

Pantry only adds keys: every key below must stay, with the same JSON type.
Numbers stay numbers with FastAPI's Decimal encoding (a whole Decimal such as
``need_qty`` is a JSON integer, ``Numeric(10, 2)`` values are floats), so the
raw text is pinned too, not just the parsed value.
"""

from decimal import Decimal

import pytest

from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_stock import fake  # noqa: F401  (fixture)
from tests.test_stock_prices import _series


def _type(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int | float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _check(obj, types):
    """Every pinned key is present with an allowed type (new keys may join)."""
    assert set(types) <= set(obj), set(types) - set(obj)
    for k, allowed in types.items():
        assert _type(obj[k]) in allowed, (k, obj[k])


ITEM = {
    "id": {"string"},
    "product_id": {"string"},
    "name": {"string"},
    "brand": {"string", "null"},
    "barcode": {"string", "null"},
    "posokanei_id": {"string", "null"},
    "quantity": {"number"},
    "min_quantity": {"number"},
    "track_price": {"boolean"},
    "low": {"boolean"},
    "cheapest": {"object", "null"},
}
CHEAPEST = {
    "retailer": {"string"},
    "retailer_name": {"string"},
    "price": {"number"},
    "unit_price": {"number", "null"},
    "is_discount": {"boolean"},
    "date": {"string"},
}
SHOP_ROW = {
    "id": {"string"},
    "name": {"string"},
    "need_qty": {"number"},
    "reason": {"string"},
    "runout_days_estimate": {"number", "null"},
    "retailer": {"string", "null"},
    "retailer_name": {"string", "null"},
    "price": {"number", "null"},
    "line_total": {"number", "null"},
    "advice": {"string"},
    "advice_reason": {"string", "null"},
    "trend_pct_30d": {"number", "null"},
}
GROUP = {
    "retailer": {"string", "null"},
    "retailer_name": {"string", "null"},
    "total": {"number"},
    "item_ids": {"array"},
}
BEST_STORE = {
    "retailer": {"string"},
    "retailer_name": {"string"},
    "total": {"number"},
    "covers": {"number"},
    "missing": {"number"},
}
PRODUCT = {
    "id": {"string"},
    "name": {"string"},
    "brand": {"string", "null"},
    "barcode": {"string", "null"},
    "unit": {"string", "null"},
    "unit_quantity": {"number", "null"},
    "image_url": {"string", "null"},
    "retailer_prices": {"array"},
    "price_stats": {"object"},
    "history": {"array"},
}
RETAILER_PRICE = {
    "retailer": {"string"},
    "display_name": {"string"},
    "price": {"number", "null"},
    "unit_price": {"number", "null"},
    "is_discount": {"boolean"},
    "discount_pct": {"number", "null"},
    "last_updated": {"string", "null"},
}
PRICE_STATS = {"min": {"number", "null"}, "max": {"number", "null"}, "avg": {"number", "null"}}


@pytest.fixture()
def flour(client, db, api, fake):  # noqa: F811
    headers, hh = api
    r = client.post(
        "/api/v1/stock",
        json={"name": "Flour", "quantity": 0, "min_quantity": 1, "posokanei_id": "p-1"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    item = stock_svc.get_stock_item(db, hh.household_id, r.json()["id"])
    _series(db, item.product_id, [1.40, 1.5], retailer="lidl", end=stock_svc.local_today())
    return headers, r


def test_post_stock_shape(flour):
    _headers, r = flour
    body = r.json()
    _check(body, ITEM)
    assert '"quantity":0.0' in r.text and '"min_quantity":1.0' in r.text
    assert body["low"] is True and body["track_price"] is True


def test_list_stock_shape(client, flour):
    headers, _ = flour
    r = client.get("/api/v1/stock", headers=headers)
    assert r.status_code == 200
    [row] = r.json()
    _check(row, ITEM)
    _check(row["cheapest"], CHEAPEST)
    assert row["cheapest"]["retailer"] == "lidl" and row["cheapest"]["price"] == 1.5
    assert len(row["cheapest"]["date"]) == 10
    assert '"quantity":0.0' in r.text


def test_adjust_shape(client, flour):
    headers, r = flour
    r = client.post(f"/api/v1/stock/{r.json()['id']}/adjust", json={"delta": 1}, headers=headers)
    assert r.status_code == 200
    _check(r.json(), ITEM)
    _check(r.json()["cheapest"], CHEAPEST)
    assert '"quantity":1.0' in r.text


def test_shopping_shape(client, flour):
    headers, _ = flour
    r = client.get("/api/v1/stock/shopping", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert {"items", "groups", "best_single_store", "total"} <= set(body)
    assert _type(body["total"]) == "number"
    [row] = body["items"]
    _check(row, SHOP_ROW)
    [group] = body["groups"]
    _check(group, GROUP)
    _check(body["best_single_store"], BEST_STORE)
    # need_qty is a whole Decimal: a JSON integer; money is a float.
    assert '"need_qty":2,' in r.text and '"line_total":3.0' in r.text
    assert '"covers":1,' in r.text and '"missing":0' in r.text


def test_shopping_shape_when_empty(client, api):  # noqa: F811
    headers, _ = api
    body = client.get("/api/v1/stock/shopping", headers=headers).json()
    assert body["items"] == [] and body["groups"] == []
    assert body["best_single_store"] is None and body["total"] == 0


def _check_product(p):
    _check(p, PRODUCT)
    for rp in p["retailer_prices"]:
        _check(rp, RETAILER_PRICE)
    _check(p["price_stats"], PRICE_STATS)


def test_product_search_shape(client, api, fake):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/products/search", params={"q": "γάλα"}, headers=headers)
    assert r.status_code == 200
    [p] = r.json()
    _check_product(p)
    assert '"unit_quantity":1,' in r.text and '"price":1.59' in r.text


def test_product_barcode_shape(client, api, fake):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/products/barcode/5201054017906", headers=headers)
    assert r.status_code == 200
    _check_product(r.json())
    assert '"unit_quantity":1,' in r.text


def test_product_history_points_keep_their_shape(client, api, fake):  # noqa: F811
    from app.integrations.posokanei import PricePoint
    from tests.test_stock import _summary

    s = _summary()
    fake.product = type(s)(
        **{
            **s.__dict__,
            "history": [PricePoint("2026-09-01", "ab", Decimal("1.5"), None, True)],
        }
    )
    headers, _ = api
    [point] = client.get("/api/v1/products/barcode/5201054017906", headers=headers).json()[
        "history"
    ]
    assert point == {
        "date": "2026-09-01",
        "retailer": "ab",
        "price": 1.5,
        "unit_price": None,
        "is_discount": True,
    }
