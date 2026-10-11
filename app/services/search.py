"""One search box over entries, recurring items and the pantry (Phase C spec
§4.1). Three queries in all, however many rows match."""

from datetime import date

from pydantic import BaseModel
from sqlalchemy import case, or_
from sqlalchemy.orm import Session

from app.models import Category, Product, RecurringBill, StockItem, Transaction, TransactionType
from app.services.transaction_filter import LIKE_ESCAPE, TransactionFilter, _like, apply_filter

MIN_QUERY = 2
MAX_QUERY = 100
PER_GROUP = 5
LABEL_MAX = 60


class EntryHit(BaseModel):
    id: str
    date: date
    label: str
    category: str | None
    amount: float  # signed: negative is money out
    currency: str


class ItemHit(BaseModel):
    id: str
    name: str
    direction: str
    is_active: bool


class PantryHit(BaseModel):
    id: str  # the stock item id
    name: str
    brand: str | None
    quantity: float


class SearchOut(BaseModel):
    entries: list[EntryHit]
    entries_more: bool
    items: list[ItemHit]
    pantry: list[PantryHit]


def _label(t: Transaction, category: str | None) -> str:
    if t.merchant and t.merchant.strip():
        return t.merchant.strip()
    first_line = (t.notes or "").strip().split("\n", 1)[0].strip()
    return first_line[:LABEL_MAX] or category or ""


def search(db: Session, household_id: str, q: str) -> SearchOut:
    """``q`` is already trimmed and length-checked."""
    entry_query = apply_filter(
        db.query(Transaction, Category.name)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(Transaction.active(), Transaction.household_id == household_id),
        TransactionFilter(q=q),
        db,
        household_id,
    )
    rows = (
        entry_query.order_by(
            Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id
        )
        .limit(PER_GROUP + 1)
        .all()
    )
    entries = [
        EntryHit(
            id=t.id,
            date=t.transaction_date,
            label=_label(t, category),
            category=category,
            amount=float(t.amount if t.type == TransactionType.income else -t.amount),
            currency=t.currency or "EUR",
        )
        for t, category in rows[:PER_GROUP]
    ]

    term = _like(q)
    bills = (
        db.query(RecurringBill)
        .filter(
            RecurringBill.household_id == household_id,
            RecurringBill.name.ilike(term, escape=LIKE_ESCAPE),
        )
        .order_by(case((RecurringBill.is_active.is_(False), 1), else_=0), RecurringBill.name)
        .limit(PER_GROUP)
        .all()
    )

    stock = (
        db.query(StockItem, Product)
        .join(Product, StockItem.product_id == Product.id)
        .filter(
            StockItem.household_id == household_id,
            Product.household_id == household_id,
            Product.archived_at.is_(None),
            or_(
                Product.name.ilike(term, escape=LIKE_ESCAPE),
                Product.brand.ilike(term, escape=LIKE_ESCAPE),
                Product.barcode == q,
            ),
        )
        .order_by(Product.name)
        .limit(PER_GROUP)
        .all()
    )

    return SearchOut(
        entries=entries,
        entries_more=len(rows) > PER_GROUP,
        items=[
            ItemHit(
                id=b.id,
                name=b.name,
                direction=b.direction,
                is_active=b.is_active is not False,
            )
            for b in bills
        ],
        pantry=[
            PantryHit(id=s.id, name=p.name, brand=p.brand, quantity=float(s.quantity))
            for s, p in stock
        ],
    )
