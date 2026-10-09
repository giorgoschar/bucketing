"""
Household stock: products, quantities, consumption log and price snapshots.

Everything is scoped by household id; a stock item id from the client is
always resolved through :func:`get_stock_item` so another household's id is
indistinguishable from a missing one.

Products are never hard-deleted here: :func:`archive_product` hides one from
the stock list but keeps its price history and movements.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.clock import local_today, utcnow_naive
from app.core.money import ZERO, quantize, to_decimal
from app.integrations import posokanei
from app.integrations.posokanei import PosokaneiUnavailable, valid_product_id
from app.models import (
    PriceSnapshot,
    Product,
    ShoppingLine,
    StockItem,
    StockMovement,
    StockReason,
)

MAX_QUANTITY = Decimal("100000")
_BARCODE_RE = re.compile(r"^\d{6,14}$")


class StockError(ValueError):
    """Invalid stock input (maps to HTTP 400)."""


class ShoppingIdConflict(Exception):
    """A client-chosen shopping-line id is already used by a row this request
    cannot be a replay of (another household's, another item's, or the other
    kind of line). Maps to 409, saying nothing about that row."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_quantity(
    raw, *, field: str = "Quantity", allow_zero: bool = True, allow_negative: bool = False
) -> Decimal:
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except Exception:
        raise StockError(f"{field} must be a number.") from None
    if not value.is_finite():
        raise StockError(f"{field} must be a number.")
    if value < 0 and not allow_negative:
        raise StockError(f"{field} cannot be negative.")
    if value == 0 and not allow_zero:
        raise StockError(f"{field} cannot be zero.")
    if abs(value) > MAX_QUANTITY:
        raise StockError(f"{field} is too large.")
    return value.quantize(Decimal("0.01"))


def clean_barcode(raw: str | None) -> str | None:
    code = (raw or "").strip()
    if not code:
        return None
    if not _BARCODE_RE.match(code):
        raise StockError("Barcode must be 6–14 digits.")
    return code


def _clip(raw, n: int) -> str | None:
    s = (raw or "").strip() if isinstance(raw, str) or raw is None else str(raw).strip()
    return s[:n] or None


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def list_stock(db: Session, hh_id: str) -> list[StockItem]:
    return (
        db.query(StockItem)
        .join(Product, Product.id == StockItem.product_id)
        .options(joinedload(StockItem.product))
        .filter(StockItem.household_id == hh_id, Product.archived_at.is_(None))
        .order_by(Product.name)
        .all()
    )


def get_stock_item(db: Session, hh_id: str, item_id: str) -> StockItem | None:
    item = db.get(StockItem, item_id)
    if item is None or item.household_id != hh_id:
        return None
    return item


def pantry_match(
    db: Session, hh_id: str, barcode: str | None, posokanei_id: str | None = None
) -> StockItem | None:
    """The household's (unarchived) stock item with this barcode or this
    PosoKanei product id, if any; a barcode match wins."""
    keys = []
    if barcode:
        keys.append(Product.barcode == barcode)
    if posokanei_id:
        keys.append(Product.posokanei_id == posokanei_id)
    if not keys:
        return None
    rows = (
        db.query(StockItem)
        .join(Product, Product.id == StockItem.product_id)
        .filter(Product.household_id == hh_id, Product.archived_at.is_(None), or_(*keys))
        .all()
    )
    rows.sort(key=lambda i: (not barcode or i.product.barcode != barcode, i.product.name, i.id))
    return rows[0] if rows else None


def _lock_query(db: Session, hh_id: str, item_id: str):
    return (
        db.query(StockItem)
        .filter(StockItem.id == item_id, StockItem.household_id == hh_id)
        .with_for_update()
        .populate_existing()
    )


def lock_stock_item(db: Session, hh_id: str, item_id: str) -> StockItem | None:
    """The household's stock item, row-locked (FOR UPDATE on Postgres) and
    freshly read, so a read-modify-write of its quantity cannot lose a
    concurrent one."""
    return _lock_query(db, hh_id, item_id).first()


def stock_summary(db: Session, hh_id: str) -> dict:
    """Home's pantry counts: count queries only (no prices, no run-out)."""
    low_count = (
        db.query(func.count(StockItem.id))
        .join(Product, Product.id == StockItem.product_id)
        .filter(
            StockItem.household_id == hh_id,
            Product.archived_at.is_(None),
            StockItem.quantity <= StockItem.min_quantity,
        )
        .scalar()
    )
    return {"low_count": int(low_count or 0), "ticked_count": ticked_count(db, hh_id)}


# ---------------------------------------------------------------------------
# Mutations (caller commits)
# ---------------------------------------------------------------------------


def _move(
    db,
    item: StockItem,
    delta: Decimal,
    reason: StockReason,
    user_id: str | None,
    client_id: str | None = None,
):
    db.add(
        StockMovement(
            stock_item_id=item.id,
            delta=delta,
            reason=reason.value,
            created_by=user_id,
            created_at=utcnow_naive(),
            client_id=client_id,
        )
    )


