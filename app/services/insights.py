"""
Insights: flexible date ranges, breakdowns, trends and KPIs.

Cash that was taken into a wallet but not logged yet counts as spending too
(see app.services.cash): it shows as a "Cash (not yet logged)"
pseudo-category, and labelled legacy cash ``out`` movements count under their
category. Which widgets include it:

* totals, KPIs, the category breakdown, the 6-month and category trends: yes;
* the forecast: yes, always the whole household's (it ignores filters);
* the payment-method breakdown: yes, as cash;
* the bucket breakdown and budget status: no, that cash has no bucket
  (and a bucket filter leaves it out of every widget);
* who paid: no, it describes logged expenses only;
* the Fuel card: no, it is about litres (:func:`get_insights_fuel`).

Household views include every member's wallet, a Person filter that person's
(:func:`app.services.cash.cash_scope`); it is household-visible, unlike the
stash it may have come from.

Income needs no bucket: bucket-less income always counts, bucketed income
only while its bucket tracks income. In / Out / Net (:func:`in_out`) sets it
against Out = logged expenses + the not-yet-logged cash above.
"""
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.clock import local_today
from app.core.money import TENTH, ZERO, percent, quantize, to_decimal
from app.models import (
    BillOccurrence,
    Bucket,
    BucketType,
    Category,
    HouseholdMember,
    OccurrenceStatus,
    PaymentMethod,
    RecurringBill,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.services.cash import (
    NOT_LOGGED_CASH,
    NOT_LOGGED_CASH_LABEL,
    CashSpend,
    cash_scope,
    cash_spending,
)
from app.services.fuel import LITRE, fuel_category_id
from app.services.money import (
    base_amount_expr,
    paid_for,
    share_of,
    shared_between,
    shares_for,
    to_base,
)
from app.services.settlement import settlement_members

UNASSIGNED_PAYER = "unassigned"

# Fuel prices are quoted to the tenth of a cent (1.789 €/L).
PRICE_PER_LITRE = Decimal("0.001")

# ``cash_for(start, end) -> CashSpend``: the cash spending to fold into a
# widget for its own window (see make_cash_lookup). None leaves cash out.
CashLookup = Callable[[date | None, date | None], CashSpend]


def make_cash_lookup(
    db: Session,
    household_id: str,
    *,
    person: str | None = None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
) -> CashLookup | None:
    """A memoised ``cash_for(start, end)`` for one filter set, or None when
    cash cannot apply (a bucket filter: not-yet-logged cash has no bucket).

    A category filter keeps the labelled outs in those categories and drops
    not-yet-logged cash, which has no category.
    """
    if bucket_type or bucket_ids:
        return None
    scope = cash_scope(db, household_id, person)
    cache: dict = {}

    def cash_for(start: date | None, end: date | None) -> CashSpend:
        if (start, end) not in cache:
            cache[(start, end)] = cash_spending(
                db, household_id, start, end, scope,
                include_not_logged=not category_ids, category_ids=category_ids,
            )
        return cache[(start, end)]

    return cash_for


def _category_label(cid, cats: dict) -> dict:
    if cid == NOT_LOGGED_CASH:
        return NOT_LOGGED_CASH_LABEL
    cat = cats.get(cid) if cid else None
    return {
        "name":  cat.name  if cat else "Uncategorised",
        "icon":  cat.icon  if cat else "📦",
        "color": cat.color if cat else "#9ca3af",
    }

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
    """Income for the month: bucket-less income, plus income in show_income
    buckets (see :func:`get_insights_income`)."""
    start, end = _month_range(year, month)
    return get_insights_income(db, household_id, start, end)


def in_out(income: Decimal, summary: dict) -> dict:
    """Money in vs money out for one period, rough by design.

    ``summary`` is a :func:`get_insights_summary` result built with the cash
    lookup, so Out is logged expenses (labelled cash outs included) plus the
    cash not logged yet. Insights and the dashboard both show this, so they
    agree.
    """
    out = summary["total_spent"]
    not_logged = summary["cash_not_logged"]
    return {
        "in":              quantize(income),
        "out":             quantize(out),
        "logged":          quantize(out - not_logged),
        "cash_not_logged": quantize(not_logged),
        "net":             quantize(income - out),
    }


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
            # A skipped occurrence will not be paid, so it is not due.
            BillOccurrence.status != OccurrenceStatus.skipped,
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
    cash_for: CashLookup | None = None,
    split_members: dict | None = None,
) -> list[dict]:
    """Expense totals for the last n_months calendar months (oldest → newest).

    Accepts the insight filters so the trend chart describes the same slice of
    data as the rest of the page; the dashboard calls it without filters.
    ``cash_for`` adds not-yet-logged cash and labelled cash outs per month.
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
        split_members=split_members,
    )
    if cash_for:
        totals = defaultdict(Decimal, totals)
        for key, amount in cash_for(
            _month_range(*months[0])[0], _month_range(*months[-1])[1],
        ).by_month().items():
            totals[key] += amount

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


def get_forecast(db: Session, household_id: str, cash_for: CashLookup | None = None) -> dict:
    """
    Project current month spend using a trend-based baseline:
    - baseline = average of last 3 complete months
    - projected = (spend_so_far / days_elapsed) * days_in_month
    - trend_delta = projected - baseline
    Returns empty dict if less than 3 months of history.

    ``cash_for`` (a household-wide lookup, see :func:`make_cash_lookup`) adds
    not-yet-logged cash and labelled cash outs to the baseline and to the spend so
    far, so the forecast describes the same spending as the trend beside it.
    """
    today = local_today()
    # Projections ignore one-off purchases; the trend chart shows actual spend.
    trend = get_monthly_trend(db, household_id, n_months=4, include_one_offs=False,
                              cash_for=cash_for)
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
    if cash_for:
        spend_so_far += cash_for(start, today).total
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
    split_members: dict | None = None,
):
    """Return a base Transaction query pre-filtered by all insight dimensions.

    One-off purchases (exclude_from_forecast) are actual spend, so they are
    included unless a projection asks for ``include_one_offs=False``.

    ``paid_by`` is the Person filter (the parameter keeps its old name so
    bookmarks and API clients still work): it selects every expense the person
    takes part in, and callers then count only that person's share of each
    (see :func:`_amount_for`). That includes an unsplit expense in a bucket
    where they settle up, which settle-up shares equally (``split_members``,
    :func:`_split_members`).
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
        # The payer, or anyone with a split; an own-share expense always has
        # splits. Rows where their share works out to zero (they fronted an
        # expense split entirely to others) drop out when amounts are summed.
        takes_part = [
            Transaction.paid_by == paid_by,
            Transaction.splits.any(TransactionSplit.user_id == paid_by),
        ]
        members = _split_members(db, household_id, split_members)
        their_buckets = [bid for bid, ids in members.items() if paid_by in ids]
        if their_buckets:
            # Unsplit, in a bucket where settle-up shares it with them (the
            # conditions of app.services.money.shared_between).
            takes_part.append(and_(
                Transaction.bucket_id.in_(their_buckets),
                ~Transaction.splits.any(),
                Transaction.paid_by.isnot(None),
                Transaction.exclude_from_settlement.is_(False),
            ))
        q = q.filter(or_(*takes_part))
    return q


