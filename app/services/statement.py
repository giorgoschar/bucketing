"""Month statements (Phase B spec §2, §3.2-§3.5).

A statement is the household's month recalculated each time it is opened:
nothing is frozen and no month is locked. Every number comes from the service
that already shows it elsewhere, asked for that month. ``today`` is always
passed in; nothing here reads the clock.
"""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, exists, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import local_date, utcnow_naive
from app.core.money import ZERO, quantize
from app.models import (
    BillOccurrence,
    CashMovement,
    Category,
    HouseholdMember,
    ItemDirection,
    MonthReview,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)
from app.services.bill_change import assess_item, entry_points_by_item
from app.services.budgets import monthly_overruns
from app.services.cash import WALLET_KINDS, wallet_summaries
from app.services.insights import _month_range, in_out_by_month
from app.services.money import base_amount_expr
from app.services.planning import list_entries
from app.services.usual import categories_vs_usual

REVIEW_DAYS = 5  # days 1 to 5 of a month review the month before it
OPEN_LIMIT = 50
BIGGEST_LIMIT = 5
LIST_LIMIT = 120
UNLOGGED_MIN = Decimal("0.005")

_MONTH = re.compile(r"(\d{4})-(\d{2})", re.ASCII)


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


def parse_month_key(value: str) -> tuple[int, int] | None:
    """``YYYY-MM`` -> (year, month), or None for anything else."""
    m = _MONTH.fullmatch(value or "")
    if not m or not 1 <= int(m.group(2)) <= 12 or not 1970 <= int(m.group(1)) <= 2200:
        return None
    return int(m.group(1)), int(m.group(2))


def is_past(year: int, month: int, today: date) -> bool:
    """A month strictly before the current one."""
    return (year, month) < (today.year, today.month)


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def window_end(year: int, month: int) -> date:
    """The last day of the review window of a month (the 5th of the next)."""
    return date(*_next_month(year, month), REVIEW_DAYS)


def review_state(year: int, month: int, reviewed: bool, today: date) -> tuple[bool, int | None]:
    """``(closed, days_left)`` (spec §2, §3.2): closed once reviewed or past
    the window; ``days_left`` counts today and is None when closed."""
    end = window_end(year, month)
    if reviewed or today > end:
        return True, None
    return False, max((end - today).days + 1, 0)


# ------------------------------------------------------------------- data


def cash_data_filter():
    """Which cash movements count as the household's data: wallet movements
    only. A stash movement is private to its owner and never shows a number,
    so it must not make a month appear. One rule for the list, the review row
    and the notification."""
    return and_(CashMovement.active(), CashMovement.kind.in_(WALLET_KINDS))


def month_has_data(db: Session, household_id: str, year: int, month: int) -> bool:
    """Any transaction or wallet cash movement dated in the month."""
    start, end = _month_range(year, month)
    in_txn = exists().where(
        Transaction.household_id == household_id,
        Transaction.active(),
        Transaction.transaction_date >= start,
        Transaction.transaction_date <= end,
    )
    in_cash = exists().where(
        CashMovement.household_id == household_id,
        cash_data_filter(),
        CashMovement.movement_date >= start,
        CashMovement.movement_date <= end,
    )
    return bool(db.query(in_txn | in_cash).scalar())


def first_data_month(db: Session, household_id: str) -> tuple[int, int] | None:
    """The month of the household's earliest transaction or wallet movement."""
    found = [
        d
        for d in (
            db.query(func.min(Transaction.transaction_date))
            .filter(Transaction.household_id == household_id, Transaction.active())
            .scalar(),
            db.query(func.min(CashMovement.movement_date))
            .filter(CashMovement.household_id == household_id, cash_data_filter())
            .scalar(),
        )
        if d is not None
    ]
    if not found:
        return None
    first = min(found)
    return first.year, first.month


def get_review(db: Session, household_id: str, month: str) -> MonthReview | None:
    return db.query(MonthReview).filter_by(household_id=household_id, month=month).first()


def mark_reviewed(db: Session, household_id: str, month: str, user_id: str) -> MonthReview:
    """Record the review; the first reviewer is kept. Two members pressing
    Done together end with one row and no error for either. Does not commit."""
    existing = get_review(db, household_id, month)
    if existing is not None:
        return existing
    try:
        with db.begin_nested():
            row = MonthReview(
                household_id=household_id,
                month=month,
                reviewed_at=utcnow_naive(),
                reviewed_by=user_id,
            )
            db.add(row)
            db.flush()
        return row
    except IntegrityError:
        # The other request won: keep its row.
        db.expire_all()
        existing = get_review(db, household_id, month)
        if existing is None:
            raise
        return existing


