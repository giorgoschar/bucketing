"""GET /api/v1/products/barcode/{code}: the Open Food Facts fallback.

Order: household pantry match, PosoKanei, then Open Food Facts when PosoKanei
has no product (not found OR unavailable). No network anywhere.
"""

from decimal import Decimal

import pytest

from app.integrations import openfoodfacts
from app.integrations.openfoodfacts import OffProduct, OpenFoodFactsUnavailable
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_stock import down, fake  # noqa: F401  (fixtures)
from tests.test_stock_detail import _item, other  # noqa: F401  (helper, fixture)

BARCODE = "5201054017906"
URL = f"/api/v1/products/barcode/{BARCODE}"

PRODUCT_KEYS = {
    "id", "name", "brand", "barcode", "unit", "unit_quantity", "image_url",
    "retailer_prices", "price_stats", "history",
}  # fmt: skip


class FakeOff:
    def __init__(self, product=None, down=False):
        self.product = product
        self.down = down
        self.calls = []

    def by_barcode(self, code):
        self.calls.append(code)
        if self.down:
            raise OpenFoodFactsUnavailable("down")
        return self.product


def off_hit(**over):
    base = dict(
        barcode=BARCODE, name="Γάλα φρέσκο", brand="ΔΕΛΤΑ", unit="L", unit_quantity=Decimal("1")
    )
    base.update(over)
    return OffProduct(**base)


@pytest.fixture()
def off(monkeypatch):
    client = FakeOff(off_hit())
    monkeypatch.setattr(openfoodfacts, "_client", client)
    return client


# ---------------------------------------------------------------- snapshot


def test_posokanei_result_keeps_every_key_and_adds_only_source(client, api, fake, off):  # noqa: F811
    headers, _ = api
    r = client.get(URL, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == PRODUCT_KEYS | {"in_pantry", "source"}
    assert body["source"] == "posokanei"
    assert body["id"] == "p-1"
    assert isinstance(body["retailer_prices"], list) and body["retailer_prices"]
    assert set(body["price_stats"]) == {"min", "max", "avg"}
    assert body["in_pantry"] is None
    assert off.calls == []  # PosoKanei answered: Open Food Facts is not asked


# ---------------------------------------------------------------- the order


def test_posokanei_not_found_then_off_hit(client, api, fake, off):  # noqa: F811
    headers, _ = api
    fake.product = None
    r = client.get(URL, headers=headers)
    assert r.status_code == 200
    assert r.json() == {
        "id": f"off:{BARCODE}",
        "name": "Γάλα φρέσκο",
        "brand": "ΔΕΛΤΑ",
        "barcode": BARCODE,
        "unit": "L",
        "unit_quantity": 1,
        "image_url": None,
        "retailer_prices": [],
        "price_stats": {"min": None, "max": None, "avg": None},
        "history": [],
        "in_pantry": None,
        "source": "openfoodfacts",
    }
    assert off.calls == [BARCODE]


def test_posokanei_unavailable_then_off_hit(client, api, down, off):  # noqa: F811
    headers, _ = api
    r = client.get(URL, headers=headers)
    assert r.status_code == 200 and r.json()["source"] == "openfoodfacts"


def test_off_hit_without_size_or_brand(client, api, fake, off):  # noqa: F811
    headers, _ = api
    fake.product = None
    off.product = off_hit(brand=None, unit=None, unit_quantity=None)
    body = client.get(URL, headers=headers).json()
    assert body["brand"] is None and body["unit"] is None and body["unit_quantity"] is None


def test_posokanei_not_found_off_not_found_is_404(client, api, fake, off):  # noqa: F811
    headers, _ = api
    fake.product = None
    off.product = None
    r = client.get(URL, headers=headers)
    assert r.status_code == 404
    assert r.json() == {"detail": "Product not found", "in_pantry": None}


def test_posokanei_unavailable_off_not_found_is_404(client, api, down, off):  # noqa: F811
    headers, _ = api
    off.product = None
    r = client.get(URL, headers=headers)
    assert r.status_code == 404
    assert r.json() == {"detail": "Product not found", "in_pantry": None}


def test_both_unavailable_is_503(client, api, down, off):  # noqa: F811
    headers, _ = api
    off.down = True
    r = client.get(URL, headers=headers)
    assert r.status_code == 503
    assert r.json() == {"detail": "Prices unavailable", "in_pantry": None}


def test_posokanei_not_found_off_unavailable_is_404(client, api, fake, off):  # noqa: F811
    headers, _ = api
    fake.product = None
    off.down = True
    r = client.get(URL, headers=headers)
    assert r.status_code == 404
    assert r.json() == {"detail": "Product not found", "in_pantry": None}


def test_off_disabled_behaves_as_before(client, api, fake, monkeypatch):  # noqa: F811
    """The autouse switched-off client: 404 when PosoKanei misses."""
    headers, _ = api
    fake.product = None
    assert client.get(URL, headers=headers).status_code == 404


def test_invalid_barcode_is_400_and_never_looked_up(client, api, fake, off):  # noqa: F811
    headers, _ = api
    r = client.get("/api/v1/products/barcode/12ab", headers=headers)
    assert r.status_code == 400
    assert off.calls == []


# ---------------------------------------------------------------- in_pantry


def test_in_pantry_on_off_hit(client, db, api, down, off):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="3", barcode=BARCODE)
    r = client.get(URL, headers=headers)
    assert r.status_code == 200
    assert r.json()["source"] == "openfoodfacts"
    assert r.json()["in_pantry"] == {"stock_item_id": milk.id, "quantity": 3}


