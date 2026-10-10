"""Bill history and the Bills list (Phase A spec §3.5-3.6), on top of
app.services.bill_change."""

from dataclasses import asdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.core.money import quantize
from app.models import ItemDirection, RecurringBill
from app.services.bill_change import (
    ALERT_WINDOW_DAYS,
    Point,
    assess_item,
    entry_points,
    entry_points_by_item,
)

HISTORY_LIMIT = 240
RECENT_LIMIT = 12
_UNIT_PRICE_PLACES = Decimal("0.0001")


def unit_price(point: Point) -> Decimal | None:
    """Amount per unit to 4 places; None without usage or with usage 0."""
    if not point.usage:
        return None
    return (point.amount / point.usage).quantize(_UNIT_PRICE_PLACES, rounding=ROUND_HALF_UP)


def item_history(db: Session, item: RecurringBill) -> dict:
    """The ``ItemHistoryOut`` payload of ``item``."""
    points = entry_points(db, item)
    change = assess_item(item, points)
    return {
        "item": {
            "id": item.id,
            "name": item.name,
            "direction": item.direction,
            "currency": item.currency or "EUR",
            "usage_unit": item.usage_unit,
            "category_id": item.category_id,
            "is_active": item.is_active is not False,
        },
        "points": [
            {
                "entry_id": p.entry_id,
                "due_date": p.due_date,
                "amount": quantize(p.amount),
                "usage": p.usage,
                "unit_price": unit_price(p),
                "transaction_id": p.transaction_id,
            }
            for p in points[-HISTORY_LIMIT:]
        ],
        "change": asdict(change) if change else None,
    }


def _window(today: date) -> tuple[date, date]:
    """The first day of the 12 calendar months that end this month, and the
    first day after them."""
    first = today.replace(day=1)
    return first - relativedelta(months=11), first + relativedelta(months=1)


def bills_overview(db: Session, household_id: str, today: date) -> list[dict]:
    """One row per out item that is active or has a done entry (``BillRowOut``).

    At most three queries however many items: the items, their done entries and
    the transactions those entries fall back to.
    """
    items = (
        db.query(RecurringBill)
        .filter(
            RecurringBill.household_id == household_id,
            RecurringBill.direction == ItemDirection.out.value,
        )
        .all()
    )
    points = entry_points_by_item(db, items)
    # A done entry whose amount could not be found is not a point, so "has a done
    # entry" is asked of the points: they are what the row shows.
    start, stop = _window(today)
    recent_cutoff = today - timedelta(days=ALERT_WINDOW_DAYS)
    rows = []
    for item in items:
        pts = points[item.id]
        active = item.is_active is not False
        if not active and not pts:
            continue
        last = pts[-1] if pts else None
        in_window = [p.amount for p in pts if start <= p.due_date < stop]
        total = quantize(sum(in_window, Decimal(0))) if in_window else None
        average = quantize(sum(in_window, Decimal(0)) / len(in_window)) if in_window else None
        change = assess_item(item, pts) if last and last.due_date >= recent_cutoff else None
        rows.append(
            {
                "item_id": item.id,
                "name": item.name,
                "category_id": item.category_id,
                "usage_unit": item.usage_unit,
                "is_active": active,
                "last": {
                    "entry_id": last.entry_id,
                    "due_date": last.due_date,
                    "amount": quantize(last.amount),
                }
                if last
                else None,
                "recent": [quantize(p.amount) for p in pts[-RECENT_LIMIT:]],
                "total_12m": total,
                "average_12m": average,
                "change": asdict(change) if change else None,
            }
        )
    rows.sort(key=lambda r: (r["change"] is None, -(r["total_12m"] or 0), r["name"]))
    return rows


__all__ = ["bills_overview", "item_history", "unit_price"]