def reviewer_fields(db: Session, review: MonthReview | None, names: dict | None = None) -> dict:
    """``reviewed_at``, ``reviewed_on`` (the household-local date), ``reviewed_by``
    and ``reviewed_by_name`` (display name, else username; None when the user is
    gone) of a review, all None without one."""
    if review is None:
        return {
            "reviewed_at": None,
            "reviewed_on": None,
            "reviewed_by": None,
            "reviewed_by_name": None,
        }
    if names is None:
        names = _names(db, {review.reviewed_by})
    return {
        "reviewed_at": review.reviewed_at,
        "reviewed_on": local_date(review.reviewed_at),
        "reviewed_by": review.reviewed_by,
        "reviewed_by_name": names.get(review.reviewed_by),
    }


def _names(db: Session, user_ids: set) -> dict[str, str]:
    ids = {u for u in user_ids if u}
    if not ids:
        return {}
    return {
        u.id: u.display_name or u.username for u in db.query(User).filter(User.id.in_(ids)).all()
    }


# -------------------------------------------------------------- sections


def _planned(db: Session, household_id: str, year: int, month: int, today: date) -> dict:
    start, end = _month_range(year, month)
    # Paused items keep their done entries (those happened, and the totals count
    # their money); only their still-expected entries go, as in Plan.
    entries = [
        e
        for e in list_entries(db, household_id, start, end, today=today, include_paused=True)
        if not (e.paused and e.status == "expected")
    ]
    sides = {}
    for name in (ItemDirection.in_.value, ItemDirection.out.value):
        mine = [e for e in entries if e.direction == name]
        sides[name] = {
            "planned": quantize(
                sum((e.amount or ZERO for e in mine if e.status != "skipped"), ZERO)
            ),
            "actual": quantize(
                sum(
                    (e.amount or ZERO for e in mine if e.status == "done" and not e.estimated), ZERO
                )
            ),
        }
    open_entries = [
        {
            "entry_id": e.id,
            "item_id": e.item_id,
            "name": e.name,
            "direction": e.direction,
            "due_date": e.due_date,
            "amount": e.amount,
            "estimated": e.estimated,
            "status": "expected",
        }
        for e in entries
        if e.status == "expected"
    ][:OPEN_LIMIT]
    return {"in": sides["in"], "out": sides["out"], "open": open_entries}


def _bills_changed(db: Session, household_id: str, year: int, month: int) -> list[dict]:
    start, end = _month_range(year, month)
    items = (
        db.query(RecurringBill)
        .filter(
            RecurringBill.household_id == household_id,
            RecurringBill.direction == ItemDirection.out.value,
            RecurringBill.occurrences.any(
                (BillOccurrence.status == OccurrenceStatus.paid)
                & (BillOccurrence.due_date >= start)
                & (BillOccurrence.due_date <= end)
            ),
        )
        .all()
    )
    points_by_item = entry_points_by_item(db, items)
    rows = []
    for item in items:
        points = points_by_item[item.id]
        for i, point in enumerate(points):
            if not start <= point.due_date <= end:
                continue
            change = assess_item(item, points[: i + 1])
            if change is None:
                continue
            rows.append(
                {
                    "item_id": item.id,
                    "name": item.name,
                    "entry_id": change.entry_id,
                    "due_date": point.due_date,
                    "amount": change.amount,
                    "usual": change.usual,
                    "basis": change.basis,
                    "direction": change.direction,
                    "pct": change.pct,
                    "reason": change.reason,
                    "reason_pct": change.reason_pct,
                    "_delta": abs(change.delta),
                }
            )
    rows.sort(key=lambda r: (-r["_delta"], r["name"], r["due_date"]))
    for r in rows:
        del r["_delta"]
    return rows


