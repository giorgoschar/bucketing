"""
Household stock list with PosoKanei price lookup.

Pages never depend on PosoKanei being up: the list renders from stored price
snapshots, and lookups that fail render "prices unavailable" instead of an
error (see docs/POSOKANEI.md).
"""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import posokanei
from app.auth import require_auth, require_csrf
from app.clock import local_today
from app.config import settings
from app.database import get_db
from app.posokanei import PosokaneiUnavailable
from app.services import base_ctx
from app.services import stock as stock_svc
from app.services.stock import StockError
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_csrf)])

# Fixed messages selected by ?notice=; user input is never reflected.
NOTICES = {
    "added": "Added to your stock.",
    "prices_unavailable": "Added — live prices unavailable right now; they will refresh automatically.",
    "refreshed": "Prices refreshed.",
    "refresh_failed": "Prices unavailable right now — PosoKanei did not respond. Try again later.",
    "removed": "Removed from your stock. Its price history is kept.",
    "saved": "Saved.",
}


def _bad(exc: StockError):
    return HTTPException(status_code=400, detail=str(exc))


def _rows(db, hh_id, items):
    prices = stock_svc.current_prices(db, [i.product_id for i in items])
    return [{"item": i, "prices": prices.get(i.product_id, [])} for i in items]


def snapshot_now(db, product) -> bool:
    """Fetch and store today's prices for a linked product. False if unavailable."""
    if not product.posokanei_id:
        return False
    try:
        summary = posokanei.get(product.posokanei_id)
    except PosokaneiUnavailable:
        return False
    stock_svc.record_snapshots(db, product, summary, local_today())
    return True


@router.get("/stock", response_class=HTMLResponse)
def stock_page(
    request: Request,
    notice: str = "",
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = base_ctx(db, user, hh_id)
    items = stock_svc.list_stock(db, hh_id)
    ctx.update({
        "request": request,
        "user": user,
        "rows": _rows(db, hh_id, items),
        "notice": NOTICES.get(notice),
        "posokanei_enabled": settings.posokanei_enabled,
        "retailer_label": stock_svc.retailer_label,
    })
    return templates.TemplateResponse("stock/list.html", ctx)


def _lookup_response(request, results, *, error=False, empty_msg="No products found."):
    return templates.TemplateResponse("stock/_lookup_results.html", {
        "request": request,
        "results": results,
        "error": error,
        "empty_msg": empty_msg,
        "retailer_label": stock_svc.retailer_label,
    })


@router.get("/stock/search", response_class=HTMLResponse)
def stock_search(request: Request, q: str = "", auth=Depends(require_auth)):
    q = q.strip()
    if len(q) < 2:
        return _lookup_response(request, [], empty_msg="Type at least 2 letters to search.")
    try:
        results = posokanei.search(q)
    except PosokaneiUnavailable:
        return _lookup_response(request, [], error=True)
    return _lookup_response(request, results)


@router.get("/stock/barcode", response_class=HTMLResponse)
def stock_barcode(request: Request, code: str = "", auth=Depends(require_auth)):
    try:
        barcode = stock_svc.clean_barcode(code)
    except StockError:
        barcode = None
    if not barcode:
        return _lookup_response(request, [], empty_msg="Enter a barcode of 6–14 digits.")
    try:
        product = posokanei.by_barcode(barcode)
    except PosokaneiUnavailable:
        return _lookup_response(request, [], error=True)
    return _lookup_response(
        request, [product] if product else [],
        empty_msg="No product found for this barcode — add it manually below.",
    )


@router.post("/stock")
def stock_add(
    name: str = Form(""),
    brand: str = Form(""),
    barcode: str = Form(""),
    posokanei_id: str = Form(""),
    unit: str = Form(""),
    unit_quantity: str = Form(""),
    quantity: str = Form("0"),
    min_quantity: str = Form("1"),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    try:
        uq = stock_svc.parse_quantity(unit_quantity, field="Size") if unit_quantity.strip() else None
        item = stock_svc.add_product(
            db, hh_id, user.id, name=name, brand=brand, barcode=barcode,
            posokanei_id=posokanei_id, unit=unit, unit_quantity=uq,
            quantity=quantity or "0", min_quantity=min_quantity or "1",
        )
    except StockError as exc:
        raise _bad(exc) from None
    notice = "added"
    if item.product.posokanei_id and not snapshot_now(db, item.product):
        notice = "prices_unavailable"
    db.commit()
    return RedirectResponse(f"/stock?notice={notice}", status_code=303)


@router.post("/stock/{item_id}/adjust", response_class=HTMLResponse)
def stock_adjust(
    request: Request,
    item_id: str,
    delta: str = Query(...),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    try:
        d = stock_svc.parse_quantity(delta, field="Change", allow_zero=False, allow_negative=True)
    except StockError as exc:
        raise _bad(exc) from None
    item = stock_svc.adjust_stock(db, hh_id, item_id, d, user.id)
    if item is None:
        raise HTTPException(status_code=404)
    db.commit()
    if not request.headers.get("HX-Request"):
        return RedirectResponse("/stock", status_code=303)
    row = _rows(db, hh_id, [item])[0]
    return templates.TemplateResponse("stock/_row.html", {
        "request": request, "row": row, "retailer_label": stock_svc.retailer_label,
    })


@router.post("/stock/{item_id}/settings")
def stock_settings(
    item_id: str,
    min_quantity: str = Form(""),
    track_price: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    _user, hh_id = auth
    try:
        item = stock_svc.update_stock_settings(
            db, hh_id, item_id,
            min_quantity=min_quantity if min_quantity.strip() else None,
            track_price=track_price in ("on", "true", "1"),
        )
    except StockError as exc:
        raise _bad(exc) from None
    if item is None:
        raise HTTPException(status_code=404)
    db.commit()
    return RedirectResponse("/stock?notice=saved", status_code=303)


@router.post("/stock/{item_id}/refresh")
def stock_refresh(item_id: str, db: Session = Depends(get_db), auth=Depends(require_auth)):
    _user, hh_id = auth
    item = stock_svc.get_stock_item(db, hh_id, item_id)
    if item is None:
        raise HTTPException(status_code=404)
    ok = snapshot_now(db, item.product)
    db.commit()
    return RedirectResponse(f"/stock?notice={'refreshed' if ok else 'refresh_failed'}", status_code=303)


@router.post("/stock/{item_id}/archive")
def stock_archive(item_id: str, db: Session = Depends(get_db), auth=Depends(require_auth)):
    _user, hh_id = auth
    if stock_svc.archive_product(db, hh_id, item_id) is None:
        raise HTTPException(status_code=404)
    db.commit()
    return RedirectResponse("/stock?notice=removed", status_code=303)
