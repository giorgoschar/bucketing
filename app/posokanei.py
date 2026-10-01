"""
Client for PosoKanei (https://posokanei.gov.gr), the Greek supermarket price
observatory.

The API is UNOFFICIAL from our point of view: undocumented, unversioned and
free to change or block us at any time. Every failure — network, timeout,
HTTP error, non-JSON body, unexpected shape, or the POSOKANEI_ENABLED switch
being off — surfaces as :class:`PosokaneiUnavailable`, and every caller is
expected to degrade (show "prices unavailable", skip the scheduler stage)
rather than error. See docs/POSOKANEI.md.

Politeness: one request at a time per process, at least ``min_interval``
seconds apart (≤ 4 req/s), a 15 s timeout, an identifying User-Agent, and a
5-minute in-process cache of successful responses.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.posokanei.gov.gr"
TIMEOUT_SECONDS = 15.0
MIN_INTERVAL_SECONDS = 0.25
CACHE_TTL_SECONDS = 300.0
_BARCODE_RE = re.compile(r"^\d{6,14}$")


class PosokaneiUnavailable(Exception):
    """PosoKanei could not be used right now; callers must degrade."""


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetailerPrice:
    retailer: str
    display_name: str
    price: Decimal | None
    unit_price: Decimal | None
    is_discount: bool
    discount_pct: Decimal | None
    last_updated: str | None


@dataclass(frozen=True)
class PriceStats:
    min: Decimal | None
    max: Decimal | None
    avg: Decimal | None


@dataclass(frozen=True)
class PricePoint:
    """One historical observation (only present on ``get(include_history)``)."""
    date: str
    retailer: str
    price: Decimal
    unit_price: Decimal | None = None
    is_discount: bool = False


@dataclass(frozen=True)
class ProductSummary:
    id: str
    name: str
    brand: str | None
    barcode: str | None
    unit: str | None
    unit_quantity: Decimal | None
    image_url: str | None
    retailer_prices: list[RetailerPrice]
    price_stats: PriceStats
    history: list[PricePoint] = field(default_factory=list)

    @property
    def cheapest(self) -> RetailerPrice | None:
        priced = [r for r in self.retailer_prices if r.price is not None]
        return min(priced, key=lambda r: r.price) if priced else None


# ---------------------------------------------------------------------------
# Mapping (tolerant: the API is undocumented, so accept common key variants)
# ---------------------------------------------------------------------------

def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _map_retailer(raw: dict) -> RetailerPrice:
    retailer = _first(raw, "retailer", "retailer_id", "retailer_code", "store", "chain")
    if isinstance(retailer, dict):  # {"retailer": {"id":..., "name":...}}
        nested = retailer
        retailer = _first(nested, "id", "code", "slug", "name")
        display = _first(raw, "display_name") or _first(nested, "display_name", "name")
    else:
        display = _first(raw, "display_name", "retailer_name", "store_name", "name")
    retailer = _str(retailer) or _str(display) or "unknown"
    return RetailerPrice(
        retailer=retailer[:40],
        display_name=_str(display) or retailer,
        price=_dec(_first(raw, "price", "final_price", "current_price")),
        unit_price=_dec(_first(raw, "unit_price", "price_per_unit")),
        is_discount=bool(_first(raw, "is_discount", "discount", "on_offer", default=False)),
        discount_pct=_dec(_first(raw, "discount_pct", "discount_percent", "discount_percentage")),
        last_updated=_str(_first(raw, "last_updated", "updated_at", "date")),
    )


def _map_history(raw) -> list[PricePoint]:
    points = []
    for h in raw or []:
        if not isinstance(h, dict):
            continue
        price = _dec(_first(h, "price", "min_price", "final_price"))
        day = _str(_first(h, "date", "snapshot_date", "day"))
        if price is None or day is None:
            continue
        points.append(PricePoint(
            date=day[:10],
            retailer=(_str(_first(h, "retailer", "retailer_id", "store")) or "unknown")[:40],
            price=price,
            unit_price=_dec(_first(h, "unit_price", "price_per_unit")),
            is_discount=bool(_first(h, "is_discount", "discount", default=False)),
        ))
    return points


def _map_product(raw) -> ProductSummary:
    if not isinstance(raw, dict):
        raise PosokaneiUnavailable("unexpected product shape")
    pid = _str(_first(raw, "id", "product_id", "uuid"))
    name = _str(_first(raw, "name", "title", "product_name"))
    if not pid or not name:
        raise PosokaneiUnavailable("product without id/name")

    prices_raw = _first(raw, "retailer_prices", "prices", "retailers", default=[])
    prices = [_map_retailer(p) for p in prices_raw if isinstance(p, dict)]

    stats_raw = _first(raw, "price_stats", "stats", default=None)
    if isinstance(stats_raw, dict):
        stats = PriceStats(
            min=_dec(_first(stats_raw, "min", "min_price")),
            max=_dec(_first(stats_raw, "max", "max_price")),
            avg=_dec(_first(stats_raw, "avg", "mean", "avg_price")),
        )
    else:
        values = [p.price for p in prices if p.price is not None]
        stats = PriceStats(
            min=min(values) if values else None,
            max=max(values) if values else None,
            avg=(sum(values) / len(values)).quantize(Decimal("0.01")) if values else None,
        )

    return ProductSummary(
        id=pid[:64],
        name=name[:200],
        brand=(_str(_first(raw, "brand", "brand_name")) or None),
        barcode=_str(_first(raw, "barcode", "ean", "gtin")),
        unit=_str(_first(raw, "unit", "unit_of_measure")),
        unit_quantity=_dec(_first(raw, "unit_quantity", "quantity", "size")),
        image_url=_str(_first(raw, "image_url", "image", "thumbnail")),
        retailer_prices=prices,
        price_stats=stats,
        history=_map_history(_first(raw, "history", "price_history", default=[])),
    )


def _map_search(payload) -> list[ProductSummary]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = _first(payload, "results", "items", "products", "data")
        if not isinstance(items, list):
            raise PosokaneiUnavailable("unexpected search shape")
    else:
        raise PosokaneiUnavailable("unexpected search shape")
    return [_map_product(p) for p in items]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class PosokaneiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        enabled: bool | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = TIMEOUT_SECONDS,
        min_interval: float = MIN_INTERVAL_SECONDS,
        cache_ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        from app.config import settings

        self.enabled = settings.posokanei_enabled if enabled is None else enabled
        self.base_url = (base_url or settings.posokanei_base_url or DEFAULT_BASE_URL).rstrip("/")
        self.min_interval = min_interval
        self.cache_ttl = cache_ttl
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request: float | None = None
        self._cache: dict[tuple, tuple[float, object]] = {}
        ua = f"expenses-app/1.0 (+{settings.app_base_url or 'self-hosted'})"
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": ua, "Accept": "application/json"},
        )

    # -- plumbing --------------------------------------------------------

    def _cached(self, key):
        hit = self._cache.get(key)
        if hit and hit[0] > self._clock():
            return True, hit[1]
        return False, None

    def _send(self, method: str, path: str, *, allow_404=False, **kw):
        """One spaced HTTP request; caller holds self._lock."""
        if self._last_request is not None and self.min_interval > 0:
            wait = self._last_request + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            resp = self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            logger.warning("PosoKanei %s %s failed: %s", method, path, exc)
            raise PosokaneiUnavailable(str(exc)) from exc
        finally:
            self._last_request = self._clock()
        if allow_404 and resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning("PosoKanei %s %s -> HTTP %s", method, path, resp.status_code)
            raise PosokaneiUnavailable(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise PosokaneiUnavailable("non-JSON response") from exc

    def _store(self, key, value):
        self._cache[key] = (self._clock() + self.cache_ttl, value)
        if len(self._cache) > 512:  # bound memory: drop expired, then oldest
            now = self._clock()
            for k in [k for k, (exp, _) in self._cache.items() if exp <= now]:
                self._cache.pop(k, None)
            while len(self._cache) > 512:
                self._cache.pop(next(iter(self._cache)))
        return value

    def _call(self, key, mapper, method, path, **kw):
        if not self.enabled:
            raise PosokaneiUnavailable("PosoKanei lookups are disabled (POSOKANEI_ENABLED=false)")
        found, value = self._cached(key)
        if found:
            return value
        # Serialised: keeps the spacing guarantee and lets a concurrent caller
        # for the same key reuse the result instead of calling out twice.
        with self._lock:
            found, value = self._cached(key)
            if found:
                return value
            payload = self._send(method, path, **kw)
            try:
                mapped = mapper(payload)
            except PosokaneiUnavailable:
                raise
            except Exception as exc:  # any shape surprise is "unavailable"
                raise PosokaneiUnavailable(f"unexpected response: {exc}") from exc
            return self._store(key, mapped)

    # -- public API ------------------------------------------------------

    def search(self, query: str, page: int = 1, page_size: int = 20) -> list[ProductSummary]:
        query = (query or "").strip()[:100]
        if not query:
            return []
        body = {"query": query, "page": page, "page_size": page_size}
        return self._call(("search", query, page, page_size), _map_search,
                          "POST", "/products/search", json=body)

    def by_barcode(self, barcode: str) -> ProductSummary | None:
        barcode = (barcode or "").strip()
        if not _BARCODE_RE.match(barcode):
            return None
        return self._call(
            ("barcode", barcode),
            lambda p: None if p is None else _map_product(p),
            "GET", f"/products/barcode/{barcode}", allow_404=True,
        )

    def get(self, product_id: str, include_history: bool = True) -> ProductSummary:
        pid = (product_id or "").strip()
        if not pid or "/" in pid or len(pid) > 64:
            raise PosokaneiUnavailable("invalid product id")
        params = {
            "countries": "GR",
            "include_tax": "true",
            "include_history": "true" if include_history else "false",
        }
        return self._call(("get", pid, include_history), _map_product,
                          "GET", f"/products/{pid}", params=params)


# ---------------------------------------------------------------------------
# Module-level convenience (one shared client per process)
# ---------------------------------------------------------------------------

_client: PosokaneiClient | None = None
_client_lock = threading.Lock()


def get_client() -> PosokaneiClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = PosokaneiClient()
    return _client


def search(query: str, page: int = 1, page_size: int = 20) -> list[ProductSummary]:
    return get_client().search(query, page, page_size)


def by_barcode(barcode: str) -> ProductSummary | None:
    return get_client().by_barcode(barcode)


def get(product_id: str, include_history: bool = True) -> ProductSummary:
    return get_client().get(product_id, include_history)
