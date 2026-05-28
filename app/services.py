"""
Balance and summary calculations for dashboards and bucket views.
"""
from datetime import date, timedelta
from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, case

from app.models import (
    Transaction, TransactionSplit, TransactionType,
    BillOccurrence, OccurrenceStatus, RecurringBill,
    User, HouseholdMember, Bucket, BucketType, BucketStatus, Category, Household
)


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

    total_spent = sum(float(t.amount) for t in txns)

    # Amount paid by each user — use splits when present, else paid_by
    paid_by: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += float(s.amount)
        elif t.paid_by:
            paid_by[t.paid_by] += float(t.amount)

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

    total_spent = sum(float(t.amount) for t in txns)

    # Amount paid by each user — use splits when present, else paid_by
    paid_by: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += float(s.amount)
        elif t.paid_by:
            paid_by[t.paid_by] += float(t.amount)

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
    total_spent = sum(float(t.amount) for t in txns)

    paid_by: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by[s.user_id] += float(s.amount)
        elif t.paid_by:
            paid_by[t.paid_by] += float(t.amount)

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
        func.sum(case((Transaction.type == TransactionType.income, Transaction.amount), else_=0)), 0
    )
    expense_sum = func.coalesce(
        func.sum(case((Transaction.type == TransactionType.expense, Transaction.amount), else_=0)), 0
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
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
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
        .filter(
            RecurringBill.household_id == household_id,
            BillOccurrence.due_date >= start,
            BillOccurrence.due_date <= end,
        )
        .all()
    )
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
        totals[t.category_id] += float(t.amount)

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


def get_monthly_trend(db: Session, household_id: str, n_months: int = 6) -> list[dict]:
    """Expense totals for the last n_months calendar months (oldest → newest)."""
    today = date.today()
    results = []
    for i in range(n_months - 1, -1, -1):
        # Go back i months from current
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start, end = _month_range(y, m)
        total = (
            db.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(
                Transaction.household_id == household_id,
                Transaction.type == TransactionType.expense,
                Transaction.transaction_date >= start,
                Transaction.transaction_date <= end,
                Transaction.exclude_from_forecast == False,  # noqa: E712
            )
            .scalar()
        )
        results.append({
            "label":      date(y, m, 1).strftime("%b"),
            "year":       y,
            "month":      m,
            "total":      round(float(total), 2),
            "is_current": (y == today.year and m == today.month),
        })
    return results


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
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
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
        db.query(Transaction.bucket_id, func.sum(Transaction.amount))
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


