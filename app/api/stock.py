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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, PlainSerializer, WithJsonSchema
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


class ShoppingOut(BaseModel):
    items: list[ShoppingRowOut]
    groups: list[ShoppingGroupOut]
    best_single_store: BestStoreOut | None
    total: Num


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


def _payloads(db: Session, hh_id: str, items) -> list[dict]:
    """List rows for ``items``, with prices, advice and run-out from bulk
    queries (a fixed number of statements whatever the item count)."""
    pids = [i.product_id for i in items]
    prices = stock_svc.current_prices(db, pids)
    advice = stock_svc.price_advice_bulk(db, pids)
    runout = stock_svc.runout_bulk(db, items)
    return [
        item_payload(
            i,
            prices.get(i.product_id),
            advice=advice.get(i.product_id),
            runout=runout.get(i.id),
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
    item = stock_svc.adjust_stock(db, hh_id, item_id, delta, user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="Stock item not found")
    db.commit()
    return _payloads(db, hh_id, [item])[0]


@router.get("/shopping", response_model=ShoppingOut)
def shopping(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    data = stock_svc.shopping_list(db, hh_id)

    def row(r):
        a = r["advice"] or {}
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
    }


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


@products_router.get("/barcode/{code}", response_model=ProductOut)
def product_by_barcode(code: str, auth=Depends(require_api_auth)):
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
    return _product(product)
