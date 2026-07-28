"""
Balance and summary calculations for dashboards and bucket views.
"""
from datetime import date, timedelta
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, case, or_

from app.models import (
    Transaction, TransactionSplit, TransactionType,
    BillOccurrence, OccurrenceStatus, RecurringBill,
    User, HouseholdMember, Bucket, BucketType, BucketStatus, Category, Household,
    Settlement,
)


# ---------------------------------------------------------------------------
# Currency normalisation
#
# Transaction.amount is stored in Transaction.currency; exchange_rate converts
# it to the household's default currency. The rate was captured and stored but
# never applied, so every total silently added raw amounts across currencies —
# a EUR 50 dinner and a USD 50 dinner summed to "100" of nothing. Aggregate
# base_amount, never amount.
# ---------------------------------------------------------------------------

def base_amount_expr():
    """SQL expression: transaction amount converted to the household currency."""
    return Transaction.amount * func.coalesce(Transaction.exchange_rate, 1)


def to_base(amount, exchange_rate) -> float:
    """Python equivalent of :func:`base_amount_expr` for loaded ORM objects."""
    if amount is None:
        return 0.0
    rate = 1 if exchange_rate is None else exchange_rate
    return float(amount) * float(rate)


def shares_for(txn, member_ids: set[str] | None = None) -> dict[str, float]:
    """Who is responsible for how much of this expense, in household currency.

    Three cases, and the middle one is the reason this helper exists:

    * **Explicit splits covering the total** — each user takes their split.
    * **Explicit splits covering only part of it** — the payer absorbs the
      remainder. Logging a EUR 100 dinner as a single EUR 50 split for the
      other person is the natural way to record "you owe me half", but the
      other EUR 50 used to be attributed to nobody. Balances then failed to sum
      to zero, inflating the payer's credit and making the settle-up figures
      wrong.
    * **No splits** — divided equally among ``member_ids`` when given (the
      shared-bucket convention), otherwise borne entirely by the payer.

    The returned shares always sum to the transaction total, which is what
    guarantees household balances net to zero.
    """
    total = to_base(txn.amount, txn.exchange_rate)
    shares: dict[str, float] = defaultdict(float)

    if txn.splits:
        assigned = 0.0
        for s in txn.splits:
            value = split_to_base(s, txn)
            shares[s.user_id] += value
            assigned += value
        remainder = total - assigned
        if abs(remainder) > 0.005:
            if txn.paid_by:
                shares[txn.paid_by] += remainder
            elif member_ids:
                per = remainder / len(member_ids)
                for uid in member_ids:
                    shares[uid] += per
        return dict(shares)

    if member_ids:
        per = total / len(member_ids)
        for uid in member_ids:
            shares[uid] += per
    elif txn.paid_by:
        shares[txn.paid_by] += total
    return dict(shares)


def split_to_base(split, txn) -> float:
    """A split share converted to the household currency.

    Splits are denominated in the parent transaction's currency, so they take
    that transaction's rate.
    """
    return to_base(split.amount, txn.exchange_rate)


def base_ctx(db: Session, user, hh_id: str) -> dict:
    """Minimal context shared by every page: current household + switcher list."""
    household = db.get(Household, hh_id)
    memberships = db.query(HouseholdMember).filter_by(user_id=user.id).all()
    households = [db.get(Household, m.household_id) for m in memberships]
    return {"household": household, "households": households}


def full_ctx(db: Session, user, hh_id: str) -> dict:
    """Extended context including members, categories and active buckets."""
    ctx = base_ctx(db, user, hh_id)
    ctx["members"] = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == hh_id)
        .all()
    )
    ctx["categories"] = db.query(Category).filter_by(household_id=hh_id).all()
    ctx["buckets"] = db.query(Bucket).filter_by(household_id=hh_id, status=BucketStatus.active).all()
    return ctx


def get_month_summary(db: Session, household_id: str, year: int, month: int, bucket_type: str = "", bucket_ids: list | None = None) -> dict:
    """
    Returns:
      - total_spent: total expense amount for the month
      - paid_by: {user_id: {"name": str, "color": str, "amount": float}}
      - balance: who owes whom (simplified two-person logic + multi-person)
    """
    start = date(year, month, 1)
    # Last day of month
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    q = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
    if bucket_type:
        q = q.join(Bucket, Bucket.id == Transaction.bucket_id).filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    txns = q.options(joinedload(Transaction.splits)).all()

    total_spent = sum(to_base(t.amount, t.exchange_rate) for t in txns)

    # Amount paid by each user — use splits when present, else paid_by
    paid_by: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            paid_by[t.paid_by] += to_base(t.amount, t.exchange_rate)

    # Load member info
    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    member_map = {m.id: m for m in members}

    paid_by_detail = {}
    for uid, amount in paid_by.items():
        user = member_map.get(uid)
        if user:
            paid_by_detail[uid] = {
                "name": user.display_name,
                "color": user.avatar_color,
                "amount": amount,
            }

    return {
        "total_spent": round(total_spent, 2),
        "paid_by": paid_by_detail,
        "period_start": start,
        "period_end": end,
    }


