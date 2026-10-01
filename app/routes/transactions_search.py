"""
Transactions: cross-bucket search, CSV export and duplicate detection.
"""
import csv
import io
import logging
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.auth import require_auth, require_csrf
from app.database import get_db
from app.models import (
    Bucket,
    Category,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.routes.transactions import _get_context, _maybe_number
from app.services import (
    find_duplicate_candidates,
    find_household_duplicates,
)
from app.templates import templates
from app.validators import (
    parse_amount,
    parse_year_month,
    require_bucket,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", dependencies=[Depends(require_csrf)])


# ---------------------------------------------------------------------------
# Transaction search (cross-bucket)
# ---------------------------------------------------------------------------

SEARCH_PAGE_SIZE = 25

@router.get("/search", response_class=HTMLResponse)
def search_transactions(
    request: Request,
    q: str = Query(""),
    category_id: str = Query(""),
    type: str = Query(""),
    from_date: str = Query(""),
    to_date: str = Query(""),
    bucket_id: str = Query(""),
    min_amount: str = Query(""),
    max_amount: str = Query(""),
    paid_by: str = Query(""),
    missing_payer: str = Query(""),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)

    # Settle-up links here to show exactly which expenses it had to skip.
    want_missing_payer = missing_payer in ("1", "on", "true")

    has_filter = any([q.strip(), category_id, type, from_date, to_date, bucket_id,
                      min_amount.strip(), max_amount.strip(), paid_by,
                      want_missing_payer])

    if has_filter:
        query = db.query(Transaction).filter(Transaction.active(), Transaction.household_id == hh_id)

        if q.strip():
            # Free text used to match notes only, so a scanned receipt whose
            # merchant landed in the category or bucket name was unfindable —
            # and a bare number could not be searched at all.
            term = f"%{q.strip()}%"
            conditions = [
                Transaction.notes.ilike(term),
                Transaction.category_id.in_(
                    db.query(Category.id).filter(
                        Category.household_id == hh_id, Category.name.ilike(term)
                    ).scalar_subquery()
                ),
                Transaction.bucket_id.in_(
                    db.query(Bucket.id).filter(
                        Bucket.household_id == hh_id, Bucket.name.ilike(term)
                    ).scalar_subquery()
                ),
                Transaction.paid_by.in_(
                    db.query(User.id).filter(User.display_name.ilike(term)).scalar_subquery()
                ),
            ]
            # A numeric term also matches the amount exactly, so "42.50" works.
            exact = _maybe_number(q)
            if exact is not None:
                conditions.append(Transaction.amount == exact)
            query = query.filter(or_(*conditions))

        lo = parse_amount(min_amount, field="Min amount", allow_blank=True, allow_zero=True)
        if lo is not None:
            query = query.filter(Transaction.amount >= lo)
        hi = parse_amount(max_amount, field="Max amount", allow_blank=True, allow_zero=True)
        if hi is not None:
            query = query.filter(Transaction.amount <= hi)

        if paid_by:
            # Match the payer or anyone carrying a split on the transaction.
            query = query.filter(
                or_(
                    Transaction.paid_by == paid_by,
                    Transaction.id.in_(
                        db.query(TransactionSplit.transaction_id)
                        .filter(TransactionSplit.user_id == paid_by)
                        .scalar_subquery()
                    ),
                )
            )

        if category_id:
            query = query.filter(Transaction.category_id == category_id)
        if type:
            try:
                query = query.filter(Transaction.type == TransactionType(type))
            except ValueError:
                pass
        if from_date:
            try:
                query = query.filter(Transaction.transaction_date >= date.fromisoformat(from_date))
            except ValueError:
                pass
        if to_date:
            try:
                query = query.filter(Transaction.transaction_date <= date.fromisoformat(to_date))
            except ValueError:
                pass
        if bucket_id:
            query = query.filter(Transaction.bucket_id == bucket_id)
        if want_missing_payer:
            query = query.filter(
                Transaction.paid_by.is_(None),
                Transaction.type == TransactionType.expense,
            )

        total = query.count()
        total_pages = max(1, -(-total // SEARCH_PAGE_SIZE))
        page = min(page, total_pages)
        transactions = (
            query
            .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
            .offset((page - 1) * SEARCH_PAGE_SIZE)
            .limit(SEARCH_PAGE_SIZE)
            .all()
        )
    else:
        transactions = []
        total = None
        total_pages = 1
        page = 1

    ctx.update({
        "request": request,
        "user": user,
        "transactions": transactions,
        "q": q,
        "category_id": category_id,
        "selected_type": type,
        "from_date": from_date,
        "to_date": to_date,
        "selected_bucket_id": bucket_id,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "selected_paid_by": paid_by,
        "missing_payer": want_missing_payer,
        "page": page,
        "total_pages": total_pages,
        "total": total,
        "transaction_types": [t.value for t in TransactionType],
    })

    return templates.TemplateResponse("transactions/list.html", ctx)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection.

    Excel/Sheets execute a cell starting with = + - @ (or a leading tab/CR), so
    an expense note like `=HYPERLINK("http://evil","click")` becomes a live
    formula in whoever opens the export. Prefixing with an apostrophe keeps the
    text visible while forcing it to be read as a literal.
    """
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@router.get("/export", response_class=StreamingResponse)
def export_transactions(
    year: int = Query(None),
    month: int = Query(None),
    bucket_id: str = Query(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    parse_year_month(year, month)

    query = (
        db.query(Transaction)
        .filter(Transaction.active(), Transaction.household_id == hh_id)
        .options(
            joinedload(Transaction.bucket),
            joinedload(Transaction.category),
            joinedload(Transaction.paid_by_user),
        )
    )
    if bucket_id:
        require_bucket(db, bucket_id, hh_id)
        query = query.filter(Transaction.bucket_id == bucket_id)
    if year:
        # Half-open range avoids the old end-of-month arithmetic, which used
        # day 28 for February and so dropped Feb 29 in every leap year.
        if month:
            start = date(year, month, 1)
            end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        else:
            start, end = date(year, 1, 1), date(year + 1, 1, 1)
        query = query.filter(
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        )

    # Materialise rows now, not inside the generator. FastAPI closes the
    # get_db() session before the streaming body is consumed, so touching
    # txn.bucket lazily at that point raised DetachedInstanceError.
    rows = [
        [
            txn.transaction_date.isoformat(),
            _csv_safe(txn.bucket.name if txn.bucket else ""),
            _csv_safe(txn.category.name if txn.category else ""),
            txn.type.value,
            float(txn.amount),
            txn.currency,
            _csv_safe(txn.paid_by_user.display_name if txn.paid_by_user else ""),
            _csv_safe(txn.notes or ""),
        ]
        for txn in query.order_by(Transaction.transaction_date.desc()).all()
    ]

    def generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Date", "Bucket", "Category", "Type", "Amount", "Currency", "Paid By", "Notes"])
        yield buf.getvalue()
        for row in rows:
            buf = io.StringIO()
            csv.writer(buf).writerow(row)
            yield buf.getvalue()

    filename = f"transactions_{year or 'all'}{'_' + str(month) if month else ''}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

@router.get("/check-duplicate", response_class=JSONResponse)
def check_duplicate(
    amount: str = Query(""),
    transaction_date: str = Query(""),
    bucket_id: str = Query(""),
    exclude_id: str = Query(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Live check used by the add-expense form. Advisory only — never blocks."""
    user, hh_id = auth

    value = parse_amount(amount, field="Amount", allow_blank=True)
    if value is None or not transaction_date.strip():
        return {"duplicates": []}

    try:
        when = date.fromisoformat(transaction_date.strip())
    except ValueError:
        return {"duplicates": []}

    matches = find_duplicate_candidates(
        db, hh_id,
        amount=value,
        transaction_date=when,
        bucket_id=bucket_id or None,
        exclude_id=exclude_id or None,
    )
    return {
        "duplicates": [
            {
                "id":       t.id,
                "amount":   float(t.amount),
                "currency": t.currency,
                "date":     t.transaction_date.isoformat(),
                "notes":    t.notes,
                "bucket":   t.bucket.name if t.bucket else None,
                "paid_by":  t.paid_by_user.display_name if t.paid_by_user else None,
                "same_bucket": bool(bucket_id) and t.bucket_id == bucket_id,
            }
            for t in matches
        ]
    }


@router.get("/duplicates", response_class=HTMLResponse)
def duplicates_page(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Review possible duplicates across recent history."""
    user, hh_id = auth
    ctx = _get_context(db, user, hh_id)
    ctx.update({
        "request": request,
        "user": user,
        "groups": find_household_duplicates(db, hh_id),
    })
    return templates.TemplateResponse("transactions/duplicates.html", ctx)
