"""Open Food Facts client: mapping, size parsing, failures, politeness, cache.

No network: every test drives the client through httpx.MockTransport.
"""

from decimal import Decimal

import httpx
import pytest

from app.integrations import openfoodfacts as off
from app.integrations.openfoodfacts import OffProduct, OpenFoodFactsClient, OpenFoodFactsUnavailable

CODE = "5201054017906"


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
    kw.setdefault("enabled", True)
    client = OpenFoodFactsClient(transport=httpx.MockTransport(rec), **kw)
    return client, rec


def hit(**product):
    base = {"code": CODE, "product_name": "Fresh milk"}
    base.update(product)
    return httpx.Response(200, json={"status": 1, "code": CODE, "product": base})


def test_mapping_prefers_greek_name_and_first_brand():
    client, rec = make_client(
        lambda r: hit(
            product_name_el="Γάλα φρέσκο",
            product_name="Fresh milk",
            generic_name_el="Γάλα",
            brands=" ΔΕΛΤΑ , Other",
            product_quantity="1000",
            product_quantity_unit="ml",
        )
    )
    p = client.by_barcode(CODE)
    assert p == OffProduct(
        barcode=CODE, name="Γάλα φρέσκο", brand="ΔΕΛΤΑ", unit="ml", unit_quantity=Decimal("1000")
    )
    assert len(rec.requests) == 1


@pytest.mark.parametrize(
    ("product", "name"),
    [
        ({"product_name": "Plain", "generic_name_el": "Γενικό"}, "Plain"),
        ({"product_name": "", "generic_name_el": "Γενικό"}, "Γενικό"),
        ({"product_name": "  ", "product_name_el": None, "generic_name_el": "Γενικό"}, "Γενικό"),
    ],
)
def test_name_fallback_order(product, name):
    client, _ = make_client(lambda r: hit(**product))
    assert client.by_barcode(CODE).name == name


def test_no_name_is_not_found():
    client, _ = make_client(lambda r: hit(product_name="", brands="X"))
    assert client.by_barcode(CODE) is None


def test_brand_absent_is_none():
    client, _ = make_client(lambda r: hit(brands=""))
    assert client.by_barcode(CODE).brand is None


def test_code_in_response_is_never_trusted():
    def handler(r):
        return httpx.Response(
            200,
            json={
                "status": 1,
                "code": "999999999",
                "product": {"code": "111111", "product_name": "X"},
            },
        )

    client, _ = make_client(handler)
    assert client.by_barcode(CODE).barcode == CODE


def test_text_is_truncated_and_stripped_of_control_chars():
    client, _ = make_client(
        lambda r: hit(product_name="A\x00B\x1f" + "x" * 500, brands="Br\x07and" + "y" * 300)
    )
    p = client.by_barcode(CODE)
    assert p.name.startswith("AB") and len(p.name) == 200
    assert p.brand.startswith("Brand") and len(p.brand) == 100
    assert not any(ord(c) < 32 for c in p.name + p.brand)


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        ("500 g", ("g", "500")),
        ("500g", ("g", "500")),
        ("1 L", ("L", "1")),
        ("1 l", ("L", "1")),
        ("1,5 l", ("L", "1.5")),
        ("1.5 kg", ("kg", "1.5")),
        ("6 x 330 ml", ("ml", "330")),
        ("6x330ml", ("ml", "330")),
        ("330ml", ("ml", "330")),
        ("330 ML", ("ml", "330")),
        ("2 oz", None),
        ("a dozen", None),
        ("", None),
        ("0 g", None),
        ("g 500", None),
        ("500", None),
        ("1,2,3 g", None),
        ("500 g " + "x" * 1000, None),
    ],
)
def test_quantity_parser(quantity, expected):
    assert off.parse_quantity(quantity) == (
        None if expected is None else (expected[0], Decimal(expected[1]))
    )


def test_quantity_parser_is_linear_on_hostile_input():
    import time

    start = time.perf_counter()
    off.parse_quantity("1" * 100_000 + " " * 100_000 + "x")
    off.parse_quantity("6 x " * 50_000)
    assert time.perf_counter() - start < 0.5


def test_product_quantity_wins_over_quantity_text():
    client, _ = make_client(
        lambda r: hit(quantity="6 x 330 ml", product_quantity=500, product_quantity_unit="g")
    )
    p = client.by_barcode(CODE)
    assert (p.unit, p.unit_quantity) == ("g", Decimal("500"))


def test_quantity_text_used_when_product_quantity_not_numeric():
    client, _ = make_client(
        lambda r: hit(quantity="1,5 l", product_quantity="abc", product_quantity_unit="ml")
    )
    p = client.by_barcode(CODE)
    assert (p.unit, p.unit_quantity) == ("L", Decimal("1.5"))


