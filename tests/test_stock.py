"""Stock list: CRUD, HTMX adjust, PosoKanei lookup, isolation, degraded mode."""

from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.integrations import posokanei
from app.integrations.posokanei import (
    PosokaneiUnavailable,
    PriceStats,
    ProductSummary,
    RetailerPrice,
)
from app.models import PriceSnapshot, Product, StockItem, StockMovement
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)


def _summary(pid="p-1", name="Γάλα 1L", barcode="5201054017906", prices=(("ab", "1.59"),)):
    rps = [
        RetailerPrice(
            retailer=r,
            display_name=r.upper(),
            price=Decimal(p),
            unit_price=Decimal(p),
            is_discount=False,
            discount_pct=None,
            last_updated=None,
        )
        for r, p in prices
    ]
    values = [Decimal(p) for _, p in prices]
    return ProductSummary(
        id=pid,
        name=name,
        brand="ΔΕΛΤΑ",
        barcode=barcode,
        unit="l",
        unit_quantity=Decimal("1"),
        image_url=None,
        retailer_prices=rps,
        price_stats=PriceStats(min(values), max(values), None),
    )


class FakeClient:
    def __init__(self, results=(), product=None):
        self.results = list(results)
        self.product = product
        self.calls = []

    def search(self, q, page=1, page_size=20):
        self.calls.append(("search", q))
        return self.results

    def by_barcode(self, code):
        self.calls.append(("barcode", code))
        return self.product

    def get(self, pid, include_history=True):
        self.calls.append(("get", pid))
        if self.product is None:
            raise PosokaneiUnavailable("nope")
        return self.product


class DownClient:
    def search(self, *a, **k):
        raise PosokaneiUnavailable("down")

    by_barcode = get = search


@pytest.fixture()
def fake(monkeypatch):
    client = FakeClient(results=[_summary()], product=_summary())
    monkeypatch.setattr(posokanei, "_client", client)
    return client


@pytest.fixture()
def down(monkeypatch):
    monkeypatch.setattr(posokanei, "_client", DownClient())


def _add(client, authed, **over):
    data = {"name": "Olive oil", "min_quantity": "2", "quantity": "1"}
    data.update(over)
    r = client.post("/stock", data=data, headers=authed.headers)
    assert r.status_code == 303, r.text[:300]
    return r


# ---------------------------------------------------------------- service


def test_add_and_adjust_records_movements(db, make_household):
    hh = make_household()
    item = stock_svc.add_product(
        db,
        hh.household_id,
        hh.user_id,
        name="Rice",
        quantity=Decimal("2"),
        min_quantity=Decimal("1"),
    )
    stock_svc.adjust_stock(db, hh.household_id, item.id, Decimal("-1"), hh.user_id)
    stock_svc.adjust_stock(db, hh.household_id, item.id, Decimal("3"), hh.user_id)
    db.commit()

    assert item.quantity == Decimal("4")
    reasons = [
        (m.reason, m.delta)
        for m in db.query(StockMovement).order_by(StockMovement.created_at, StockMovement.delta)
    ]
    assert ("use", Decimal("-1")) in reasons and ("buy", Decimal("3")) in reasons


def test_adjust_never_goes_negative(db, make_household):
    hh = make_household()
    item = stock_svc.add_product(db, hh.household_id, hh.user_id, name="Rice")
    stock_svc.adjust_stock(db, hh.household_id, item.id, Decimal("-1"), hh.user_id)
    db.commit()
    assert item.quantity == Decimal("0")
    assert db.query(StockMovement).count() == 0  # nothing was actually used


def test_same_barcode_reuses_the_product(db, make_household):
    hh = make_household()
    a = stock_svc.add_product(db, hh.household_id, hh.user_id, name="Milk", barcode="5201054017906")
    stock_svc.archive_product(db, hh.household_id, a.id)
    b = stock_svc.add_product(db, hh.household_id, hh.user_id, name="Milk", barcode="5201054017906")
    db.commit()
    assert a.id == b.id
    assert b.product.archived_at is None
    assert db.query(Product).count() == 1


def test_record_snapshots_is_idempotent_per_day(db, make_household):
    hh = make_household()
    item = stock_svc.add_product(db, hh.household_id, hh.user_id, name="Milk", posokanei_id="p-1")
    s = _summary(prices=(("ab", "1.59"), ("sklavenitis", "1.79")))
    today = local_today()
    assert stock_svc.record_snapshots(db, item.product, s, today) == 2
    assert stock_svc.record_snapshots(db, item.product, s, today) == 0
    db.commit()
    assert db.query(PriceSnapshot).count() == 2


# ---------------------------------------------------------------- pages


def test_stock_page_lists_items(client, authed, db):
    _add(client, authed, name="Olive oil")
    r = client.get("/stock")
    assert r.status_code == 200
    assert "Olive oil" in r.text
    item = db.query(StockItem).one()
    assert item.quantity == Decimal("1") and item.min_quantity == Decimal("2")
    assert item.household_id == authed.household_id