def add_product(
    db: Session,
    hh_id: str,
    user_id: str | None,
    *,
    name: str,
    brand: str | None = None,
    barcode: str | None = None,
    posokanei_id: str | None = None,
    unit: str | None = None,
    unit_quantity=None,
    image_url: str | None = None,
    quantity=ZERO,
    min_quantity=Decimal("1"),
    category_id: str | None = None,
) -> StockItem:
    """Add a product to the household's stock (or revive the existing one
    with the same barcode)."""
    name = _clip(name, 200)
    if not name:
        raise StockError("Name is required.")
    barcode = clean_barcode(barcode)
    posokanei_id = (posokanei_id or "").strip() or None
    if posokanei_id is not None and not valid_product_id(posokanei_id):
        raise StockError("Invalid PosoKanei product id.")
    quantity = parse_quantity(quantity)
    min_quantity = parse_quantity(min_quantity, field="Minimum")
    if image_url and not str(image_url).startswith("https://"):
        image_url = None

    product = None
    if barcode:
        product = (
            db.query(Product)
            .filter(Product.household_id == hh_id, Product.barcode == barcode)
            .first()
        )
    if product is not None:
        product.archived_at = None
        product.posokanei_id = product.posokanei_id or _clip(posokanei_id, 64)
        item = product.stock_item
        if item is None:
            item = StockItem(
                household_id=hh_id, product_id=product.id, quantity=ZERO, min_quantity=min_quantity
            )
            db.add(item)
            db.flush()
        return item

    product = Product(
        household_id=hh_id,
        name=name,
        brand=_clip(brand, 100),
        barcode=barcode,
        posokanei_id=_clip(posokanei_id, 64),
        unit=_clip(unit, 20),
        unit_quantity=to_decimal(unit_quantity) if unit_quantity not in (None, "") else None,
        image_url=_clip(image_url, 500),
        category_id=category_id,
        created_at=utcnow_naive(),
    )
    db.add(product)
    db.flush()
    item = StockItem(
        household_id=hh_id,
        product_id=product.id,
        quantity=quantity,
        min_quantity=min_quantity,
        track_price=True,
        updated_at=utcnow_naive(),
    )
    db.add(item)
    db.flush()
    if quantity > 0:
        _move(db, item, quantity, StockReason.adjust, user_id)
    return item


def adjust_stock(
    db: Session,
    hh_id: str,
    item_id: str,
    delta,
    user_id: str | None,
    reason: StockReason | None = None,
    client_id: str | None = None,
) -> StockItem | None:
    """Change a quantity by ``delta`` (never below zero) and log the movement.

    The logged delta is what actually changed, so using an item already at
    zero records nothing and cannot skew the consumption rate. ``client_id``
    (the PWA's queued stepper) is stored on the movement for
    :func:`find_adjust_replay`. The item row is locked first.
    """
    item = lock_stock_item(db, hh_id, item_id)
    if item is None:
        return None
    delta = to_decimal(delta)
    before = to_decimal(item.quantity)
    after = max(ZERO, before + delta)
    actual = after - before
    if reason is None:
        reason = StockReason.buy if delta > 0 else StockReason.use
    item.quantity = after
    item.updated_at = utcnow_naive()
    if actual != 0:
        _move(db, item, actual, reason, user_id, client_id)
    db.flush()
    return item


ADJUST_DEDUPE_WINDOW = timedelta(hours=24)


def find_adjust_replay(db: Session, hh_id: str, client_id: str) -> StockMovement | None:
    """The household's movement logged with ``client_id`` in the last 24 h:
    an adjust with that id was already applied. (A clamped no-op logs no
    movement, so its replay runs again, and clamps again.)"""
    since = utcnow_naive() - ADJUST_DEDUPE_WINDOW
    return (
        db.query(StockMovement)
        .join(StockItem, StockItem.id == StockMovement.stock_item_id)
        .filter(
            StockItem.household_id == hh_id,
            StockMovement.client_id == client_id,
            StockMovement.created_at >= since,
        )
        .first()
    )


def update_stock_settings(
    db: Session, hh_id: str, item_id: str, *, min_quantity=None, track_price: bool | None = None
) -> StockItem | None:
    item = get_stock_item(db, hh_id, item_id)
    if item is None:
        return None
    if min_quantity is not None:
        item.min_quantity = parse_quantity(min_quantity, field="Minimum")
    if track_price is not None:
        item.track_price = track_price
    item.updated_at = utcnow_naive()
    return item


class BarcodeTaken(Exception):
    """Another product of the household already has this barcode (409)."""


BARCODE_TAKEN = "Another product already has this barcode"


