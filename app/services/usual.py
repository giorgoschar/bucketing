"""Categories against their usual (spec §4.2, §5.5).

A category's usual is the median of its spend over the last 3 full months,
counting months with zero spend, but only months the household has any data
for. Fewer than 2 such months: no usual and no flag. A category is flagged
when this month is at least 20% and at least €20 above its usual. There are
no category budgets.
"""

from collections import defaultdict
from decimal import Decimal
from statistics import median

from sqlalchemy.orm import Session

from app.core.money import ZERO, quantize
from app.models import Category, Transaction, TransactionType
from app.services.insights import _month_range
from app.services.money import to_base

USUAL_MONTHS = 3
MIN_MONTHS_WITH_DATA = 2
FLAG_RATIO = Decimal("1.2")
FLAG_MIN_ABOVE = Decimal("20")
FALLBACK_ICON = "📦"
FALLBACK_COLOR = "#9ca3af"


def _months_before(year: int, month: int, n: int) -> list[tuple[int, int]]:
    out = []
    for _ in range(n):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        out.append((year, month))
    return list(reversed(out))


def categories_vs_usual(db: Session, household_id: str, year: int, month: int) -> list[dict]:
    """Each category with spend this month or in the 3 months before it:
    this month, its usual and whether it is flagged. Flagged first, then by
    this month's spend."""
    past = _months_before(year, month, USUAL_MONTHS)
    window_start = _month_range(*past[0])[0]
    month_end = _month_range(year, month)[1]
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.transaction_date >= window_start,
            Transaction.transaction_date <= month_end,
        )
        .all()
    )
    with_data = set()
    spend: dict = defaultdict(lambda: defaultdict(Decimal))
    for t in rows:
        key = (t.transaction_date.year, t.transaction_date.month)
        with_data.add(key)
        if t.type == TransactionType.expense:
            spend[key][t.category_id] += to_base(t.amount, t.exchange_rate)
    data_months = [m for m in past if m in with_data]
    this = spend[(year, month)]
    category_ids = set(this) | {c for m in data_months for c in spend[m]}
    cats = {
        c.id: c for c in db.query(Category).filter(Category.id.in_([c for c in category_ids if c]))
    }
    result = []
    for cid in category_ids:
        now = quantize(this.get(cid, ZERO))
        usual = None
        flagged = False
        if len(data_months) >= MIN_MONTHS_WITH_DATA:
            usual = quantize(median([spend[m].get(cid, ZERO) for m in data_months]))
            flagged = now >= usual * FLAG_RATIO and now - usual >= FLAG_MIN_ABOVE
        cat = cats.get(cid)
        result.append(
            {
                "category_id": cid,
                "name": cat.name if cat else "Uncategorised",
                "icon": (cat.icon if cat else None) or FALLBACK_ICON,
                "color": (cat.color if cat else None) or FALLBACK_COLOR,
                "this_month": now,
                "usual": usual,
                "flagged": flagged,
            }
        )
    result.sort(key=lambda r: (not r["flagged"], -r["this_month"], r["name"]))
    return result
