"""
Shopping list ticks, one-off lines and apply-ticked (spec §3.1, §3.2).

A tick marks a computed shopping-list item as picked up; it never touches
stock until apply-ticked, and nothing here ever touches transactions.
"""

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.clock import utcnow_naive
from app.models import ShoppingLine, StockMovement, Transaction
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_stock_prices import _series

D = Decimal


def _item(db, hh, name="Milk", qty="0", min_qty="1"):
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name=name, quantity=D(qty), min_quantity=D(min_qty)
    )
    db.commit()
    return item


@pytest.fixture()
def other(make_household):
    return make_household(name="Other", username="other")


def _tick(client, headers, item_id, **extra):
    return client.post(
        "/api/v1/stock/shopping/ticks", json={"stock_item_id": item_id, **extra}, headers=headers
    )


def _line(client, headers, name="Bin bags", **extra):
    return client.post(
        "/api/v1/stock/shopping/lines", json={"name": name, **extra}, headers=headers
    )


# ---------------------------------------------------------------- ticks


def test_tick_defaults_to_need_qty_and_is_idempotent(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0", min_qty="1")
    r = _tick(client, headers, milk.id)
    assert r.status_code == 201, r.text
    tick = r.json()
    assert set(tick) == {"id", "stock_item_id", "quantity"}
    assert tick["stock_item_id"] == milk.id and tick["quantity"] == 2  # need_qty

    again = _tick(client, headers, milk.id, quantity=5)
    assert again.status_code == 201
    assert again.json() == tick  # the existing tick, unchanged
    assert db.query(ShoppingLine).count() == 1
    # A tick never changes stock.
    db.refresh(milk)
    assert milk.quantity == 0 and db.query(StockMovement).count() == 0


def test_tick_with_a_quantity(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    r = _tick(client, headers, milk.id, quantity="3")
    assert r.status_code == 201 and r.json()["quantity"] == 3


@pytest.mark.parametrize("qty", ["0", "-1", "lots"])
def test_tick_rejects_a_bad_quantity(client, db, api, qty):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    assert _tick(client, headers, milk.id, quantity=qty).status_code == 422
    assert db.query(ShoppingLine).count() == 0


def test_tick_foreign_archived_or_unknown_item_is_404(client, db, api, other):  # noqa: F811
    headers, hh = api
    theirs = _item(db, other, "Theirs")
    gone = _item(db, hh, "Gone")
    stock_svc.archive_product(db, hh.household_id, gone.id)
    db.commit()
    for item_id in (theirs.id, gone.id, "nope"):
        assert _tick(client, headers, item_id).status_code == 404, item_id
    assert db.query(ShoppingLine).count() == 0


def test_untick_deletes_the_tick(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    tick_id = _tick(client, headers, milk.id).json()["id"]
    r = client.delete(f"/api/v1/stock/shopping/ticks/{tick_id}", headers=headers)
    assert r.status_code == 204
    assert db.query(ShoppingLine).count() == 0
    assert (
        client.delete(f"/api/v1/stock/shopping/ticks/{tick_id}", headers=headers).status_code == 404
    )
    # It can be ticked again.
    assert _tick(client, headers, milk.id).status_code == 201


def test_untick_is_household_scoped(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    tick = stock_svc.tick_item(db, other.household_id, other.user_id, theirs.id)
    db.commit()
    r = client.delete(f"/api/v1/stock/shopping/ticks/{tick.id}", headers=headers)
    assert r.status_code == 404
    assert db.query(ShoppingLine).count() == 1


def test_untick_does_not_delete_a_one_off_line(client, db, api):  # noqa: F811
    headers, _ = api
    line_id = _line(client, headers).json()["id"]
    r = client.delete(f"/api/v1/stock/shopping/ticks/{line_id}", headers=headers)
    assert r.status_code == 404


def test_one_active_tick_per_item_in_the_database(db, make_household):
    hh = make_household()
    milk = _item(db, hh)
    first = stock_svc.tick_item(db, hh.household_id, hh.user_id, milk.id)
    db.commit()
    db.add(
        ShoppingLine(
            household_id=hh.household_id,
            stock_item_id=milk.id,
            quantity=D("1"),
            checked_at=utcnow_naive(),
            created_at=utcnow_naive(),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # A cleared tick does not count: the item can be ticked again.
    first.cleared_at = utcnow_naive()
    db.commit()
    second = stock_svc.tick_item(db, hh.household_id, hh.user_id, milk.id)
    db.commit()
    assert second.id != first.id


def test_archive_clears_the_active_tick(db, make_household):
    hh = make_household()
    milk = _item(db, hh)
    tick = stock_svc.tick_item(db, hh.household_id, hh.user_id, milk.id)
    db.commit()
    stock_svc.archive_product(db, hh.household_id, milk.id)
    db.commit()
    db.refresh(tick)
    assert tick.cleared_at is not None
    assert stock_svc.active_ticks(db, hh.household_id) == {}


# ---------------------------------------------------------------- one-off lines


def test_line_create_check_uncheck_delete(client, db, api):  # noqa: F811
    headers, _ = api
    r = _line(client, headers, name="  Bin bags ", quantity="2")
    assert r.status_code == 201, r.text
    line = r.json()
    assert line == {"id": line["id"], "name": "Bin bags", "quantity": 2, "checked": False}
    assert '"quantity":2.0' in r.text

    url = f"/api/v1/stock/shopping/lines/{line['id']}"
    r = client.patch(url, json={"checked": True}, headers=headers)
    assert r.status_code == 200 and r.json()["checked"] is True
    r = client.patch(url, json={"checked": False}, headers=headers)
    assert r.status_code == 200 and r.json()["checked"] is False

    assert client.delete(url, headers=headers).status_code == 204
    assert db.query(ShoppingLine).count() == 0
    assert client.delete(url, headers=headers).status_code == 404


def test_line_without_quantity(client, api):  # noqa: F811
    headers, _ = api
    r = _line(client, headers, name="Foil")
    assert r.status_code == 201 and r.json()["quantity"] is None


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_line_needs_a_name(client, db, api, name):  # noqa: F811
    headers, _ = api
    assert _line(client, headers, name=name).status_code == 422
    assert db.query(ShoppingLine).count() == 0


def test_line_rejects_a_bad_quantity(client, db, api):  # noqa: F811
    headers, _ = api
    assert _line(client, headers, quantity="-2").status_code == 422


def test_lines_are_household_scoped(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = stock_svc.add_line(db, other.household_id, other.user_id, "Their foil")
    db.commit()
    url = f"/api/v1/stock/shopping/lines/{theirs.id}"
    assert client.patch(url, json={"checked": True}, headers=headers).status_code == 404
    assert client.delete(url, headers=headers).status_code == 404
    db.refresh(theirs)
    assert theirs.checked_at is None
    assert client.get("/api/v1/stock/shopping", headers=headers).json()["lines"] == []


def test_patch_does_not_check_a_tick_row(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh)
    tick_id = _tick(client, headers, milk.id).json()["id"]
    r = client.patch(
        f"/api/v1/stock/shopping/lines/{tick_id}", json={"checked": False}, headers=headers
    )
    assert r.status_code == 404
    assert (
        client.delete(f"/api/v1/stock/shopping/lines/{tick_id}", headers=headers).status_code == 404
    )


# ---------------------------------------------------------------- apply-ticked


def test_apply_ticked_adds_stock_and_clears(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk", qty="0", min_qty="1")
    oil = _item(db, hh, "Olive oil", qty="1", min_qty="1")
    _tick(client, headers, milk.id)  # need 2
    _tick(client, headers, oil.id, quantity=1)
    bags = _line(client, headers, name="Bin bags").json()
    foil = _line(client, headers, name="Foil").json()
    client.patch(
        f"/api/v1/stock/shopping/lines/{bags['id']}", json={"checked": True}, headers=headers
    )
    txns = db.query(Transaction).count()

    r = client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cleared_lines"] == 1
    applied = {a["name"]: a for a in body["applied"]}
    assert applied["Milk"]["before"] == 0 and applied["Milk"]["after"] == 2
    assert applied["Olive oil"]["before"] == 1 and applied["Olive oil"]["after"] == 2
    assert applied["Milk"]["stock_item_id"] == milk.id
    assert '"before":0.0' in r.text

    db.expire_all()
    assert db.get(type(milk), milk.id).quantity == 2
    moves = {(m.stock_item_id, m.reason, m.delta) for m in db.query(StockMovement)}
    assert (milk.id, "buy", D("2")) in moves and (oil.id, "buy", D("1")) in moves
    # Ticks and the checked line are cleared; the unchecked line stays.
    active = db.query(ShoppingLine).filter(ShoppingLine.cleared_at.is_(None)).all()
    assert [a.id for a in active] == [foil["id"]]
    # Never a transaction.
    assert db.query(Transaction).count() == txns

    again = client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    assert again.status_code == 200
    assert again.json() == {"applied": [], "cleared_lines": 0}
    db.expire_all()
    assert db.get(type(milk), milk.id).quantity == 2
    assert db.query(Transaction).count() == txns


def test_apply_ticked_clears_an_archived_items_tick_without_adjusting(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="0")
    tick_id = _tick(client, headers, milk.id).json()["id"]
    # Archived behind the tick's back (not through archive_product).
    milk.product.archived_at = utcnow_naive()
    db.commit()

    r = client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json() == {"applied": [], "cleared_lines": 0}
    db.expire_all()
    assert db.get(ShoppingLine, tick_id).cleared_at is not None
    assert db.get(type(milk), milk.id).quantity == 0
    assert db.query(StockMovement).count() == 0


def test_apply_ticked_is_household_scoped(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    stock_svc.tick_item(db, other.household_id, other.user_id, theirs.id)
    line = stock_svc.add_line(db, other.household_id, other.user_id, "Their foil")
    stock_svc.set_line_checked(db, other.household_id, line.id, True)
    db.commit()
    r = client.post("/api/v1/stock/shopping/apply-ticked", json={}, headers=headers)
    assert r.json() == {"applied": [], "cleared_lines": 0}
    db.expire_all()
    assert db.get(type(theirs), theirs.id).quantity == 0
    assert db.query(ShoppingLine).filter(ShoppingLine.cleared_at.is_(None)).count() == 2


def test_apply_ticked_requires_auth(client):
    assert client.post("/api/v1/stock/shopping/apply-ticked", json={}).status_code == 401
    assert client.post("/api/v1/stock/shopping/lines", json={"name": "x"}).status_code == 401
    assert (
        client.post("/api/v1/stock/shopping/ticks", json={"stock_item_id": "x"}).status_code == 401
    )


# ---------------------------------------------------------------- reads


def test_shopping_carries_ticks_lines_and_counts(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk", qty="0", min_qty="1")
    _item(db, hh, "Salt", qty="0", min_qty="1")  # unpriced
    item_milk = stock_svc.get_stock_item(db, hh.household_id, milk.id)
    item_milk.product.unit = "l"
    db.commit()
    _series(db, milk.product_id, [1.40], retailer="lidl", end=stock_svc.local_today())
    tick = _tick(client, headers, milk.id).json()
    line = _line(client, headers, name="Foil", quantity=1).json()
    client.patch(
        f"/api/v1/stock/shopping/lines/{line['id']}", json={"checked": True}, headers=headers
    )
    _line(client, headers, name="Bags")

    body = client.get("/api/v1/stock/shopping", headers=headers).json()
    assert body["unpriced"] == 1
    assert body["ticked_count"] == 2  # one tick + one checked line
    rows = {r["name"]: r for r in body["items"]}
    assert rows["Milk"]["unit"] == "l" and rows["Milk"]["need_qty"] == 2
    assert rows["Milk"]["ticked"] is True and rows["Milk"]["tick_id"] == tick["id"]
    assert rows["Salt"]["ticked"] is False and rows["Salt"]["tick_id"] is None
    lines = {ln["name"]: ln for ln in body["lines"]}
    assert set(lines) == {"Foil", "Bags"}
    assert lines["Foil"] == {"id": line["id"], "name": "Foil", "quantity": 1, "checked": True}
    assert lines["Bags"]["checked"] is False and lines["Bags"]["quantity"] is None


def test_stock_list_and_summary_carry_ticks(client, db, api):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, "Milk")
    _item(db, hh, "Rice", qty="5")
    tick = _tick(client, headers, milk.id).json()
    line = _line(client, headers).json()
    client.patch(
        f"/api/v1/stock/shopping/lines/{line['id']}", json={"checked": True}, headers=headers
    )
    _line(client, headers, name="unchecked")

    rows = {r["name"]: r for r in client.get("/api/v1/stock", headers=headers).json()}
    assert rows["Milk"]["ticked"] is True and rows["Milk"]["tick_id"] == tick["id"]
    assert rows["Rice"]["ticked"] is False and rows["Rice"]["tick_id"] is None
    assert client.get("/api/v1/stock/summary", headers=headers).json() == {
        "low_count": 1,
        "ticked_count": 2,
    }


def test_reads_ignore_other_households_ticks(client, db, api, other):  # noqa: F811
    headers, _ = api
    theirs = _item(db, other, "Theirs")
    stock_svc.tick_item(db, other.household_id, other.user_id, theirs.id)
    stock_svc.add_line(db, other.household_id, other.user_id, "Their foil")
    db.commit()
    assert client.get("/api/v1/stock/summary", headers=headers).json()["ticked_count"] == 0
    body = client.get("/api/v1/stock/shopping", headers=headers).json()
    assert body["lines"] == [] and body["ticked_count"] == 0