def _split_members(db: Session, household_id: str, given: dict | None) -> dict:
    """``given`` when the caller already has it, else
    :func:`app.services.settlement.settlement_members` (one lookup per widget;
    :func:`build_insights` computes it once for all of them)."""
    return given if given is not None else settlement_members(db, household_id)


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
    split_members: dict | None = None,
) -> dict:
    """Sum filtered expenses grouped by one dimension, in a single round trip.

    ``group_by`` is "bucket", "category", "method", "month" or "category_month".

    Several insight widgets used to loop and issue one query per bucket / per
    month, which is what made the filter bar feel sluggish: a single filter
    change cost ~38 queries. Everything now aggregates in one pass.

    Without a Person filter the database does the aggregation. With one,
    each row counts as that person's share, which depends on the splits, so
    the filtered rows are summed in Python instead (the same arithmetic as
    /me, via :func:`_amount_for`).
    """
    if paid_by:
        split_members = _split_members(db, household_id, split_members)
    q = _build_expense_query(
        db, household_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
        include_one_offs=include_one_offs,
        split_members=split_members,
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

    if paid_by:
        for t in q.options(joinedload(Transaction.splits)).all():
            share = _amount_for(t, paid_by, split_members)
            if not share:
                continue
            if group_by == "method":
                totals[t.payment_method] += share
            else:
                totals[key_for(t.bucket_id, t.category_id, t.transaction_date)] += share
        return dict(totals)

    if group_by == "bucket":
        cols = [Transaction.bucket_id]
    elif group_by == "category":
        cols = [Transaction.category_id]
    elif group_by == "method":
        cols = [Transaction.payment_method]
    else:
        # Group in Python: month bucketing differs per SQL dialect, and one
        # round trip beats a portable-but-chatty per-month query.
        cols = [Transaction.category_id, Transaction.transaction_date]

    rows = q.with_entities(*cols, func.sum(base_amount_expr())).group_by(*cols).all()
    for row in rows:
        total = to_decimal(row[-1] or 0)
        if group_by == "bucket":
            totals[row[0]] += total
        elif group_by in ("category", "method"):
            totals[row[0]] += total
        else:
            cat_id, d = row[0], row[1]
            totals[key_for(None, cat_id, d)] += total
    return dict(totals)


def _effective_amount(t: Transaction) -> Decimal:
    """The full amount of the transaction in household currency."""
    return to_base(t.amount, t.exchange_rate)


def _amount_for(t: Transaction, person: str | None, split_members: dict | None = None) -> Decimal:
    """What a transaction counts for under the Person filter.

    Everyone: the full amount. A person: their share (the /me definition,
    :func:`app.services.money.share_of`, with settle-up's ``split_members``),
    so the filtered insights add up to the same figures as that person's /me
    page.
    """
    return share_of(t, person, split_members) if person else _effective_amount(t)


def get_insights_summary(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    cash_for: CashLookup | None = None,
    split_members: dict | None = None,
) -> dict:
    """Unified summary: total expenses + paid-by breakdown for any date range + filters.

    ``total_spent`` includes cash spending from ``cash_for`` (not-yet-logged
    cash plus labelled cash outs); ``logged_total`` is the expenses alone and
    ``cash_not_logged`` / ``cash_outs`` the two cash parts. Who paid describes
    the logged expenses only.

    ``total_spent`` honours the Person filter (that person's share), while
    ``gross_total`` is the full amount of the same expenses. The who-paid rows
    always describe those full amounts — who handed over how much, and whose
    share it was — so with a Person filter they read as "on the expenses this
    person took part in", and the card scales its bars by ``gross_total``.
    Shares follow settle-up: an unsplit expense in a settlement bucket is
    shared equally (``split_members``).
    """
    split_members = _split_members(db, household_id, split_members)
    q = _build_expense_query(db, household_id, start, end, bucket_type, bucket_ids, category_ids,
                             paid_by, split_members=split_members)
    txns = q.options(joinedload(Transaction.splits)).all()
    total_spent = sum((_amount_for(t, paid_by, split_members) for t in txns), ZERO)
    gross_total = sum((_effective_amount(t) for t in txns), ZERO)

    paid_acc: dict[str, Decimal] = defaultdict(Decimal)
    share_acc: dict[str, Decimal] = defaultdict(Decimal)
    for t in txns:
        # Each amount is credited to whoever handed it over (the payer, or every
        # member for an own-share expense); money nobody is credited with goes
        # to an "Unassigned" row so the bars still sum to total_spent.
        amount = to_base(t.amount, t.exchange_rate)
        among = shared_between(t, split_members)
        paid = paid_for(t, among)
        for uid, value in paid.items():
            paid_acc[uid] += value
        uncredited = amount - sum(paid.values(), ZERO)
        if abs(uncredited) > Decimal("0.005"):
            paid_acc[UNASSIGNED_PAYER] += uncredited
        shares = shares_for(t, among)
        assigned = sum(shares.values(), ZERO)
        for uid, share in shares.items():
            share_acc[uid] += share
        # With no payer there is nobody to absorb the unsplit remainder.
        share_acc[UNASSIGNED_PAYER] += (amount - assigned) if not t.paid_by else ZERO

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

    cash = cash_for(start, end) if cash_for else CashSpend()
    return {
        "total_spent": quantize(total_spent + cash.total),
        "logged_total": quantize(total_spent),
        "cash_not_logged": cash.not_logged_total,
        "cash_outs":   cash.outs_total,
        "gross_total": quantize(gross_total),
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
    """Sum of income transactions in the date range.

    Bucket-less income always counts; income in a bucket counts only while
    that bucket has "Track income" (show_income) on. A bucket filter keeps
    only income in those buckets. The Person filter is the recipient
    (``paid_by``): income is not split.
    """
    q = (
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .outerjoin(Bucket, Bucket.id == Transaction.bucket_id)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.income,
            or_(Transaction.bucket_id.is_(None), Bucket.show_income.is_(True)),
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
        .filter(
            RecurringBill.household_id == household_id,
            # A skipped occurrence will not be paid, so it is not due.
            BillOccurrence.status != OccurrenceStatus.skipped,
        )
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
    cash_for: CashLookup | None = None,
    split_members: dict | None = None,
) -> list[dict]:
    """Top spending categories filtered by all insight dimensions.

    Labelled cash outs join their category; not-yet-logged cash is its own
    "Cash (not yet logged)" row.
    """
    if paid_by:
        split_members = _split_members(db, household_id, split_members)
    q = _build_expense_query(db, household_id, start, end, bucket_type, bucket_ids, category_ids,
                             paid_by, split_members=split_members)
    txns = q.options(joinedload(Transaction.splits)).all() if paid_by else q.all()

    totals: dict[str | None, Decimal] = defaultdict(Decimal)
    for t in txns:
        amount = _amount_for(t, paid_by, split_members)
        if amount:
            totals[t.category_id] += amount
    if cash_for:
        for cid, amount in cash_for(start, end).by_category(NOT_LOGGED_CASH).items():
            totals[cid] += amount

    grand = sum(totals.values()) or 1
    cat_ids = [cid for cid in totals if cid is not None and cid != NOT_LOGGED_CASH]
    cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}

    rows = []
    for cat_id, amount in sorted(totals.items(), key=lambda x: -x[1])[:limit]:
        rows.append({
            **_category_label(cat_id, cats),
            "amount": quantize(amount),
            "pct":    quantize(amount / grand * 100, TENTH),
        })
    return rows


_METHOD_LABELS = {
    PaymentMethod.card.value: "Card",
    PaymentMethod.cash.value: "Cash",
    PaymentMethod.apple_pay.value: "Apple Pay",
    PaymentMethod.transfer.value: "Transfer",
    PaymentMethod.other.value: "Other",
}


def get_insights_by_method(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    cash_for: CashLookup | None = None,
    split_members: dict | None = None,
) -> tuple[list[dict], Decimal]:
    """Actual spend per payment method plus cash's share of all spending (%).

    Rows are ``{method, label, amount, pct}``, biggest first, zero methods
    omitted. A missing method counts as "other"; not-yet-logged cash and labelled
    cash outs count as cash.
    """
    raw = _sum_expenses_by(
        db, household_id, start, end,
        group_by="method",
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
        split_members=split_members,
    )
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for method, amount in raw.items():
        totals[method or PaymentMethod.other.value] += amount
    if cash_for:
        totals[PaymentMethod.cash.value] += cash_for(start, end).total
    grand = sum(totals.values(), ZERO)
    rows = [
        {
            "method": m,
            "label":  _METHOD_LABELS.get(m, m.replace("_", " ").title()),
            "amount": quantize(amt),
            "pct":    percent(amt, grand),
        }
        for m, amt in totals.items() if quantize(amt) > 0
    ]
    rows.sort(key=lambda r: -r["amount"])
    cash_share = percent(totals.get(PaymentMethod.cash.value, ZERO), grand)
    return rows, cash_share


def get_insights_bucket_breakdown(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    split_members: dict | None = None,
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
        split_members=split_members,
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
    cash_for: CashLookup | None = None,
    split_members: dict | None = None,
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
        split_members=split_members,
    )
    if cash_for:
        grid = defaultdict(Decimal, grid)
        for key, amount in cash_for(
            _month_range(*month_list[0])[0], _month_range(*month_list[-1])[1],
        ).by_category_month(NOT_LOGGED_CASH).items():
            grid[key] += amount

    cat_totals: dict[str | None, Decimal] = defaultdict(Decimal)
    for (cid, _y, _m), amount in grid.items():
        cat_totals[cid] += amount

    # Pick top_n categories
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:top_n]
    top_cat_ids = [cid for cid, _ in top_cats]

    # Load category objects
    cat_objs = {c.id: c for c in db.query(Category).filter(
        Category.id.in_([c for c in top_cat_ids if c and c != NOT_LOGGED_CASH])).all()}

    labels = [date(y, m, 1).strftime("%b") for y, m in month_list]
    monthly_data: dict[str | None, list[Decimal]] = {
        cid: [quantize(grid.get((cid, y, m), ZERO)) for y, m in month_list]
        for cid in top_cat_ids
    }

    series = []
    for cid in top_cat_ids:
        series.append({
            **_category_label(cid, cat_objs),
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
    category_ids: list | None = None,
    paid_by: str | None = None,
    split_members: dict | None = None,
) -> list[dict]:
    """Spending vs budget for each bucket with a budget, over a date range.

    Spending honours the category and Person filters like every other figure
    on the page (with a person, it is their share of the bucket's spending);
    it used to always be the bucket's whole spend.
    """
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

    # One-off purchases (exclude_from_forecast) still count: the flag only
    # keeps them out of projections, not out of actual spend, so this matches
    # the dashboard's bucket spend.
    spend_map = _sum_expenses_by(
        db, household_id, start, end,
        group_by="bucket",
        bucket_ids=[b.id for b in buckets],
        category_ids=category_ids,
        paid_by=paid_by,
        split_members=split_members,
    )

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


def get_insights_fuel(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
    split_members: dict | None = None,
) -> dict | None:
    """The Fuel card: litres, spend and price per litre, or None without data.

    Only fuel expenses with litres recorded (a price was given) count towards
    ``litres``, ``spend`` and the average, so the average is the weighted one:
    spend in household currency / litres. Fuel expenses without a price are
    reported as ``unpriced_count`` only. ``months`` lists each month with data,
    oldest first, for the litres and price trends.

    Honours the date, bucket and category filters like every other widget.
    With a Person filter, each fill counts that person's share of it: litres
    and spend both scale by their share of the amount (see
    :func:`_amount_for`), which leaves the price per litre as it was.
    """
    fuel_id = fuel_category_id(db, household_id)
    if fuel_id is None:
        return None
    if paid_by:
        split_members = _split_members(db, household_id, split_members)
    q = _build_expense_query(
        db, household_id, start, end,
        bucket_type=bucket_type, bucket_ids=bucket_ids,
        category_ids=category_ids, paid_by=paid_by, split_members=split_members,
    ).filter(Transaction.category_id == fuel_id)
    txns = q.options(joinedload(Transaction.splits)).all() if paid_by else q.all()

    litres: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    spend: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    # The same per bucket (one bucket per car), keyed (bucket_id, year, month).
    car_litres: dict[tuple[str, int, int], Decimal] = defaultdict(Decimal)
    car_spend: dict[tuple[str, int, int], Decimal] = defaultdict(Decimal)
    car_fills: dict[str, int] = defaultdict(int)
    # Every priced refuel per car, for the price-per-refuel chart.
    car_refuels: dict[str, list] = defaultdict(list)
    fills = unpriced = 0
    for t in txns:
        full = _effective_amount(t)
        part = _amount_for(t, paid_by, split_members)
        # Checked before the price, so an unpriced fill outside the person's
        # share is not reported against them either.
        if not part or not full:
            continue
        if t.fuel_litres is None:
            unpriced += 1
            continue
        fraction = part / full
        key = (t.transaction_date.year, t.transaction_date.month)
        volume = to_decimal(t.fuel_litres) * fraction
        litres[key] += volume
        spend[key] += part
        car_litres[(t.bucket_id, *key)] += volume
        car_spend[(t.bucket_id, *key)] += part
        car_fills[t.bucket_id] += 1
        car_refuels[t.bucket_id].append((t.transaction_date, t.created_at, volume, part, t))
        fills += 1

    total_litres = sum(litres.values(), Decimal(0))
    if total_litres <= 0:
        return None

    def per_litre(money: Decimal, volume: Decimal) -> Decimal | None:
        return quantize(money / volume, PRICE_PER_LITRE) if volume > 0 else None

    def months(lit: dict, spe: dict) -> list[dict]:
        return [
            {
                "year":   y,
                "month":  m,
                "label":  date(y, m, 1).strftime("%b %Y"),
                "litres": quantize(lit[(y, m)], LITRE),
                "spend":  quantize(spe[(y, m)]),
                "avg_price_per_litre": per_litre(spe[(y, m)], lit[(y, m)]),
            }
            for (y, m) in sorted(lit)
        ]

    # Per car: each bucket's own totals and monthly trend, most litres first.
    buckets = {
        b.id: b for b in db.query(Bucket).filter(Bucket.id.in_(list(car_fills))).all()
    } if car_fills else {}
    cars = []
    for bid in car_fills:
        lit = {(y, m): v for (b, y, m), v in car_litres.items() if b == bid}
        spe = {(y, m): v for (b, y, m), v in car_spend.items() if b == bid}
        c_litres, c_spend = sum(lit.values(), Decimal(0)), sum(spe.values(), ZERO)
        bucket = buckets.get(bid)
        cars.append({
            "bucket_id":           bid,
            "name":                bucket.name if bucket else "—",
            "icon":                bucket.icon if bucket else "",
            "litres":              quantize(c_litres, LITRE),
            "spend":               quantize(c_spend),
            "avg_price_per_litre": per_litre(c_spend, c_litres),
            "fills":               car_fills[bid],
            "months":              months(lit, spe),
            # Oldest first. The price is the one paid, in household currency
            # (a share changes the litres and spend, not the price).
            "refuels": [
                {
                    "date":            day,
                    "price_per_litre": quantize(
                        to_decimal(t.fuel_price_per_litre) * to_decimal(t.exchange_rate or 1),
                        PRICE_PER_LITRE),
                    "litres":          quantize(volume, LITRE),
                    "spend":           quantize(part),
                }
                for day, _, volume, part, t in sorted(
                    car_refuels[bid], key=lambda r: (r[0], str(r[1] or "")))
            ],
        })
    cars.sort(key=lambda c: (-c["litres"], c["name"]))

    total_spend = sum(spend.values(), ZERO)
    return {
        "litres":              quantize(total_litres, LITRE),
        "spend":               quantize(total_spend),
        "avg_price_per_litre": per_litre(total_spend, total_litres),
        "fills":               fills,
        "unpriced_count":      unpriced,
        "months":              months(litres, spend),
        "cars":                cars,
    }


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
    # Not-yet-logged cash and labelled cash outs, for the widgets that count them
    # (see the module docstring); computed once per window.
    cash_for = make_cash_lookup(
        db, household_id,
        person=filters.paid_by or None,
        bucket_type=bucket_type, bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
    )
    # Settle-up's members per bucket, looked up once for every widget.
    shares = {**common, "split_members": settlement_members(db, household_id)}
    with_cash = {**shares, "cash_for": cash_for}
    # The forecast is always household-wide, whatever the filters.
    household_cash = cash_for if not any(common.values()) else make_cash_lookup(db, household_id)

    summary          = get_insights_summary(db, household_id, start, end, **with_cash)
    income_total     = get_insights_income(db, household_id, start, end, **common)
    bills_due        = get_insights_bills_due(
        db, household_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=selected_bucket_ids or None,
        category_ids=selected_category_ids or None,
    )
    categories       = get_insights_category_breakdown(db, household_id, start, end, **with_cash)
    budget_status    = get_insights_budget_status(db, household_id, start, end, **shares)
    bucket_breakdown = get_insights_bucket_breakdown(db, household_id, start, end, **shares)
    category_trend   = get_insights_category_trend(db, household_id, n_months=6, **with_cash)
    trend            = get_monthly_trend(db, household_id, n_months=6, **with_cash)
    forecast         = (
        get_forecast(db, household_id, household_cash) if period["is_current_month"] else {}
    )
    kpis             = get_insights_kpis(db, household_id, start, end, **with_cash)
    by_method, cash_share = get_insights_by_method(db, household_id, start, end, **with_cash)
    fuel             = get_insights_fuel(db, household_id, start, end, **shares)

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
        "in_out":                in_out(income_total, summary),
        "categories":            categories,
        "budget_status":         budget_status,
        "bucket_breakdown":      bucket_breakdown,
        "category_trend":        category_trend,
        "trend":                 trend,
        "forecast":              forecast,
        "kpis":                  kpis,
        "by_method":             by_method,
        "cash_share":            cash_share,
        "fuel":                  fuel,
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
    cash_for: CashLookup | None = None,
    split_members: dict | None = None,
) -> dict:
    """Headline numbers for the insights board, under the active filters.

    Cash spending from ``cash_for`` adds to the totals, averages and
    per-month figures (not to the count or the largest expense).

    Everything here answers "for the slice I am currently looking at", so the
    same filter set drives the KPIs, the charts and the totals — the previous
    version of this page mixed filtered and unfiltered figures.
    """
    if paid_by:
        split_members = _split_members(db, household_id, split_members)
    q = _build_expense_query(
        db, household_id, start, end,
        bucket_type=bucket_type, bucket_ids=bucket_ids,
        category_ids=category_ids, paid_by=paid_by, split_members=split_members,
    )
    txns = q.options(joinedload(Transaction.splits), joinedload(Transaction.category)).all()

    amounts = [(t, _amount_for(t, paid_by, split_members)) for t in txns]
    amounts = [(t, a) for t, a in amounts if a]
    cash = cash_for(start, end) if cash_for else CashSpend()
    total = sum((a for _, a in amounts), cash.total)
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
    for key, a in cash.by_month().items():
        by_month[key] += a

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
            category_ids=category_ids, paid_by=paid_by, split_members=split_members,
        )
        prev_txns = prev_q.options(joinedload(Transaction.splits)).all()
        prev_cash = cash_for(prev_start, prev_end).total if cash_for else ZERO
        previous_total = quantize(sum(
            (_amount_for(t, paid_by, split_members) for t in prev_txns), prev_cash,
        ))
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
