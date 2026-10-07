"""
API stock list (Plan › Pantry) and PosoKanei product lookup (auth-only proxy).

Responses are typed (``*Out`` below). Every key the untyped dicts sent before
keeps its JSON type (tests/test_stock_api_shapes.py): numbers use FastAPI's
own Decimal encoding (``Num``), so a whole Decimal stays a JSON integer and a
``Numeric(10, 2)`` value a float.
"""

from dataclasses import asdict
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, PlainSerializer, WithJsonSchema, field_validator
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.integrations import posokanei
from app.integrations.posokanei import PosokaneiUnavailable
from app.services import stock as stock_svc
from app.services.stock import StockError

router = APIRouter(prefix="/stock", tags=["stock"])
products_router = APIRouter(prefix="/products", tags=["stock"])


def _num(v: Decimal) -> int | float:
    # fastapi.encoders.decimal_encoder: what the untyped endpoints sent.
    return int(v) if v.as_tuple().exponent >= 0 else float(v)


# A JSON number either way (the schema says so; TypeScript reads ``number``).
Num = Annotated[
    Decimal,
    PlainSerializer(_num, return_type=int | float, when_used="json"),
    WithJsonSchema({"type": "number"}),
]
Advice = Literal["buy_now", "wait", "neutral", "unknown"]


class CheapestOut(BaseModel):
    retailer: str
    retailer_name: str
    price: Num
    unit_price: Num | None
    is_discount: bool
    date: str  # ISO date of the snapshot


class StockItemOut(BaseModel):
    """A pantry row. ``need_qty`` is what a restock buys (max(1, ceil(2·min −
    qty))); ``runout_days`` is a whole-day estimate (floored), null without
    enough use history; ``advice`` is the price-advice verdict."""

    id: str
    product_id: str
    name: str
    brand: str | None
    barcode: str | None
    posokanei_id: str | None
    quantity: Num
    min_quantity: Num
    track_price: bool
    low: bool
    cheapest: CheapestOut | None
    unit: str | None
    unit_quantity: Num | None
    image_url: str | None
    need_qty: Num
    runout_days: int | None
    advice: Advice
    ticked: bool
    tick_id: str | None


class ShoppingRowOut(BaseModel):
    id: str  # the stock item id
    name: str
    need_qty: Num
    reason: Literal["low", "runout"]
    runout_days_estimate: Num | None  # fractional days (estimate)
    retailer: str | None
    retailer_name: str | None
    price: Num | None
    line_total: Num | None
    advice: Advice
    advice_reason: str | None
    trend_pct_30d: Num | None
    unit: str | None
    quantity: Num  # current stock, as on /stock ("Low · 1 left")
    ticked: bool
    tick_id: str | None


class ShoppingGroupOut(BaseModel):
    retailer: str | None  # null: the unpriced items
    retailer_name: str | None
    total: Num
    item_ids: list[str]


class BestStoreOut(BaseModel):
    retailer: str
    retailer_name: str
    total: Num
    covers: int
    missing: int


class ShoppingLineOut(BaseModel):
    """A one-off line the user added to the shopping list."""

    id: str
    name: str
    quantity: Num | None
    checked: bool


class ShoppingOut(BaseModel):
    items: list[ShoppingRowOut]
    groups: list[ShoppingGroupOut]
    best_single_store: BestStoreOut | None
    total: Num
    unpriced: int  # items without a current price (the last group)
    lines: list[ShoppingLineOut]  # active one-off lines, oldest first
    ticked_count: int  # active ticks + checked one-off lines


class TickOut(BaseModel):
    id: str
    stock_item_id: str
    quantity: Num


class AppliedOut(BaseModel):
    stock_item_id: str
    name: str
    before: Num
    after: Num


class ApplyTickedOut(BaseModel):
    applied: list[AppliedOut]
    cleared_lines: int


