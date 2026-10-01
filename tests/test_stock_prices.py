"""Price advice, run-out prediction and the shopping list.

Price series are synthetic: one snapshot per day per retailer, written
straight into price_snapshots so each scenario is exact.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from app.models import Category, PriceSnapshot, StockItem, StockMovement
from app.services import stock as stock_svc

TODAY = date(2026, 10, 1)
D = Decimal


@pytest.fixture()
def hh(make_household):
    return make_household()


def _item(db, hh, name="Milk", qty="1", min_qty="1"):
    item = stock_svc.add_product(db, hh.household_id, hh.user_id, name=name,
                                 quantity=D(qty), min_quantity=D(min_qty))
    db.commit()
    return item


def _series(db, product_id, prices, retailer="ab", discount_last=False, end=TODAY):
    """prices[-1] is today's price; earlier entries are the preceding days."""
    n = len(prices)
    for i, p in enumerate(prices):
        db.add(PriceSnapshot(
            product_id=product_id, retailer=retailer, price=D(str(p)),
            unit_price=D(str(p)), snapshot_date=end - timedelta(days=n - 1 - i),
            is_discount=discount_last and i == n - 1,
        ))
    db.commit()


def _uses(db, item, days_ago_amounts):
    for days_ago, amount in days_ago_amounts:
        db.add(StockMovement(stock_item_id=item.id, delta=D(str(-amount)), reason="use",
                             created_at=datetime.combine(TODAY, time(12)) - timedelta(days=days_ago)))
    db.commit()


# ---------------------------------------------------------------- price_advice


def test_flat_series_is_at_its_low_so_buy_now(db, hh):
    item = _item(db, hh)
    _series(db, item.product_id, [2.00] * 30)
    a = stock_svc.price_advice(db, item.product, TODAY)
    assert a["advice"] == "buy_now"
    assert a["current_min"] == D("2.00")
    assert a["median_30d"] == D("2.00") and a["min_90d"] == D("2.00")
    assert a["trend_pct_30d"] == D("0.0")
    assert a["reason"]


def test_dipping_series_says_buy_now_and_trends_down(db, hh):
    item = _item(db, hh)
    _series(db, item.product_id, [2.00] * 29 + [1.70], discount_last=True)
    a = stock_svc.price_advice(db, item.product, TODAY)
    assert a["advice"] == "buy_now"
    assert a["current_min"] == D("1.70")
    assert a["trend_pct_30d"] < 0


def test_rising_series_says_wait_and_trends_up(db, hh):
    item = _item(db, hh)
    prices = [round(1.00 + 0.02 * i, 2) for i in range(31)]   # 1.00 → 1.60
    _series(db, item.product_id, prices)
    a = stock_svc.price_advice(db, item.product, TODAY)
    assert a["advice"] == "wait"
    assert a["current_min"] == D("1.60")
    assert a["trend_pct_30d"] > 30          # ~+46%/month on these numbers
    assert "rising" in a["reason"].lower() or "above" in a["reason"].lower()


def test_wobbling_series_is_neutral(db, hh):
    item = _item(db, hh)
    _series(db, item.product_id, [1.90, 2.10] * 15 + [2.05])
    a = stock_svc.price_advice(db, item.product, TODAY)
    assert a["advice"] == "neutral"


def test_discount_well_below_median_is_buy_now(db, hh):
    item = _item(db, hh)
    # 90-day low of 1.50 two months ago, ~2.00 lately, 1.80 on offer today.
    _series(db, item.product_id, [1.50] + [2.00] * 59 + [1.80], discount_last=True)
    assert stock_svc.price_advice(db, item.product, TODAY)["advice"] == "buy_now"


def test_same_price_without_discount_is_neutral(db, hh):
    item = _item(db, hh)
    _series(db, item.product_id, [1.50] + [2.00] * 59 + [1.80], discount_last=False)
    assert stock_svc.price_advice(db, item.product, TODAY)["advice"] == "neutral"


def test_cheapest_retailer_sets_the_current_min(db, hh):
    item = _item(db, hh)
    _series(db, item.product_id, [2.00] * 10, retailer="ab")
    _series(db, item.product_id, [2.20] * 9 + [1.90], retailer="lidl")
    a = stock_svc.price_advice(db, item.product, TODAY)
    assert a["current_min"] == D("1.90")


def test_too_little_history_is_unknown(db, hh):
    item = _item(db, hh)
    _series(db, item.product_id, [2.00] * 6)
    a = stock_svc.price_advice(db, item.product, TODAY)
    assert a["advice"] == "unknown"
    assert a["current_min"] == D("2.00")
    assert stock_svc.price_advice(db, _item(db, hh, "Empty").product, TODAY)["advice"] == "unknown"


# ---------------------------------------------------------------- run-out


def test_runout_needs_two_uses(db, hh):
    item = _item(db, hh, qty="4")
    assert stock_svc.predicted_runout_days(db, item, TODAY) is None
    _uses(db, item, [(3, 1)])
    assert stock_svc.predicted_runout_days(db, item, TODAY) is None


