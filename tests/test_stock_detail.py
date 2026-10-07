"""
Pantry product detail and its writes (spec §3.2): ``GET/PATCH /stock/{id}``,
refresh, archive, the barcode lookup's ``in_pantry`` and the stepper's
``client_id`` dedupe on adjust (§4.8).
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import utcnow_naive
from app.models import PriceSnapshot, ShoppingLine, StockMovement
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_stock import down, fake  # noqa: F401  (fixtures)

D = Decimal


def _item(db, hh, name="Milk", qty="1", min_qty="1", **kw):
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name=name, quantity=D(qty), min_quantity=D(min_qty), **kw
    )
    db.commit()
    return item


def _snap(db, product_id, retailer, days_ago, price, unit_price=None, discount=False):
    db.add(
        PriceSnapshot(
            product_id=product_id,
            retailer=retailer,
            price=D(str(price)),
            unit_price=D(str(unit_price)) if unit_price is not None else None,
            snapshot_date=stock_svc.local_today() - timedelta(days=days_ago),
            is_discount=discount,
        )
    )
    db.commit()


@pytest.fixture()
def other(make_household):
    return make_household(name="Other", username="other")


# ---------------------------------------------------------------- GET /stock/{id}


def test_detail_prices_today_history_and_advice(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk", qty="0", min_qty="1", unit="l")
    pid = milk.product_id
    # Today: three stores; cheapest unit price first, not cheapest price.
    _snap(db, pid, "ab", 0, "1.59", unit_price="1.59")
    _snap(db, pid, "lidl", 0, "1.20", unit_price="1.60", discount=True)
    _snap(db, pid, "sklavenitis", 0, "1.49", unit_price="1.49")
    # 10 days ago two retailers: the day's point is the lower price.
    _snap(db, pid, "ab", 10, "1.80")
    _snap(db, pid, "lidl", 10, "1.70")
    _snap(db, pid, "ab", 182, "1.99")  # inside the 183-day window
    _snap(db, pid, "ab", 200, "0.50")  # outside it

    r = client.get(f"/api/v1/stock/{milk.id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # The list-item fields are all there.
    assert body["id"] == milk.id and body["name"] == "Milk" and body["unit"] == "l"
    assert body["need_qty"] == 2 and body["low"] is True and body["ticked"] is False

    assert [p["retailer"] for p in body["prices_today"]] == ["sklavenitis", "ab", "lidl"]
    first = body["prices_today"][0]
    assert first == {
        "retailer": "sklavenitis",
        "retailer_name": "Sklavenitis",
        "price": 1.49,
        "unit_price": 1.49,
        "is_discount": False,
    }
    assert body["prices_today"][2]["is_discount"] is True

    today = stock_svc.local_today()
    assert body["history"] == [
        {"date": (today - timedelta(days=182)).isoformat(), "min_price": 1.99},
        {"date": (today - timedelta(days=10)).isoformat(), "min_price": 1.7},
        {"date": today.isoformat(), "min_price": 1.2},
    ]
    assert body["prices_as_of"] == today.isoformat()

    a = body["advice_detail"]
    assert set(a) >= {
        "advice",
        "reason",
        "current_min",
        "median_30d",
        "min_90d",
        "trend_pct_30d",
        "as_of",
    }
    assert a["current_min"] == 1.2 and a["min_90d"] == 1.2
    assert a["as_of"] == today.isoformat()
    assert a["advice"] == body["advice"] == "unknown"  # under 7 days of history


def test_detail_without_prices(client, db, api):  # noqa: F811
    headers, hh = api
    rice = _item(db, hh, "Rice")
    body = client.get(f"/api/v1/stock/{rice.id}", headers=headers).json()
    assert body["prices_today"] == [] and body["history"] == []
    assert body["prices_as_of"] is None and body["cheapest"] is None
    assert body["advice_detail"]["advice"] == "unknown"
    assert body["advice_detail"]["current_min"] is None
    assert body["advice_detail"]["as_of"] is None


def test_detail_foreign_archived_or_unknown_is_404(client, db, api, other):  # noqa: F811
    headers, hh = api
    theirs = _item(db, other, "Theirs")
    gone = _item(db, hh, "Gone")
    stock_svc.archive_product(db, hh.household_id, gone.id)
    db.commit()
    for item_id in (theirs.id, gone.id, "nope"):
        assert client.get(f"/api/v1/stock/{item_id}", headers=headers).status_code == 404


def test_literal_routes_are_not_shadowed_by_the_detail(client, api):  # noqa: F811
    headers, _ = api
    assert client.get("/api/v1/stock/summary", headers=headers).status_code == 200
    assert client.get("/api/v1/stock/shopping", headers=headers).status_code == 200


# ---------------------------------------------------------------- PATCH /stock/{id}


def test_patch_min_and_track(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="2", min_qty="1")
    r = client.patch(f"/api/v1/stock/{milk.id}", json={"min_quantity": 3}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["min_quantity"] == 3 and r.json()["low"] is True
    assert r.json()["track_price"] is True
    r = client.patch(f"/api/v1/stock/{milk.id}", json={"track_price": False}, headers=headers)
    assert r.json()["track_price"] is False and r.json()["min_quantity"] == 3
    db.expire_all()
    item = stock_svc.get_stock_item(db, hh.household_id, milk.id)
    assert item.min_quantity == D("3") and item.track_price is False


@pytest.mark.parametrize("bad", [-1, "lots"])
def test_patch_rejects_a_bad_minimum(client, db, api, bad):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    r = client.patch(f"/api/v1/stock/{milk.id}", json={"min_quantity": bad}, headers=headers)
    assert r.status_code == 422
    db.expire_all()
    assert stock_svc.get_stock_item(db, hh.household_id, milk.id).min_quantity == D("1")


def test_patch_is_household_scoped(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    r = client.patch(f"/api/v1/stock/{theirs.id}", json={"min_quantity": 5}, headers=headers)
    assert r.status_code == 404
    db.expire_all()
    assert stock_svc.get_stock_item(db, other.household_id, theirs.id).min_quantity == D("1")


# ---------------------------------------------------------------- refresh


def test_refresh_snapshots_and_returns_the_detail(client, db, api, fake):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, posokanei_id="p-1")
    r = client.post(f"/api/v1/stock/{milk.id}/refresh", headers=headers)
    assert r.status_code == 200, r.text
    assert [p["retailer"] for p in r.json()["prices_today"]] == ["ab"]
    assert db.query(PriceSnapshot).count() == 1


def test_refresh_503_when_posokanei_is_down(client, db, api, down):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, posokanei_id="p-1")
    r = client.post(f"/api/v1/stock/{milk.id}/refresh", headers=headers)
    assert r.status_code == 503
    assert db.query(PriceSnapshot).count() == 0


def test_refresh_of_an_unlinked_product_returns_the_detail(client, db, api, fake):  # noqa: F811
    headers, hh = api
    rice = _item(db, hh, "Rice")
    r = client.post(f"/api/v1/stock/{rice.id}/refresh", headers=headers)
    assert r.status_code == 200 and r.json()["prices_today"] == []
    assert fake.calls == []


def test_refresh_is_household_scoped(client, db, api, other, fake):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs", posokanei_id="p-1")
    assert client.post(f"/api/v1/stock/{theirs.id}/refresh", headers=headers).status_code == 404
    assert fake.calls == []


# ---------------------------------------------------------------- archive


def test_archive_hides_the_item_and_clears_its_tick(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0")
    tick_id = client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id}, headers=headers
    ).json()["id"]
    r = client.post(f"/api/v1/stock/{milk.id}/archive", headers=headers)
    assert r.status_code == 204 and r.content == b""
    assert client.get("/api/v1/stock", headers=headers).json() == []
    db.expire_all()
    assert db.get(ShoppingLine, tick_id).cleared_at is not None
    assert client.get("/api/v1/stock/summary", headers=headers).json() == {
        "low_count": 0,
        "ticked_count": 0,
    }
    assert client.post(f"/api/v1/stock/{milk.id}/archive", headers=headers).status_code == 404


def test_archive_is_household_scoped(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    assert client.post(f"/api/v1/stock/{theirs.id}/archive", headers=headers).status_code == 404
    db.expire_all()
    assert stock_svc.get_stock_item(db, other.household_id, theirs.id).product.archived_at is None


# ---------------------------------------------------------------- barcode in_pantry


BARCODE = "5201054017906"


def test_barcode_in_pantry_for_a_household_match(client, db, api, fake):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="3", barcode=BARCODE)
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 200
    assert r.json()["in_pantry"] == {"stock_item_id": milk.id, "quantity": 3}
    assert '"quantity":3.0' in r.text


def test_barcode_not_in_pantry(client, db, api, fake):  # noqa: F811
    headers, hh = api
    _item(db, hh, "Other milk", barcode="5201054017999")
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 200 and r.json()["in_pantry"] is None


def test_barcode_never_reports_another_households_item(client, db, api, other, fake):  # noqa: F811
    headers, _ = api
    _item(db, other, "Theirs", barcode=BARCODE)
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.json()["in_pantry"] is None


def test_barcode_ignores_an_archived_item(client, db, api, fake):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, barcode=BARCODE)
    stock_svc.archive_product(db, hh.household_id, milk.id)
    db.commit()
    assert (
        client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers).json()["in_pantry"]
        is None
    )


# ---------------------------------------------------------------- adjust client_id


def _adjust(client, headers, item_id, delta, client_id=None):
    body = {"delta": delta}
    if client_id is not None:
        body["client_id"] = client_id
    return client.post(f"/api/v1/stock/{item_id}/adjust", json=body, headers=headers)


def test_adjust_replay_with_the_same_client_id_applies_once(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="1")
    first = _adjust(client, headers, milk.id, 1, "c-1")
    assert first.status_code == 200 and first.json()["quantity"] == 2
    again = _adjust(client, headers, milk.id, 1, "c-1")  # the reply was lost; the queue retries
    assert again.status_code == 200
    assert again.json() == first.json()
    db.expire_all()
    assert stock_svc.get_stock_item(db, hh.household_id, milk.id).quantity == D("2")
    assert db.query(StockMovement).filter(StockMovement.reason == "buy").count() == 1

    other_id = _adjust(client, headers, milk.id, 1, "c-2")
    assert other_id.json()["quantity"] == 3
    without = _adjust(client, headers, milk.id, -1)
    assert without.json()["quantity"] == 2


def test_adjust_client_id_is_per_household(client, db, api, other):  # noqa: F811
    headers, hh = api
    mine = _item(db, hh, qty="1")
    theirs = _item(db, other, "Theirs", qty="1")
    stock_svc.adjust_stock(
        db, other.household_id, theirs.id, D("1"), other.user_id, client_id="shared"
    )
    db.commit()
    r = _adjust(client, headers, mine.id, 1, "shared")
    assert r.status_code == 200 and r.json()["quantity"] == 2


def test_adjust_client_id_dedupes_within_24h_only(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="1")
    _adjust(client, headers, milk.id, 1, "old")
    move = db.query(StockMovement).filter(StockMovement.client_id == "old").one()
    move.created_at = utcnow_naive() - timedelta(hours=25)
    db.commit()
    r = _adjust(client, headers, milk.id, 1, "old")
    assert r.json()["quantity"] == 3


def test_adjust_client_id_on_another_item_is_409(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="1")
    rice = _item(db, hh, "Rice", qty="1")
    _adjust(client, headers, milk.id, 1, "c-1")
    r = _adjust(client, headers, rice.id, 1, "c-1")
    assert r.status_code == 409
    db.expire_all()
    assert stock_svc.get_stock_item(db, hh.household_id, rice.id).quantity == D("1")


def test_adjust_client_id_is_bounded(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    assert _adjust(client, headers, milk.id, 1, "x" * 65).status_code == 422


# ---------------------------------------------------------------- shopping quantity


def test_shopping_rows_carry_the_current_quantity(client, db, api):  # noqa: F811
    """Controller addition to §3.2: each shopping row has the item's stock
    quantity, a JSON number like /stock's ("Low · 1 left")."""
    headers, hh = api
    _item(db, hh, "Milk", qty="1", min_qty="2")
    r = client.get("/api/v1/stock/shopping", headers=headers)
    [row] = r.json()["items"]
    assert row["quantity"] == 1 and isinstance(row["quantity"], float)
    assert '"quantity":1.0' in r.text
    listed = client.get("/api/v1/stock", headers=headers).json()[0]["quantity"]
    assert row["quantity"] == listed