def _quantity(v):
    """An optional positive quantity (422 otherwise)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return stock_svc.parse_quantity(v, allow_zero=False)
    except StockError as exc:
        raise ValueError(str(exc)) from None


class TickIn(BaseModel):
    stock_item_id: str
    quantity: float | str | None = None  # default: the item's need_qty now

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v):
        return _quantity(v)


class LineIn(BaseModel):
    name: str
    quantity: float | str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required.")
        if len(v) > 200:
            raise ValueError("Name must be at most 200 characters.")
        return v

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v):
        return _quantity(v)


class LineCheckIn(BaseModel):
    checked: bool


def _line_payload(line) -> dict:
    return {
        "id": line.id,
        "name": line.name,
        "quantity": line.quantity,
        "checked": line.checked_at is not None,
    }


def _tick_payload(tick) -> dict:
    return {"id": tick.id, "stock_item_id": tick.stock_item_id, "quantity": tick.quantity}


class RetailerPriceOut(BaseModel):
    retailer: str
    display_name: str
    price: Num | None
    unit_price: Num | None
    is_discount: bool
    discount_pct: Num | None
    last_updated: str | None


class PriceStatsOut(BaseModel):
    min: Num | None
    max: Num | None
    avg: Num | None


class PricePointOut(BaseModel):
    date: str
    retailer: str
    price: Num
    unit_price: Num | None
    is_discount: bool


class ProductOut(BaseModel):
    """A PosoKanei product (app.integrations.posokanei.ProductSummary)."""

    id: str
    name: str
    brand: str | None
    barcode: str | None
    unit: str | None
    unit_quantity: Num | None
    image_url: str | None
    retailer_prices: list[RetailerPriceOut]
    price_stats: PriceStatsOut
    history: list[PricePointOut]


class PriceTodayOut(BaseModel):
    retailer: str
    retailer_name: str
    price: Num
    unit_price: Num | None
    is_discount: bool


class HistoryPointOut(BaseModel):
    date: str  # ISO date
    min_price: Num  # the lowest price across retailers that day


class AdviceDetailOut(BaseModel):
    """app.services.stock.price_advice: the verdict and the figures behind it."""

    advice: Advice
    reason: str
    current_min: Num | None
    median_30d: Num | None
    min_90d: Num | None
    trend_pct_30d: Num | None
    is_discount: bool
    as_of: str | None  # ISO date of the latest snapshot in the last 90 days


class StockDetailOut(StockItemOut):
    prices_today: list[PriceTodayOut]  # the latest day's snapshots, cheapest unit price first
    history: list[HistoryPointOut]  # one point per day, last 183 days, oldest first
    advice_detail: AdviceDetailOut
    prices_as_of: str | None  # ISO date of the latest snapshot


class InPantryOut(BaseModel):
    stock_item_id: str
    quantity: Num


class ProductLookupOut(ProductOut):
    in_pantry: InPantryOut | None  # this household's item with the barcode


class StockSummaryOut(BaseModel):
    low_count: int
    ticked_count: int


def item_payload(item, prices=None, *, advice=None, runout=None, tick=None) -> dict:
    p = item.product
    best = (prices or [None])[0]
    return {
        "id": item.id,
        "product_id": p.id,
        "name": p.name,
        "brand": p.brand,
        "barcode": p.barcode,
        "posokanei_id": p.posokanei_id,
        "quantity": item.quantity,
        "min_quantity": item.min_quantity,
        "track_price": item.track_price,
        "low": item.quantity <= item.min_quantity,
        "cheapest": None
        if best is None
        else {
            "retailer": best.retailer,
            "retailer_name": stock_svc.retailer_label(best.retailer),
            "price": best.price,
            "unit_price": best.unit_price,
            "is_discount": best.is_discount,
            "date": best.snapshot_date.isoformat(),
        },
        "unit": p.unit,
        "unit_quantity": p.unit_quantity,
        "image_url": p.image_url,
        "need_qty": stock_svc.restock_quantity(item),
        "runout_days": None if runout is None else int(runout),
        "advice": (advice or {}).get("advice", "unknown"),
        "ticked": tick is not None,
        "tick_id": tick.id if tick is not None else None,
    }


def _detail(db: Session, hh_id: str, item) -> dict:
    out = _payloads(db, hh_id, [item])[0]
    snaps = stock_svc.current_prices(db, [item.product_id]).get(item.product_id, [])
    advice = stock_svc.price_advice(db, item.product)
    as_of = advice["as_of"]
    out.update(
        prices_today=[
            {
                "retailer": s.retailer,
                "retailer_name": stock_svc.retailer_label(s.retailer),
                "price": s.price,
                "unit_price": s.unit_price,
                "is_discount": s.is_discount,
            }
            for s in snaps
        ],
        history=[
            {"date": d.isoformat(), "min_price": p}
            for d, p in stock_svc.price_history(db, item.product_id)
        ],
        advice_detail={**advice, "as_of": as_of.isoformat() if as_of else None},
        prices_as_of=snaps[0].snapshot_date.isoformat() if snaps else None,
    )
    return out


def _live_or_404(db: Session, hh_id: str, item_id: str):
    item = stock_svc.get_live_item(db, hh_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Stock item not found")
    return item


def _payloads(db: Session, hh_id: str, items) -> list[dict]:
    """List rows for ``items``, with prices, advice and run-out from bulk
    queries (a fixed number of statements whatever the item count)."""
    pids = [i.product_id for i in items]
    prices = stock_svc.current_prices(db, pids)
    advice = stock_svc.price_advice_bulk(db, pids)
    runout = stock_svc.runout_bulk(db, items)
    ticks = stock_svc.active_ticks(db, hh_id)
    return [
        item_payload(
            i,
            prices.get(i.product_id),
            advice=advice.get(i.product_id),
            runout=runout.get(i.id),
            tick=ticks.get(i.id),
        )
        for i in items
    ]


class StockAdd(BaseModel):
    name: str
    brand: str | None = None
    barcode: str | None = None
    posokanei_id: str | None = None
    unit: str | None = None
    unit_quantity: float | str | None = None  # the size, e.g. 400 (g)
    image_url: str | None = None  # https only; anything else is dropped
    quantity: float | str = 0
    min_quantity: float | str = 1


class StockAdjust(BaseModel):
    delta: float | str
    # One per queued stepper tap: a replay within 24 h is not applied again.
    client_id: str | None = None

    @field_validator("client_id")
    @classmethod
    def _client_id(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if len(v) > 64:
            raise ValueError("client_id must be at most 64 characters.")
        return v or None


class StockSettingsIn(BaseModel):
    min_quantity: float | str | None = None
    track_price: bool | None = None

    @field_validator("min_quantity")
    @classmethod
    def _min(cls, v):
        if v is None:
            return None
        try:
            return stock_svc.parse_quantity(v, field="Minimum")
        except StockError as exc:
            raise ValueError(str(exc)) from None


@router.get("", response_model=list[StockItemOut])
def list_stock(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    return _payloads(db, hh_id, stock_svc.list_stock(db, hh_id))


@router.get("/summary", response_model=StockSummaryOut)
def stock_summary(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    return stock_svc.stock_summary(db, hh_id)


@router.post("", status_code=201, response_model=StockItemOut)
def add_stock(body: StockAdd, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    try:
        size = body.unit_quantity
        if size is not None and str(size).strip():
            size = stock_svc.parse_quantity(size, field="Size")
        else:
            size = None
        item = stock_svc.add_product(
            db,
            hh_id,
            user.id,
            name=body.name,
            brand=body.brand,
            barcode=body.barcode,
            posokanei_id=body.posokanei_id,
            unit=body.unit,
            unit_quantity=size,
            image_url=body.image_url,
            quantity=body.quantity,
            min_quantity=body.min_quantity,
        )
    except StockError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    # Best effort, as the old app's add: no prices is not an error.
    stock_svc.snapshot_now(db, item.product)
    db.commit()
    return _payloads(db, hh_id, [item])[0]


@router.post("/{item_id}/adjust", response_model=StockItemOut)
def adjust_stock(
    item_id: str, body: StockAdjust, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    user, hh_id = auth
    try:
        delta = stock_svc.parse_quantity(
            body.delta, field="Change", allow_zero=False, allow_negative=True
        )
    except StockError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if body.client_id:
        prior = stock_svc.find_adjust_replay(db, hh_id, body.client_id)
        if prior is not None:
            # Already applied (the reply was lost): answer again, change nothing.
            if prior.stock_item_id != item_id:
                raise HTTPException(status_code=409, detail="client_id already used")
            return _payloads(db, hh_id, [prior.stock_item])[0]
    item = stock_svc.adjust_stock(db, hh_id, item_id, delta, user.id, client_id=body.client_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Stock item not found")
    db.commit()
    return _payloads(db, hh_id, [item])[0]


@router.get("/shopping", response_model=ShoppingOut)
def shopping(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    data = stock_svc.shopping_list(db, hh_id)
    ticks = stock_svc.active_ticks(db, hh_id)

    def row(r):
        a = r["advice"] or {}
        tick = ticks.get(r["item"].id)
        return {
            "id": r["item"].id,
            "name": r["product"].name,
            "need_qty": r["need_qty"],
            "reason": r["reason"],
            "runout_days_estimate": r["runout_days"],
            "retailer": r["retailer"],
            "retailer_name": r["retailer_name"],
            "price": r["price"],
            "line_total": r["line_total"],
            "advice": a.get("advice", "unknown"),
            "advice_reason": a.get("reason"),
            "trend_pct_30d": a.get("trend_pct_30d"),
            "unit": r["product"].unit,
            "quantity": r["item"].quantity,
            "ticked": tick is not None,
            "tick_id": tick.id if tick is not None else None,
        }

    return {
        "items": [row(r) for r in data["items"]],
        "groups": [
            {
                "retailer": g["retailer"],
                "retailer_name": g["retailer_name"],
                "total": g["total"],
                "item_ids": [r["item"].id for r in g["items"]],
            }
            for g in data["groups"]
        ],
        "best_single_store": data["best_single_store"],
        "total": data["total"],
        "unpriced": data["unpriced"],
        "lines": [_line_payload(ln) for ln in stock_svc.one_off_lines(db, hh_id)],
        "ticked_count": stock_svc.ticked_count(db, hh_id),
    }


@router.post("/shopping/ticks", status_code=201, response_model=TickOut)
def tick(body: TickIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Tick a shopping-list item. Idempotent: ticking it again returns the
    existing tick unchanged. Never changes stock."""
    user, hh_id = auth
    t = stock_svc.tick_item(db, hh_id, user.id, body.stock_item_id, body.quantity)
    if t is None:
        raise HTTPException(status_code=404, detail="Stock item not found")
    db.commit()
    return _tick_payload(t)