def test_add_requires_a_name(client, authed, db):
    r = client.post("/stock", data={"name": "  "}, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(Product).count() == 0


def test_add_rejects_bad_barcode(client, authed, db):
    r = client.post("/stock", data={"name": "x", "barcode": "12ab"}, headers=authed.headers)
    assert r.status_code == 400


def test_add_requires_csrf(client, authed, db):
    r = client.post("/stock", data={"name": "Rice"}, headers={"Accept": "application/json"})
    assert r.status_code == 403
    assert db.query(Product).count() == 0


def test_htmx_adjust_returns_row(client, authed, db):
    _add(client, authed, name="Pasta", quantity="2")
    item = db.query(StockItem).one()

    r = client.post(
        f"/stock/{item.id}/adjust?delta=-1", headers={**authed.headers, "HX-Request": "true"}
    )
    assert r.status_code == 200
    assert f'id="stock-row-{item.id}"' in r.text
    db.expire_all()
    assert db.get(StockItem, item.id).quantity == Decimal("1")
    mv = db.query(StockMovement).filter_by(reason="use").one()
    assert mv.delta == Decimal("-1") and mv.created_by == authed.user_id

    client.post(f"/stock/{item.id}/adjust?delta=1", headers=authed.headers)
    db.expire_all()
    assert db.get(StockItem, item.id).quantity == Decimal("2")
    assert db.query(StockMovement).filter_by(reason="buy").count() == 1


@pytest.mark.parametrize("delta", ["abc", "0", "1000000", "nan"])
def test_adjust_rejects_bad_delta(client, authed, db, delta):
    _add(client, authed)
    item = db.query(StockItem).one()
    r = client.post(f"/stock/{item.id}/adjust?delta={delta}", headers=authed.headers)
    assert r.status_code == 400


def test_settings_update_min_and_tracking(client, authed, db):
    _add(client, authed)
    item = db.query(StockItem).one()
    r = client.post(
        f"/stock/{item.id}/settings",
        data={"min_quantity": "3", "track_price": ""},
        headers=authed.headers,
    )
    assert r.status_code == 303
    db.expire_all()
    item = db.get(StockItem, item.id)
    assert item.min_quantity == Decimal("3") and item.track_price is False


def test_remove_archives_and_keeps_history(client, authed, db):
    _add(client, authed, name="Coffee")
    item = db.query(StockItem).one()
    db.add(
        PriceSnapshot(
            product_id=item.product_id,
            retailer="ab",
            price=Decimal("3"),
            snapshot_date=local_today(),
        )
    )
    db.commit()

    r = client.post(f"/stock/{item.id}/archive", headers=authed.headers)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Product, item.product_id).archived_at is not None
    assert db.query(PriceSnapshot).count() == 1
    assert db.query(StockMovement).count() >= 1
    assert "Coffee" not in client.get("/stock").text


def test_add_from_posokanei_snapshots_prices(client, authed, db, fake):
    _add(
        client,
        authed,
        name="Γάλα 1L",
        posokanei_id="p-1",
        barcode="5201054017906",
        brand="ΔΕΛΤΑ",
        unit="l",
        unit_quantity="1",
    )
    product = db.query(Product).one()
    assert product.posokanei_id == "p-1" and product.brand == "ΔΕΛΤΑ"
    snaps = db.query(PriceSnapshot).all()
    assert [(s.retailer, s.price) for s in snaps] == [("ab", Decimal("1.59"))]
    page = client.get("/stock").text
    assert "1.59" in page