def get_bucket_month_summary(db: Session, bucket_id: str, year: int, month: int) -> dict:
    """
    Who-paid breakdown for a single bucket in a given month.
    Returns total_spent, paid_by_detail, balances (same shape as get_month_summary).
    Members are derived from the bucket's household.
    """
    from app.models import Bucket
    bucket = db.get(Bucket, bucket_id)
    if not bucket:
        return {"total_spent": 0, "paid_by": {}, "balances": []}

    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    txns = (
        db.query(Transaction)
        .filter(
            Transaction.bucket_id == bucket_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .options(joinedload(Transaction.splits))
        .all()
    )

    total_spent = sum(to_base(t.amount, t.exchange_rate) for t in txns)

    # Amount paid by each user — use splits when present, else paid_by
    paid_by: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            paid_by[t.paid_by] += to_base(t.amount, t.exchange_rate)

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == bucket.household_id)
        .all()
    )
    member_map = {m.id: m for m in members}

    paid_by_detail = {}
    for uid, amount in paid_by.items():
        user = member_map.get(uid)
        if user:
            paid_by_detail[uid] = {
                "name": user.display_name,
                "color": user.avatar_color,
                "amount": round(amount, 2),
            }

    return {
        "total_spent": round(total_spent, 2),
        "paid_by": paid_by_detail,
        "period_start": start,
        "period_end": end,
    }


def get_all_time_summary(db: Session, household_id: str, bucket_type: str = "", bucket_ids: list | None = None) -> dict:
    """Total expenses and who-paid breakdown across all time for a household."""
    q = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
    if bucket_type:
        q = q.join(Bucket, Bucket.id == Transaction.bucket_id).filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    txns = q.options(joinedload(Transaction.splits)).all()
    total_spent = sum(to_base(t.amount, t.exchange_rate) for t in txns)

    paid_by: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            paid_by[t.paid_by] += to_base(t.amount, t.exchange_rate)

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    member_map = {m.id: m for m in members}

    paid_by_detail = {}
    for uid, amount in paid_by.items():
        user = member_map.get(uid)
        if user:
            paid_by_detail[uid] = {
                "name": user.display_name,
                "color": user.avatar_color,
                "amount": round(amount, 2),
            }

    return {
        "total_spent": round(total_spent, 2),
        "paid_by": paid_by_detail,
    }


def get_bucket_balance(db: Session, bucket_id: str) -> dict:
    """Total income, expenses, and net for a bucket — single SQL aggregation query."""
    income_sum = func.coalesce(
        func.sum(case((Transaction.type == TransactionType.income, base_amount_expr()), else_=0)), 0
    )
    expense_sum = func.coalesce(
        func.sum(case((Transaction.type == TransactionType.expense, base_amount_expr()), else_=0)), 0
    )
    row = db.query(income_sum, expense_sum).filter(Transaction.bucket_id == bucket_id).one()
    income = float(row[0])
    expenses = float(row[1])
    return {
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "net": round(income - expenses, 2),
    }


def get_upcoming_bills(db: Session, household_id: str, days: int = 30) -> list:
    """Bills due within the next N days."""
    today = date.today()
    cutoff = today + timedelta(days=days)

    occurrences = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        # Templates render occ.bill.name/amount for every row — eager-load it.
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == household_id,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date >= today,
            BillOccurrence.due_date <= cutoff,
        )
        .order_by(BillOccurrence.due_date)
        .all()
    )
    return occurrences


def get_overdue_bills(db: Session, household_id: str) -> list:
    today = date.today()
    occurrences = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .options(joinedload(BillOccurrence.bill))
        .filter(
            RecurringBill.household_id == household_id,
            BillOccurrence.status == OccurrenceStatus.unpaid,
            BillOccurrence.due_date < today,
        )
        .order_by(BillOccurrence.due_date)
        .all()
    )
    return occurrences


# ---------------------------------------------------------------------------
# New analytics functions
# ---------------------------------------------------------------------------

def _recent_months(n_months: int, today: date | None = None) -> list[tuple[int, int]]:
    """The last n_months as (year, month) pairs, oldest → newest."""
    today = today or date.today()
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


def get_income_total(db: Session, household_id: str, year: int, month: int) -> float:
    """Sum of income transactions for the month, limited to show_income buckets."""
    start, end = _month_range(year, month)
    total = (
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .join(Bucket, Bucket.id == Transaction.bucket_id)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.income,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Bucket.show_income.is_(True),
        )
        .scalar()
    )
    return round(float(total), 2)


def get_bills_due_month_total(db: Session, household_id: str, year: int, month: int) -> float:
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
        float(occ.amount or occ.bill.amount or 0) for occ in occurrences
    )
    return round(total, 2)


def get_category_breakdown(
    db: Session,
    household_id: str,
    year: int,
    month: int,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    limit: int = 6,
) -> list[dict]:
    """Top spending categories for the month, sorted by amount desc."""
    start, end = _month_range(year, month)
    q = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
    if bucket_type:
        q = q.join(Bucket, Bucket.id == Transaction.bucket_id).filter(Bucket.type == BucketType(bucket_type))
    if bucket_ids:
        q = q.filter(Transaction.bucket_id.in_(bucket_ids))
    txns = q.all()

    totals: dict[str | None, float] = defaultdict(float)
    for t in txns:
        totals[t.category_id] += to_base(t.amount, t.exchange_rate)

    grand = sum(totals.values()) or 1

    # Load category objects
    cat_ids = [cid for cid in totals if cid is not None]
    cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}

    rows = []
    for cat_id, amount in sorted(totals.items(), key=lambda x: -x[1])[:limit]:
        cat = cats.get(cat_id) if cat_id else None
        rows.append({
            "name":   cat.name  if cat else "Uncategorised",
            "icon":   cat.icon  if cat else "📦",
            "color":  cat.color if cat else "#9ca3af",
            "amount": round(amount, 2),
            "pct":    round(amount / grand * 100, 1),
        })
    return rows


