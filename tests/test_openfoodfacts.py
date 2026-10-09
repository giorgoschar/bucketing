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
def test_failures_are_unavailable_and_cached_briefly(handler):
    client, rec = make_client(handler)
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert len(rec.requests) == 1


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
    assert off.TIMEOUT_SECONDS == 5.0


def test_settings_defaults():
    from app.core.config import Settings

    f = Settings.model_fields
    assert f["openfoodfacts_enabled"].default is True
    assert f["openfoodfacts_base_url"].default == "https://world.openfoodfacts.org"


# ---------------------------------------------------------------- bounds


@pytest.mark.parametrize(
    "value",
    [
        "1e309",
        "NaN",
        "Infinity",
        "-5",
        "0",
        "100000.01",
        "9" * 30,
        "1" * 21,
        "",
        "abc",
        -1,
        True,
        [1],
        {"a": 1},
    ],
)
def test_out_of_bounds_product_quantity_means_no_size(value):
    client, _ = make_client(lambda r: hit(product_quantity=value, product_quantity_unit="g"))
    p = client.by_barcode(CODE)
    assert p is not None and p.unit is None and p.unit_quantity is None


def test_quantity_text_out_of_bounds_means_no_size():
    for text in ("1e309 g", "99999999 g", "NaN g", "-5 g", "100001 g"):
        client, _ = make_client(lambda r, t=text: hit(quantity=t))
        p = client.by_barcode(CODE)
        assert p.unit is None and p.unit_quantity is None, text


def test_size_is_rounded_to_three_decimals_and_upper_bound_allowed():
    client, _ = make_client(lambda r: hit(product_quantity=0.33349, product_quantity_unit="kg"))
    assert client.by_barcode(CODE).unit_quantity == Decimal("0.333")
    client, _ = make_client(lambda r: hit(product_quantity="100000", product_quantity_unit="g"))
    assert client.by_barcode(CODE).unit_quantity == Decimal("100000")
    client, _ = make_client(lambda r: hit(product_quantity="0.0001", product_quantity_unit="g"))
    assert client.by_barcode(CODE).unit_quantity is None  # rounds to zero


def test_oversized_body_is_unavailable():
    big = b'{"status": 1, "product": {"product_name": "' + b"x" * 1_000_000 + b'"}}'
    client, _ = make_client(lambda r: httpx.Response(200, content=big))
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)


@pytest.mark.parametrize(
    "product",
    [
        {"product_name": ["Milk"]},
        {"product_name": {"a": 1}},
        {"product_name": 5},
        {"product_name": "Milk", "brands": ["Delta"]},
    ],
)
def test_non_string_text_is_ignored(product):
    client, _ = make_client(lambda r: hit(**product))
    try:
        p = client.by_barcode(CODE)
    except OpenFoodFactsUnavailable:
        return
    assert p is None or (p.name == "Milk" and p.brand is None)


# ---------------------------------------------------------------- resilience


def test_failure_cache_expires_after_60s():
    now = [0.0]
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(500)

    client, _ = make_client(handler, clock=lambda: now[0])
    for _ in range(2):
        with pytest.raises(OpenFoodFactsUnavailable):
            client.by_barcode(CODE)
    assert len(calls) == 1
    now[0] += 61
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert len(calls) == 2


def test_circuit_breaker_opens_after_three_and_closes_after_60s():
    now = [0.0]
    state = {"down": True, "n": 0}

    def handler(r):
        state["n"] += 1
        return httpx.Response(500) if state["down"] else hit()

    client, _ = make_client(handler, clock=lambda: now[0])
    for code in ("111111", "222222", "333333"):
        with pytest.raises(OpenFoodFactsUnavailable):
            client.by_barcode(code)
    assert state["n"] == 3
    state["down"] = False
    with pytest.raises(OpenFoodFactsUnavailable):  # open: no network at all
        client.by_barcode("444444")
    assert state["n"] == 3
    now[0] += 61
    assert client.by_barcode("444444") is not None
    assert state["n"] == 4


def test_a_success_resets_the_consecutive_failure_count():
    results = iter([500, 500, 200, 500, 500])

    def handler(r):
        return httpx.Response(500) if next(results) == 500 else hit()

    client, rec = make_client(handler)
    codes = iter(["111111", "222222", "333333", "444444", "555555"])
    outcomes = []
    for _ in range(5):
        try:
            client.by_barcode(next(codes))
            outcomes.append("ok")
        except OpenFoodFactsUnavailable:
            outcomes.append("down")
    assert outcomes == ["down", "down", "ok", "down", "down"]
    assert len(rec.requests) == 5  # never short-circuited