def edit_product(db: Session, item: StockItem, fields: dict) -> StockItem:
    """Change the item's product details (polish C2). ``fields`` holds only
    what the client sent, already validated: ``name`` (non-empty), ``brand``,
    ``unit``, ``unit_quantity`` (> 0 or None) and ``barcode`` (cleaned or
    None); a None clears the field. Raises :class:`BarcodeTaken` when another
    product of the household (archived ones too: the unique index covers
    them) has the barcode."""
    product = item.product
    if "barcode" in fields and fields["barcode"] and fields["barcode"] != product.barcode:
        clash = (
            db.query(Product.id)
            .filter(
                Product.household_id == item.household_id,
                Product.barcode == fields["barcode"],
                Product.id != product.id,
            )
            .first()
        )
        if clash is not None:
            raise BarcodeTaken(fields["barcode"])
    limits = {"name": 200, "brand": 100, "unit": 20}
    for key, value in fields.items():
        if key in limits:
            value = _clip(value, limits[key])
        setattr(product, key, value)
    item.updated_at = utcnow_naive()
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # A concurrent edit or add took the barcode between the check and here.
        raise BarcodeTaken(fields.get("barcode")) from None
    return item


def archive_product(db: Session, hh_id: str, item_id: str) -> StockItem | None:
    """Hide a product from the stock list. History stays (soft delete); its
    active shopping-list tick is cleared."""
    item = get_stock_item(db, hh_id, item_id)
    if item is None:
        return None
    now = utcnow_naive()
    item.product.archived_at = now
    _active_lines(db, hh_id).filter(ShoppingLine.stock_item_id == item.id).update(
        {ShoppingLine.cleared_at: now}, synchronize_session="fetch"
    )
    return item


# ---------------------------------------------------------------------------
# Price snapshots
# ---------------------------------------------------------------------------


def snapshot_now(db: Session, product: Product) -> bool:
    """Fetch and store today's prices for a linked product. False if the
    product is not linked to PosoKanei or PosoKanei is unavailable."""
    if not product.posokanei_id:
        return False
    try:
        summary = posokanei.get(product.posokanei_id)
    except PosokaneiUnavailable:
        return False
    record_snapshots(db, product, summary, local_today())
    return True


def record_snapshots(db: Session, product: Product, summary, day: date) -> int:
    """Store ``summary``'s retailer prices as ``day``'s snapshots, plus any
    earlier history it carries. Existing (product, retailer, day) rows are left
    alone, so this is safe to repeat. Returns the number of rows inserted."""
    rows: dict[tuple[str, date], tuple] = {}
    for point in getattr(summary, "history", None) or []:
        try:
            d = date.fromisoformat(point.date)
        except (TypeError, ValueError):
            continue
        if d < day:
            rows[(point.retailer, d)] = (point.price, point.unit_price, point.is_discount)
    for rp in summary.retailer_prices:
        if rp.price is not None:
            rows[(rp.retailer, day)] = (rp.price, rp.unit_price, rp.is_discount)
    if not rows:
        return 0

    existing = {
        (r, d)
        for r, d in db.query(PriceSnapshot.retailer, PriceSnapshot.snapshot_date).filter(
            PriceSnapshot.product_id == product.id,
            PriceSnapshot.snapshot_date.in_({d for _, d in rows}),
        )
    }
    added = 0
    for (retailer, d), (price, unit_price, is_discount) in rows.items():
        if (retailer, d) in existing:
            continue
        db.add(
            PriceSnapshot(
                product_id=product.id,
                retailer=retailer[:40],
                snapshot_date=d,
                price=to_decimal(price).quantize(Decimal("0.01")),
                unit_price=to_decimal(unit_price).quantize(Decimal("0.0001"))
                if unit_price is not None
                else None,
                is_discount=bool(is_discount),
            )
        )
        added += 1
    db.flush()
    return added


_RETAILER_LABELS = {
    "ab": "AB Vassilopoulos",
    "sklavenitis": "Sklavenitis",
    "lidl": "Lidl",
    "mymarket": "My Market",
    "my_market": "My Market",
    "masoutis": "Masoutis",
    "kritikos": "Kritikos",
    "galaxias": "Galaxias",
    "bazaar": "Bazaar",
    "marketin": "Market In",
    "market_in": "Market In",
    "thanopoulos": "Thanopoulos",
    "egnatia": "Egnatia",
}


def retailer_label(code: str | None) -> str:
    if not code:
        return "—"
    return _RETAILER_LABELS.get(
        code.lower(), code.replace("_", " ").replace("-", " ").title() if code.isascii() else code
    )


OTHER_RETAILER = "other"
MANUAL = "manual"
MAX_PRICE = Decimal("100000")


def retailer_choices() -> list[dict]:
    """The stores a logged price can be from: each known chain once (by name;
    the first code of an alias pair), by name, then "Other" last."""
    seen: dict[str, str] = {}
    for code, name in _RETAILER_LABELS.items():
        seen.setdefault(name, code)
    rows = [{"code": code, "name": name} for name, code in seen.items()]
    rows.sort(key=lambda r: r["name"].casefold())
    return rows + [{"code": OTHER_RETAILER, "name": "Other"}]


def known_retailer(code: str | None) -> str | None:
    """``code`` normalised (lower case) when it is a known chain or "other"."""
    code = (code or "").strip().lower()
    return code if code in _RETAILER_LABELS or code == OTHER_RETAILER else None