def get_monthly_trend(
    db: Session,
    household_id: str,
    n_months: int = 6,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
    paid_by: str | None = None,
) -> list[dict]:
    """Expense totals for the last n_months calendar months (oldest → newest).

    Accepts the insight filters so the trend chart describes the same slice of
    data as the rest of the page; the dashboard calls it without filters.
    """
    today = date.today()
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
    )

    return [
        {
            "label":      date(y, m, 1).strftime("%b"),
            "year":       y,
            "month":      m,
            "total":      round(totals.get((y, m), 0.0), 2),
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
    today = date.today()
    trend = get_monthly_trend(db, household_id, n_months=4)
    past = [m for m in trend if not m["is_current"]]
    if len(past) < 3:
        return {}
    baseline = round(sum(m["total"] for m in past[-3:]) / 3, 2)

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
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= today,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
        .scalar()
    )
    spend_so_far = float(spend_so_far)
    daily_rate  = spend_so_far / days_elapsed if days_elapsed > 0 else 0
    projected   = round(daily_rate * days_in_month, 2)
    delta       = round(projected - baseline, 2)

    return {
        "baseline":        baseline,
        "projected":       projected,
        "trend_delta":     delta,
        "above_trend":     delta > 0,
        "days_elapsed":    days_elapsed,
        "days_in_month":   days_in_month,
        "spend_so_far":    round(spend_so_far, 2),
    }


def get_bucket_budget_status(db: Session, household_id: str, year: int, month: int) -> list[dict]:
    """Spending vs budget for each bucket that has a budget set."""
    start, end = _month_range(year, month)
    buckets = (
        db.query(Bucket)
        .filter(
            Bucket.household_id == household_id,
            Bucket.budget.isnot(None),
            Bucket.status == "active",
        )
        .all()
    )
    if not buckets:
        return []

    bucket_ids = [b.id for b in buckets]
    rows = (
        db.query(Transaction.bucket_id, func.sum(base_amount_expr()))
        .filter(
            Transaction.bucket_id.in_(bucket_ids),
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .group_by(Transaction.bucket_id)
        .all()
    )
    spend_map = {bid: float(total) for bid, total in rows}

    result = []
    for b in buckets:
        spent  = round(spend_map.get(b.id, 0.0), 2)
        budget = float(b.budget)
        pct    = min(round(spent / budget * 100, 1), 100) if budget > 0 else 0
        result.append({
            "bucket":       b,
            "spent":        spent,
            "budget":       budget,
            "pct":          pct,
            "over_budget":  spent > budget,
        })
    result.sort(key=lambda x: -x["pct"])
    return result


def compute_bucket_net(db: Session, bucket_id: str) -> dict[str, float]:
    """Per-user net position inside one bucket, before debt simplification.

    net > 0 → is owed money; net < 0 → owes money. Split out from
    get_bucket_settlement so household-wide settlement can sum raw nets across
    buckets and simplify once, rather than trying to add up already-simplified
    per-bucket transfers (which does not compose).
    """
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.bucket_id == bucket_id,
            Transaction.type == TransactionType.expense,
        )
        .options(joinedload(Transaction.splits))
        .all()
    )
    # Payments already recorded against this bucket.
    recorded = (
        db.query(Settlement).filter(Settlement.bucket_id == bucket_id).all()
    )
    if not txns and not recorded:
        return {}

    # Collect all involved user ids
    user_ids: set[str] = set()
    for t in txns:
        if t.paid_by:
            user_ids.add(t.paid_by)
        for s in t.splits:
            user_ids.add(s.user_id)
    for st in recorded:
        user_ids.update((st.from_user_id, st.to_user_id))

    if len(user_ids) < 2:
        return {}

    # actually_paid[uid] = total they fronted
    # owes[uid] = total they should cover
    actually_paid: dict[str, float] = defaultdict(float)
    owes: dict[str, float] = defaultdict(float)

    for t in txns:
        if t.paid_by:
            actually_paid[t.paid_by] += to_base(t.amount, t.exchange_rate)
        # shares_for() always accounts for the full amount, including any part
        # not covered by explicit splits, so the nets below sum to zero.
        for uid, share in shares_for(t, user_ids).items():
            owes[uid] += share

    net: dict[str, float] = defaultdict(float)
    for uid in user_ids:
        net[uid] = actually_paid[uid] - owes[uid]

    # Offset by payments already made. A settlement from A to B means A has
    # handed over cash, so A owes that much less and B is owed that much less.
    # Without this the computed balance never reset and the same debt was shown
    # forever, however many times it had been paid.
    for st in recorded:
        amount = float(st.amount)
        net[st.from_user_id] += amount
        net[st.to_user_id] -= amount

    return dict(net)