def test_in_pantry_on_404_and_503(client, db, api, fake, off):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="2", barcode=BARCODE)
    fake.product = None
    off.product = None
    r = client.get(URL, headers=headers)
    assert r.status_code == 404
    assert r.json()["in_pantry"] == {"stock_item_id": milk.id, "quantity": 2}


def test_in_pantry_on_503(client, db, api, down, off):  # noqa: F811
    headers, hh = api
    milk = _item(db, hh, qty="1", barcode=BARCODE)
    off.down = True
    r = client.get(URL, headers=headers)
    assert r.status_code == 503
    assert r.json()["in_pantry"] == {"stock_item_id": milk.id, "quantity": 1}


def test_off_hit_ignores_a_pantry_item_matched_only_by_posokanei_id(client, db, api, down, off):  # noqa: F811
    """An item whose posokanei_id happens to look like the synthetic id is not
    reported: only the barcode matches for an Open Food Facts result."""
    headers, hh = api
    _item(db, hh, qty="1", posokanei_id="p-1")
    assert client.get(URL, headers=headers).json()["in_pantry"] is None


def test_household_isolation(client, db, api, other, down, off):  # noqa: F811
    headers, _ = api
    _item(db, other, "Theirs", barcode=BARCODE)
    r = client.get(URL, headers=headers)
    assert r.status_code == 200 and r.json()["in_pantry"] is None
    off.product = None
    r = client.get(URL, headers=headers)
    assert r.status_code == 404 and r.json()["in_pantry"] is None
    off.down = True
    r = client.get(URL, headers=headers)
    assert r.status_code == 503 and r.json()["in_pantry"] is None


def test_pantry_is_read_before_any_lookup(client, db, api, fake, off):  # noqa: F811
    """The pantry match is computed even when PosoKanei answers (existing
    behaviour) and Open Food Facts is not asked."""
    headers, hh = api
    milk = _item(db, hh, qty="4", barcode=BARCODE)
    body = client.get(URL, headers=headers).json()
    assert body["in_pantry"]["stock_item_id"] == milk.id
    assert off.calls == []


def test_add_flow_accepts_an_off_result(client, api, fake, off):  # noqa: F811
    """POST /stock with an OFF result's fields (no posokanei_id) works."""
    headers, _ = api
    fake.product = None
    p = client.get(URL, headers=headers).json()
    r = client.post(
        "/api/v1/stock",
        json={
            "name": p["name"], "brand": p["brand"], "barcode": p["barcode"], "unit": p["unit"],
            "unit_quantity": p["unit_quantity"], "quantity": 0, "min_quantity": 1,
        },
        headers=headers,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    assert r.json()["posokanei_id"] is None and r.json()["barcode"] == BARCODE


def test_api_add_treats_off_prefixed_posokanei_id_as_null(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(
        "/api/v1/stock",
        json={"name": "Milk", "barcode": BARCODE, "posokanei_id": f"off:{BARCODE}"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["posokanei_id"] is None


def test_service_and_jinja_add_ignore_off_prefixed_id(client, db, api):  # noqa: F811
    from app.services import stock as stock_svc

    _, hh = api
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name="Milk", posokanei_id="OFF:123456"
    )
    assert item.product.posokanei_id is None
    item = stock_svc.add_product(
        db, hh.household_id, hh.user_id, name="Oil", posokanei_id=f"off:{BARCODE}"
    )
    assert item.product.posokanei_id is None


def test_barcode_route_is_limited_to_30_a_minute_per_user(client, api, fake, off):  # noqa: F811
    headers, _ = api
    fake.product = None
    off.product = None
    for _ in range(30):
        assert client.get(URL, headers=headers).status_code == 404
    calls_before = len(off.calls)
    fake_calls = len(fake.calls)
    r = client.get(URL, headers=headers)
    assert r.status_code == 429
    assert "lookups" in r.json()["detail"].lower()
    assert len(off.calls) == calls_before and len(fake.calls) == fake_calls


def test_barcode_limit_is_per_user(client, api, other, fake, off, make_household):  # noqa: F811
    headers, _ = api
    fake.product = None
    off.product = None
    for _ in range(31):
        client.get(URL, headers=headers)
    from tests.test_api import PASSWORD  # noqa: F401
    import pyotp

    r = client.post("/api/v1/auth/login", json={"username": other.username, "password": PASSWORD})
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(other.secret).now()},
    )
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(URL, headers=h2).status_code == 404
