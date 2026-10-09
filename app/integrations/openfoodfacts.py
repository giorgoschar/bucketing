"""
Client for Open Food Facts (https://world.openfoodfacts.org), used only to
fill in a scanned barcode's name, brand and size. No search, no images, no
prices. See docs/OPENFOODFACTS.md.

Every failure — network, timeout, HTTP error (other than 404), non-JSON body,
unexpected shape, or OPENFOODFACTS_ENABLED being off — surfaces as
:class:`OpenFoodFactsUnavailable`; callers degrade to "add it by hand".
"Not in their database" is not a failure: ``by_barcode`` returns None.

Politeness: one request at a time per process, at least 0.7 s apart (well
under their 100 product reads a minute), a 10 s timeout, an honest
User-Agent, only ASCII digits ever sent, and a 24 h in-process LRU cache
(hits and "not found", at most 2000 entries).
"""

from __future__ import annotations

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
TIMEOUT_SECONDS = 10.0
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
    r"(?:[0-9]{1,3} ?[x×] ?)?([0-9]{1,7}(?:[.,][0-9]{1,3})?) ?([A-Za-z]{1,3})", re.ASCII
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


def _size(unit_raw, number: Decimal) -> tuple[str, Decimal] | None:
    unit = _UNITS.get(unit_raw.lower()) if isinstance(unit_raw, str) else None
    if unit is None or not number.is_finite() or number <= 0:
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
    try:
        number = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None
    return _size(m.group(2), number)


def _product_size(raw: dict) -> tuple[str, Decimal] | None:
    pq, pu = raw.get("product_quantity"), raw.get("product_quantity_unit")
    if pq is not None and pu is not None and not isinstance(pq, bool):
        try:
            size = _size(pu, Decimal(str(pq).strip()))
        except InvalidOperation:
            size = None
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
        self.cache_ttl = cache_ttl
        self.max_entries = max_entries
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request: float | None = None
        self._cache: OrderedDict[str, tuple[float, OffProduct | None]] = OrderedDict()
        ua = f"Tameio/1.0 (+{settings.app_base_url or 'self-hosted'})"
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": ua, "Accept": "application/json"},
        )

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

    def _fetch(self, barcode: str):
        """One spaced request; caller holds self._lock."""
        if self._last_request is not None and self.min_interval > 0:
            wait = self._last_request + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        path = f"/api/v2/product/{barcode}.json"
        try:
            resp = self._http.get(path, params={"fields": FIELDS})
        except httpx.HTTPError as exc:
            logger.warning("Open Food Facts GET %s failed: %s", path, exc)
            raise OpenFoodFactsUnavailable(str(exc)) from exc
        finally:
            self._last_request = self._clock()
        if resp.status_code == 404:
            return {"status": 0}
        if resp.status_code != 200:
            logger.warning("Open Food Facts GET %s -> HTTP %s", path, resp.status_code)
            raise OpenFoodFactsUnavailable(f"HTTP {resp.status_code}")
        try:
            return resp.json()
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
            payload = self._fetch(barcode)
            try:
                mapped = _map(barcode, payload)
            except OpenFoodFactsUnavailable:
                raise
            except Exception as exc:  # any shape surprise is "unavailable"
                raise OpenFoodFactsUnavailable(f"unexpected response: {exc}") from exc
            self._store(barcode, mapped)
            return mapped


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
