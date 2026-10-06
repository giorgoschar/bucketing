"""PosoKanei client: field mapping, error wrapping, caching, spacing.

No network: every test drives the client through httpx.MockTransport.
"""
import json
from decimal import Decimal

import httpx
import pytest

from app.integrations import posokanei
from app.integrations.posokanei import PosokaneiClient, PosokaneiUnavailable

SEARCH_PAYLOAD = {
    "results": [
        {
            "id": "p-123",
            "name": "Γάλα φρέσκο πλήρες 1L",
            "brand": "ΔΕΛΤΑ",
            "barcode": "5201054017906",
            "unit": "l",
            "unit_quantity": 1,
            "image_url": "https://img.example/p-123.jpg",
            "retailer_prices": [
                {"retailer": "sklavenitis", "display_name": "Σκλαβενίτης",
                 "price": 1.79, "unit_price": 1.79, "is_discount": False,
                 "discount_pct": None, "last_updated": "2026-09-30"},
                {"retailer": "ab", "display_name": "ΑΒ Βασιλόπουλος",
                 "price": "1.59", "unit_price": "1.59", "is_discount": True,
                 "discount_pct": 11, "last_updated": "2026-09-30"},
            ],
            "price_stats": {"min": 1.59, "max": 1.79, "avg": 1.69},
        }
    ],
    "total": 1,
}


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        return self.handler(request)


def make_client(handler, **kw):
    rec = Recorder(handler)
    kw.setdefault("min_interval", 0)
    client = PosokaneiClient(transport=httpx.MockTransport(rec), enabled=True, **kw)
    return client, rec


def test_search_maps_fields():
    client, rec = make_client(lambda req: httpx.Response(200, json=SEARCH_PAYLOAD))

    results = client.search("γάλα")

    assert len(results) == 1
    p = results[0]
    assert p.id == "p-123"
    assert p.name == "Γάλα φρέσκο πλήρες 1L"
    assert p.brand == "ΔΕΛΤΑ"
    assert p.barcode == "5201054017906"
    assert p.unit == "l"
    assert p.unit_quantity == Decimal("1")
    assert p.image_url == "https://img.example/p-123.jpg"
    assert [r.retailer for r in p.retailer_prices] == ["sklavenitis", "ab"]
    ab = p.retailer_prices[1]
    assert ab.display_name == "ΑΒ Βασιλόπουλος"
    assert ab.price == Decimal("1.59") and isinstance(ab.price, Decimal)
    assert ab.unit_price == Decimal("1.59")
    assert ab.is_discount is True
    assert ab.discount_pct == Decimal("11")
    assert ab.last_updated == "2026-09-30"
    assert p.price_stats.min == Decimal("1.59")
    assert p.price_stats.max == Decimal("1.79")
    assert p.price_stats.avg == Decimal("1.69")
    assert p.cheapest.retailer == "ab"

    req = rec.requests[0]
    assert req.method == "POST"
    assert str(req.url) == "https://api.posokanei.gov.gr/products/search"
    assert json.loads(req.content) == {"query": "γάλα", "page": 1, "page_size": 20}
    assert req.headers["user-agent"].startswith("expenses-app/1.0 (+")


def test_price_stats_derived_when_missing():
    payload = json.loads(json.dumps(SEARCH_PAYLOAD))
    del payload["results"][0]["price_stats"]
    client, _ = make_client(lambda req: httpx.Response(200, json=payload))
    stats = client.search("γάλα")[0].price_stats
    assert (stats.min, stats.max, stats.avg) == (Decimal("1.59"), Decimal("1.79"), Decimal("1.69"))


def test_search_accepts_a_bare_list():
    client, _ = make_client(lambda req: httpx.Response(200, json=SEARCH_PAYLOAD["results"]))
    assert client.search("γάλα")[0].id == "p-123"


def test_get_requests_history_and_maps_product():
    product = dict(SEARCH_PAYLOAD["results"][0])
    product["history"] = [
        {"date": "2026-09-29", "retailer": "ab", "price": 1.69, "is_discount": False},
        {"date": "2026-09-30", "retailer": "ab", "price": 1.59, "is_discount": True},
    ]
    client, rec = make_client(lambda req: httpx.Response(200, json=product))

    p = client.get("p-123")

    assert p.id == "p-123"
    assert len(p.history) == 2
    assert p.history[1].price == Decimal("1.59") and p.history[1].is_discount
    req = rec.requests[0]
    assert req.method == "GET"
    assert req.url.path == "/products/p-123"
    assert dict(req.url.params) == {
        "countries": "GR", "include_tax": "true", "include_history": "true",
    }


def test_by_barcode_hits_barcode_endpoint():
    client, rec = make_client(lambda req: httpx.Response(200, json=SEARCH_PAYLOAD["results"][0]))
    p = client.by_barcode("5201054017906")
    assert p.barcode == "5201054017906"
    assert rec.requests[0].url.path == "/products/barcode/5201054017906"


def test_by_barcode_not_found_returns_none():
    client, _ = make_client(lambda req: httpx.Response(404, json={"detail": "not found"}))
    assert client.by_barcode("0000000000000") is None