# A size in these units -> how many kg / l / pieces it is, so a logged price
# gets a unit price comparable with PosoKanei's (per kg or l).
_UNIT_FACTORS = {
    "kg": Decimal(1),
    "g": Decimal("0.001"),
    "gr": Decimal("0.001"),
    "l": Decimal(1),
    "lt": Decimal(1),
    "ml": Decimal("0.001"),
    "pcs": Decimal(1),
}


def unit_price_for(product: Product, price: Decimal) -> Decimal | None:
    """``price`` per kg, l or piece from the product's size, or None when the
    size or its unit is unknown."""
    factor = _UNIT_FACTORS.get((product.unit or "").strip().lower())
    size = to_decimal(product.unit_quantity) if product.unit_quantity is not None else None
    if factor is None or not size or size <= 0:
        return None
    unit_price = (to_decimal(price) / (size * factor)).quantize(Decimal("0.0001"))
    # The column is Numeric(10, 4): an absurd per-kg figure is no unit price.
    return unit_price if unit_price < 1_000_000 else None


def record_manual_price(
    db: Session, product: Product, retailer: str, price: Decimal, day: date
) -> PriceSnapshot:
    """The price the user paid (polish C3): one ``manual`` snapshot per
    product, retailer and day; a second entry the same day replaces it (and a
    PosoKanei snapshot of that retailer and day). It then counts for the
    cheapest price, today's prices, the history and the advice like any
    other snapshot. The caller validates and commits."""
    values = {
        "price": to_decimal(price).quantize(Decimal("0.01")),
        "unit_price": unit_price_for(product, price),
        "is_discount": False,
        "source": MANUAL,
    }

    def existing():
        return (
            db.query(PriceSnapshot)
            .filter(
                PriceSnapshot.product_id == product.id,
                PriceSnapshot.retailer == retailer,
                PriceSnapshot.snapshot_date == day,
            )
            .first()
        )

    snap = existing()
    if snap is None:
        snap = PriceSnapshot(product_id=product.id, retailer=retailer, snapshot_date=day, **values)
        try:
            with db.begin_nested():
                db.add(snap)
            return snap
        except IntegrityError:
            snap = existing()  # a concurrent save (or the daily refresh) won: update it
    for key, value in values.items():
        setattr(snap, key, value)
    db.flush()
    return snap


def current_prices(db: Session, product_ids) -> dict[str, list[PriceSnapshot]]:
    """Latest day's snapshots per product, cheapest first (unit price, then price)."""
    product_ids = list(product_ids)
    if not product_ids:
        return {}
    latest = (
        db.query(
            PriceSnapshot.product_id.label("pid"), func.max(PriceSnapshot.snapshot_date).label("d")
        )
        .filter(PriceSnapshot.product_id.in_(product_ids))
        .group_by(PriceSnapshot.product_id)
        .subquery()
    )
    snaps = (
        db.query(PriceSnapshot)
        .join(
            latest,
            (latest.c.pid == PriceSnapshot.product_id)
            & (latest.c.d == PriceSnapshot.snapshot_date),
        )
        .all()
    )
    out: dict[str, list[PriceSnapshot]] = {}
    for s in snaps:
        out.setdefault(s.product_id, []).append(s)
    for rows in out.values():
        rows.sort(key=_price_key)
    return out


HISTORY_DAYS = 183


def price_history(
    db: Session, product_id: str, today: date | None = None, days: int = HISTORY_DAYS
) -> list[tuple[date, Decimal]]:
    """One point per day over the last ``days`` days (today included): the
    lowest price across retailers that day, oldest first."""
    today = today or local_today()
    rows = (
        db.query(PriceSnapshot.snapshot_date, func.min(PriceSnapshot.price))
        .filter(
            PriceSnapshot.product_id == product_id,
            PriceSnapshot.snapshot_date > today - timedelta(days=days),
            PriceSnapshot.snapshot_date <= today,
        )
        .group_by(PriceSnapshot.snapshot_date)
        .order_by(PriceSnapshot.snapshot_date)
        .all()
    )
    return [(d, to_decimal(p)) for d, p in rows]


def _price_key(s: PriceSnapshot):
    # Lowest unit price where known; rows without one sort after by price.
    return (s.unit_price is None, s.unit_price if s.unit_price is not None else s.price, s.price)


# ---------------------------------------------------------------------------
# Price advice ("price prediction" — an estimate, labelled as such in the UI)
# ---------------------------------------------------------------------------

