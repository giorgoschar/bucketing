"""
Household stock: products, quantities, consumption log and price snapshots.

Everything is scoped by household id; a stock item id from the client is
always resolved through :func:`get_stock_item` so another household's id is
indistinguishable from a missing one.

Products are never hard-deleted here: :func:`archive_product` hides one from
the stock list but keeps its price history and movements.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.clock import utcnow_naive
from app.models import PriceSnapshot, Product, StockItem, StockMovement, StockReason
from app.money import ZERO, to_decimal

MAX_QUANTITY = Decimal("100000")
_BARCODE_RE = re.compile(r"^\d{6,14}$")


class StockError(ValueError):
    """Invalid stock input (maps to HTTP 400)."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_quantity(raw, *, field: str = "Quantity", allow_zero: bool = True,
                   allow_negative: bool = False) -> Decimal:
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


# ---------------------------------------------------------------------------
# Mutations (caller commits)
# ---------------------------------------------------------------------------

def _move(db, item: StockItem, delta: Decimal, reason: StockReason, user_id: str | None):
    db.add(StockMovement(stock_item_id=item.id, delta=delta, reason=reason.value,
                         created_by=user_id, created_at=utcnow_naive()))


def add_product(
    db: Session, hh_id: str, user_id: str | None, *,
    name: str, brand: str | None = None, barcode: str | None = None,
    posokanei_id: str | None = None, unit: str | None = None,
    unit_quantity=None, image_url: str | None = None,
    quantity=ZERO, min_quantity=Decimal("1"), category_id: str | None = None,
) -> StockItem:
    """Add a product to the household's stock (or revive the existing one
    with the same barcode)."""
    name = _clip(name, 200)
    if not name:
        raise StockError("Name is required.")
    barcode = clean_barcode(barcode)
    quantity = parse_quantity(quantity)
    min_quantity = parse_quantity(min_quantity, field="Minimum")
    if image_url and not str(image_url).startswith("https://"):
        image_url = None

    product = None
    if barcode:
        product = (db.query(Product)
                   .filter(Product.household_id == hh_id, Product.barcode == barcode)
                   .first())
    if product is not None:
        product.archived_at = None
        product.posokanei_id = product.posokanei_id or _clip(posokanei_id, 64)
        item = product.stock_item
        if item is None:
            item = StockItem(household_id=hh_id, product_id=product.id,
                             quantity=ZERO, min_quantity=min_quantity)
            db.add(item)
            db.flush()
        return item

    product = Product(
        household_id=hh_id, name=name, brand=_clip(brand, 100), barcode=barcode,
        posokanei_id=_clip(posokanei_id, 64), unit=_clip(unit, 20),
        unit_quantity=to_decimal(unit_quantity) if unit_quantity not in (None, "") else None,
        image_url=_clip(image_url, 500), category_id=category_id,
        created_at=utcnow_naive(),
    )
    db.add(product)
    db.flush()
    item = StockItem(household_id=hh_id, product_id=product.id, quantity=quantity,
                     min_quantity=min_quantity, track_price=True, updated_at=utcnow_naive())
    db.add(item)
    db.flush()
    if quantity > 0:
        _move(db, item, quantity, StockReason.adjust, user_id)
    return item


def adjust_stock(db: Session, hh_id: str, item_id: str, delta, user_id: str | None,
                 reason: StockReason | None = None) -> StockItem | None:
    """Change a quantity by ``delta`` (never below zero) and log the movement.

    The logged delta is what actually changed, so using an item already at
    zero records nothing and cannot skew the consumption rate.
    """
    item = get_stock_item(db, hh_id, item_id)
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
        _move(db, item, actual, reason, user_id)
    db.flush()
    return item


def update_stock_settings(db: Session, hh_id: str, item_id: str, *,
                          min_quantity=None, track_price: bool | None = None) -> StockItem | None:
    item = get_stock_item(db, hh_id, item_id)
    if item is None:
        return None
    if min_quantity is not None:
        item.min_quantity = parse_quantity(min_quantity, field="Minimum")
    if track_price is not None:
        item.track_price = track_price
    item.updated_at = utcnow_naive()
    return item


def archive_product(db: Session, hh_id: str, item_id: str) -> StockItem | None:
    """Hide a product from the stock list. History stays (soft delete)."""
    item = get_stock_item(db, hh_id, item_id)
    if item is None:
        return None
    item.product.archived_at = utcnow_naive()
    return item


# ---------------------------------------------------------------------------
# Price snapshots
# ---------------------------------------------------------------------------

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
        (r, d) for r, d in db.query(PriceSnapshot.retailer, PriceSnapshot.snapshot_date)
        .filter(PriceSnapshot.product_id == product.id,
                PriceSnapshot.snapshot_date.in_({d for _, d in rows}))
    }
    added = 0
    for (retailer, d), (price, unit_price, is_discount) in rows.items():
        if (retailer, d) in existing:
            continue
        db.add(PriceSnapshot(
            product_id=product.id, retailer=retailer[:40], snapshot_date=d,
            price=to_decimal(price).quantize(Decimal("0.01")),
            unit_price=to_decimal(unit_price).quantize(Decimal("0.0001")) if unit_price is not None else None,
            is_discount=bool(is_discount),
        ))
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
    return _RETAILER_LABELS.get(code.lower(), code.replace("_", " ").replace("-", " ").title()
                                if code.isascii() else code)


def current_prices(db: Session, product_ids) -> dict[str, list[PriceSnapshot]]:
    """Latest day's snapshots per product, cheapest first (unit price, then price)."""
    product_ids = list(product_ids)
    if not product_ids:
        return {}
    latest = (db.query(PriceSnapshot.product_id.label("pid"),
                       func.max(PriceSnapshot.snapshot_date).label("d"))
              .filter(PriceSnapshot.product_id.in_(product_ids))
              .group_by(PriceSnapshot.product_id)
              .subquery())
    snaps = (db.query(PriceSnapshot)
             .join(latest, (latest.c.pid == PriceSnapshot.product_id)
                   & (latest.c.d == PriceSnapshot.snapshot_date))
             .all())
    out: dict[str, list[PriceSnapshot]] = {}
    for s in snaps:
        out.setdefault(s.product_id, []).append(s)
    for rows in out.values():
        rows.sort(key=_price_key)
    return out


def _price_key(s: PriceSnapshot):
    # Lowest unit price where known; rows without one sort after by price.
    return (s.unit_price is None, s.unit_price if s.unit_price is not None else s.price, s.price)