def _cash(db: Session, household_id: str, year: int, month: int, viewer_id: str | None) -> list:
    start, end = _month_range(year, month)
    members = (
        db.query(User.id, User.display_name)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    if not members:
        return []
    wallets = wallet_summaries(
        db, household_id, [m.id for m in members], start, end, viewer_id=viewer_id
    )
    rows = [
        {
            "member_id": m.id,
            "name": m.display_name,
            "not_yet_logged": wallets[m.id]["not_yet_logged"],
        }
        for m in members
        if wallets[m.id]["not_yet_logged"] > UNLOGGED_MIN
    ]
    rows.sort(key=lambda r: (r["name"], r["member_id"]))
    return rows


def _biggest(db: Session, household_id: str, year: int, month: int) -> list[dict]:
    start, end = _month_range(year, month)
    rows = (
        db.query(Transaction, Category.name, base_amount_expr().label("base"))
        .outerjoin(Category, Category.id == Transaction.category_id)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .order_by(base_amount_expr().desc(), Transaction.transaction_date.desc(), Transaction.id)
        .limit(BIGGEST_LIMIT)
        .all()
    )
    return [
        {
            "transaction_id": t.id,
            # The Activity feed's label: merchant, else notes, else the category.
            "date": t.transaction_date,
            "label": t.merchant or t.notes or category or "Transaction",
            "category": category,
            "amount": quantize(base),
        }
        for t, category, base in rows
    ]


def _categories_over(db: Session, household_id: str, year: int, month: int) -> list[dict]:
    return [
        {
            "category_id": r["category_id"],
            "name": r["name"],
            "icon": r["icon"],
            "amount": r["this_month"],
            "usual": r["usual"],
        }
        for r in categories_vs_usual(db, household_id, year, month)
        if r["flagged"]
    ]


# ------------------------------------------------------------- statement


def build_statement(
    db: Session,
    household_id: str,
    year: int,
    month: int,
    *,
    today: date,
    viewer_id: str | None = None,
) -> dict:
    """The statement of a past month (spec §3.2). The caller has checked that
    the month is strictly before ``today``'s."""
    key = month_key(year, month)
    prev_y, prev_m = previous_month(year, month)
    both = in_out_by_month(db, household_id, date(prev_y, prev_m, 1), date(year, month, 1))
    previous = None
    if month_has_data(db, household_id, prev_y, prev_m):
        previous = {"month": month_key(prev_y, prev_m), **both[(prev_y, prev_m)]}
    review = get_review(db, household_id, key)
    closed, days_left = review_state(year, month, review is not None, today)
    return {
        **reviewer_fields(db, review),
        "month": key,
        "label": month_label(year, month),
        "closed": closed,
        "days_left": days_left,
        "totals": {**both[(year, month)], "previous": previous},
        "planned": _planned(db, household_id, year, month, today),
        "budgets_over": monthly_overruns(db, household_id, year, month),
        "bills_changed": _bills_changed(db, household_id, year, month),
        "cash": _cash(db, household_id, year, month, viewer_id),
        "categories_over": _categories_over(db, household_id, year, month),
        "biggest": _biggest(db, household_id, year, month),
    }


# ------------------------------------------------------------------ list


def review_candidate(db: Session, household_id: str, today: date) -> dict | None:
    """Last month, when today is in its review window, it is not reviewed and
    it has any data; else None (spec §3.3)."""
    if today.day > REVIEW_DAYS:
        return None
    year, month = previous_month(today.year, today.month)
    if get_review(db, household_id, month_key(year, month)) is not None:
        return None
    if not month_has_data(db, household_id, year, month):
        return None
    _closed, days_left = review_state(year, month, False, today)
    return {
        "month": month_key(year, month),
        "label": month_label(year, month),
        "days_left": days_left,
    }


def build_list(db: Session, household_id: str, *, today: date) -> dict:
    """The statements list (spec §3.3): every month from the first one with
    data to last month, newest first, at most LIST_LIMIT."""
    last = previous_month(today.year, today.month)
    first = first_data_month(db, household_id)
    if first is None or first > last:
        return {"review": None, "months": []}
    span = []
    y, m = last
    while (y, m) >= first and len(span) < LIST_LIMIT:
        span.append((y, m))
        y, m = previous_month(y, m)
    totals = in_out_by_month(db, household_id, date(*span[-1], 1), date(*last, 1))
    reviews = {r.month: r for r in db.query(MonthReview).filter_by(household_id=household_id)}
    names = _names(db, {r.reviewed_by for r in reviews.values()})
    months = []
    for y, m in span:
        key = month_key(y, m)
        review = reviews.get(key)
        closed, _left = review_state(y, m, review is not None, today)
        months.append(
            {
                "month": key,
                "label": month_label(y, m),
                **totals[(y, m)],
                **reviewer_fields(db, review, names),
                "closed": closed,
            }
        )
    return {"review": review_candidate(db, household_id, today), "months": months}