ADVICE_MIN_DAYS = 7  # distinct snapshot days needed before advising
BUY_NEAR_LOW = Decimal("1.02")  # within 2% of the 90-day low
DISCOUNT_BELOW_MEDIAN = Decimal("0.9")
WAIT_ABOVE_MEDIAN = Decimal("1.08")


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _trend_pct_30d(daily: dict[date, Decimal], today: date) -> Decimal | None:
    """Least-squares slope of the daily minimum over the last 30 days, scaled
    to a month and expressed as a percentage of the mean price."""
    pts = [(-(today - d).days, p) for d, p in daily.items() if (today - d).days < 30]
    if len(pts) < 2:
        return None
    n = Decimal(len(pts))
    mx = sum(Decimal(x) for x, _ in pts) / n
    my = sum(p for _, p in pts) / n
    sxx = sum((Decimal(x) - mx) ** 2 for x, _ in pts)
    if not sxx or not my:
        return None
    slope = sum((Decimal(x) - mx) * (p - my) for x, p in pts) / sxx
    return (slope * 30 / my * 100).quantize(Decimal("0.1"))


def _advice_from(snaps: list[PriceSnapshot], today: date) -> dict:
    out = {
        "advice": "unknown",
        "reason": "Not enough price history yet",
        "current_min": None,
        "median_30d": None,
        "min_90d": None,
        "trend_pct_30d": None,
        "is_discount": False,
        "as_of": None,
    }
    recent = [s for s in snaps if 0 <= (today - s.snapshot_date).days < 90]
    if not recent:
        return out

    daily: dict[date, Decimal] = {}
    for s in recent:
        price = to_decimal(s.price)
        if s.snapshot_date not in daily or price < daily[s.snapshot_date]:
            daily[s.snapshot_date] = price
    latest = max(daily)
    current = daily[latest]
    is_discount = any(
        s.is_discount
        for s in recent
        if s.snapshot_date == latest and to_decimal(s.price) == current
    )
    median_30d = _median([p for d, p in daily.items() if (today - d).days < 30])
    min_90d = min(daily.values())
    trend = _trend_pct_30d(daily, today)
    out.update(
        current_min=current,
        median_30d=median_30d,
        min_90d=min_90d,
        trend_pct_30d=trend,
        is_discount=is_discount,
        as_of=latest,
    )
    if len(daily) < ADVICE_MIN_DAYS or median_30d is None:
        return out

    trend_txt = ""
    if trend is not None and abs(trend) >= 1:
        trend_txt = f"; prices {'rising' if trend > 0 else 'falling'} {abs(trend)}%/month"
    if current <= min_90d * BUY_NEAR_LOW:
        out.update(advice="buy_now", reason=f"At its 90-day low{trend_txt}")
    elif is_discount and current <= median_30d * DISCOUNT_BELOW_MEDIAN:
        out.update(advice="buy_now", reason=f"On offer, 10%+ below the 30-day median{trend_txt}")
    elif current >= median_30d * WAIT_ABOVE_MEDIAN and current > min_90d:
        out.update(advice="wait", reason=f"8%+ above the 30-day median{trend_txt}")
    else:
        out.update(advice="neutral", reason=f"Around its usual price{trend_txt}")
    return out


def _snapshots_by_product(db: Session, product_ids, today: date) -> dict[str, list[PriceSnapshot]]:
    product_ids = list(product_ids)
    if not product_ids:
        return {}
    rows = (
        db.query(PriceSnapshot)
        .filter(
            PriceSnapshot.product_id.in_(product_ids),
            PriceSnapshot.snapshot_date > today - timedelta(days=90),
            PriceSnapshot.snapshot_date <= today,
        )
        .all()
    )
    out: dict[str, list[PriceSnapshot]] = {}
    for s in rows:
        out.setdefault(s.product_id, []).append(s)
    return out


def price_advice(db: Session, product: Product, today: date | None = None) -> dict:
    """advice: buy_now | wait | neutral | unknown, with the figures behind it
    (current_min, median_30d, min_90d, trend_pct_30d)."""
    today = today or local_today()
    return _advice_from(_snapshots_by_product(db, [product.id], today).get(product.id, []), today)


def price_advice_bulk(db: Session, product_ids, today: date | None = None) -> dict[str, dict]:
    today = today or local_today()
    product_ids = list(product_ids)
    snaps = _snapshots_by_product(db, product_ids, today)
    return {pid: _advice_from(snaps.get(pid, []), today) for pid in product_ids}


# ---------------------------------------------------------------------------
# Run-out prediction (estimate)
# ---------------------------------------------------------------------------

RUNOUT_WINDOW_DAYS = 60
RUNOUT_MIN_OBSERVED_DAYS = 7


def _runout_from(quantity, uses: list[tuple[date, Decimal]], today: date) -> Decimal | None:
    if len(uses) < 2:
        return None
    total = sum(abs(d) for _, d in uses)
    if not total:
        return None
    observed = max(RUNOUT_MIN_OBSERVED_DAYS, (today - min(day for day, _ in uses)).days)
    # quantity / (total / observed), rearranged to keep the division last.
    return (to_decimal(quantity) * observed / total).quantize(Decimal("0.1"))


