"""
Client for Open Food Facts (https://world.openfoodfacts.org), used only to
fill in a scanned barcode's name, brand and size. No search, no images, no
prices. See docs/OPENFOODFACTS.md.

Every failure — network, timeout, HTTP error (other than 404), non-JSON body,
unexpected shape, or OPENFOODFACTS_ENABLED being off — surfaces as
:class:`OpenFoodFactsUnavailable`; callers degrade to "add it by hand".
"Not in their database" is not a failure: ``by_barcode`` returns None.

Politeness and availability: see docs/OPENFOODFACTS.md. In short: spacing of
0.7 s x workers and one request in flight per process when there are several
workers (about 86 reads a minute combined, a per-process approximation), a
5 s wall-clock deadline for the whole exchange, no redirects, an honest
User-Agent, only ASCII digits sent, a 24 h LRU cache, a 60 s per-barcode
failure cache and a circuit breaker with a half-open probe. The lock only
guards bookkeeping and is never held across a sleep or HTTP call; callers
are sync endpoints (threadpool), so nothing blocks the event loop.

Third-party data is bounded here: body at most 64 kB, text must be strings,
sizes are Decimals in (0, 100000] rounded to 3 places, else None.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://world.openfoodfacts.org"
TIMEOUT_SECONDS = 5.0  # connect + read
MAX_BODY_BYTES = 64 * 1024
MAX_WAIT_SECONDS = 2.0
MAX_IN_FLIGHT = 2
FAILURE_TTL_SECONDS = 60.0
BREAKER_THRESHOLD = 3
BREAKER_OPEN_SECONDS = 60.0
MAX_SIZE = Decimal("100000")  # app.services.stock.MAX_QUANTITY
_NUMBER_MAX_CHARS = 20
MIN_INTERVAL_SECONDS = 0.7  # per worker; multiplied by the worker count
CACHE_TTL_SECONDS = 24 * 3600.0
CACHE_MAX_ENTRIES = 2000
FIELDS = (
    "code,product_name,product_name_el,generic_name_el,brands,quantity,"
    "product_quantity,product_quantity_unit"
)
NAME_MAX = 200
BRAND_MAX = 100

_BARCODE_RE = re.compile(r"[0-9]{6,14}", re.ASCII)
# "500 g", "1,5 l", "330ml", "6 x 330 ml". Every part is length-bounded, so
# matching is linear; longer input is rejected before it reaches the regex.
_QUANTITY_RE = re.compile(
    r"(?:[0-9]{1,3} ?[x×] ?)?([0-9]{1,6}(?:[.,][0-9]{1,3})?) ?([A-Za-z]{1,3})", re.ASCII
)
_QUANTITY_MAX_LEN = 40
_UNITS = {"g": "g", "kg": "kg", "ml": "ml", "l": "L"}


class OpenFoodFactsUnavailable(Exception):
    """Open Food Facts could not be used right now; callers must degrade."""


@dataclass(frozen=True)
class OffProduct:
    barcode: str  # always the one asked for, never the one in the response
    name: str
    brand: str | None
    unit: str | None  # g, kg, ml or L
    unit_quantity: Decimal | None


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def _text(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = "".join(c for c in value if unicodedata.category(c) != "Cc").strip()
    return cleaned[:limit].strip() or None


_NUMBER_RE = re.compile(r"[0-9]{1,7}(?:[.,][0-9]{1,3})?", re.ASCII)


def _number(raw) -> Decimal | None:
    """A Decimal in (0, MAX_SIZE] rounded to 3 places, or None. The cheap
    checks (type, length, strict pattern, float range) all run before any
    Decimal is built, so no hostile input reaches an expensive conversion."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        if not (0 < raw <= MAX_SIZE):  # False for NaN too
            return None
        text = str(raw)
    elif isinstance(raw, str):
        if len(raw) > _NUMBER_MAX_CHARS:
            return None
        text = raw.strip().replace(",", ".")
        if not _NUMBER_RE.fullmatch(raw.strip()):
            return None
    else:
        return None
    try:
        value = Decimal(text).quantize(Decimal("0.001"))
    except InvalidOperation:
        return None
    return value if 0 < value <= MAX_SIZE else None