def test_not_found_does_not_count_as_an_outage():
    client, rec = make_client(lambda r: httpx.Response(404))
    for code in ("111111", "222222", "333333", "444444"):
        assert client.by_barcode(code) is None
    assert len(rec.requests) == 4


def test_far_off_slot_fails_fast_without_sleeping_or_requesting():
    now = [0.0]
    slept = []
    client, rec = make_client(
        lambda r: hit(), min_interval=0.7, clock=lambda: now[0], sleep=slept.append
    )
    client._next_slot = 5.0  # callers already queued several seconds ahead
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert slept == [] and rec.requests == []


def test_concurrency_is_capped_at_two_and_does_not_serialise():
    import threading

    gate = threading.Event()
    entered = threading.Semaphore(0)

    def handler(r):
        entered.release()
        gate.wait(5)
        return hit()

    client, rec = make_client(handler)
    results: dict[str, str] = {}

    def run(code):
        try:
            client.by_barcode(code)
            results[code] = "ok"
        except OpenFoodFactsUnavailable:
            results[code] = "down"

    first = [threading.Thread(target=run, args=(c,)) for c in ("111111", "222222")]
    for t in first:
        t.start()
    assert entered.acquire(timeout=5) and entered.acquire(timeout=5)  # both in flight together
    # A third (and its fellows) fail fast instead of queueing behind the slow two.
    run("333333")
    assert results["333333"] == "down"
    gate.set()
    for t in first:
        t.join(5)
    assert results["111111"] == results["222222"] == "ok"
    assert len(rec.requests) == 2


def test_lock_is_not_held_during_network_io():
    import threading

    started = threading.Event()
    release = threading.Event()

    def handler(r):
        started.set()
        release.wait(5)
        return hit()

    client, _ = make_client(handler)
    t = threading.Thread(target=lambda: client.by_barcode("111111"))
    t.start()
    assert started.wait(5)
    # Cache reads (which take the lock) are not blocked by the in-flight call.
    assert client._lock.acquire(timeout=1)
    client._lock.release()
    release.set()
    t.join(5)


def test_local_congestion_does_not_count_as_an_outage():
    client, rec = make_client(lambda r: hit(), clock=lambda: 0.0)
    client._next_slot = 50.0
    for code in ("111111", "222222", "333333", "444444"):
        with pytest.raises(OpenFoodFactsUnavailable):
            client.by_barcode(code)
    client._next_slot = 0.0
    assert client.by_barcode("111111") is not None  # no breaker, no failure cache


# ---------------------------------------------------------------- where the bounds sit


class _Stream(httpx.SyncByteStream):
    def __init__(self, chunks, on_chunk=None):
        self.chunks, self.on_chunk, self.sent = chunks, on_chunk, 0

    def __iter__(self):
        for c in self.chunks:
            self.sent += len(c)
            if self.on_chunk:
                self.on_chunk()
            yield c


def test_chunked_megabyte_body_is_aborted_near_the_cap():
    stream = _Stream(iter([b"x" * 8192] * 128))  # 1 MB, no Content-Length
    client, _ = make_client(lambda r: httpx.Response(200, stream=stream))
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert stream.sent <= off.MAX_BODY_BYTES + 8192


def test_declared_content_length_over_cap_is_rejected_before_reading():
    stream = _Stream(iter([b"{}"]))
    client, _ = make_client(
        lambda r: httpx.Response(200, headers={"content-length": "999999"}, stream=stream)
    )
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert stream.sent == 0


def test_slow_drip_body_is_aborted_at_the_total_deadline():
    now = [0.0]

    def tick():
        now[0] += 1.0

    stream = _Stream(iter([b" "] * 100), on_chunk=tick)
    client, _ = make_client(lambda r: httpx.Response(200, stream=stream), clock=lambda: now[0])
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert stream.sent <= 7


def test_redirect_is_not_followed():
    def handler(r):
        if r.url.host == "evil.example":
            raise AssertionError("followed a redirect")
        return httpx.Response(302, headers={"location": "https://evil.example/x"})

    client, rec = make_client(handler)
    with pytest.raises(OpenFoodFactsUnavailable):
        client.by_barcode(CODE)
    assert len(rec.requests) == 1


@pytest.mark.parametrize(
    "value", ["1e400", "9" * 500, True, "+5", "-5", " 1e3 ", float("nan"), float("inf")]
)
def test_hostile_numbers_give_no_size_quickly(value):
    import time

    start = time.perf_counter()
    assert off._number(value) is None
    assert time.perf_counter() - start < 0.05
    client, _ = make_client(lambda r: hit(quantity=str(value), product_quantity=None))
    p = client.by_barcode(CODE)
    assert p.unit is None and p.unit_quantity is None
