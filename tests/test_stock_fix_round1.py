"""
Pantry fix round 1 (stream B review):

- I1: a ticked item stays on /stock/shopping (reason "ticked") after it stops
  being low, so every counted / applied tick has a visible row;
- I2: ticks and one-off lines take an optional client-generated uuid4 ``id``
  so the offline queue can replay creates and address them before the
  server answered;
- I3: the barcode lookup reports ``in_pantry`` on 404 and 503 too, and
  matches by PosoKanei id as well as barcode;
- I4: adjust locks the stock item row before the client_id replay lookup;
- m6: ticked_count ignores a tick on an archived product.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.core.clock import utcnow_naive
from app.models import ShoppingLine, StockItem
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_stock import down, fake  # noqa: F401  (fixtures)
from tests.test_stock_prices import _series

D = Decimal
BARCODE = "5201054017906"


def _item(db, hh, name="Milk", qty="0", min_qty="1", **kw):
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name=name, quantity=D(qty), min_quantity=D(min_qty), **kw
    )
    db.commit()
    return item


@pytest.fixture()
def other(make_household):
    return make_household(name="Other", username="other")


def _shopping(client, headers):
    r = client.get("/api/v1/stock/shopping", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- I1


def test_a_ticked_item_stays_listed_after_it_stops_being_low(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk", qty="0", min_qty="1")
    _series(db, milk.product_id, [1.40], retailer="lidl", end=stock_svc.local_today())
    salt = _item(db, hh, "Salt", qty="0", min_qty="1")  # unpriced
    for i in (milk, salt):
        client.post("/api/v1/stock/shopping/ticks", json={"stock_item_id": i.id}, headers=headers)
    # Someone at home tops both up: neither is low any more.
    for i in (milk, salt):
        client.post(f"/api/v1/stock/{i.id}/adjust", json={"delta": 5}, headers=headers)

    body = _shopping(client, headers)
    rows = {r["name"]: r for r in body["items"]}
    assert set(rows) == {"Milk", "Salt"}
    assert rows["Milk"]["reason"] == "ticked" and rows["Milk"]["ticked"] is True
    assert rows["Salt"]["reason"] == "ticked"
    groups = {g["retailer"]: g["item_ids"] for g in body["groups"]}
    assert groups == {"lidl": [milk.id], None: [salt.id]}
    assert body["unpriced"] == 1
    # The count matches what is listed ...
    listed_ticks = sum(1 for r in body["items"] if r["ticked"])
    assert body["ticked_count"] == listed_ticks == 2
    summary = client.get("/api/v1/stock/summary", headers=headers).json()
    assert summary == {"low_count": 0, "ticked_count": 2}
    # ... and apply-ticked applies exactly the listed ticks.
    r = client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    assert {a["stock_item_id"] for a in r.json()["applied"]} == {
        row["id"] for row in body["items"] if row["ticked"]
    }
    # Applied: no longer ticked, no longer low, so off the list.
    assert _shopping(client, headers)["items"] == []


def test_an_unticked_item_that_is_not_low_is_not_listed(client, db, api):  # noqa: F811
    headers, hh = api
    _item(db, hh, "Rice", qty="5", min_qty="1")
    assert _shopping(client, headers)["items"] == []


def test_low_items_keep_their_reason_when_ticked(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk", qty="0", min_qty="1")
    client.post("/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id}, headers=headers)
    [row] = _shopping(client, headers)["items"]
    assert row["reason"] == "low" and row["ticked"] is True


def test_old_shopping_page_is_unchanged_by_ticks(client, db, authed):
    hh_id = authed.household_id
    rice = stock_svc.add_product(
        db, hh_id, authed.user_id, name="Rice", quantity=D("5"), min_quantity=D("1")
    )
    stock_svc.tick_item(db, hh_id, authed.user_id, rice.id)
    db.commit()
    r = client.get("/stock/shopping")
    assert r.status_code == 200 and "Rice" not in r.text


# ---------------------------------------------------------------- m6


def test_ticked_count_ignores_a_tick_on_an_archived_product(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    client.post("/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id}, headers=headers)
    milk.product.archived_at = utcnow_naive()  # behind the tick's back
    db.commit()
    assert client.get("/api/v1/stock/summary", headers=headers).json()["ticked_count"] == 0
    body = _shopping(client, headers)
    assert body["ticked_count"] == 0 and body["items"] == []


# ---------------------------------------------------------------- I2 ticks


def test_tick_with_a_client_id_is_created_with_it(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    tid = str(uuid.uuid4())
    r = client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id, "id": tid}, headers=headers
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == tid
    # The queue can untick it by that id.
    assert client.delete(f"/api/v1/stock/shopping/ticks/{tid}", headers=headers).status_code == 204


def test_tick_replay_by_id_does_not_duplicate(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    tid = str(uuid.uuid4())
    body = {"stock_item_id": milk.id, "id": tid}
    first = client.post("/api/v1/stock/shopping/ticks", json=body, headers=headers)
    again = client.post("/api/v1/stock/shopping/ticks", json=body, headers=headers)
    assert again.status_code == 201 and again.json() == first.json()
    assert db.query(ShoppingLine).count() == 1


def test_tick_replay_after_apply_does_not_tick_again(client, db, api):  # noqa: F811
    """Review scenario B: a queued tick replayed after someone applied it
    returns the cleared tick unchanged instead of creating a new one."""
    headers, hh = api
    milk = _item(db, hh)
    tid = str(uuid.uuid4())
    body = {"stock_item_id": milk.id, "id": tid}
    client.post("/api/v1/stock/shopping/ticks", json=body, headers=headers)
    client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    r = client.post("/api/v1/stock/shopping/ticks", json=body, headers=headers)
    assert r.status_code == 201 and r.json()["id"] == tid
    assert stock_svc.active_ticks(db, hh.household_id) == {}
    assert client.get("/api/v1/stock/summary", headers=headers).json()["ticked_count"] == 0


def test_tick_with_a_new_id_on_an_already_ticked_item_returns_the_existing_tick(
    client,
    db,
    api,  # noqa: F811
):
    headers, hh = api
    milk = _item(db, hh)
    first = client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id}, headers=headers
    ).json()
    r = client.post(
        "/api/v1/stock/shopping/ticks",
        json={"stock_item_id": milk.id, "id": str(uuid.uuid4())},
        headers=headers,
    )
    assert r.status_code == 201 and r.json() == first
    assert db.query(ShoppingLine).count() == 1


def test_tick_id_from_another_household_is_refused(client, db, api, other):  # noqa: F811
    headers, hh = api
    theirs = _item(db, other, "Theirs")
    their_tick = stock_svc.tick_item(db, other.household_id, other.user_id, theirs.id)
    db.commit()
    mine = _item(db, hh)
    r = client.post(
        "/api/v1/stock/shopping/ticks",
        json={"stock_item_id": mine.id, "id": their_tick.id},
        headers=headers,
    )
    assert r.status_code == 409
    assert theirs.id not in r.text and "Theirs" not in r.text
    assert db.query(ShoppingLine).count() == 1


def test_tick_id_reused_for_another_item_or_a_line_is_refused(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    rice = _item(db, hh, "Rice")
    tid = str(uuid.uuid4())
    client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id, "id": tid}, headers=headers
    )
    r = client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": rice.id, "id": tid}, headers=headers
    )
    assert r.status_code == 409
    line_id = client.post(
        "/api/v1/stock/shopping/lines", json={"name": "Foil"}, headers=headers
    ).json()["id"]
    r = client.post(
        "/api/v1/stock/shopping/ticks",
        json={"stock_item_id": rice.id, "id": line_id},
        headers=headers,
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "bad",
    ["nope", "", "c232ab00-9414-11ec-b3c8-9f6bdeced846", "12345678-1234-1234-1234-123456789012"],
)
def test_tick_id_must_be_a_uuid4(client, db, api, bad):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    r = client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id, "id": bad}, headers=headers
    )
    assert r.status_code == 422


# ---------------------------------------------------------------- I2 lines


def test_line_with_a_client_id_replays_without_duplicating(client, db, api):  # noqa: F811
    headers, _ = api
    lid = str(uuid.uuid4())
    body = {"name": "Bin bags", "quantity": 2, "id": lid}
    first = client.post("/api/v1/stock/shopping/lines", json=body, headers=headers)
    assert first.status_code == 201 and first.json()["id"] == lid
    # Checked in the meantime; the replay returns the row as it is now.
    client.patch(f"/api/v1/stock/shopping/lines/{lid}", json={"checked": True}, headers=headers)
    again = client.post("/api/v1/stock/shopping/lines", json=body, headers=headers)
    assert again.status_code == 201
    assert again.json() == {"id": lid, "name": "Bin bags", "quantity": 2, "checked": True}
    assert db.query(ShoppingLine).count() == 1


def test_line_id_from_another_household_is_refused(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = stock_svc.add_line(db, other.household_id, other.user_id, "Secret foil")
    db.commit()
    r = client.post(
        "/api/v1/stock/shopping/lines", json={"name": "Foil", "id": theirs.id}, headers=headers
    )
    assert r.status_code == 409
    assert "Secret" not in r.text
    assert db.query(ShoppingLine).count() == 1


def test_line_id_of_a_tick_is_refused(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    tick_id = client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": milk.id}, headers=headers
    ).json()["id"]
    r = client.post(
        "/api/v1/stock/shopping/lines", json={"name": "Foil", "id": tick_id}, headers=headers
    )
    assert r.status_code == 409


def test_line_id_must_be_a_uuid4(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(
        "/api/v1/stock/shopping/lines", json={"name": "Foil", "id": "x"}, headers=headers
    )
    assert r.status_code == 422


def test_patch_and_delete_of_an_unknown_id_stay_404(client, api):  # noqa: F811
    headers, _ = api
    lid = str(uuid.uuid4())
    url = f"/api/v1/stock/shopping/lines/{lid}"
    assert client.patch(url, json={"checked": True}, headers=headers).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404
    assert client.delete(f"/api/v1/stock/shopping/ticks/{lid}", headers=headers).status_code == 404


# ---------------------------------------------------------------- I3


def test_barcode_404_carries_in_pantry(client, db, api, fake):  # noqa: F811
    headers, hh = api
    fake.product = None
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 404
    assert r.json() == {"detail": "Product not found", "in_pantry": None}
    milk = _item(db, hh, qty="2", barcode=BARCODE)
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 404
    assert r.json() == {
        "detail": "Product not found",
        "in_pantry": {"stock_item_id": milk.id, "quantity": 2},
    }


def test_barcode_503_carries_in_pantry(client, db, api, down):  # noqa: F811
    headers, hh = api
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 503
    assert r.json() == {"detail": "Prices unavailable", "in_pantry": None}
    milk = _item(db, hh, qty="1", barcode=BARCODE)
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 503
    assert r.json()["in_pantry"] == {"stock_item_id": milk.id, "quantity": 1}
    assert isinstance(r.json()["detail"], str)


def test_barcode_error_bodies_never_show_another_households_item(
    client,
    db,
    api,
    other,
    down,  # noqa: F811
):
    headers, _ = api
    _item(db, other, "Theirs", barcode=BARCODE)
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 503 and r.json()["in_pantry"] is None


def test_barcode_200_matches_by_posokanei_id(client, db, api, fake):  # noqa: F811
    """A pantry item added from search (no barcode) is matched by its
    PosoKanei id."""
    headers, hh = api
    milk = _item(db, hh, posokanei_id="p-1")  # the fake's product id
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.status_code == 200
    assert r.json()["in_pantry"] == {"stock_item_id": milk.id, "quantity": 0}


def test_barcode_posokanei_id_match_is_household_scoped(client, db, api, other, fake):  # noqa: F811
    headers, _ = api
    _item(db, other, "Theirs", posokanei_id="p-1")
    r = client.get(f"/api/v1/products/barcode/{BARCODE}", headers=headers)
    assert r.json()["in_pantry"] is None


def test_barcode_400_is_unchanged(client, api):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/products/barcode/abc", headers=headers)
    assert r.status_code == 400 and set(r.json()) == {"detail"}


# ---------------------------------------------------------------- I4


def test_adjust_locks_the_item_row_before_the_replay_lookup(client, db, api, monkeypatch):  # noqa: F811
    """The row lock comes first, so a concurrent duplicate waits for the
    first adjust to commit and then finds its movement."""
    headers, hh = api
    milk = _item(db, hh, qty="1")
    calls = []
    real_lock, real_find = stock_svc.lock_stock_item, stock_svc.find_adjust_replay

    def lock(*a, **k):
        calls.append("lock")
        return real_lock(*a, **k)

    def find(*a, **k):
        calls.append("find")
        return real_find(*a, **k)

    monkeypatch.setattr(stock_svc, "lock_stock_item", lock)
    monkeypatch.setattr(stock_svc, "find_adjust_replay", find)
    r = client.post(
        f"/api/v1/stock/{milk.id}/adjust", json={"delta": 1, "client_id": "c"}, headers=headers
    )
    assert r.status_code == 200
    assert calls[:2] == ["lock", "find"]


def test_lock_stock_item_is_household_scoped_and_selects_for_update(db, make_household):
    hh = make_household()
    other = make_household(name="Other", username="other")
    milk = _item(db, hh)
    assert stock_svc.lock_stock_item(db, other.household_id, milk.id) is None
    locked = stock_svc.lock_stock_item(db, hh.household_id, milk.id)
    assert isinstance(locked, StockItem) and locked.id == milk.id
    query = stock_svc._lock_query(db, hh.household_id, milk.id)
    sql = str(query.statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