def _size(unit_raw, raw_number) -> tuple[str, Decimal] | None:
    unit = _UNITS.get(unit_raw.lower()) if isinstance(unit_raw, str) else None
    number = _number(raw_number)
    if unit is None or number is None:
        return None
    return unit, number


def parse_quantity(text) -> tuple[str, Decimal] | None:
    """A free-text pack size ("500 g", "1,5 l", "6 x 330 ml") as (unit, amount).
    For multipacks the size of one unit. None when it does not parse cleanly or
    the unit is not g, kg, ml or L."""
    if not isinstance(text, str) or len(text) > _QUANTITY_MAX_LEN:
        return None
    m = _QUANTITY_RE.fullmatch(text.strip())
    if not m:
        return None
    return _size(m.group(2), m.group(1))


def _product_size(raw: dict) -> tuple[str, Decimal] | None:
    pq, pu = raw.get("product_quantity"), raw.get("product_quantity_unit")
    size = _size(pu, pq) if pq is not None and pu is not None else None
    if size:
        return size
    return parse_quantity(raw.get("quantity"))


def _map(barcode: str, payload) -> OffProduct | None:
    if not isinstance(payload, dict):
        raise OpenFoodFactsUnavailable("unexpected response shape")
    status = payload.get("status")
    if status == 0 and not isinstance(status, bool):
        return None
    if status != 1 or isinstance(status, bool):
        raise OpenFoodFactsUnavailable("unexpected status")
    raw = payload.get("product")
    if not isinstance(raw, dict):
        raise OpenFoodFactsUnavailable("hit without a product")
    name = (
        _text(raw.get("product_name_el"), NAME_MAX)
        or _text(raw.get("product_name"), NAME_MAX)
        or _text(raw.get("generic_name_el"), NAME_MAX)
    )
    if not name:
        return None
    brands = raw.get("brands")
    brand = _text(brands.split(",")[0], BRAND_MAX) if isinstance(brands, str) else None
    size = _product_size(raw)
    return OffProduct(
        barcode=barcode,
        name=name,
        brand=brand,
        unit=size[0] if size else None,
        unit_quantity=size[1] if size else None,
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

MAX_NESTING = 32


class _Outage(OpenFoodFactsUnavailable):
    """Upstream trouble proper (transport error, timeout, 5xx, 429, deadline):
    the only kind that counts toward the circuit breaker."""


def configured_workers() -> int:
    """The worker count entrypoint.sh starts uvicorn with (WEB_CONCURRENCY, default 2)."""
    try:
        n = int(os.environ.get("WEB_CONCURRENCY", ""))
    except ValueError:
        return 2
    return n if 1 <= n <= 64 else 2


def _too_deep(body: bytes) -> bool:
    """Cheap linear check: do [ and { nest deeper than MAX_NESTING (outside strings)?"""
    depth = 0
    in_string = escaped = False
    for c in body:
        if in_string:
            if escaped:
                escaped = False
            elif c == 0x5C:  # backslash
                escaped = True
            elif c == 0x22:
                in_string = False
        elif c == 0x22:
            in_string = True
        elif c in (0x5B, 0x7B):
            depth += 1
            if depth > MAX_NESTING:
                return True
        elif c in (0x5D, 0x7D):
            depth -= 1
    return False


class OpenFoodFactsClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        enabled: bool | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = TIMEOUT_SECONDS,
        min_interval: float | None = None,
        workers: int | None = None,
        max_in_flight: int | None = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        from app.core.config import settings

        self.enabled = settings.openfoodfacts_enabled if enabled is None else enabled
        self.base_url = (base_url or settings.openfoodfacts_base_url or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        # The caches, slot clock and breaker are per process; the budget of
        # roughly 86 reads a minute is shared by dividing it over the workers.
        self.workers = configured_workers() if workers is None else max(1, workers)
        self.min_interval = (
            MIN_INTERVAL_SECONDS * self.workers if min_interval is None else min_interval
        )
        self.max_in_flight = (
            (1 if self.workers > 1 else MAX_IN_FLIGHT) if max_in_flight is None else max_in_flight
        )
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.max_entries = max_entries
        self._clock = clock
        self._sleep = sleep
        self._transport = transport
        self._lock = threading.Lock()  # bookkeeping only: never held across I/O or sleep
        self._slots = threading.BoundedSemaphore(self.max_in_flight)
        self._next_slot = 0.0
        self._cache: OrderedDict[str, tuple[float, OffProduct | None]] = OrderedDict()
        self._failed: dict[str, float] = {}  # barcode -> unavailable until
        self._failures = 0  # consecutive outage errors
        self._breaker_open = False
        self._breaker_until = 0.0
        self._probing = False  # half-open: one probe in flight
        ua = f"Tameio/1.0 (+{settings.app_base_url or 'self-hosted'})"
        self._headers = {
            "User-Agent": ua,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }

    # -- bookkeeping (all under self._lock, no I/O) -----------------------

    def _cached(self, key: str):
        hit = self._cache.get(key)
        if hit and hit[0] > self._clock():
            self._cache.move_to_end(key)
            return True, hit[1]
        return False, None

    def _store(self, key: str, value: OffProduct | None):
        self._cache[key] = (self._clock() + self.cache_ttl, value)
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_entries:
            self._cache.popitem(last=False)

    def _remember_failure(self, barcode: str, now: float):
        self._failed[barcode] = now + FAILURE_TTL_SECONDS
        if len(self._failed) > self.max_entries:
            for k in [k for k, until in self._failed.items() if until <= now]:
                self._failed.pop(k, None)
            while len(self._failed) > self.max_entries:
                self._failed.pop(next(iter(self._failed)))

    def _record_failure(self, barcode: str, *, outage: bool, probe: bool):
        with self._lock:
            now = self._clock()
            self._remember_failure(barcode, now)
            if outage:
                self._failures += 1
                if probe or self._failures >= BREAKER_THRESHOLD:
                    self._breaker_open = True
                    self._breaker_until = now + BREAKER_OPEN_SECONDS
                    self._failures = 0
            elif probe:  # upstream answered: it is reachable again
                self._breaker_open = False
                self._failures = 0

    def _record_success(self):
        with self._lock:
            self._failures = 0
            self._breaker_open = False

    def _reserve(self) -> float:
        """Claim the next request slot; returns how long to wait for it. Fails
        fast when it is too far away (too many callers already waiting)."""
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            if slot - now > MAX_WAIT_SECONDS:
                raise OpenFoodFactsUnavailable("too many lookups waiting")
            self._next_slot = slot + self.min_interval
            return slot - now

    # -- HTTP (no lock held) ----------------------------------------------

    def _exchange(self, http: httpx.Client, path: str) -> bytes | None:
        """The request and capped body read; runs in a worker thread."""
        try:
            with http.stream("GET", path, params={"fields": FIELDS}) as resp:
                code = resp.status_code
                if code == 404:
                    return None
                if code != 200:
                    logger.warning("Open Food Facts GET %s -> HTTP %s", path, code)
                    if code >= 500 or code == 429:
                        raise _Outage(f"HTTP {code}")
                    raise OpenFoodFactsUnavailable(f"HTTP {code}")
                encoding = resp.headers.get("content-encoding", "").strip().lower()
                if encoding not in ("", "identity"):
                    raise OpenFoodFactsUnavailable("encoded response")
                declared = resp.headers.get("content-length", "")
                if (
                    declared.isascii()
                    and declared.isdigit()
                    and int(declared[:12]) > MAX_BODY_BYTES
                ):
                    raise OpenFoodFactsUnavailable("response too large")
                body = bytearray()
                try:
                    for chunk in resp.iter_raw():
                        body += chunk
                        if len(body) > MAX_BODY_BYTES:
                            raise OpenFoodFactsUnavailable("response too large")
                except httpx.StreamConsumed:  # a mock transport pre-read it; real ones stream
                    if len(resp.content) > MAX_BODY_BYTES:
                        raise OpenFoodFactsUnavailable("response too large") from None
                    body = bytearray(resp.content)
                return bytes(body)
        except httpx.HTTPError as exc:
            logger.warning("Open Food Facts GET %s failed: %s", path, exc)
            raise _Outage(str(exc)) from exc

    def _fetch(self, barcode: str) -> bytes | None:
        """One exchange under a wall-clock deadline covering connect, headers
        and body. At the deadline the connection is torn down."""
        path = f"/api/v2/product/{barcode}.json"
        http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=min(2.0, self.timeout)),
            follow_redirects=False,
            transport=self._transport,
            headers=self._headers,
        )
        box: dict = {}

        def work():
            try:
                box["body"] = self._exchange(http, path)
            except BaseException as exc:  # handed back to the caller's thread
                box["error"] = exc

        worker = threading.Thread(target=work, daemon=True, name="off-fetch")
        worker.start()
        worker.join(self.timeout)
        try:
            if worker.is_alive():
                logger.warning("Open Food Facts GET %s hit the %.1fs deadline", path, self.timeout)
                raise _Outage("deadline exceeded")
        finally:
            try:
                http.close()
            except Exception:  # best effort: tears the socket down
                pass
        if "error" in box:
            exc = box["error"]
            if isinstance(exc, OpenFoodFactsUnavailable):
                raise exc
            logger.warning("Open Food Facts GET %s: unexpected error while fetching", path)
            raise OpenFoodFactsUnavailable("unexpected error") from None
        return box["body"]

    def _parse(self, barcode: str, body: bytes | None) -> OffProduct | None:
        if body is None:
            return None
        try:
            if _too_deep(body):
                raise OpenFoodFactsUnavailable("response nested too deeply")
            return _map(barcode, json.loads(body))
        except OpenFoodFactsUnavailable:
            raise
        except Exception:  # incl. RecursionError, MemoryError: never escape as a 500
            logger.warning("Open Food Facts: unusable response")
            raise OpenFoodFactsUnavailable("unusable response") from None

    def by_barcode(self, barcode: str) -> OffProduct | None:
        if not self.enabled:
            raise OpenFoodFactsUnavailable("lookups are disabled (OPENFOODFACTS_ENABLED=false)")
        barcode = (barcode or "").strip() if isinstance(barcode, str) else ""
        if not _BARCODE_RE.fullmatch(barcode):
            return None
        probe = False
        with self._lock:
            found, value = self._cached(barcode)
            if found:
                return value
            now = self._clock()
            if self._failed.get(barcode, 0.0) > now:
                raise OpenFoodFactsUnavailable("recently failed")
            if self._breaker_open:
                if now < self._breaker_until or self._probing:
                    raise OpenFoodFactsUnavailable("circuit open")
                self._probing = probe = True  # half-open: this call is the probe
        resolved = False
        try:
            if not self._slots.acquire(blocking=False):
                raise OpenFoodFactsUnavailable("too many lookups in flight")
            try:
                wait = self._reserve()  # local congestion is not an upstream outage
                if wait > 0:
                    self._sleep(wait)
                try:
                    mapped = self._parse(barcode, self._fetch(barcode))
                except OpenFoodFactsUnavailable as exc:
                    resolved = True
                    self._record_failure(barcode, outage=isinstance(exc, _Outage), probe=probe)
                    raise
                resolved = True
                self._record_success()
                with self._lock:
                    self._store(barcode, mapped)
                return mapped
            finally:
                self._slots.release()
        finally:
            if probe:
                with self._lock:
                    self._probing = False
            del resolved


# ---------------------------------------------------------------------------
# Module-level convenience (one shared client per process)
# ---------------------------------------------------------------------------

_client: OpenFoodFactsClient | None = None
_client_lock = threading.Lock()


def get_client() -> OpenFoodFactsClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenFoodFactsClient()
    return _client


def by_barcode(barcode: str) -> OffProduct | None:
    return get_client().by_barcode(barcode)
