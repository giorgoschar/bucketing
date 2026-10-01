"""
Insights: flexible date ranges, breakdowns, trends and KPIs.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.clock import local_today
from app.models import (
    BillOccurrence,
    Bucket,
    BucketType,
    Category,
    HouseholdMember,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)
from app.money import TENTH, ZERO, quantize, to_decimal
from app.services.money import base_amount_expr, shares_for, to_base

UNASSIGNED_PAYER = "unassigned"

# ---------------------------------------------------------------------------
# New analytics functions
# ---------------------------------------------------------------------------

def _recent_months(n_months: int, today: date | None = None) -> list[tuple[int, int]]:
    """The last n_months as (year, month) pairs, oldest → newest."""
    today = today or local_today()
    months: list[tuple[int, int]] = []
    for i in range(n_months - 1, -1, -1):
        m, y = today.month - i, today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append((y, m))
    return months


def _month_range(year: int, month: int):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def get_income_total(db: Session, household_id: str, year: int, month: int) -> Decimal:
    """Sum of income transactions for the month, limited to show_income buckets."""
    start, end = _month_range(year, month)
    total = (
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .join(Bucket, Bucket.id == Transaction.bucket_id)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.income,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Bucket.show_income.is_(True),
        )
        .scalar()
    )
    return quantize(total)


def get_bills_due_month_total(db: Session, household_id: str, year: int, month: int) -> Decimal:
    """Sum of amounts for bill occurrences due within the given calendar month."""
    start, end = _month_range(year, month)
    occurrences = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        # Without the eager load, the bill.amount fallback below issues one
        # SELECT per occurrence on every dashboard render.
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == household_id,
            BillOccurrence.due_date >= start,
            BillOccurrence.due_date <= end,
        )
        .all()
    )
    # NOTE: RecurringBill has a currency but no exchange_rate, so a bill priced
    # in a non-default currency is counted at face value here. Transactions are
    # converted (see base_amount_expr); bills would need a rate column to match.
    total = sum(
        to_decimal(occ.amount or occ.bill.amount or 0) for occ in occurrences
    )
    return quantize(total)


def get_monthly_trend(
    db: Session,
    household_id: str,
    n_months: int = 6,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    include_one_offs: bool = True,
) -> list[dict]:
    """Expense totals for the last n_months calendar months (oldest → newest).

    Accepts the insight filters so the trend chart describes the same slice of
    data as the rest of the page; the dashboard calls it without filters.
    """
    today = local_today()
    months = _recent_months(n_months, today)

    # One query for the whole window instead of one per month.
    totals = _sum_expenses_by(
        db, household_id,
        _month_range(*months[0])[0],
        _month_range(*months[-1])[1],
        group_by="month",
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
        include_one_offs=include_one_offs,
    )

    return [
        {
            "label":      date(y, m, 1).strftime("%b"),
            "year":       y,
            "month":      m,
            "total":      quantize(totals.get((y, m), ZERO)),
            "is_current": (y == today.year and m == today.month),
        }
        for y, m in months
    ]


def get_forecast(db: Session, household_id: str) -> dict:
    """
    Project current month spend using a trend-based baseline:
    - baseline = average of last 3 complete months
    - projected = (spend_so_far / days_elapsed) * days_in_month
    - trend_delta = projected - baseline
    Returns empty dict if less than 3 months of history.
    """
    today = local_today()
    # Projections ignore one-off purchases; the trend chart shows actual spend.
    trend = get_monthly_trend(db, household_id, n_months=4, include_one_offs=False)
    past = [m for m in trend if not m["is_current"]]
    if len(past) < 3:
        return {}
    baseline = quantize(sum(m["total"] for m in past[-3:]) / 3)

    year, month = today.year, today.month
    start, _ = _month_range(year, month)
    days_elapsed = (today - start).days + 1
    if month == 12:
        days_in_month = (date(year + 1, 1, 1) - start).days
    else:
        days_in_month = (date(year, month + 1, 1) - start).days

    spend_so_far = (
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= today,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
        .scalar()
    )
    spend_so_far = to_decimal(spend_so_far)
    daily_rate  = spend_so_far / days_elapsed if days_elapsed > 0 else 0
    projected   = quantize(daily_rate * days_in_month)
    delta       = quantize(projected - baseline)

    return {
        "baseline":        baseline,
        "projected":       projected,
        "trend_delta":     delta,
        "above_trend":     delta > 0,
        "days_elapsed":    days_elapsed,
        "days_in_month":   days_in_month,
        "spend_so_far":    quantize(spend_so_far),
    }


# ---------------------------------------------------------------------------
# Insights v2 — unified helpers that accept flexible date ranges + new filters
# ---------------------------------------------------------------------------

INSIGHT_PRESETS = (
    "this_month", "last_month", "last_3m", "last_6m", "this_year", "all_time", "custom",
)


def _parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value and value.strip() else None
    except (ValueError, AttributeError):
        return None


def resolve_insight_period(
    preset: str,
    start_date: str = "",
    end_date: str = "",
    today: date | None = None,
) -> dict:
    """Turn a preset (+ optional custom dates) into a concrete date range.

    Shared by the HTML and JSON insights endpoints, which previously carried
    two hand-maintained copies of this logic that could drift apart.
    """
    today = today or local_today()
    start: date | None = None
    end: date | None = None

    if preset == "all_time":
        start, end = None, None
    elif preset == "last_month":
        first_of_month = today.replace(day=1)
        end = first_of_month - timedelta(days=1)
        start = end.replace(day=1)
    elif preset in ("last_3m", "last_6m"):
        months = 3 if preset == "last_3m" else 6
        end = today
        m, y = today.month - months, today.year
        while m <= 0:
            m += 12
            y -= 1
        start = date(y, m, 1)
    elif preset == "this_year":
        start = date(today.year, 1, 1)
        end = today
    elif preset == "custom":
        start = _parse_iso(start_date)
        end = _parse_iso(end_date)
        # Unparseable custom dates used to fall through as None/None, silently
        # showing all-time data under a "custom range" label.
        if start is None and end is None:
            preset = "this_month"
            start, end = date(today.year, today.month, 1), today
        elif start and end and start > end:
            start, end = end, start
    else:
        preset = "this_month"
        start, end = date(today.year, today.month, 1), today

    all_time = start is None and end is None
    is_current_month = (
        not all_time
        and start == date(today.year, today.month, 1)
        and end == today
    )

    if all_time:
        label = "All time"
    elif preset == "last_month":
        label = start.strftime("%B %Y")
    elif preset == "last_3m":
        label = "Last 3 months"
    elif preset == "last_6m":
        label = "Last 6 months"
    elif preset == "this_year":
        label = str(today.year)
    elif preset == "custom":
        if start and end:
            label = f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
        elif start:
            label = f"From {start.strftime('%d %b %Y')}"
        else:
            label = f"Until {end.strftime('%d %b %Y')}"
    else:
        label = today.strftime("%B %Y")

    return {
        "preset":           preset,
        "start":            start,
        "end":              end,
        "all_time":         all_time,
        "is_current_month": is_current_month,
        "period_label":     label,
    }

def _build_expense_query(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    include_one_offs: bool = True,
):
    """Return a base Transaction query pre-filtered by all insight dimensions.

    One-off purchases (exclude_from_forecast) are actual spend, so they are
    included unless a projection asks for ``include_one_offs=False``.
    """
    q = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
        )
    )
    if not include_one_offs:
        q = q.filter(Transaction.exclude_from_forecast == False)  # noqa: E712
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    if bucket_type:
        q = q.join(Bucket, Bucket.id == Transaction.bucket_id).filter(
            Bucket.type == BucketType(bucket_type)
        )
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    if category_ids:
        q = q.filter(Transaction.category_id.in_(category_ids))
    if paid_by:
        # "Paid by" means the payer: who fronted the money, not who owes a share.
        q = q.filter(Transaction.paid_by == paid_by)
    return q


def _sum_expenses_by(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    *,
    group_by: str,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    include_one_offs: bool = True,
) -> dict:
    """Sum filtered expenses grouped by one dimension, in a single round trip.

    ``group_by`` is "bucket", "category", "month" or "category_month".

    Several insight widgets used to loop and issue one query per bucket / per
    month, which is what made the filter bar feel sluggish: a single filter
    change cost ~38 queries. Everything now aggregates in one pass.

    ``paid_by`` filters on the payer, so the database does the aggregation.
    """
    q = _build_expense_query(
        db, household_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
        include_one_offs=include_one_offs,
    )

    def key_for(bucket_id, category_id, txn_date):
        if group_by == "bucket":
            return bucket_id
        if group_by == "category":
            return category_id
        if group_by == "month":
            return (txn_date.year, txn_date.month)
        return (category_id, txn_date.year, txn_date.month)

    totals: dict = defaultdict(Decimal)

    # The payer filter is a plain column filter, so SQL does the grouping.
    if group_by == "bucket":
        cols = [Transaction.bucket_id]
    elif group_by == "category":
        cols = [Transaction.category_id]
    else:
        # Group in Python: month bucketing differs per SQL dialect, and one
        # round trip beats a portable-but-chatty per-month query.
        cols = [Transaction.category_id, Transaction.transaction_date]

    rows = q.with_entities(*cols, func.sum(base_amount_expr())).group_by(*cols).all()
    for row in rows:
        total = to_decimal(row[-1] or 0)
        if group_by == "bucket":
            totals[row[0]] += total
        elif group_by == "category":
            totals[row[0]] += total
        else:
            cat_id, d = row[0], row[1]
            totals[key_for(None, cat_id, d)] += total
    return dict(totals)


def _effective_amount(t: Transaction) -> Decimal:
    """The full amount of the transaction in household currency."""
    return to_base(t.amount, t.exchange_rate)


def get_insights_summary(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
) -> dict:
    """Unified summary: total expenses + paid-by breakdown for any date range + filters."""
    q = _build_expense_query(db, household_id, start, end, bucket_type, bucket_ids, category_ids, paid_by)
    txns = q.options(joinedload(Transaction.splits)).all()
    total_spent = sum(_effective_amount(t) for t in txns)

    paid_acc: dict[str, Decimal] = defaultdict(Decimal)
    share_acc: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        # Full amount is credited to whoever fronted it; expenses with no payer
        # go to an "Unassigned" row so the bars still sum to total_spent.
        paid_acc[t.paid_by or UNASSIGNED_PAYER] += to_base(t.amount, t.exchange_rate)
        shares = shares_for(t)
        assigned = sum(shares.values(), ZERO)
        for uid, share in shares.items():
            share_acc[uid] += share
        # With no payer there is nobody to absorb the unsplit remainder.
        share_acc[UNASSIGNED_PAYER] += (to_base(t.amount, t.exchange_rate) - assigned) if not t.paid_by else ZERO

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    member_map = {m.id: m for m in members}
    # Payers / split users who left the household still hold real money.
    missing = {uid for uid in set(paid_acc) | set(share_acc) if uid != UNASSIGNED_PAYER} - set(member_map)
    former = {u.id: u for u in db.query(User).filter(User.id.in_(missing)).all()} if missing else {}
    paid_by_detail = {}
    for uid in sorted(set(paid_acc) | set(share_acc), key=lambda k: (-paid_acc.get(k, ZERO), k)):
        paid = paid_acc.get(uid, ZERO)
        share = share_acc.get(uid, ZERO)
        if uid == UNASSIGNED_PAYER:
            if not paid and abs(share) < Decimal("0.005"):
                continue
            name, color = "Unassigned", "#9ca3af"
        elif uid in member_map:
            name, color = member_map[uid].display_name, member_map[uid].avatar_color
        else:
            u = former.get(uid)
            name, color = f"Former member: {u.display_name if u else 'unknown'}", "#9ca3af"
        paid_q = quantize(paid)
        paid_by_detail[uid] = {
            "name":   name,
            "color":  color,
            "paid":   paid_q,
            "share":  quantize(share),
            "amount": paid_q,  # alias of ``paid``, kept for one release
        }

    return {
        "total_spent": quantize(total_spent),
        "paid_by":     paid_by_detail,
        "period_start": start,
        "period_end":   end,
    }


def get_insights_income(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
) -> Decimal:
    """Sum of income transactions in the date range, limited to show_income buckets."""
    q = (
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .join(Bucket, Bucket.id == Transaction.bucket_id)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.income,
            Bucket.show_income.is_(True),
        )
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    if bucket_type:
        q = q.filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    if category_ids:
        q = q.filter(Transaction.category_id.in_(category_ids))
    if paid_by:
        q = q.filter(Transaction.paid_by == paid_by)
    return quantize(q.scalar())


def get_insights_bills_due(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
) -> Decimal:
    """Sum of bill occurrence amounts due within the date range.

    Honours the same bucket/category filters as the rest of the insights page —
    it previously always reported the household-wide total, so the "Bills due"
    tile contradicted every other number whenever a filter was active.
    """
    # joinedload avoids one SELECT per occurrence for the bill.amount fallback.
    q = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(RecurringBill.household_id == household_id)
    )
    if start:
        q = q.filter(BillOccurrence.due_date >= start)
    if end:
        q = q.filter(BillOccurrence.due_date <= end)
    if bucket_type:
        q = q.join(Bucket, Bucket.id == RecurringBill.bucket_id).filter(
            Bucket.type == BucketType(bucket_type)
        )
    if bucket_ids:
        q = q.filter(RecurringBill.bucket_id.in_(bucket_ids))
    if category_ids:
        q = q.filter(RecurringBill.category_id.in_(category_ids))

    total = sum(to_decimal(occ.amount or occ.bill.amount or 0) for occ in q.all())
    return quantize(total)


def get_insights_category_breakdown(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    limit: int = 8,
) -> list[dict]:
    """Top spending categories filtered by all insight dimensions."""
    q = _build_expense_query(db, household_id, start, end, bucket_type, bucket_ids, category_ids, paid_by)
    txns = q.options(joinedload(Transaction.splits)).all() if paid_by else q.all()

    totals: dict[str | None, Decimal] = defaultdict(Decimal)
    for t in txns:
        totals[t.category_id] += _effective_amount(t)

    grand = sum(totals.values()) or 1
    cat_ids = [cid for cid in totals if cid is not None]
    cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}

    rows = []
    for cat_id, amount in sorted(totals.items(), key=lambda x: -x[1])[:limit]:
        cat = cats.get(cat_id) if cat_id else None
        rows.append({
            "name":   cat.name  if cat else "Uncategorised",
            "icon":   cat.icon  if cat else "📦",
            "color":  cat.color if cat else "#9ca3af",
            "amount": quantize(amount),
            "pct":    quantize(amount / grand * 100, TENTH),
        })
    return rows


def get_insights_bucket_breakdown(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
) -> list[dict]:
    """Spending per active bucket within the date range."""
    buckets = (
        db.query(Bucket)
        .filter_by(household_id=household_id, status="active")
        .order_by(Bucket.created_at)
        .all()
    )
    if not buckets:
        return []

    # Respect an explicit bucket filter. This chart used to ignore bucket_ids
    # entirely, so selecting two buckets still rendered every bucket — and its
    # percentages disagreed with the filtered total shown above it.
    selected = set(bucket_ids) if bucket_ids else None

    visible = [
        b for b in buckets
        if not (bucket_type and b.type.value != bucket_type)
        and (selected is None or b.id in selected)
    ]
    if not visible:
        return []

    # One aggregate query for every bucket at once. This used to run a separate
    # query per bucket, so a household with 10 buckets paid 10 round trips on
    # every filter change.
    totals = _sum_expenses_by(
        db, household_id, start, end,
        group_by="bucket",
        bucket_ids=[b.id for b in visible],
        category_ids=category_ids,
        paid_by=paid_by,
    )

    result = [
        {"bucket": b, "total": quantize(totals.get(b.id, ZERO))}
        for b in visible
    ]

    result = [r for r in result if r["total"] > 0]
    result.sort(key=lambda x: -x["total"])
    grand = sum(r["total"] for r in result) or 1
    for r in result:
        r["pct"] = quantize(r["total"] / grand * 100, TENTH)
    return result


def get_insights_category_trend(
    db: Session,
    household_id: str,
    n_months: int = 6,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    top_n: int = 5,
) -> dict:
    """
    Per-category expense totals for each of the last n_months calendar months.
    Returns {months: [label,...], series: [{name, color, icon, values: [Decimal,...]}]}
    Only includes the top_n categories by total spend across the period.
    """
    today = local_today()
    month_list = _recent_months(n_months, today)

    # One pass over the whole window, grouped by (category, year, month) —
    # this previously ran a separate query for every month on top of an
    # overview query.
    grid = _sum_expenses_by(
        db, household_id,
        _month_range(*month_list[0])[0],
        _month_range(*month_list[-1])[1],
        group_by="category_month",
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
    )

    cat_totals: dict[str | None, Decimal] = defaultdict(Decimal)
    for (cid, _y, _m), amount in grid.items():
        cat_totals[cid] += amount

    # Pick top_n categories
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:top_n]
    top_cat_ids = [cid for cid, _ in top_cats]

    # Load category objects
    cat_objs = {c.id: c for c in db.query(Category).filter(Category.id.in_([c for c in top_cat_ids if c])).all()}

    labels = [date(y, m, 1).strftime("%b") for y, m in month_list]
    monthly_data: dict[str | None, list[Decimal]] = {
        cid: [quantize(grid.get((cid, y, m), ZERO)) for y, m in month_list]
        for cid in top_cat_ids
    }

    series = []
    for cid in top_cat_ids:
        cat = cat_objs.get(cid) if cid else None
        series.append({
            "name":   cat.name  if cat else "Uncategorised",
            "icon":   cat.icon  if cat else "📦",
            "color":  cat.color if cat else "#9ca3af",
            "values": monthly_data[cid],
        })

    # The chart plots one bar per (category, month), so the y-axis maximum is
    # the largest single monthly value. Callers used to derive it from
    # sum(values) — a whole-period total — which squashed every bar to roughly
    # a sixth of its correct height.
    max_value = max(
        (v for row in series for v in row["values"]),
        default=ZERO,
    )

    return {"months": labels, "series": series, "max_value": quantize(max_value)}


def get_insights_budget_status(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
) -> list[dict]:
    """Spending vs budget for each bucket with a budget, over a date range."""
    bq = (
        db.query(Bucket)
        .filter(
            Bucket.household_id == household_id,
            Bucket.budget.isnot(None),
            Bucket.status == "active",
        )
    )
    if bucket_type:
        bq = bq.filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        bq = bq.filter(Bucket.id.in_(bucket_ids))
    buckets = bq.all()
    if not buckets:
        return []

    ids = [b.id for b in buckets]
    q = (
        db.query(Transaction.bucket_id, func.sum(base_amount_expr()))
        .filter(
            Transaction.active(),
            Transaction.bucket_id.in_(ids),
            Transaction.type == TransactionType.expense,
            # One-off purchases (exclude_from_forecast) still count: the flag
            # only keeps them out of projections, not out of actual spend, so
            # this matches the dashboard's bucket spend.
        )
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    rows = q.group_by(Transaction.bucket_id).all()
    spend_map = {bid: to_decimal(total) for bid, total in rows}

    result = []
    for b in buckets:
        spent  = quantize(spend_map.get(b.id, ZERO))
        budget = to_decimal(b.budget)
        raw_pct = quantize(spent / budget * 100, TENTH) if budget > 0 else 0
        result.append({
            "bucket":      b,
            "spent":       spent,
            "budget":      budget,
            # pct drives the progress bar width and must stay <= 100; pct_actual
            # is the true figure so the UI can show "140% of budget".
            "pct":         min(raw_pct, 100),
            "pct_actual":  raw_pct,
            "remaining":   quantize(budget - spent),
            "over_budget": spent > budget,
        })
    result.sort(key=lambda x: -x["pct_actual"])
    return result


@dataclass(frozen=True)
class InsightFilters:
    """The insights filter bar, as sent by both the HTML page and the API.

    ``bucket_ids`` / ``category_ids`` are the raw comma-separated query
    strings; ``today`` pins "this month" (defaults to the local date).
    """
    preset:       str = "this_month"
    start_date:   str = ""
    end_date:     str = ""
    bucket_type:  str = ""
    bucket_ids:   str = ""
    category_ids: str = ""
    paid_by:      str = ""
    today:        date | None = None


def build_insights(db: Session, household_id: str, filters: InsightFilters) -> dict:
    """Every figure on the insights board, for the HTML page and the JSON API.

    The two endpoints used to orchestrate these calls separately; they now
    share this so they cannot drift apart. Every chart takes the same filter
    set, so the numbers all describe the same slice of data.
    """
    period = resolve_insight_period(
        filters.preset, filters.start_date, filters.end_date, filters.today,
    )
    start, end = period["start"], period["end"]

    selected_bucket_ids   = [b for b in filters.bucket_ids.split(",")   if b.strip()]
    selected_category_ids = [c for c in filters.category_ids.split(",") if c.strip()]
    bucket_type = filters.bucket_type

    common = {
        "bucket_type":  bucket_type,
        "bucket_ids":   selected_bucket_ids or None,
        "category_ids": selected_category_ids or None,
        "paid_by":      filters.paid_by or None,
    }

    summary          = get_insights_summary(db, household_id, start, end, **common)
    income_total     = get_insights_income(db, household_id, start, end, **common)
    bills_due        = get_insights_bills_due(
        db, household_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
    )
    categories       = get_insights_category_breakdown(db, household_id, start, end, **common)
    budget_status    = get_insights_budget_status(
        db, household_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
    )
    bucket_breakdown = get_insights_bucket_breakdown(db, household_id, start, end, **common)
    category_trend   = get_insights_category_trend(db, household_id, n_months=6, **common)
    trend            = get_monthly_trend(db, household_id, n_months=6, **common)
    forecast         = get_forecast(db, household_id) if period["is_current_month"] else {}
    kpis             = get_insights_kpis(db, household_id, start, end, **common)

    return {
        "period":                period,
        "start":                 start,
        "end":                   end,
        "selected_bucket_ids":   selected_bucket_ids,
        "selected_category_ids": selected_category_ids,
        "summary":               summary,
        "income_total":          income_total,
        "bills_due":             bills_due,
        "net":                   quantize(income_total - summary["total_spent"]),
        "categories":            categories,
        "budget_status":         budget_status,
        "bucket_breakdown":      bucket_breakdown,
        "category_trend":        category_trend,
        "trend":                 trend,
        "forecast":              forecast,
        "kpis":                  kpis,
    }


# ---------------------------------------------------------------------------
# Insight KPIs
# ---------------------------------------------------------------------------

def _months_spanned(start: date, end: date) -> int:
    """Calendar months touched by the range, inclusive. Never zero."""
    return max((end.year - start.year) * 12 + (end.month - start.month) + 1, 1)


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _month_end(year: int, month: int) -> date:
    """Last calendar day of the month."""
    return (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))


def get_insights_kpis(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
) -> dict:
    """Headline numbers for the insights board, under the active filters.

    Everything here answers "for the slice I am currently looking at", so the
    same filter set drives the KPIs, the charts and the totals — the previous
    version of this page mixed filtered and unfiltered figures.
    """
    q = _build_expense_query(
        db, household_id, start, end,
        bucket_type=bucket_type, bucket_ids=bucket_ids,
        category_ids=category_ids, paid_by=paid_by,
    )
    txns = q.options(joinedload(Transaction.splits), joinedload(Transaction.category)).all()

    amounts = [(t, _effective_amount(t)) for t in txns]
    amounts = [(t, a) for t, a in amounts if a]
    total = sum((a for _, a in amounts), ZERO)
    count = len(amounts)

    # Range bounds: fall back to the data when the period is open-ended.
    dates = [t.transaction_date for t, _ in amounts if t.transaction_date]
    range_start = start or (min(dates) if dates else None)
    range_end = end or (max(dates) if dates else None)

    months = _months_spanned(range_start, range_end) if range_start and range_end else 1
    days = ((range_end - range_start).days + 1) if range_start and range_end else 1

    # Per-month totals, for the busiest/quietest month and the average.
    by_month: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for t, a in amounts:
        if t.transaction_date:
            by_month[(t.transaction_date.year, t.transaction_date.month)] += a

    def _month_row(item):
        (y, m), value = item
        return {"label": date(y, m, 1).strftime("%b %Y"), "total": quantize(value)}

    # "Quietest" is only meaningful for months that actually finished, and that
    # the filter covers end to end. A month still in progress — or clipped by
    # the range — always looks cheapest simply because less of it has happened.
    today = local_today()
    complete = {
        (y, m): value
        for (y, m), value in by_month.items()
        if _month_start(y, m) >= range_start
        and _month_end(y, m) <= range_end
        and _month_end(y, m) < today
    } if range_start and range_end else {}

    busiest = _month_row(max(by_month.items(), key=lambda kv: kv[1])) if by_month else None
    quietest = _month_row(min(complete.items(), key=lambda kv: kv[1])) if complete else None

    largest = None
    if amounts:
        t, a = max(amounts, key=lambda pair: pair[1])
        largest = {
            "amount": quantize(a),
            "notes": t.notes,
            "date": t.transaction_date,
            "category": t.category.name if t.category else None,
        }

    # Same-length window immediately before this one, for a like-for-like delta.
    previous_total = None
    change_pct = None
    if range_start and range_end:
        span = (range_end - range_start).days + 1
        prev_end = range_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        prev_q = _build_expense_query(
            db, household_id, prev_start, prev_end,
            bucket_type=bucket_type, bucket_ids=bucket_ids,
            category_ids=category_ids, paid_by=paid_by,
        )
        prev_txns = prev_q.options(joinedload(Transaction.splits)).all()
        previous_total = quantize(sum(_effective_amount(t) for t in prev_txns))
        if previous_total > 0:
            change_pct = quantize((total - previous_total) / previous_total * 100, TENTH)

    income = get_insights_income(
        db, household_id, start, end,
        bucket_type=bucket_type, bucket_ids=bucket_ids,
        category_ids=category_ids, paid_by=paid_by,
    )

    return {
        "total":          quantize(total),
        "count":          count,
        "months":         months,
        "days":           days,
        "avg_per_month":  quantize(total / months) if months else ZERO,
        "avg_per_day":    quantize(total / days) if days else ZERO,
        "avg_per_txn":    quantize(total / count) if count else ZERO,
        "busiest_month":  busiest,
        "quietest_month": quietest,
        "largest":        largest,
        "previous_total": previous_total,
        "change_pct":     change_pct,
        "income":         income,
        "net":            quantize(income - total),
        # Share of income kept. Only meaningful when income is actually tracked.
        "savings_rate":   quantize((income - total) / income * 100, TENTH) if income > 0 else None,
        "range_start":    range_start,
        "range_end":      range_end,
    }