def test_runout_from_consumption_rate(db, hh):
    item = _item(db, hh, qty="4")
    _uses(db, item, [(10, 1), (5, 1)])     # 2 used over 10 days → 0.2/day
    assert stock_svc.predicted_runout_days(db, item, TODAY) == D("20.0")


def test_runout_observes_at_least_seven_days(db, hh):
    item = _item(db, hh, qty="2")
    _uses(db, item, [(0, 1), (0, 1)])      # 2 today → 2/7 per day
    assert stock_svc.predicted_runout_days(db, item, TODAY) == D("7.0")


def test_runout_ignores_old_and_non_use_movements(db, hh):
    item = _item(db, hh, qty="4")
    _uses(db, item, [(90, 5), (70, 5), (10, 1)])
    db.add(StockMovement(stock_item_id=item.id, delta=D("6"), reason="buy",
                         created_at=datetime.combine(TODAY, time(0)) - timedelta(days=1)))
    db.commit()
    assert stock_svc.predicted_runout_days(db, item, TODAY) is None


# ---------------------------------------------------------------- shopping list


def test_shopping_list_picks_low_and_soon_empty_items(db, hh):
    _item(db, hh, "Low", qty="0", min_qty="1")
    soon = _item(db, hh, "Soon", qty="3", min_qty="1")
    _uses(db, soon, [(7, 3), (1, 3)])      # 6 over 7 days → runs out in 3.5 d
    _item(db, hh, "Plenty", qty="10", min_qty="1")

    data = stock_svc.shopping_list(db, hh.household_id, TODAY)
    names = {row["product"].name for row in data["items"]}
    assert names == {"Low", "Soon"}
    low_row = next(r for r in data["items"] if r["product"].name == "Low")
    assert low_row["need_qty"] == D("2")    # restock to 2 × minimum


def test_shopping_list_groups_by_cheapest_retailer(db, hh):
    milk = _item(db, hh, "Milk", qty="0", min_qty="1")       # needs 2
    feta = _item(db, hh, "Feta", qty="0", min_qty="1")       # needs 2
    _item(db, hh, "Salt", qty="0", min_qty="1")       # no prices
    _series(db, milk.product_id, [1.50], retailer="ab")
    _series(db, milk.product_id, [1.40], retailer="lidl")
    _series(db, feta.product_id, [5.00], retailer="ab")
    _series(db, feta.product_id, [5.50], retailer="lidl")

    data = stock_svc.shopping_list(db, hh.household_id, TODAY)
    groups = {g["retailer"]: g for g in data["groups"]}
    assert {r["product"].name for r in groups["lidl"]["items"]} == {"Milk"}
    assert groups["lidl"]["total"] == D("2.80")
    assert groups["ab"]["total"] == D("10.00")
    assert {r["product"].name for r in groups[None]["items"]} == {"Salt"}

    best = data["best_single_store"]
    # ab: 3.00 + 10.00 = 13.00; lidl: 2.80 + 11.00 = 13.80
    assert best["retailer"] == "ab" and best["total"] == D("13.00")
    assert best["covers"] == 2 and best["missing"] == 0
    assert all(isinstance(g["total"], Decimal) for g in data["groups"])


def test_rotation_suggestions(db, hh):
    cheap = _item(db, hh, "Cheap now", qty="1", min_qty="1")
    pricey = _item(db, hh, "Pricey now", qty="5", min_qty="1")
    _series(db, cheap.product_id, [2.00] * 30)                                # buy_now
    _series(db, pricey.product_id, [round(1.00 + 0.02 * i, 2) for i in range(31)])  # wait

    out = {s["product"].name: s["kind"] for s in stock_svc.rotation_suggestions(db, hh.household_id, TODAY)}
    assert out == {"Cheap now": "stock_up", "Pricey now": "hold_off"}


# ---------------------------------------------------------------- pages


def test_shopping_page_renders_with_advice_and_estimate_label(client, db, authed):
    item = stock_svc.add_product(db, authed.household_id, authed.user_id, name="Milk",
                                 quantity=D("0"), min_quantity=D("1"))
    db.commit()
    _series(db, item.product_id, [1.40], retailer="lidl", end=stock_svc.local_today())

    r = client.get("/stock/shopping")
    assert r.status_code == 200
    assert "Milk" in r.text and "Lidl" in r.text and "2.80" in r.text
    assert "estimate" in r.text.lower()
    assert "Cheapest single store" in r.text


def test_shopping_page_says_prices_unavailable_without_data(client, db, authed):
    stock_svc.add_product(db, authed.household_id, authed.user_id, name="Salt",
                          quantity=D("0"), min_quantity=D("1"))
    db.commit()
    r = client.get("/stock/shopping")
    assert r.status_code == 200
    assert "prices unavailable" in r.text.lower()