def test_search_partial_lists_results(client, authed, fake):
    r = client.get("/stock/search", params={"q": "γάλα"}, headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert "Γάλα 1L" in r.text and "ΔΕΛΤΑ" in r.text and "1.59" in r.text
    assert ("search", "γάλα") in fake.calls


def test_barcode_lookup_found_and_not_found(client, authed, fake):
    r = client.get("/stock/barcode", params={"code": "5201054017906"})
    assert r.status_code == 200 and "Γάλα 1L" in r.text
    fake.product = None
    r = client.get("/stock/barcode", params={"code": "5201054017906"})
    assert r.status_code == 200 and "No product found" in r.text


def test_refresh_button_snapshots_prices(client, authed, db, fake):
    _add(client, authed, name="Milk", posokanei_id="p-1")
    db.query(PriceSnapshot).delete()
    db.commit()
    r = client.post(f"/stock/{db.query(StockItem).one().id}/refresh", headers=authed.headers)
    assert r.status_code == 303
    assert db.query(PriceSnapshot).count() == 1


# ---------------------------------------------------------------- degraded mode


def test_page_renders_when_posokanei_is_down(client, authed, db, down):
    _add(client, authed, name="Milk", posokanei_id="p-1")  # add still works
    assert db.query(Product).count() == 1
    r = client.get("/stock")
    assert r.status_code == 200
    assert "Milk" in r.text
    assert "prices unavailable" in r.text.lower()


def test_search_degrades_when_posokanei_is_down(client, authed, down):
    r = client.get("/stock/search", params={"q": "γάλα"})
    assert r.status_code == 200
    assert "prices unavailable" in r.text.lower()
    r = client.get("/stock/barcode", params={"code": "5201054017906"})
    assert r.status_code == 200
    assert "prices unavailable" in r.text.lower()


def test_refresh_degrades_when_posokanei_is_down(client, authed, db, down):
    _add(client, authed, name="Milk", posokanei_id="p-1")
    r = client.post(f"/stock/{db.query(StockItem).one().id}/refresh", headers=authed.headers)
    assert r.status_code == 303
    assert db.query(PriceSnapshot).count() == 0


def test_page_renders_with_posokanei_disabled(client, authed, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "posokanei_enabled", False)
    monkeypatch.setattr(posokanei, "_client", None)
    r = client.get("/stock")
    assert r.status_code == 200
    assert "prices unavailable" in r.text.lower()


# ---------------------------------------------------------------- isolation


def test_other_household_cannot_see_or_touch_stock(client, db, authed, make_household, login):
    _add(client, authed, name="Secret saffron")
    item = db.query(StockItem).one()

    other = make_household(name="Other", username="other")
    client.cookies.clear()
    headers = login(other.username, other.secret)

    assert "Secret saffron" not in client.get("/stock").text
    for path in (
        f"/stock/{item.id}/adjust?delta=1",
        f"/stock/{item.id}/archive",
        f"/stock/{item.id}/refresh",
    ):
        assert client.post(path, headers=headers).status_code == 404, path
    r = client.post(f"/stock/{item.id}/settings", data={"min_quantity": "9"}, headers=headers)
    assert r.status_code == 404

    db.expire_all()
    item = db.get(StockItem, item.id)
    assert item.quantity == Decimal("1") and item.min_quantity == Decimal("2")
    assert item.product.archived_at is None


def test_requires_login(client):
    r = client.get("/stock")
    assert r.status_code in (302, 303, 401)


# ---------------------------------------------------------------- API


def test_api_list_and_adjust(client, db, api, fake):  # noqa: F811
    headers, hh = api
    r = client.post(
        "/api/v1/stock", json={"name": "Flour", "quantity": 2, "min_quantity": 1}, headers=headers
    )
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]

    r = client.get("/api/v1/stock", headers=headers)
    assert r.status_code == 200
    [row] = r.json()
    assert row["name"] == "Flour" and row["quantity"] == 2

    r = client.post(f"/api/v1/stock/{item_id}/adjust", json={"delta": -1}, headers=headers)
    assert r.status_code == 200 and r.json()["quantity"] == 1


def test_api_isolation(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    foreign = stock_svc.add_product(db, other.household_id, other.user_id, name="Theirs")
    db.commit()
    assert client.get("/api/v1/stock", headers=headers).json() == []
    r = client.post(f"/api/v1/stock/{foreign.id}/adjust", json={"delta": 1}, headers=headers)
    assert r.status_code == 404


def test_api_product_lookup_proxies(client, api, fake):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/products/search", params={"q": "γάλα"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body[0]["id"] == "p-1" and body[0]["retailer_prices"][0]["price"] == 1.59
    r = client.get("/api/v1/products/barcode/5201054017906", headers=headers)
    assert r.status_code == 200 and r.json()["barcode"] == "5201054017906"
    fake.product = None
    assert client.get("/api/v1/products/barcode/5201054017906", headers=headers).status_code == 404


def test_api_product_lookup_unavailable(client, api, down):  # noqa: F811
    headers, _ = api
    assert (
        client.get("/api/v1/products/search", params={"q": "xy"}, headers=headers).status_code
        == 503
    )
    assert client.get("/api/v1/products/barcode/123456", headers=headers).status_code == 503


def test_api_product_lookup_requires_auth(client):
    assert client.get("/api/v1/products/search", params={"q": "x"}).status_code == 401


@pytest.mark.parametrize("pid", ["..", ".", "x?a=b#", "a/b", "x" * 65])
def test_unsafe_posokanei_id_rejected_on_web_form(client, authed, db, pid):
    r = client.post("/stock", data={"name": "Milk", "posokanei_id": pid}, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(Product).count() == 0


def test_unsafe_posokanei_id_rejected_on_api(client, db, api):  # noqa: F811
    headers, _ = api
    r = client.post("/api/v1/stock", json={"name": "Milk", "posokanei_id": ".."}, headers=headers)
    assert r.status_code == 400
    assert db.query(Product).count() == 0