def simplify_debts(db: Session, net: dict[str, float]) -> list[dict]:
    """Turn per-user net positions into the fewest transfers that clear them."""
    net = {uid: round(v, 2) for uid, v in net.items()}
    user_ids = set(net)
    if len(user_ids) < 2:
        return []

    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    # Greedy settlement: pair largest creditor with largest debtor
    creditors = sorted([(uid, v) for uid, v in net.items() if v > 0.005], key=lambda x: -x[1])
    debtors   = sorted([(uid, -v) for uid, v in net.items() if v < -0.005], key=lambda x: -x[1])

    settlements = []
    ci, di = 0, 0
    while ci < len(creditors) and di < len(debtors):
        cuid, camt = creditors[ci]
        duid, damt = debtors[di]
        amount = round(min(camt, damt), 2)
        if amount > 0.01:
            cu = users.get(cuid)
            du = users.get(duid)
            settlements.append({
                # ids are needed to record a payment against this suggestion
                "from_id":    duid,
                "to_id":      cuid,
                "from_name":  du.display_name if du else duid,
                "to_name":    cu.display_name if cu else cuid,
                "from_color": du.avatar_color if du else "#9ca3af",
                "to_color":   cu.avatar_color if cu else "#6366f1",
                "amount":     amount,
            })
        if camt > damt:
            creditors[ci] = (cuid, round(camt - damt, 2))
            di += 1
        elif damt > camt:
            debtors[di] = (duid, round(damt - camt, 2))
            ci += 1
        else:
            ci += 1
            di += 1

    return settlements


def get_bucket_settlement(db: Session, bucket_id: str) -> list[dict]:
    """Who owes whom inside a single bucket (all-time), debt-simplified."""
    return simplify_debts(db, compute_bucket_net(db, bucket_id))


def get_household_settlement(db: Session, household_id: str) -> list[dict]:
    """Who owes whom across the whole household, netted over every bucket.

    Only settlement-enabled buckets count: the equal-split fallback used for
    transactions without explicit splits would otherwise treat every solo
    expense in every bucket as shared, which is not what "settle up" means.

    Per-bucket nets are summed *before* simplification, so a debt in one bucket
    cancels a credit in another and members settle once rather than per bucket.
    """
    buckets = (
        db.query(Bucket.id)
        .filter(Bucket.household_id == household_id, Bucket.enable_settlement.is_(True))
        .all()
    )

    net: dict[str, float] = defaultdict(float)
    for (bucket_id,) in buckets:
        for uid, value in compute_bucket_net(db, bucket_id).items():
            net[uid] += value

    # Household-scoped payments (bucket_id NULL) offset the combined position.
    for st in (
        db.query(Settlement)
        .filter(Settlement.household_id == household_id, Settlement.bucket_id.is_(None))
        .all()
    ):
        amount = float(st.amount)
        net[st.from_user_id] += amount
        net[st.to_user_id] -= amount

    return simplify_debts(db, net)


def record_household_settlement(
    db: Session,
    household_id: str,
    *,
    created_by: str | None = None,
    from_user_id: str | None = None,
    to_user_id: str | None = None,
    amount: float | None = None,
    note: str | None = None,
) -> list[Settlement]:
    """Record household-wide debt payment(s). Callers must commit."""
    outstanding = get_household_settlement(db, household_id)

    if from_user_id and to_user_id:
        if amount is None:
            amount = next(
                (r["amount"] for r in outstanding
                 if r["from_id"] == from_user_id and r["to_id"] == to_user_id),
                None,
            )
            if amount is None:
                return []
        pairs = [(from_user_id, to_user_id, float(amount))]
    else:
        pairs = [(r["from_id"], r["to_id"], r["amount"]) for r in outstanding]

    created = []
    for payer, payee, value in pairs:
        if value <= 0:
            continue
        row = Settlement(
            household_id=household_id,
            bucket_id=None,          # household-scoped
            from_user_id=payer,
            to_user_id=payee,
            amount=value,
            note=note,
            created_by=created_by,
        )
        db.add(row)
        created.append(row)
    return created


def get_household_settlement_history(db: Session, household_id: str, limit: int = 50) -> list[dict]:
    """All recorded payments in the household, newest first, bucket or not."""
    rows = (
        db.query(Settlement)
        .filter(Settlement.household_id == household_id)
        .order_by(Settlement.created_at.desc())
        .limit(limit)
        .all()
    )
    if not rows:
        return []

    ids = {r.from_user_id for r in rows} | {r.to_user_id for r in rows}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()}
    bucket_ids = {r.bucket_id for r in rows if r.bucket_id}
    buckets = (
        {b.id: b for b in db.query(Bucket).filter(Bucket.id.in_(bucket_ids)).all()}
        if bucket_ids else {}
    )

    return [
        {
            "id":          r.id,
            "from_name":   users[r.from_user_id].display_name if r.from_user_id in users else "?",
            "to_name":     users[r.to_user_id].display_name if r.to_user_id in users else "?",
            "from_color":  users[r.from_user_id].avatar_color if r.from_user_id in users else "#9ca3af",
            "to_color":    users[r.to_user_id].avatar_color if r.to_user_id in users else "#6366f1",
            "amount":      round(float(r.amount), 2),
            "note":        r.note,
            "bucket_name": buckets[r.bucket_id].name if r.bucket_id in buckets else None,
            "created_at":  r.created_at,
        }
        for r in rows
    ]