def test_unknown_product_quantity_unit_means_no_size():
    client, _ = make_client(lambda r: hit(product_quantity=12, product_quantity_unit="oz"))
    p = client.by_barcode(CODE)
    assert p.unit is None and p.unit_quantity is None


def test_no_size_at_all():
    client, _ = make_client(lambda r: hit())
    p = client.by_barcode(CODE)
    assert p.unit is None and p.unit_quantity is None


def test_status_zero_is_not_found_and_cached():
    client, rec = make_client(
        lambda r: httpx.Response(200, json={"status": 0, "status_verbose": "product not found"})
    )
    assert client.by_barcode(CODE) is None
    assert client.by_barcode(CODE) is None
    assert len(rec.requests) == 1


def test_http_404_is_not_found():
    client, _ = make_client(lambda r: httpx.Response(404, json={"status": 0}))
    assert client.by_barcode(CODE) is None


def _timeout(request):
    raise httpx.ReadTimeout("slow", request=request)


def _transport_error(request):
    raise httpx.ConnectError("refused", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        _timeout,
        _transport_error,
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(429),
        lambda r: httpx.Response(403),
        lambda r: httpx.Response(200, content=b"<html>not json</html>"),
        lambda r: httpx.Response(200, json=[1, 2]),
        lambda r: httpx.Response(200, json={"nope": True}),
        lambda r: httpx.Response(200, json={"status": 1, "product": "str"}),
        lambda r: httpx.Response(200, json={"status": 1}),
    ],
)
def test_failures_are_unavailable_and_not_cached(handler):
    client, rec = make_client(handler)
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert len(rec.requests) == 2


def test_disabled_makes_no_request():
    client, rec = make_client(lambda r: hit(), enabled=False)
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert rec.requests == []


def test_cache_hit_makes_no_second_request_until_ttl():
    now = [1000.0]
    client, rec = make_client(lambda r: hit(), clock=lambda: now[0])
    client.by_barcode(CODE)
    client.by_barcode(CODE)
    assert len(rec.requests) == 1
    now[0] += 24 * 3600 - 1
    client.by_barcode(CODE)
    assert len(rec.requests) == 1
    now[0] += 2
    client.by_barcode(CODE)
    assert len(rec.requests) == 2


def test_cache_is_bounded_lru():
    client, rec = make_client(lambda r: hit(), max_entries=3)
    for code in ("111111", "222222", "333333"):
        client.by_barcode(code)
    client.by_barcode("111111")  # refresh: 222222 is now the oldest
    client.by_barcode("444444")  # evicts 222222
    assert len(client._cache) == 3
    before = len(rec.requests)
    client.by_barcode("111111")
    assert len(rec.requests) == before
    client.by_barcode("222222")
    assert len(rec.requests) == before + 1


def test_default_cache_bound_is_2000():
    assert off.CACHE_MAX_ENTRIES == 2000
    assert off.CACHE_TTL_SECONDS == 24 * 3600


@pytest.mark.parametrize(
    "bad", ["", "12345", "1" * 15, "abc123456", "5201054017906/../x", "12 3456", "١٢٣٤٥٦٧"]
)
def test_only_valid_digit_barcodes_are_sent(bad):
    client, rec = make_client(lambda r: hit())
    assert client.by_barcode(bad) is None
    assert rec.requests == []


def test_request_url_and_headers():
    client, rec = make_client(lambda r: hit(), base_url="https://world.openfoodfacts.org")
    client.by_barcode(f" {CODE} ")
    [req] = rec.requests
    assert req.method == "GET"
    assert req.url.host == "world.openfoodfacts.org"
    assert req.url.path == f"/api/v2/product/{CODE}.json"
    assert req.url.params["fields"] == (
        "code,product_name,product_name_el,generic_name_el,brands,quantity,"
        "product_quantity,product_quantity_unit"
    )
    ua = req.headers["user-agent"]
    assert ua.startswith("Tameio/1.0 (+") and ua.endswith(")")
    assert "Mozilla" not in ua


def test_user_agent_uses_app_base_url(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_base_url", "https://tameio.example")
    client, rec = make_client(lambda r: hit())
    client.by_barcode(CODE)
    assert rec.requests[0].headers["user-agent"] == "Tameio/1.0 (+https://tameio.example)"


def test_requests_are_spaced_700ms():
    now = [0.0]
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    client, _ = make_client(lambda r: hit(), min_interval=0.7, clock=lambda: now[0], sleep=sleep)
    client.by_barcode("111111")
    client.by_barcode("222222")
    assert len(slept) == 1 and slept[0] == pytest.approx(0.7)
    assert off.MIN_INTERVAL_SECONDS == 0.7
    assert off.TIMEOUT_SECONDS == 10.0


def test_settings_defaults():
    from app.core.config import Settings

    f = Settings.model_fields
    assert f["openfoodfacts_enabled"].default is True
    assert f["openfoodfacts_base_url"].default == "https://world.openfoodfacts.org"
