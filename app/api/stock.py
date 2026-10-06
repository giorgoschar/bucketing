"""
API stock list and PosoKanei product lookup (auth-only proxy).
"""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.integrations import posokanei
from app.integrations.posokanei import PosokaneiUnavailable
from app.services import stock as stock_svc
from app.services.stock import StockError

router = APIRouter(prefix="/stock", tags=["stock"])
products_router = APIRouter(prefix="/products", tags=["stock"])


def item_payload(item, prices=None) -> dict:
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
        "cheapest": None if best is None else {
            "retailer": best.retailer,
            "retailer_name": stock_svc.retailer_label(best.retailer),
            "price": best.price,
            "unit_price": best.unit_price,
            "is_discount": best.is_discount,
            "date": best.snapshot_date.isoformat(),
        },
    }


class StockAdd(BaseModel):
    name: str
    brand: str | None = None
    barcode: str | None = None
    posokanei_id: str | None = None
    unit: str | None = None
    quantity: float | str = 0
    min_quantity: float | str = 1


class StockAdjust(BaseModel):
    delta: float | str


@router.get("")
def list_stock(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    _user, hh_id = auth
    items = stock_svc.list_stock(db, hh_id)
    prices = stock_svc.current_prices(db, [i.product_id for i in items])
    return [item_payload(i, prices.get(i.product_id)) for i in items]


@router.post("", status_code=201)
def add_stock(body: StockAdd, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    try:
        item = stock_svc.add_product(
            db, hh_id, user.id, name=body.name, brand=body.brand, barcode=body.barcode,
            posokanei_id=body.posokanei_id, unit=body.unit,
            quantity=body.quantity, min_quantity=body.min_quantity,
        )
    except StockError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    return item_payload(item)


@router.post("/{item_id}/adjust")
def adjust_stock(item_id: str, body: StockAdjust,
                 auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    try:
        delta = stock_svc.parse_quantity(body.delta, field="Change",
                                         allow_zero=False, allow_negative=True)
    except StockError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    item = stock_svc.adjust_stock(db, hh_id, item_id, delta, user.id)
    if item is None:
        raise HTTPException(status_code=404, detail="Stock item not found")
    db.commit()
    prices = stock_svc.current_prices(db, [item.product_id])
    return item_payload(item, prices.get(item.product_id))


@router.get("/shopping")
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
        "groups": [{"retailer": g["retailer"], "retailer_name": g["retailer_name"],
                    "total": g["total"], "item_ids": [r["item"].id for r in g["items"]]}
                   for g in data["groups"]],
        "best_single_store": data["best_single_store"],
        "total": data["total"],
    }


def _product(summary) -> dict:
    return asdict(summary)


@products_router.get("/search")
def search_products(q: str = "", auth=Depends(require_api_auth)):
    if len(q.strip()) < 2:
        return []
    try:
        return [_product(p) for p in posokanei.search(q)]
    except PosokaneiUnavailable:
        raise HTTPException(status_code=503, detail="Prices unavailable") from None


@products_router.get("/barcode/{code}")
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