def _uses_by_item(db: Session, item_ids, today: date) -> dict[str, list[tuple[date, Decimal]]]:
    item_ids = list(item_ids)
    if not item_ids:
        return {}
    since = datetime.combine(today - timedelta(days=RUNOUT_WINDOW_DAYS), time.min)
    rows = (
        db.query(StockMovement.stock_item_id, StockMovement.created_at, StockMovement.delta)
        .filter(
            StockMovement.stock_item_id.in_(item_ids),
            StockMovement.reason == StockReason.use.value,
            StockMovement.created_at >= since,
        )
        .all()
    )
    out: dict[str, list[tuple[date, Decimal]]] = {}
    for item_id, created_at, delta in rows:
        if created_at.date() <= today:
            out.setdefault(item_id, []).append((created_at.date(), to_decimal(delta)))
    return out


def predicted_runout_days(
    db: Session, item: StockItem, today: date | None = None
) -> Decimal | None:
    """Days until ``item`` runs out at its recent consumption rate (estimate).

    rate = Σ|use deltas| over the last 60 days / days observed (at least 7);
    None with fewer than two "use" movements.
    """
    today = today or local_today()
    return _runout_from(item.quantity, _uses_by_item(db, [item.id], today).get(item.id, []), today)


def runout_bulk(db: Session, items, today: date | None = None) -> dict[str, Decimal | None]:
    today = today or local_today()
    uses = _uses_by_item(db, [i.id for i in items], today)
    return {i.id: _runout_from(i.quantity, uses.get(i.id, []), today) for i in items}


# ---------------------------------------------------------------------------
# Shopping list & rotation
# ---------------------------------------------------------------------------

RUNOUT_SOON_DAYS = 7


def _line(price, qty) -> Decimal:
    return quantize(to_decimal(price) * to_decimal(qty))


def restock_quantity(item: StockItem) -> Decimal:
    """How many to buy: back up to twice the minimum, at least one."""
    gap = to_decimal(item.min_quantity) * 2 - to_decimal(item.quantity)
    return max(Decimal("1"), Decimal(math.ceil(gap)))


def shopping_list(
    db: Session, hh_id: str, today: date | None = None, *, include_ticked: bool = False
) -> dict:
    """Items to buy (at/below minimum, or running out within a week), each at
    its cheapest current retailer, grouped into per-retailer baskets.

    ``include_ticked`` (the PWA list) also keeps any item with an active tick
    that is neither, with reason ``ticked``, so every tick that is counted
    and applied has a row it can be unticked from."""
    today = today or local_today()
    items = list_stock(db, hh_id)
    runout = runout_bulk(db, items, today)
    ticked = set(active_ticks(db, hh_id)) if include_ticked else set()

    def _low(i):
        return to_decimal(i.quantity) <= to_decimal(i.min_quantity)

    def _soon(i):
        return runout[i.id] is not None and runout[i.id] <= RUNOUT_SOON_DAYS

    wanted = [i for i in items if _low(i) or _soon(i) or i.id in ticked]
    pids = [i.product_id for i in wanted]
    prices = current_prices(db, pids)
    advice = price_advice_bulk(db, pids, today)

    rows = []
    for i in wanted:
        need = restock_quantity(i)
        snaps = prices.get(i.product_id, [])
        best = snaps[0] if snaps else None
        rows.append(
            {
                "item": i,
                "product": i.product,
                "need_qty": need,
                "reason": "low" if _low(i) else "runout" if _soon(i) else "ticked",
                "runout_days": runout[i.id],
                "retailer": best.retailer if best else None,
                "retailer_name": retailer_label(best.retailer) if best else None,
                "price": to_decimal(best.price) if best else None,
                "unit_price": best.unit_price if best else None,
                "is_discount": bool(best and best.is_discount),
                "line_total": _line(best.price, need) if best else None,
                "advice": advice.get(i.product_id),
                "prices": snaps,
            }
        )

    groups: dict[str | None, dict] = {}
    for r in rows:
        g = groups.setdefault(
            r["retailer"],
            {
                "retailer": r["retailer"],
                "retailer_name": r["retailer_name"],
                "items": [],
                "total": ZERO,
            },
        )
        g["items"].append(r)
        if r["line_total"] is not None:
            g["total"] += r["line_total"]
    ordered = sorted(
        groups.values(), key=lambda g: (g["retailer"] is None, -len(g["items"]), g["total"])
    )

    # Cheapest single store for the whole list: most items covered, then total.
    priced = [r for r in rows if r["prices"]]
    candidates = []
    for ret in {s.retailer for r in priced for s in r["prices"]}:
        total, covers = ZERO, 0
        for r in priced:
            snap = next((s for s in r["prices"] if s.retailer == ret), None)
            if snap is not None:
                total += _line(snap.price, r["need_qty"])
                covers += 1
        candidates.append((-covers, total, ret))
    best_store = None
    if candidates:
        neg_covers, total, ret = min(candidates)
        best_store = {
            "retailer": ret,
            "retailer_name": retailer_label(ret),
            "total": total,
            "covers": -neg_covers,
            "missing": len(priced) + neg_covers,
        }

    return {
        "items": rows,
        "groups": ordered,
        "best_single_store": best_store,
        "total": sum((r["line_total"] for r in rows if r["line_total"] is not None), ZERO),
        "unpriced": sum(1 for r in rows if r["price"] is None),
    }