def get_member_balances(db: Session, household_id: str) -> list[dict]:
    """Each member's net position across the household, for a per-person view."""
    net: dict[str, float] = defaultdict(float)
    for (bucket_id,) in (
        db.query(Bucket.id)
        .filter(Bucket.household_id == household_id, Bucket.enable_settlement.is_(True))
        .all()
    ):
        for uid, value in compute_bucket_net(db, bucket_id).items():
            net[uid] += value
    for st in (
        db.query(Settlement)
        .filter(Settlement.household_id == household_id, Settlement.bucket_id.is_(None))
        .all()
    ):
        net[st.from_user_id] += float(st.amount)
        net[st.to_user_id] -= float(st.amount)

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .order_by(User.display_name)
        .all()
    )
    return [
        {
            "user_id": m.id,
            "name":    m.display_name,
            "color":   m.avatar_color,
            "net":     round(net.get(m.id, 0.0), 2),
        }
        for m in members
    ]


def get_bucket_spend_this_month(db: Session, household_id: str, year: int, month: int) -> dict[str, float]:
    """Return {bucket_id: spend} for all active buckets in the given month."""
    start, end = _month_range(year, month)
    rows = (
        db.query(Transaction.bucket_id, func.sum(base_amount_expr()))
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .group_by(Transaction.bucket_id)
        .all()
    )
    return {bid: round(float(total), 2) for bid, total in rows}


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
    today = today or date.today()
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
):
    """Return a base Transaction query pre-filtered by all insight dimensions."""
    q = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
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
        split_subq = (
            db.query(TransactionSplit.transaction_id)
            .filter(TransactionSplit.user_id == paid_by)
            .scalar_subquery()
        )
        q = q.filter(
            or_(
                Transaction.paid_by == paid_by,
                Transaction.id.in_(split_subq),
            )
        )
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
) -> dict:
    """Sum filtered expenses grouped by one dimension, in a single round trip.

    ``group_by`` is "bucket", "category", "month" or "category_month".

    Several insight widgets used to loop and issue one query per bucket / per
    month, which is what made the filter bar feel sluggish: a single filter
    change cost ~38 queries. Everything now aggregates in one pass.

    When ``paid_by`` is set the per-user share has to come from the split rows,
    so the transactions are loaded with their splits and folded in Python;
    otherwise the database does the aggregation.
    """
    q = _build_expense_query(
        db, household_id, start, end,
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
    )

    def key_for(bucket_id, category_id, txn_date):
        if group_by == "bucket":
            return bucket_id
        if group_by == "category":
            return category_id
        if group_by == "month":
            return (txn_date.year, txn_date.month)
        return (category_id, txn_date.year, txn_date.month)

    totals: dict = defaultdict(float)

    if paid_by:
        for t in q.options(joinedload(Transaction.splits)).all():
            totals[key_for(t.bucket_id, t.category_id, t.transaction_date)] += _effective_amount(t, paid_by)
        return dict(totals)

    # No split apportioning needed — let SQL do the grouping.
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
        total = float(row[-1] or 0)
        if group_by == "bucket":
            totals[row[0]] += total
        elif group_by == "category":
            totals[row[0]] += total
        else:
            cat_id, d = row[0], row[1]
            totals[key_for(None, cat_id, d)] += total
    return dict(totals)


