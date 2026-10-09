"""
Client for Open Food Facts (https://world.openfoodfacts.org), used only to
fill in a scanned barcode's name, brand and size. No search, no images, no
prices. See docs/OPENFOODFACTS.md.

Every failure — network, timeout, HTTP error (other than 404), non-JSON body,
unexpected shape, or OPENFOODFACTS_ENABLED being off — surfaces as
:class:`OpenFoodFactsUnavailable`; callers degrade to "add it by hand".
"Not in their database" is not a failure: ``by_barcode`` returns None.

Politeness: requests are at least 0.7 s apart process-wide (well under their
100 product reads a minute), a 5 s timeout, an honest User-Agent, only ASCII
digits ever sent, and a 24 h in-process LRU cache (hits and "not found", at
most 2000 entries).

Availability: the lock only guards bookkeeping (the next free request slot,
the caches, the breaker) and is never held across a sleep or HTTP call. A
caller whose slot is more than 2 s away, or who finds 2 lookups already in
flight, fails fast instead of queueing. An outage error is remembered per
barcode for 60 s, and 3 in a row open a breaker that short-circuits every
lookup for 60 s. Callers are sync endpoints (threadpool), so none of this
blocks the event loop.

Third-party data is bounded here: body at most 64 kB, text must be strings,
sizes are Decimals in (0, 100000] rounded to 3 places, else None.
"""

from __future__ import annotations

import json
import logging
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
MIN_INTERVAL_SECONDS = 0.7
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


class OpenFoodFactsClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        enabled: bool | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = TIMEOUT_SECONDS,
        min_interval: float = MIN_INTERVAL_SECONDS,
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
        self.min_interval = min_interval
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.max_entries = max_entries
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()  # bookkeeping only: never held across I/O or sleep
        self._slots = threading.BoundedSemaphore(MAX_IN_FLIGHT)
        self._next_slot = 0.0
        self._cache: OrderedDict[str, tuple[float, OffProduct | None]] = OrderedDict()
        self._failed: dict[str, float] = {}  # barcode -> unavailable until
        self._failures = 0  # consecutive outage errors
        self._breaker_until = 0.0
        ua = f"Tameio/1.0 (+{settings.app_base_url or 'self-hosted'})"
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=min(2.0, timeout)),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": ua, "Accept": "application/json"},
        )

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

    def _record_failure(self, barcode: str):
        with self._lock:
            now = self._clock()
            self._failed[barcode] = now + FAILURE_TTL_SECONDS
            if len(self._failed) > self.max_entries:
                for k in [k for k, until in self._failed.items() if until <= now]:
                    self._failed.pop(k, None)
                while len(self._failed) > self.max_entries:
                    self._failed.pop(next(iter(self._failed)))
            self._failures += 1
            if self._failures >= BREAKER_THRESHOLD:
                self._breaker_until = now + BREAKER_OPEN_SECONDS
                self._failures = 0

    def _record_success(self):
        with self._lock:
            self._failures = 0

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

    def _fetch(self, barcode: str):
        path = f"/api/v2/product/{barcode}.json"
        try:
            deadline = self._clock() + self.timeout  # total, not per read
            with self._http.stream("GET", path, params={"fields": FIELDS}) as resp:
                if resp.status_code == 404:
                    return {"status": 0}
                if resp.status_code != 200:
                    logger.warning("Open Food Facts GET %s -> HTTP %s", path, resp.status_code)
                    raise OpenFoodFactsUnavailable(f"HTTP {resp.status_code}")
                declared = resp.headers.get("content-length", "")
                if (
                    declared.isascii()
                    and declared.isdigit()
                    and int(declared[:12]) > MAX_BODY_BYTES
                ):
                    raise OpenFoodFactsUnavailable("response too large")
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY_BYTES:
                        raise OpenFoodFactsUnavailable("response too large")
                    if self._clock() > deadline:
                        raise OpenFoodFactsUnavailable("response too slow")
                if self._clock() > deadline:
                    raise OpenFoodFactsUnavailable("response too slow")
        except httpx.HTTPError as exc:
            logger.warning("Open Food Facts GET %s failed: %s", path, exc)
            raise OpenFoodFactsUnavailable(str(exc)) from exc
        try:
            return json.loads(bytes(body))
        except ValueError as exc:
            raise OpenFoodFactsUnavailable("non-JSON response") from exc

    def by_barcode(self, barcode: str) -> OffProduct | None:
        if not self.enabled:
            raise OpenFoodFactsUnavailable("lookups are disabled (OPENFOODFACTS_ENABLED=false)")
        barcode = (barcode or "").strip() if isinstance(barcode, str) else ""
        if not _BARCODE_RE.fullmatch(barcode):
            return None
        with self._lock:
            found, value = self._cached(barcode)
            if found:
                return value
            now = self._clock()
            if now < self._breaker_until:
                raise OpenFoodFactsUnavailable("circuit open")
            if self._failed.get(barcode, 0.0) > now:
                raise OpenFoodFactsUnavailable("recently failed")
        if not self._slots.acquire(blocking=False):
            raise OpenFoodFactsUnavailable("too many lookups in flight")
        try:
            wait = self._reserve()  # local congestion is not an upstream outage
            if wait > 0:
                self._sleep(wait)
            try:
                payload = self._fetch(barcode)
                try:
                    mapped = _map(barcode, payload)
                except OpenFoodFactsUnavailable:
                    raise
                except Exception as exc:  # any shape surprise is "unavailable"
                    raise OpenFoodFactsUnavailable(f"unexpected response: {exc}") from exc
            except OpenFoodFactsUnavailable:
                self._record_failure(barcode)
                raise
            self._record_success()
            with self._lock:
                self._store(barcode, mapped)
            return mapped
        finally:
            self._slots.release()


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