def test_mark_bought_adds_stock_and_offers_expense_link(client, db, authed):
    db.add(Category(household_id=authed.household_id, name="Food & Groceries"))
    item = stock_svc.add_product(db, authed.household_id, authed.user_id, name="Milk",
                                 quantity=D("0"), min_quantity=D("1"))
    db.commit()
    _series(db, item.product_id, [1.40], retailer="lidl", end=stock_svc.local_today())

    r = client.post("/stock/shopping/bought",
                    data={"item_id": [item.id], f"qty_{item.id}": "2", "retailer": "lidl"},
                    headers=authed.headers)
    assert r.status_code == 200
    db.expire_all()
    assert db.get(StockItem, item.id).quantity == D("2")
    mv = db.query(StockMovement).filter_by(reason="buy").one()
    assert mv.delta == D("2")

    import re
    href = re.search(r'href="(/transactions/new\?[^"]+)"', r.text).group(1).replace("&amp;", "&")
    qs = parse_qs(urlparse(href).query)
    assert qs["amount"] == ["2.80"]
    cat = db.query(Category).filter_by(name="Food & Groceries").one()
    assert qs["category_id"] == [cat.id]
    assert "Lidl" in qs["notes"][0]


def test_mark_bought_ignores_foreign_items(client, db, authed, make_household):
    other = make_household(name="Other", username="other")
    foreign = stock_svc.add_product(db, other.household_id, other.user_id, name="Theirs")
    db.commit()
    r = client.post("/stock/shopping/bought",
                    data={"item_id": [foreign.id], f"qty_{foreign.id}": "5"},
                    headers=authed.headers)
    assert r.status_code == 404
    db.expire_all()
    assert db.get(StockItem, foreign.id).quantity == D("0")


def test_stock_page_shows_badge_and_runout_estimate(client, db, authed):
    item = stock_svc.add_product(db, authed.household_id, authed.user_id, name="Milk",
                                 quantity=D("4"), min_quantity=D("1"))
    db.commit()
    today = stock_svc.local_today()
    _series(db, item.product_id, [2.00] * 30, end=today)
    now = datetime.combine(today, datetime.min.time())
    for d in (10, 5):
        db.add(StockMovement(stock_item_id=item.id, delta=D("-1"), reason="use",
                             created_at=now - timedelta(days=d)))
    db.commit()

    r = client.get("/stock")
    assert "Buy now" in r.text
    assert "(est.)" in r.text


def test_api_shopping(client, db, api):  # noqa: F811
    headers, hh = api
    item = stock_svc.add_product(db, hh.household_id, hh.user_id, name="Milk",
                                 quantity=D("0"), min_quantity=D("1"))
    db.commit()
    _series(db, item.product_id, [1.40], retailer="lidl", end=stock_svc.local_today())
    r = client.get("/api/v1/stock/shopping", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["name"] == "Milk"
    assert body["items"][0]["retailer"] == "lidl"
    assert body["groups"][0]["total"] == 2.8
    assert body["best_single_store"]["retailer"] == "lidl"


def _init_cfg(html):
    import html as htmllib
    import json
    import re

    raw = re.search(r"data-init='([^']*)'", html, re.S).group(1)
    return json.loads(htmllib.unescape(raw))


def test_expense_link_prefills_the_new_expense_form(client, db, authed):
    import re

    cat = Category(household_id=authed.household_id, name="Food & Groceries")
    db.add(cat)
    item = stock_svc.add_product(db, authed.household_id, authed.user_id, name="Milk",
                                 quantity=D("0"), min_quantity=D("1"))
    db.commit()
    _series(db, item.product_id, [1.40], retailer="lidl", end=stock_svc.local_today())
    r = client.post("/stock/shopping/bought",
                    data={"item_id": [item.id], f"qty_{item.id}": "2", "retailer": "lidl"},
                    headers=authed.headers)
    href = re.search(r'href="(/transactions/new\?[^"]+)"', r.text).group(1).replace("&amp;", "&")
    assert "merchant=Lidl" in href

    page = client.get(href)
    assert page.status_code == 200
    pre = _init_cfg(page.text)["prefill"]
    assert pre == {"amount": "2.80", "category_id": cat.id,
                   "notes": "Groceries at Lidl", "merchant": "Lidl", "currency": "EUR"}


def test_prefill_ignores_foreign_category_and_bad_amount(client, db, authed, make_household):
    other = make_household(name="Other", username="other")
    foreign = Category(household_id=other.household_id, name="Theirs")
    db.add(foreign)
    db.commit()
    nasty = "x'<b>"
    page = client.get("/transactions/new", params={
        "amount": "abc", "category_id": foreign.id, "notes": nasty, "merchant": "M"})
    assert page.status_code == 200
    pre = _init_cfg(page.text)["prefill"]
    assert pre["amount"] == "" and pre["category_id"] == ""
    assert pre["notes"] == nasty and pre["merchant"] == "M"
    assert nasty not in page.text      # escaped, not raw


from tests.test_api import api  # noqa: E402,F401  (fixture)