def _effective_amount(t: Transaction, paid_by: str | None) -> float:
    """When a paid_by filter is active, return only that user's share of the transaction.
    For split transactions: returns the user's split amount (0.0 if they have no split).
    Without a filter: returns the full transaction amount.
    """
    if paid_by and t.splits:
        for s in t.splits:
            if s.user_id == paid_by:
                return split_to_base(s, t)
        return 0.0
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
    total_spent = sum(_effective_amount(t, paid_by) for t in txns)

    paid_by_acc: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                if paid_by is None or s.user_id == paid_by:
                    paid_by_acc[s.user_id] += split_to_base(s, t)
        elif t.paid_by:
            if paid_by is None or t.paid_by == paid_by:
                paid_by_acc[t.paid_by] += to_base(t.amount, t.exchange_rate)

    members = (
        db.query(User)
        .join(HouseholdMember, HouseholdMember.user_id == User.id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    member_map = {m.id: m for m in members}
    paid_by_detail = {}
    for uid, amount in paid_by_acc.items():
        u = member_map.get(uid)
        if u:
            paid_by_detail[uid] = {
                "name":   u.display_name,
                "color":  u.avatar_color,
                "amount": round(amount, 2),
            }

    return {
        "total_spent": round(total_spent, 2),
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
) -> float:
    """Sum of income transactions in the date range, limited to show_income buckets."""
    q = (
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .join(Bucket, Bucket.id == Transaction.bucket_id)
        .filter(
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
        split_subq = (
            db.query(TransactionSplit.transaction_id)
            .filter(TransactionSplit.user_id == paid_by)
            .scalar_subquery()
        )
        q = q.filter(
            or_(
                Transaction.paid_by == paid_by,
                Transaction.id.in_(split_subq),
            )
        )
    return round(float(q.scalar()), 2)


def get_insights_bills_due(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    bucket_type: str = "",
    bucket_ids: list | None = None,
    category_ids: list | None = None,
) -> float:
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

    total = sum(float(occ.amount or occ.bill.amount or 0) for occ in q.all())
    return round(total, 2)


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

    totals: dict[str | None, float] = defaultdict(float)
    for t in txns:
        totals[t.category_id] += _effective_amount(t, paid_by)

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
            "amount": round(amount, 2),
            "pct":    round(amount / grand * 100, 1),
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
        {"bucket": b, "total": round(totals.get(b.id, 0.0), 2)}
        for b in visible
    ]

    result = [r for r in result if r["total"] > 0]
    result.sort(key=lambda x: -x["total"])
    grand = sum(r["total"] for r in result) or 1
    for r in result:
        r["pct"] = round(r["total"] / grand * 100, 1)
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
    Returns {months: [label,...], series: [{name, color, icon, values: [float,...]}]}
    Only includes the top_n categories by total spend across the period.
    """
    today = date.today()
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

    cat_totals: dict[str | None, float] = defaultdict(float)
    for (cid, _y, _m), amount in grid.items():
        cat_totals[cid] += amount

    # Pick top_n categories
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:top_n]
    top_cat_ids = [cid for cid, _ in top_cats]

    # Load category objects
    cat_objs = {c.id: c for c in db.query(Category).filter(Category.id.in_([c for c in top_cat_ids if c])).all()}

    labels = [date(y, m, 1).strftime("%b") for y, m in month_list]
    monthly_data: dict[str | None, list[float]] = {
        cid: [round(grid.get((cid, y, m), 0.0), 2) for y, m in month_list]
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
        default=0.0,
    )

    return {"months": labels, "series": series, "max_value": round(max_value, 2)}


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
            Transaction.bucket_id.in_(ids),
            Transaction.type == TransactionType.expense,
            # Excluded transactions are left out of every other spend figure;
            # counting them here made a bucket look over budget on the same
            # page that reported it under.
            Transaction.exclude_from_forecast == False,  # noqa: E712
        )
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    rows = q.group_by(Transaction.bucket_id).all()
    spend_map = {bid: float(total) for bid, total in rows}

    result = []
    for b in buckets:
        spent  = round(spend_map.get(b.id, 0.0), 2)
        budget = float(b.budget)
        raw_pct = round(spent / budget * 100, 1) if budget > 0 else 0
        result.append({
            "bucket":      b,
            "spent":       spent,
            "budget":      budget,
            # pct drives the progress bar width and must stay <= 100; pct_actual
            # is the true figure so the UI can show "140% of budget".
            "pct":         min(raw_pct, 100),
            "pct_actual":  raw_pct,
            "remaining":   round(budget - spent, 2),
            "over_budget": spent > budget,
        })
    result.sort(key=lambda x: -x["pct_actual"])
    return result


def record_bucket_settlement(
    db: Session,
    bucket_id: str,
    household_id: str,
    *,
    created_by: str | None = None,
    from_user_id: str | None = None,
    to_user_id: str | None = None,
    amount: float | None = None,
    note: str | None = None,
) -> list[Settlement]:
    """Record debt payment(s) for a bucket and return the rows created.

    With no from/to/amount, settles everything currently outstanding: one row
    per suggested transfer, clearing the bucket. Passing them records a single
    (possibly partial) payment instead.

    Callers must commit.
    """
    outstanding = get_bucket_settlement(db, bucket_id)

    if from_user_id and to_user_id:
        if amount is None:
            # Settle just this pair in full.
            amount = next(
                (r["amount"] for r in outstanding
                 if r["from_id"] == from_user_id and r["to_id"] == to_user_id),
                None,
            )
            if amount is None:
                return []
        pairs = [(from_user_id, to_user_id, float(amount))]
    else:
        pairs = [(r["from_id"], r["to_id"], r["amount"]) for r in outstanding]

    created = []
    for payer, payee, value in pairs:
        if value <= 0:
            continue
        row = Settlement(
            household_id=household_id,
            bucket_id=bucket_id,
            from_user_id=payer,
            to_user_id=payee,
            amount=value,
            note=note,
            created_by=created_by,
        )
        db.add(row)
        created.append(row)
    return created


def get_bucket_settlement_history(db: Session, bucket_id: str) -> list[dict]:
    """Recorded payments for a bucket, newest first."""
    rows = (
        db.query(Settlement)
        .filter(Settlement.bucket_id == bucket_id)
        .order_by(Settlement.created_at.desc())
        .all()
    )
    users = {}
    if rows:
        ids = {r.from_user_id for r in rows} | {r.to_user_id for r in rows}
        users = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()}
    return [
        {
            "id":         r.id,
            "from_name":  users[r.from_user_id].display_name if r.from_user_id in users else "?",
            "to_name":    users[r.to_user_id].display_name if r.to_user_id in users else "?",
            "from_color": users[r.from_user_id].avatar_color if r.from_user_id in users else "#9ca3af",
            "to_color":   users[r.to_user_id].avatar_color if r.to_user_id in users else "#6366f1",
            "amount":     round(float(r.amount), 2),
            "note":       r.note,
            "created_at": r.created_at,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Typed bucket behaviour
#
# BucketType.trip and BucketType.savings previously existed only as filter
# labels with no behaviour attached. These give each one the summary that makes
# the type worth choosing.
# ---------------------------------------------------------------------------

def get_trip_summary(db: Session, bucket: Bucket) -> dict:
    """Trip-shaped view of a bucket: duration, burn rate, per-person totals.

    Falls back to the first and last transaction dates when the trip has no
    explicit range, so an existing trip bucket is useful without being edited.
    """
    if bucket.type != BucketType.trip:
        return {}

    txns = (
        db.query(Transaction)
        .filter(
            Transaction.bucket_id == bucket.id,
            Transaction.type == TransactionType.expense,
        )
        .options(joinedload(Transaction.splits))
        .all()
    )

    total = sum(to_base(t.amount, t.exchange_rate) for t in txns)
    txn_dates = [t.transaction_date for t in txns if t.transaction_date]

    start = bucket.start_date or (min(txn_dates) if txn_dates else None)
    end = bucket.end_date or (max(txn_dates) if txn_dates else None)

    # Inclusive day count: 7 Aug to 15 Aug is 9 days and 8 nights. Both are
    # reported because "how long was the trip" is genuinely ambiguous, and the
    # per-day figure below divides by days.
    days = nights = None
    if start and end:
        days = (end - start).days + 1
        nights = max(days - 1, 0)

    today = date.today()
    status, days_until, days_remaining = "none", None, None
    if bucket.start_date and bucket.end_date:
        if today < bucket.start_date:
            status = "upcoming"
            days_until = (bucket.start_date - today).days
        elif today > bucket.end_date:
            status = "past"
        else:
            status = "active"
            days_remaining = (bucket.end_date - today).days + 1

    # Per-person share, using splits when present and the payer otherwise.
    # shares_for() accounts for the whole amount, so these add up to the trip
    # total even when splits only cover part of an expense.
    per_person: dict[str, float] = defaultdict(float)
    for t in txns:
        for uid, share in shares_for(t).items():
            per_person[uid] += share

    users = {}
    if per_person:
        users = {u.id: u for u in db.query(User).filter(User.id.in_(per_person)).all()}

    return {
        "total":          round(total, 2),
        "start":          start,
        "end":            end,
        "days":           days,
        "nights":         nights,
        "per_day":        round(total / days, 2) if days and days > 0 else None,
        "status":         status,
        "days_until":     days_until,
        "days_remaining": days_remaining,
        "budget":         float(bucket.budget) if bucket.budget else None,
        "remaining":      round(float(bucket.budget) - total, 2) if bucket.budget else None,
        "transaction_count": len(txns),
        "per_person": sorted(
            (
                {
                    "user_id": uid,
                    "name":    users[uid].display_name if uid in users else "Unknown",
                    "color":   users[uid].avatar_color if uid in users else "#9ca3af",
                    "amount":  round(amount, 2),
                }
                for uid, amount in per_person.items()
            ),
            key=lambda r: -r["amount"],
        ),
    }


def get_savings_summary(db: Session, bucket: Bucket) -> dict:
    """Savings-goal view: progress toward goal_amount and what it takes to get there."""
    if bucket.type != BucketType.savings:
        return {}

    balance = get_bucket_balance(db, bucket.id)
    saved = balance["net"]          # income minus expenses in this bucket
    goal = float(bucket.goal_amount) if bucket.goal_amount else None

    result = {
        "saved":     saved,
        "goal":      goal,
        "target_date": bucket.end_date,
        "income":    balance["income"],
        "expenses":  balance["expenses"],
    }
    if not goal or goal <= 0:
        result.update({"pct": None, "remaining": None, "per_month": None,
                       "months_left": None, "on_track": None, "reached": False})
        return result

    remaining = round(goal - saved, 2)
    result["pct"] = round(min(max(saved / goal * 100, 0), 100), 1)
    result["pct_actual"] = round(saved / goal * 100, 1)
    result["remaining"] = remaining
    result["reached"] = saved >= goal

    months_left = None
    if bucket.end_date:
        today = date.today()
        months_left = max(
            (bucket.end_date.year - today.year) * 12 + (bucket.end_date.month - today.month),
            0,
        )
    result["months_left"] = months_left
    result["per_month"] = (
        round(remaining / months_left, 2)
        if months_left and remaining > 0 else None
    )
    # Without a deadline there is nothing to be on track against.
    result["on_track"] = None if not bucket.end_date else (remaining <= 0 or bool(months_left))
    return result


# ---------------------------------------------------------------------------
# Duplicate detection
#
# The most common data-quality problem in a shared household tracker is both
# people logging the same dinner. These surface likely repeats rather than
# blocking them: a genuine repeat (two coffees the same day) is legitimate, so
# the decision stays with the user.
# ---------------------------------------------------------------------------

DUPLICATE_WINDOW_DAYS = 3
DUPLICATE_AMOUNT_TOLERANCE = 0.01


def find_duplicate_candidates(
    db: Session,
    household_id: str,
    *,
    amount,
    transaction_date: date,
    bucket_id: str | None = None,
    exclude_id: str | None = None,
    window_days: int = DUPLICATE_WINDOW_DAYS,
) -> list[Transaction]:
    """Existing transactions that look like the one being entered.

    Same household, near-identical amount, within a few days. Bucket is a
    signal but not a requirement — two people often file the same expense in
    different buckets, which is exactly the case worth catching.
    """
    if amount is None or transaction_date is None:
        return []

    target = float(amount)
    lo, hi = target - DUPLICATE_AMOUNT_TOLERANCE, target + DUPLICATE_AMOUNT_TOLERANCE

    q = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.amount >= lo,
            Transaction.amount <= hi,
            Transaction.transaction_date >= transaction_date - timedelta(days=window_days),
            Transaction.transaction_date <= transaction_date + timedelta(days=window_days),
        )
    )
    if exclude_id:
        q = q.filter(Transaction.id != exclude_id)
    if bucket_id:
        # Same-bucket matches first: a stronger signal than a cross-bucket one.
        q = q.order_by((Transaction.bucket_id == bucket_id).desc(),
                       Transaction.transaction_date.desc())
    else:
        q = q.order_by(Transaction.transaction_date.desc())

    return q.options(joinedload(Transaction.bucket), joinedload(Transaction.paid_by_user)).limit(5).all()


def find_household_duplicates(
    db: Session,
    household_id: str,
    *,
    since_days: int = 90,
    window_days: int = DUPLICATE_WINDOW_DAYS,
) -> list[dict]:
    """Scan recent history for clusters of transactions that look duplicated.

    Groups by rounded amount and walks each group by date, so a pair logged
    days apart is caught without comparing every row to every other row.
    """
    cutoff = date.today() - timedelta(days=since_days)
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Transaction.transaction_date >= cutoff,
        )
        .options(joinedload(Transaction.bucket), joinedload(Transaction.paid_by_user))
        .order_by(Transaction.transaction_date)
        .all()
    )

    by_amount: dict[float, list[Transaction]] = defaultdict(list)
    for t in txns:
        by_amount[round(float(t.amount), 2)].append(t)

    groups: list[dict] = []
    for amount, rows in by_amount.items():
        if len(rows) < 2:
            continue
        cluster: list[Transaction] = []
        for t in rows:
            if cluster and (t.transaction_date - cluster[-1].transaction_date).days > window_days:
                if len(cluster) > 1:
                    groups.append({"amount": amount, "transactions": list(cluster)})
                cluster = []
            cluster.append(t)
        if len(cluster) > 1:
            groups.append({"amount": amount, "transactions": list(cluster)})

    groups.sort(key=lambda g: max(t.transaction_date for t in g["transactions"]), reverse=True)
    return groups


def get_person_summary(
    db: Session,
    household_id: str,
    user_id: str,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    """One member's own financial picture within the household.

    "My share" is what this person is actually responsible for: their split
    amount where the expense is shared, the full amount where they paid an
    unsplit expense. That differs from "what I paid out", and the gap between
    the two is what settlement resolves.
    """
    q = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
        )
        .options(joinedload(Transaction.splits), joinedload(Transaction.bucket))
    )
    if start:
        q = q.filter(Transaction.transaction_date >= start)
    if end:
        q = q.filter(Transaction.transaction_date <= end)
    txns = q.all()

    paid_out = 0.0      # money this person actually fronted
    my_share = 0.0      # what they are responsible for
    shared_count = 0
    by_bucket: dict[str, float] = defaultdict(float)
    by_category: dict[str | None, float] = defaultdict(float)

    for t in txns:
        amount = to_base(t.amount, t.exchange_rate)
        if t.paid_by == user_id:
            paid_out += amount

        # Same accounting as settlement: an expense whose splits do not cover
        # the full amount leaves the remainder with the payer, so "my share"
        # here agrees with the settlement position below.
        share = shares_for(t).get(user_id, 0.0)
        if t.splits and any(s.user_id == user_id for s in t.splits):
            shared_count += 1

        if share:
            my_share += share
            by_bucket[t.bucket_id] += share
            by_category[t.category_id] += share

    buckets = {}
    if by_bucket:
        buckets = {
            b.id: b for b in db.query(Bucket).filter(Bucket.id.in_(by_bucket)).all()
        }
    cat_ids = [c for c in by_category if c]
    categories = (
        {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()}
        if cat_ids else {}
    )

    # Household-wide net position, reusing the settlement maths.
    net = next(
        (b["net"] for b in get_member_balances(db, household_id) if b["user_id"] == user_id),
        0.0,
    )

    return {
        "paid_out":  round(paid_out, 2),
        "my_share":  round(my_share, 2),
        # Positive: fronted more than their share. This is the settlement view.
        "net":       net,
        "shared_count": shared_count,
        "transaction_count": len(txns),
        "by_bucket": sorted(
            (
                {
                    "name":   buckets[bid].name if bid in buckets else "Unknown",
                    "icon":   buckets[bid].icon if bid in buckets else "🪣",
                    "color":  buckets[bid].color if bid in buckets else "#9ca3af",
                    "amount": round(amount, 2),
                }
                for bid, amount in by_bucket.items()
            ),
            key=lambda r: -r["amount"],
        ),
        "by_category": sorted(
            (
                {
                    "name":   categories[cid].name if cid in categories else "Uncategorised",
                    "icon":   categories[cid].icon if cid in categories else "📦",
                    "color":  categories[cid].color if cid in categories else "#9ca3af",
                    "amount": round(amount, 2),
                }
                for cid, amount in by_category.items()
            ),
            key=lambda r: -r["amount"],
        )[:8],
    }