def test_by_barcode_rejects_non_digits_without_a_request():
    client, rec = make_client(lambda req: httpx.Response(200, json={}))
    assert client.by_barcode("../admin") is None
    assert rec.requests == []


def test_timeout_becomes_unavailable():
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)

    client, _ = make_client(boom)
    with pytest.raises(PosokaneiUnavailable):
        client.search("γάλα")


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="oops"),
    httpx.Response(403, text="<html>403 Forbidden</html>"),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"unexpected": "shape"}),
])
def test_http_and_shape_errors_become_unavailable(response):
    client, _ = make_client(lambda req: response)
    with pytest.raises(PosokaneiUnavailable):
        client.search("γάλα")


def test_disabled_flag_never_calls_out():
    rec = Recorder(lambda req: httpx.Response(200, json=SEARCH_PAYLOAD))
    client = PosokaneiClient(transport=httpx.MockTransport(rec), enabled=False)
    with pytest.raises(PosokaneiUnavailable):
        client.search("γάλα")
    assert rec.requests == []


def test_cache_hit_avoids_second_call():
    client, rec = make_client(lambda req: httpx.Response(200, json=SEARCH_PAYLOAD))
    first = client.search("γάλα")
    second = client.search("γάλα")
    assert first == second
    assert len(rec.requests) == 1
    client.search("τυρί")
    assert len(rec.requests) == 2


def test_cache_expires_after_ttl():
    now = [1000.0]
    client, rec = make_client(
        lambda req: httpx.Response(200, json=SEARCH_PAYLOAD),
        clock=lambda: now[0],
    )
    client.search("γάλα")
    now[0] += posokanei.CACHE_TTL_SECONDS + 1
    client.search("γάλα")
    assert len(rec.requests) == 2


def test_failures_are_not_cached():
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    client, _ = make_client(flaky)
    with pytest.raises(PosokaneiUnavailable):
        client.search("γάλα")
    assert client.search("γάλα")[0].id == "p-123"


def test_requests_are_spaced():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    client, _ = make_client(
        lambda req: httpx.Response(200, json=SEARCH_PAYLOAD),
        min_interval=0.25, clock=lambda: now[0], sleep=sleep,
    )
    client.search("a")
    client.search("b")
    client.search("c")
    assert slept and all(s <= 0.25 for s in slept)
    assert sum(slept) == pytest.approx(0.5)


def test_default_client_uses_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "posokanei_enabled", False)
    monkeypatch.setattr(posokanei, "_client", None)
    with pytest.raises(PosokaneiUnavailable):
        posokanei.search("γάλα")


def test_get_404_is_not_found_not_an_outage():
    from app.integrations.posokanei import PosokaneiNotFound

    client, _ = make_client(lambda req: httpx.Response(404, json={"detail": "nope"}))
    with pytest.raises(PosokaneiNotFound):
        client.get("p-gone")


@pytest.mark.parametrize("response", [
    httpx.Response(500), httpx.Response(503), httpx.Response(403, text="<html>"),
])
def test_get_outages_are_not_not_found(response):
    from app.integrations.posokanei import PosokaneiNotFound

    client, _ = make_client(lambda req: response)
    with pytest.raises(PosokaneiUnavailable) as exc:
        client.get("p-1")
    assert not isinstance(exc.value, PosokaneiNotFound)


@pytest.mark.parametrize("pid", ["..", ".", "x?a=b#", "a/b", "", "x" * 65, "γάλα", "a b"])
def test_get_rejects_unsafe_ids_without_a_request(pid):
    from app.integrations.posokanei import PosokaneiNotFound, valid_product_id

    assert not valid_product_id(pid)
    client, rec = make_client(lambda req: httpx.Response(200, json=SEARCH_PAYLOAD["results"][0]))
    with pytest.raises(PosokaneiNotFound):
        client.get(pid)
    assert rec.requests == []


def test_valid_ids_pass():
    from app.integrations.posokanei import valid_product_id

    for pid in ("p-123", "abc.def_1", "A" * 64, "123"):
        assert valid_product_id(pid)


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), (1, True), (0, False), ("true", True), ("True", True),
    ("1", True), ("false", False), ("0", False), (0.5, False), (12, False),
    ("yes", False), (None, False), ("0.15", False),
])
def test_is_discount_is_parsed_strictly(value, expected):
    payload = json.loads(json.dumps(SEARCH_PAYLOAD))
    payload["results"][0]["retailer_prices"][0]["is_discount"] = value
    client, _ = make_client(lambda req: httpx.Response(200, json=payload))
    assert client.search("γάλα")[0].retailer_prices[0].is_discount is expected


def test_items_container_accepted_but_unknown_aliases_rejected():
    client, _ = make_client(lambda req: httpx.Response(200, json={"items": SEARCH_PAYLOAD["results"]}))
    assert client.search("γάλα")[0].id == "p-123"
    client, _ = make_client(lambda req: httpx.Response(200, json={"products": SEARCH_PAYLOAD["results"]}))
    with pytest.raises(PosokaneiUnavailable):
        client.search("γάλα")