def basket_total(db: Session, items_with_qty, retailer: str | None) -> Decimal:
    """Σ qty × current price at ``retailer`` where it has one, else the cheapest."""
    prices = current_prices(db, [i.product_id for i, _ in items_with_qty])
    total = ZERO
    for item, qty in items_with_qty:
        snaps = prices.get(item.product_id) or []
        snap = next((s for s in snaps if s.retailer == retailer), None) if retailer else None
        snap = snap or (snaps[0] if snaps else None)
        if snap is not None:
            total += _line(snap.price, qty)
    return total


def rotation_suggestions(db: Session, hh_id: str, today: date | None = None) -> list[dict]:
    """ "Stock up now" for buy_now items below 2× minimum; "hold off" for
    wait items you still have more than the minimum of."""
    today = today or local_today()
    items = list_stock(db, hh_id)
    advice = price_advice_bulk(db, [i.product_id for i in items], today)
    out = []
    for i in items:
        a = advice[i.product_id]
        qty, mn = to_decimal(i.quantity), to_decimal(i.min_quantity)
        if a["advice"] == "buy_now" and qty < mn * 2:
            out.append(
                {
                    "item": i,
                    "product": i.product,
                    "kind": "stock_up",
                    "advice": a,
                    "message": f"Stock up on {i.product.name} now: {a['reason'].lower()}.",
                }
            )
        elif a["advice"] == "wait" and qty > mn:
            out.append(
                {
                    "item": i,
                    "product": i.product,
                    "kind": "hold_off",
                    "advice": a,
                    "message": f"Hold off on {i.product.name}: {a['reason'].lower()}.",
                }
            )
    return out


# ---------------------------------------------------------------------------
# Shopping list lines: ticks on computed items and one-off lines (caller
# commits). A tick never changes stock; apply_ticked does, after the user
# confirms. Nothing here touches transactions.
# ---------------------------------------------------------------------------


def _active_lines(db: Session, hh_id: str):
    return db.query(ShoppingLine).filter(
        ShoppingLine.household_id == hh_id, ShoppingLine.cleared_at.is_(None)
    )


def get_live_item(db: Session, hh_id: str, item_id: str) -> StockItem | None:
    """The household's stock item, unless it is archived."""
    item = get_stock_item(db, hh_id, item_id)
    if item is None or item.product.archived_at is not None:
        return None
    return item


def active_ticks(db: Session, hh_id: str, item_ids=None) -> dict[str, ShoppingLine]:
    """Active ticks by stock item id (only ``item_ids``' when given)."""
    q = _active_lines(db, hh_id).filter(ShoppingLine.stock_item_id.isnot(None))
    if item_ids is not None:
        q = q.filter(ShoppingLine.stock_item_id.in_(list(item_ids)))
    rows = q.all()
    return {r.stock_item_id: r for r in rows}


def one_off_lines(db: Session, hh_id: str) -> list[ShoppingLine]:
    """Active one-off lines, oldest first."""
    return (
        _active_lines(db, hh_id)
        .filter(ShoppingLine.stock_item_id.is_(None))
        .order_by(ShoppingLine.created_at, ShoppingLine.id)
        .all()
    )


def ticked_count(db: Session, hh_id: str) -> int:
    """Active ticks on items still in the pantry, plus checked one-off lines."""
    n = (
        _active_lines(db, hh_id)
        .outerjoin(StockItem, StockItem.id == ShoppingLine.stock_item_id)
        .outerjoin(Product, Product.id == StockItem.product_id)
        .filter(
            ShoppingLine.checked_at.isnot(None),
            or_(ShoppingLine.stock_item_id.is_(None), Product.archived_at.is_(None)),
        )
        .with_entities(func.count(ShoppingLine.id))
        .scalar()
    )
    return int(n or 0)


def _replayed(db: Session, hh_id: str, line_id: str | None, stock_item_id: str | None):
    """The row a create with client id ``line_id`` already made, if any.
    Raises ShoppingIdConflict when the id is taken by a row this create cannot
    be a replay of (another household's, or another item / kind of line)."""
    if not line_id:
        return None
    row = db.get(ShoppingLine, line_id)
    if row is None:
        return None
    if row.household_id != hh_id or row.stock_item_id != stock_item_id:
        raise ShoppingIdConflict(line_id)
    return row


