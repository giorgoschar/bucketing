"""
Polish S2: editing a pantry item (C2), logging the price you paid (C3),
unticking by item (C4), apply-ticked reading ``before`` under the row lock,
and ``POST /stock`` no longer waiting on PosoKanei.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import PriceSnapshot, Product, ShoppingLine
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user
from tests.test_stock import fake  # noqa: F401  (fixture)
from tests.test_stock_prices import _series

D = Decimal
STOCK = "/api/v1/stock"


def _item(db, hh, name="Milk", qty="1", min_qty="1", **kw):
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name=name, quantity=D(qty), min_quantity=D(min_qty), **kw
    )
    db.commit()
    return item


@pytest.fixture()
def other(make_household):
    return make_household(name="Other", username="other")


def _bearer(hh_id, user_id):
    from app.api_auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user_id, hh_id, 0)}"}


# ---------------------------------------------------------------- C2: edit


def test_patch_edits_every_field(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, brand="Old", unit="l", unit_quantity=D("1"))
    r = client.patch(
        f"{STOCK}/{milk.id}",
        json={
            "name": "  Γάλα πλήρες  ",
            "brand": "ΔΕΛΤΑ",
            "unit": "ml",
            "unit_quantity": "500",
            "barcode": "5201054017906",
            "min_quantity": "2",
            "track_price": False,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Γάλα πλήρες"
    assert body["brand"] == "ΔΕΛΤΑ" and body["unit"] == "ml" and body["unit_quantity"] == 500
    assert body["barcode"] == "5201054017906"
    assert body["min_quantity"] == 2 and body["track_price"] is False
    assert body["id"] == milk.id and "cheapest" in body and "tick_id" in body  # the list row
    db.expire_all()
    p = db.get(Product, milk.product_id)
    assert (p.name, p.brand, p.unit, p.unit_quantity, p.barcode) == (
        "Γάλα πλήρες",
        "ΔΕΛΤΑ",
        "ml",
        D("500"),
        "5201054017906",
    )


def test_patch_leaves_omitted_fields_and_clears_nulls(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, brand="ΔΕΛΤΑ", unit="l", unit_quantity=D("1"), barcode="5201054017906")
    r = client.patch(f"{STOCK}/{milk.id}", json={"name": "Milk 2"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["brand"] == "ΔΕΛΤΑ" and r.json()["barcode"] == "5201054017906"
    r = client.patch(
        f"{STOCK}/{milk.id}",
        json={"brand": None, "unit": "", "unit_quantity": None, "barcode": ""},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["brand"], body["unit"], body["unit_quantity"], body["barcode"]) == (
        None,
        None,
        None,
        None,
    )
    assert body["name"] == "Milk 2"


def test_patch_settings_only_still_work(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    r = client.patch(f"{STOCK}/{milk.id}", json={"min_quantity": "3"}, headers=headers)
    assert r.status_code == 200 and r.json()["min_quantity"] == 3 and r.json()["name"] == "Milk"


@pytest.mark.parametrize("name", ["", "   ", "x" * 201, None])
def test_patch_rejects_a_bad_name(client, db, api, name):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    r = client.patch(f"{STOCK}/{milk.id}", json={"name": name}, headers=headers)
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.get(Product, milk.product_id).name == "Milk"


@pytest.mark.parametrize(
    "body", [{"unit_quantity": "0"}, {"unit_quantity": "-1"}, {"barcode": "12ab"}]
)
def test_patch_rejects_bad_size_or_barcode(client, db, api, body):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    assert client.patch(f"{STOCK}/{milk.id}", json=body, headers=headers).status_code == 422


def test_patch_barcode_used_by_another_product_is_409(client, db, api):  # noqa: F811
    headers, hh = api
    _item(db, hh, "Feta", barcode="5201054017906")
    milk = _item(db, hh)
    r = client.patch(f"{STOCK}/{milk.id}", json={"barcode": "5201054017906"}, headers=headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Another product already has this barcode"
    db.expire_all()
    assert db.get(Product, milk.product_id).barcode is None


def test_patch_barcode_of_an_archived_product_is_also_409(client, db, api):  # noqa: F811
    headers, hh = api
    old = _item(db, hh, "Feta", barcode="5201054017906")
    stock_svc.archive_product(db, hh.household_id, old.id)
    db.commit()
    milk = _item(db, hh)
    r = client.patch(f"{STOCK}/{milk.id}", json={"barcode": "5201054017906"}, headers=headers)
    assert r.status_code == 409


def test_patch_keeping_its_own_barcode_is_fine(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, barcode="5201054017906")
    r = client.patch(
        f"{STOCK}/{milk.id}", json={"barcode": "5201054017906", "name": "M"}, headers=headers
    )
    assert r.status_code == 200, r.text


def test_patch_barcode_used_in_another_household_is_fine(client, db, api, other):  # noqa: F811
    headers, hh = api
    _item(db, other, "Theirs", barcode="5201054017906")
    milk = _item(db, hh)
    r = client.patch(f"{STOCK}/{milk.id}", json={"barcode": "5201054017906"}, headers=headers)
    assert r.status_code == 200 and r.json()["barcode"] == "5201054017906"


def test_patch_another_households_item_is_404(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    r = client.patch(f"{STOCK}/{theirs.id}", json={"name": "Mine now"}, headers=headers)
    assert r.status_code == 404
    db.expire_all()
    assert db.get(Product, theirs.product_id).name == "Theirs"


# ---------------------------------------------------------------- C3: prices


def _price(client, headers, item_id, **body):
    return client.post(f"{STOCK}/{item_id}/prices", json=body, headers=headers)


def test_retailers_endpoint(client, api):  # noqa: F811
    headers, _ = api
    r = client.get(f"{STOCK}/retailers", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert all(set(row) == {"code", "name"} for row in rows)
    assert rows[-1] == {"code": "other", "name": "Other"}
    codes = [row["code"] for row in rows]
    assert "sklavenitis" in codes and "ab" in codes and "lidl" in codes
    names = [row["name"] for row in rows[:-1]]
    assert names == sorted(names, key=str.casefold) and len(names) == len(set(names))


def test_manual_price_is_the_lists_cheapest_and_in_history(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    r = _price(client, headers, milk.id, price=1.29, retailer="lidl")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == milk.id and "prices_today" in body  # the detail
    assert body["prices_today"][0]["retailer"] == "lidl"
    assert body["prices_today"][0]["retailer_name"] == "Lidl"
    assert body["prices_today"][0]["price"] == 1.29
    assert body["history"] == [{"date": local_today().isoformat(), "min_price": 1.29}]
    snap = db.query(PriceSnapshot).one()
    assert snap.source == "manual" and snap.snapshot_date == local_today()

    row = next(i for i in client.get(STOCK, headers=headers).json() if i["id"] == milk.id)
    assert row["cheapest"]["retailer"] == "lidl" and row["cheapest"]["price"] == 1.29


def test_manual_price_beats_a_dearer_posokanei_price_the_same_day(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, unit="l", unit_quantity=D("1"))
    _series(db, milk.product_id, [1.79], retailer="ab", end=local_today())
    r = _price(client, headers, milk.id, price="1.49", retailer="sklavenitis")
    assert r.status_code == 201, r.text
    assert r.json()["cheapest"]["retailer"] == "sklavenitis"
    assert [p["retailer"] for p in r.json()["prices_today"]] == ["sklavenitis", "ab"]
    snap = db.query(PriceSnapshot).filter_by(retailer="sklavenitis").one()
    assert snap.unit_price == D("1.49")  # per litre, like PosoKanei's


def test_manual_unit_price_per_kg_from_grams(client, db, api):  # noqa: F811
    headers, hh = api
    feta = _item(db, hh, "Feta", unit="g", unit_quantity=D("400"))
    assert _price(client, headers, feta.id, price="4", retailer="ab").status_code == 201
    assert db.query(PriceSnapshot).one().unit_price == D("10")


def test_second_entry_the_same_day_upserts(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    assert _price(client, headers, milk.id, price=1.29, retailer="lidl").status_code == 201
    r = _price(client, headers, milk.id, price="1,19", retailer="lidl")
    assert r.status_code == 201, r.text
    snaps = db.query(PriceSnapshot).all()
    assert len(snaps) == 1 and snaps[0].price == D("1.19")
    assert r.json()["prices_today"][0]["price"] == 1.19


def test_a_past_date_and_other_store(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    day = local_today() - timedelta(days=3)
    r = _price(client, headers, milk.id, price=2, retailer="other", date=day.isoformat())
    assert r.status_code == 201, r.text
    snap = db.query(PriceSnapshot).one()
    assert (snap.snapshot_date, snap.retailer, snap.source) == (day, "other", "manual")
    assert r.json()["history"] == [{"date": day.isoformat(), "min_price": 2}]
    assert r.json()["prices_today"][0]["retailer_name"] == "Other"


def test_a_future_date_is_422(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    tomorrow = (local_today() + timedelta(days=1)).isoformat()
    r = _price(client, headers, milk.id, price=1, retailer="lidl", date=tomorrow)
    assert r.status_code == 422
    assert db.query(PriceSnapshot).count() == 0


@pytest.mark.parametrize(
    "body",
    [
        {"price": 1, "retailer": "walmart"},
        {"price": 1, "retailer": ""},
        {"price": 0, "retailer": "lidl"},
        {"price": -2, "retailer": "lidl"},
        {"price": "abc", "retailer": "lidl"},
        {"price": 1e9, "retailer": "lidl"},
        {"retailer": "lidl"},
        {"price": 1, "retailer": "lidl", "date": "yesterday"},
    ],
)
def test_bad_price_bodies_are_422(client, db, api, body):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    assert _price(client, headers, milk.id, **body).status_code == 422
    assert db.query(PriceSnapshot).count() == 0


def test_price_for_another_households_item_is_404(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    assert _price(client, headers, theirs.id, price=1, retailer="lidl").status_code == 404
    assert db.query(PriceSnapshot).count() == 0


def test_posokanei_snapshots_default_to_their_source(db, make_household):
    hh = make_household()
    milk = _item(db, hh)
    _series(db, milk.product_id, [1.5])
    db.expire_all()
    assert db.query(PriceSnapshot).one().source == "posokanei"


# ---------------------------------------------------------------- C4: untick by item


def _tick(client, headers, item_id):
    r = client.post(f"{STOCK}/shopping/ticks", json={"stock_item_id": item_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_untick_by_item_removes_another_members_tick(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0")
    partner, _ = _add_member_user(db, hh.household_id, "flatmate")
    _tick(client, _bearer(hh.household_id, partner.id), milk.id)
    r = client.delete(f"{STOCK}/shopping/ticks", params={"stock_item_id": milk.id}, headers=headers)
    assert r.status_code == 204
    assert db.query(ShoppingLine).count() == 0


def test_untick_by_item_is_idempotent(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0")
    _tick(client, headers, milk.id)
    for _ in range(2):
        r = client.delete(
            f"{STOCK}/shopping/ticks", params={"stock_item_id": milk.id}, headers=headers
        )
        assert r.status_code == 204
    r = client.delete(f"{STOCK}/shopping/ticks", params={"stock_item_id": "nope"}, headers=headers)
    assert r.status_code == 204


def test_untick_by_item_leaves_one_off_lines_and_cleared_ticks(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0")
    _tick(client, headers, milk.id)
    assert client.post(f"{STOCK}/shopping/apply-ticked", headers=headers).status_code == 200
    client.post(f"{STOCK}/shopping/lines", json={"name": "Foil"}, headers=headers)
    r = client.delete(f"{STOCK}/shopping/ticks", params={"stock_item_id": milk.id}, headers=headers)
    assert r.status_code == 204
    assert db.query(ShoppingLine).count() == 2  # the cleared tick (history) and Foil


def test_untick_by_item_needs_the_item(client, api):  # noqa: F811
    headers, _ = api
    assert client.delete(f"{STOCK}/shopping/ticks", headers=headers).status_code == 422


def test_untick_by_item_is_household_scoped(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs", qty="0")
    _tick(client, _bearer(other.household_id, other.user_id), theirs.id)
    r = client.delete(
        f"{STOCK}/shopping/ticks", params={"stock_item_id": theirs.id}, headers=headers
    )
    assert r.status_code == 204
    assert db.query(ShoppingLine).count() == 1  # theirs survives


def test_untick_by_id_is_unchanged(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0")
    tick_id = _tick(client, headers, milk.id)
    assert client.delete(f"{STOCK}/shopping/ticks/{tick_id}", headers=headers).status_code == 204
    assert client.delete(f"{STOCK}/shopping/ticks/{tick_id}", headers=headers).status_code == 404


# ---------------------------------------------------------------- apply-ticked


def test_apply_ticked_reads_before_after_taking_the_lock(db, make_household, monkeypatch):
    """``before`` is read from the locked, freshly read row: a quantity
    changed by someone else since this session loaded the item counts."""
    hh = make_household()
    milk = _item(db, hh, qty="1")
    stock_svc.tick_item(db, hh.household_id, hh.user_id, milk.id, D("2"))
    db.commit()
    assert milk.quantity == 1  # loaded in this session's identity map

    real_lock = stock_svc.lock_stock_item
    seen = []

    def lock_after_a_concurrent_change(db_, hh_id, item_id):
        # Another request committed 5 just before this one took the lock.
        db_.execute(
            stock_svc.StockItem.__table__.update()
            .where(stock_svc.StockItem.id == item_id)
            .values(quantity=D("5"))
        )
        seen.append(item_id)
        return real_lock(db_, hh_id, item_id)

    monkeypatch.setattr(stock_svc, "lock_stock_item", lock_after_a_concurrent_change)
    result = stock_svc.apply_ticked(db, hh.household_id, hh.user_id)
    assert seen and result["applied"][0]["before"] == D("5")
    assert result["applied"][0]["after"] == D("7")


# ---------------------------------------------------------------- POST /stock


def test_post_stock_does_not_wait_on_posokanei(client, db, api, fake, monkeypatch):  # noqa: F811
    """The PosoKanei snapshot runs as a background task with its own session:
    the reply is built first (no prices yet), the snapshot lands right after."""
    headers, _ = api
    order = []
    real_get = fake.get

    def get(pid, include_history=True):
        order.append("posokanei")
        return real_get(pid, include_history)

    monkeypatch.setattr(fake, "get", get)
    from app.api import stock as stock_api

    real_payloads = stock_api._payloads

    def payloads(*a, **k):
        order.append("reply")
        return real_payloads(*a, **k)

    monkeypatch.setattr(stock_api, "_payloads", payloads)
    r = client.post(STOCK, json={"name": "Milk", "posokanei_id": "p-1"}, headers=headers)
    assert r.status_code == 201, r.text
    assert order == ["reply", "posokanei"]
    assert r.json()["cheapest"] is None
    # The background task has run by the time TestClient returns.
    assert [(s.retailer, s.price) for s in db.query(PriceSnapshot).all()] == [("ab", D("1.59"))]
    row = client.get(STOCK, headers=headers).json()[0]
    assert row["cheapest"]["retailer"] == "ab"