def get_bucket_settlement(db: Session, bucket_id: str) -> list[dict]:
    """
    Who owes whom inside a single bucket (all-time).
    Uses greedy debt simplification.
    Returns [] if the bucket has only one payer or no transactions.
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
    if not txns:
        return []

    # Collect all involved user ids
    user_ids: set[str] = set()
    for t in txns:
        if t.paid_by:
            user_ids.add(t.paid_by)
        for s in t.splits:
            user_ids.add(s.user_id)

    if len(user_ids) < 2:
        return []

    # actually_paid[uid] = total they fronted
    # owes[uid] = total they should cover
    actually_paid: dict[str, float] = defaultdict(float)
    owes: dict[str, float] = defaultdict(float)

    for t in txns:
        if t.paid_by:
            actually_paid[t.paid_by] += float(t.amount)
        if t.splits:
            for s in t.splits:
                owes[s.user_id] += float(s.amount)
        else:
            # No splits → split equally among all members who appear in this bucket
            share = float(t.amount) / len(user_ids)
            for uid in user_ids:
                owes[uid] += share

    # net[uid] > 0 → is owed money; net[uid] < 0 → owes money
    net: dict[str, float] = defaultdict(float)
    for uid in user_ids:
        net[uid] = round(actually_paid[uid] - owes[uid], 2)

    # Load user info
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


def get_bucket_spend_this_month(db: Session, household_id: str, year: int, month: int) -> dict[str, float]:
    """Return {bucket_id: spend} for all active buckets in the given month."""
    start, end = _month_range(year, month)
    rows = (
        db.query(Transaction.bucket_id, func.sum(Transaction.amount))
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
        q = q.filter(Transaction.paid_by == paid_by)
    return q


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
    total_spent = sum(float(t.amount) for t in txns)

    paid_by_acc: dict[str, float] = defaultdict(float)
    for t in txns:
        if t.splits:
            for s in t.splits:
                paid_by_acc[s.user_id] += float(s.amount)
        elif t.paid_by:
            paid_by_acc[t.paid_by] += float(t.amount)

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


def get_insights_income(db: Session, household_id: str, start: date | None, end: date | None) -> float:
    """Sum of income transactions in the date range, limited to show_income buckets."""
    q = (
        db.query(func.coalesce(func.sum(Transaction.amount), 0))
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
    return round(float(q.scalar()), 2)


def get_insights_bills_due(db: Session, household_id: str, start: date | None, end: date | None) -> float:
    """Sum of bill occurrence amounts due within the date range."""
    q = (
        db.query(BillOccurrence)
        .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
        .filter(RecurringBill.household_id == household_id)
    )
    if start:
        q = q.filter(BillOccurrence.due_date >= start)
    if end:
        q = q.filter(BillOccurrence.due_date <= end)
    occurrences = q.all()
    total = sum(float(occ.amount or occ.bill.amount or 0) for occ in occurrences)
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
    txns = q.all()

    totals: dict[str | None, float] = defaultdict(float)
    for t in txns:
        totals[t.category_id] += float(t.amount)

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

    result = []
    for b in buckets:
        if bucket_type and b.type.value != bucket_type:
            continue
        q = _build_expense_query(
            db, household_id, start, end,
            bucket_ids=[b.id],
            category_ids=category_ids,
            paid_by=paid_by,
        )
        total = sum(float(t.amount) for t in q.all())
        result.append({
            "bucket": b,
            "total":  round(total, 2),
        })

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

    # Build month list (oldest → newest)
    month_list: list[tuple[int, int]] = []
    for i in range(n_months - 1, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_list.append((y, m))

    # Determine which categories appear at all
    all_q = _build_expense_query(
        db, household_id,
        start=_month_range(month_list[0][0], month_list[0][1])[0],
        end=_month_range(month_list[-1][0], month_list[-1][1])[1],
        bucket_type=bucket_type,
        bucket_ids=bucket_ids,
        category_ids=category_ids,
        paid_by=paid_by,
    )
    all_txns = all_q.all()
    cat_totals: dict[str | None, float] = defaultdict(float)
    for t in all_txns:
        cat_totals[t.category_id] += float(t.amount)

    # Pick top_n categories
    top_cats = sorted(cat_totals.items(), key=lambda x: -x[1])[:top_n]
    top_cat_ids = [cid for cid, _ in top_cats]

    # Load category objects
    cat_objs = {c.id: c for c in db.query(Category).filter(Category.id.in_([c for c in top_cat_ids if c])).all()}

    # Build monthly data per category
    monthly_data: dict[str | None, list[float]] = {cid: [] for cid in top_cat_ids}
    labels = []

    for y, m in month_list:
        start, end = _month_range(y, m)
        labels.append(date(y, m, 1).strftime("%b"))
        month_txns = _build_expense_query(
            db, household_id, start, end,
            bucket_type=bucket_type,
            bucket_ids=bucket_ids,
            paid_by=paid_by,
        ).all()
        month_by_cat: dict[str | None, float] = defaultdict(float)
        for t in month_txns:
            if t.category_id in top_cat_ids:
                month_by_cat[t.category_id] += float(t.amount)
        for cid in top_cat_ids:
            monthly_data[cid].append(round(month_by_cat[cid], 2))

    series = []
    for cid in top_cat_ids:
        cat = cat_objs.get(cid) if cid else None
        series.append({
            "name":   cat.name  if cat else "Uncategorised",
            "icon":   cat.icon  if cat else "📦",
            "color":  cat.color if cat else "#9ca3af",
            "values": monthly_data[cid],
        })

    return {"months": labels, "series": series}


def get_insights_budget_status(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
) -> list[dict]:
    """Spending vs budget for each bucket with a budget, over a date range."""
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
    q = (
        db.query(Transaction.bucket_id, func.sum(Transaction.amount))
        .filter(
            Transaction.bucket_id.in_(bucket_ids),
            Transaction.type == TransactionType.expense,
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
        pct    = min(round(spent / budget * 100, 1), 100) if budget > 0 else 0
        result.append({
            "bucket":      b,
            "spent":       spent,
            "budget":      budget,
            "pct":         pct,
            "over_budget": spent > budget,
        })
    result.sort(key=lambda x: -x["pct"])
    return result