@router.delete("/shopping/ticks/{tick_id}", status_code=204)
def untick(tick_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    if not stock_svc.untick(db, hh_id, tick_id):
        raise HTTPException(status_code=404, detail="Tick not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/shopping/lines", status_code=201, response_model=ShoppingLineOut)
def add_line(body: LineIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    line = stock_svc.add_line(db, hh_id, user.id, body.name, body.quantity)
    db.commit()
    return _line_payload(line)


@router.patch("/shopping/lines/{line_id}", response_model=ShoppingLineOut)
def check_line(
    line_id: str, body: LineCheckIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    _user, hh_id = auth
    line = stock_svc.set_line_checked(db, hh_id, line_id, body.checked)
    if line is None:
        raise HTTPException(status_code=404, detail="Line not found")
    db.commit()
    return _line_payload(line)


@router.delete("/shopping/lines/{line_id}", status_code=204)
def delete_line(line_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    if not stock_svc.delete_line(db, hh_id, line_id):
        raise HTTPException(status_code=404, detail="Line not found")
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/shopping/apply-ticked", response_model=ApplyTickedOut)
def apply_ticked(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Add the ticked items to the pantry and clear the checked one-off lines,
    in one transaction. Never touches transactions; a second call with
    nothing ticked returns empty results."""
    user, hh_id = auth
    result = stock_svc.apply_ticked(db, hh_id, user.id)
    db.commit()
    return result


@router.get("/{item_id}", response_model=StockDetailOut)
def stock_detail(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    return _detail(db, hh_id, _live_or_404(db, hh_id, item_id))


@router.patch("/{item_id}", response_model=StockItemOut)
def stock_settings(
    item_id: str,
    body: StockSettingsIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    _user, hh_id = auth
    item = _live_or_404(db, hh_id, item_id)
    stock_svc.update_stock_settings(
        db, hh_id, item.id, min_quantity=body.min_quantity, track_price=body.track_price
    )
    db.commit()
    return _payloads(db, hh_id, [item])[0]


@router.post("/{item_id}/refresh", response_model=StockDetailOut)
def stock_refresh(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Fetch today's prices from PosoKanei (503 when it is unavailable). A
    product not linked to PosoKanei has nothing to fetch: its detail as is."""
    _user, hh_id = auth
    item = _live_or_404(db, hh_id, item_id)
    if item.product.posokanei_id:
        if not stock_svc.snapshot_now(db, item.product):
            raise HTTPException(status_code=503, detail="Prices unavailable")
        db.commit()
    return _detail(db, hh_id, item)


@router.post("/{item_id}/archive", status_code=204)
def stock_archive(item_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Hide the product (its history stays) and clear its active tick."""
    _user, hh_id = auth
    item = _live_or_404(db, hh_id, item_id)
    stock_svc.archive_product(db, hh_id, item.id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _product(summary) -> dict:
    return asdict(summary)


@products_router.get("/search", response_model=list[ProductOut])
def search_products(q: str = "", auth=Depends(require_api_auth)):
    if len(q.strip()) < 2:
        return []
    try:
        return [_product(p) for p in posokanei.search(q)]
    except PosokaneiUnavailable:
        raise HTTPException(status_code=503, detail="Prices unavailable") from None


@products_router.get("/barcode/{code}", response_model=ProductLookupOut)
def product_by_barcode(code: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    try:
        barcode = stock_svc.clean_barcode(code)
    except StockError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    try:
        product = posokanei.by_barcode(barcode)
    except PosokaneiUnavailable:
        raise HTTPException(status_code=503, detail="Prices unavailable") from None
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    mine = stock_svc.pantry_item_by_barcode(db, hh_id, barcode)
    return {
        **_product(product),
        "in_pantry": None
        if mine is None
        else {"stock_item_id": mine.id, "quantity": mine.quantity},
    }