def tick_item(
    db: Session,
    hh_id: str,
    user_id: str | None,
    stock_item_id: str,
    quantity=None,
    tick_id: str | None = None,
) -> ShoppingLine | None:
    """Tick a stock item on the shopping list. Idempotent: an item already
    ticked returns its tick unchanged, and so does a replay of a client
    ``tick_id`` (even once applied or cleared, so a late replay never ticks
    again). ``quantity`` defaults to the item's restock quantity now. None if
    the item is missing, foreign or archived."""
    replay = _replayed(db, hh_id, tick_id, stock_item_id)
    if replay is not None:
        return replay
    item = get_live_item(db, hh_id, stock_item_id)
    if item is None:
        return None

    def existing():
        return _active_lines(db, hh_id).filter(ShoppingLine.stock_item_id == item.id).first()

    tick = existing()
    if tick is not None:
        return tick
    qty = restock_quantity(item) if quantity is None else parse_quantity(quantity, allow_zero=False)
    now = utcnow_naive()
    tick = ShoppingLine(
        **({"id": tick_id} if tick_id else {}),
        household_id=hh_id,
        stock_item_id=item.id,
        quantity=qty,
        checked_at=now,
        created_by=user_id,
        created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(tick)
    except IntegrityError:
        # A concurrent create won: the same client id replayed, or someone
        # else ticked the item. Theirs is the tick.
        return _replayed(db, hh_id, tick_id, stock_item_id) or existing()
    return tick


def untick(db: Session, hh_id: str, tick_id: str) -> bool:
    """Remove an active tick (hard delete). False if there is no such tick."""
    n = (
        _active_lines(db, hh_id)
        .filter(ShoppingLine.id == tick_id, ShoppingLine.stock_item_id.isnot(None))
        .delete(synchronize_session="fetch")
    )
    return n > 0


def untick_item(db: Session, hh_id: str, stock_item_id: str) -> int:
    """Remove the item's active tick, whoever made it (polish C4). Returns how
    many were removed (0 or 1); 0 is not an error, so a replay is harmless."""
    return (
        _active_lines(db, hh_id)
        .filter(ShoppingLine.stock_item_id == stock_item_id)
        .delete(synchronize_session="fetch")
    )


def add_line(
    db: Session,
    hh_id: str,
    user_id: str | None,
    name: str,
    quantity=None,
    line_id: str | None = None,
) -> ShoppingLine:
    """Add a one-off line. A replay of a client ``line_id`` returns that line
    as it is now (idempotent)."""
    replay = _replayed(db, hh_id, line_id, None)
    if replay is not None:
        return replay
    name = _clip(name, 200)
    if not name:
        raise StockError("Name is required.")
    qty = None if quantity in (None, "") else parse_quantity(quantity, allow_zero=False)
    line = ShoppingLine(
        **({"id": line_id} if line_id else {}),
        household_id=hh_id,
        name=name,
        quantity=qty,
        created_by=user_id,
        created_at=utcnow_naive(),
    )
    try:
        with db.begin_nested():
            db.add(line)
    except IntegrityError:
        replay = _replayed(db, hh_id, line_id, None)
        if replay is None:
            raise
        return replay
    return line


def _one_off(db: Session, hh_id: str, line_id: str):
    return _active_lines(db, hh_id).filter(
        ShoppingLine.id == line_id, ShoppingLine.stock_item_id.is_(None)
    )


def set_line_checked(db: Session, hh_id: str, line_id: str, checked: bool) -> ShoppingLine | None:
    line = _one_off(db, hh_id, line_id).first()
    if line is None:
        return None
    if not checked:
        line.checked_at = None
    elif line.checked_at is None:
        line.checked_at = utcnow_naive()
    db.flush()
    return line


def delete_line(db: Session, hh_id: str, line_id: str) -> bool:
    return _one_off(db, hh_id, line_id).delete(synchronize_session="fetch") > 0


def apply_ticked(db: Session, hh_id: str, user_id: str | None) -> dict:
    """Add every active tick's quantity to stock (a ``buy`` movement) and
    clear it; clear every checked one-off line; leave unchecked lines.

    One unit of work for the caller's single commit. The active rows are
    locked (FOR UPDATE on Postgres), so a concurrent second call waits and
    then finds nothing to apply. A tick whose item was archived meanwhile is
    cleared without an adjust. Returns ``{"applied": [{stock_item_id, name,
    before, after}], "cleared_lines": n}``.
    """
    now = utcnow_naive()
    ticks = (
        _active_lines(db, hh_id)
        .filter(ShoppingLine.stock_item_id.isnot(None))
        .order_by(ShoppingLine.created_at, ShoppingLine.id)
        .with_for_update()
        .all()
    )
    applied = []
    for tick in ticks:
        tick.cleared_at = now
        # Lock the item first: ``before`` is then the quantity as it is now,
        # not as this session last loaded it.
        item = lock_stock_item(db, hh_id, tick.stock_item_id)
        if item is None or item.product.archived_at is not None:
            continue
        before = to_decimal(item.quantity)
        qty = to_decimal(tick.quantity) if tick.quantity else restock_quantity(item)
        adjust_stock(db, hh_id, item.id, qty, user_id, reason=StockReason.buy)
        applied.append(
            {
                "stock_item_id": item.id,
                "name": item.product.name,
                "before": before,
                "after": to_decimal(item.quantity),
            }
        )
    lines = (
        _active_lines(db, hh_id)
        .filter(ShoppingLine.stock_item_id.is_(None), ShoppingLine.checked_at.isnot(None))
        .with_for_update()
        .all()
    )
    for line in lines:
        line.cleared_at = now
    db.flush()
    return {"applied": applied, "cleared_lines": len(lines)}
