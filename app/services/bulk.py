"""Bulk changes to transactions, previewed then applied (2c spec §5.3).

run_bulk previews (dry_run) or applies one change to a selection: by ids or
by recurring item (Task 5 adds by filter). The per-row rules live in
app.services.bulk_rules. Apply is one database transaction with the rows
locked, committed once at the end; nothing else here commits.

Fields are written directly, never through update_transaction: its
sync_linked_take drops a take when the method leaves cash, which R14 forbids,
and its Fixed-cost rule is already mirrored by R7 in plan_row.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import combinations

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session, joinedload

from app.core.clock import local_today, utcnow_naive
from app.core.money import quantize
from app.models import (
    BillOccurrence,
    Bucket,
    BucketKind,
    BucketStatus,
    BulkBatch,
    BulkBatchRow,
    CashMovement,
    Category,
    DuplicateDismissal,
    ItemDirection,
    PaymentMethod,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)
from app.schemas import absorb_own_share_cent
from app.services.budgets import bucket_period, bucket_spent
from app.services.bulk_rules import (
    OWN_SHARE,
    SINGLE,
    Changes,
    RowContext,
    RowPlan,
    Skip,
    UndoContext,
    plan_row,
    undo_problem,
)
from app.services.fuel import fuel_category_id
from app.services.insights import _month_range
from app.services.money import base_amount_expr, to_base
from app.services.transaction_filter import TransactionFilter, apply_filter
from app.validators import household_member_ids

BULK_MAX_ROWS = 1000
UNDO_WINDOW = timedelta(hours=24)
NO_BUCKET_NAME = "No bucket (Fixed costs)"
# app.api.recurring's messages for the same refusals (R10), kept identical.
BILL_EVENT_BUCKET = "A recurring item can use a monthly bucket only."
BILL_IN_ITEM = "Income has no bucket, auto-pay or shares."
METHOD_LABELS = {
    "card": "Card",
    "cash": "Cash",
    "apple_pay": "Apple Pay",
    "transfer": "Transfer",
    "other": "Other",
}


@dataclass(frozen=True)
class Selection:
    """Exactly one of: hand-picked ids, the feed's filter, or every active
    payment of a recurring item."""

    ids: list[str] | None = None
    filter: TransactionFilter | None = None
    bill_id: str | None = None

    @property
    def kind(self) -> str:
        if self.ids is not None:
            return "ids"
        return "filter" if self.filter is not None else "bill"


def can_undo(batch: BulkBatch, now: datetime | None = None) -> bool:
    now = now or utcnow_naive()
    return batch.undone_at is None and now <= batch.created_at + UNDO_WINDOW


# ------------------------------------------------------------ request checks


def _check_changes(db: Session, hh: str, ch: Changes) -> Bucket | None:
    """400/404 for the whole request (R1, R3); returns the target bucket."""
    if not ch.fields:
        raise HTTPException(status_code=400, detail="Choose at least one change.")
    target = None
    if ch.has_bucket and ch.bucket_id is not None:
        target = db.get(Bucket, ch.bucket_id)
        if target is None or target.household_id != hh:
            raise HTTPException(status_code=404, detail="Bucket not found.")
        if target.status != BucketStatus.active:
            raise HTTPException(
                status_code=400, detail="That bucket is archived. Choose an active one."
            )
    if ch.has_category and ch.category_id is not None:
        category = db.get(Category, ch.category_id)
        if category is None or category.household_id != hh:
            raise HTTPException(status_code=404, detail="Category not found.")
    if ch.payer is not None and ch.payer.mode == SINGLE:
        if not ch.payer.user_id:
            raise HTTPException(status_code=400, detail="Choose who paid.")
        if ch.payer.user_id not in household_member_ids(db, hh):
            raise HTTPException(status_code=404, detail="Member not found.")
    if ch.payment_method is not None:
        try:
            PaymentMethod(ch.payment_method)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Unknown payment method '{ch.payment_method}'."
            ) from None
    return target


def _bill(db: Session, hh: str, bill_id: str) -> RecurringBill:
    bill = db.query(RecurringBill).filter_by(id=bill_id, household_id=hh).first()
    if bill is None:
        raise HTTPException(status_code=404, detail="Recurring item not found.")
    return bill


def _check_move_bill(
    db: Session, hh: str, select: Selection, ch: Changes, move_bill: bool, target: Bucket | None
) -> RecurringBill | None:
    if not move_bill:
        return None
    if select.bill_id is None or not ch.has_bucket:
        raise HTTPException(
            status_code=400,
            detail="Moving the item needs its payments selected by item and a bucket change.",
        )  # R9
    bill = _bill(db, hh, select.bill_id)
    if bill.direction == ItemDirection.in_.value:
        raise HTTPException(status_code=400, detail=BILL_IN_ITEM)  # R10
    if target is not None and target.kind == BucketKind.event.value:
        raise HTTPException(status_code=400, detail=BILL_EVENT_BUCKET)  # R10
    return bill


# ----------------------------------------------------------------- selection


def _selected_query(db: Session, hh: str, select: Selection) -> Query:
    """Active rows of the household matching a filter or bill selection."""
    q = db.query(Transaction).filter(Transaction.household_id == hh, Transaction.active())
    if select.filter is not None:
        if select.filter.is_empty():
            raise HTTPException(status_code=400, detail="Choose at least one filter.")
        filtered = apply_filter(q, select.filter, db, hh)
        if str(filtered.whereclause) == str(q.whereclause):
            # Belt and braces: a filter that adds no condition would select
            # the whole household.
            raise HTTPException(status_code=400, detail="Choose what to change first.")
        return filtered
    bill = _bill(db, hh, select.bill_id)
    return q.filter(Transaction.recurring_bill_id == bill.id)


def _load(q: Query, lock: bool) -> list[Transaction]:
    q = q.options(joinedload(Transaction.splits)).order_by(
        Transaction.transaction_date.desc(), Transaction.created_at.desc(), Transaction.id
    )
    if lock:
        # OF transactions: a plain FOR UPDATE fails on Postgres here, because
        # joinedload's LEFT OUTER JOIN puts transaction_splits on the nullable
        # side ("FOR UPDATE cannot be applied to the nullable side of an outer
        # join"). SQLite ignores the clause; tests/test_bulk_pg.py proves it.
        q = q.with_for_update(of=Transaction)
    return q.all()


def _select_rows(db: Session, hh: str, select: Selection, *, lock: bool) -> list[Transaction]:
    if select.ids is not None:
        ids = list(dict.fromkeys(i for i in select.ids if i))
        if not ids:
            raise HTTPException(status_code=400, detail="Select at least one transaction.")
        if len(ids) > BULK_MAX_ROWS:
            raise HTTPException(
                status_code=400, detail=f"Select at most {BULK_MAX_ROWS:,} transactions."
            )
        q = db.query(Transaction).filter(Transaction.id.in_(ids), Transaction.household_id == hh)
        rows = _load(q, lock)
        if len(rows) != len(ids):  # R1: missing and foreign look the same
            raise HTTPException(
                status_code=404, detail="Some selected transactions were not found."
            )
        return rows  # own soft-deleted rows stay in; plan_row skips them (R2)
    q = _selected_query(db, hh, select)
    count = q.count()
    if count > BULK_MAX_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"{count:,} transactions match. Narrow the filter to {BULK_MAX_ROWS:,} or fewer.",
        )
    return _load(q, lock)


def _takers(db: Session, txn_ids: list[str]) -> dict[str, str]:
    """Transaction id -> whose wallet its active linked take went to."""
    if not txn_ids:
        return {}
    return dict(
        db.query(CashMovement.transaction_id, CashMovement.user_id)
        .filter(CashMovement.transaction_id.in_(txn_ids), CashMovement.active())
        .all()
    )


def _bucket_names(db: Session, hh: str) -> dict[str, str]:
    return dict(db.query(Bucket.id, Bucket.name).filter(Bucket.household_id == hh).all())


# ------------------------------------------------------------------- preview


def _fixed_costs_spent(db: Session, hh: str, start: date, end: date) -> Decimal:
    """Bucket-less expenses paid for an item (Fixed costs) in [start, end]."""
    return quantize(
        db.query(func.coalesce(func.sum(base_amount_expr()), 0))
        .filter(
            Transaction.household_id == hh,
            Transaction.active(),
            Transaction.type == TransactionType.expense,
            Transaction.bucket_id.is_(None),
            Transaction.recurring_bill_id.isnot(None),
            Transaction.transaction_date >= start,
            Transaction.transaction_date <= end,
        )
        .scalar()
    )


def _bucket_effects(
    db: Session, hh: str, plans: list[tuple[Transaction, RowPlan]], today: date
) -> list[dict]:
    """Every source and target bucket of the changed expenses, with its budget
    figures before and after (the same numbers as 2a Budgets). ``None`` is
    "No bucket (Fixed costs)" this month. Rows outside a bucket's period
    are counted in ``outside_period`` and don't move its figures."""
    moved = [
        (t, t.bucket_id, p.bucket_id)
        for t, p in plans
        if t.type == TransactionType.expense and t.bucket_id != p.bucket_id
    ]
    ids = {b for _, old, new in moved for b in (old, new)}
    effects = []
    for bucket_id in sorted(ids, key=lambda b: (b is None, b or "")):
        if bucket_id is None:
            start, end = _month_range(today.year, today.month)
            name, kind, budget = NO_BUCKET_NAME, "fixed", None
            spent = _fixed_costs_spent(db, hh, start, end)
        else:
            bucket = db.get(Bucket, bucket_id)
            start, end = bucket_period(bucket, today)
            name, kind = bucket.name, bucket.kind
            budget = quantize(bucket.budget) if bucket.budget is not None else None
            spent = bucket_spent(db, bucket, today)
        moved_in = moved_out = Decimal(0)
        outside = 0
        for t, old, new in moved:
            if bucket_id not in (old, new):
                continue
            if (start and t.transaction_date < start) or (end and t.transaction_date > end):
                outside += 1
                continue
            base = to_base(t.amount, t.exchange_rate)
            if new == bucket_id:
                moved_in += base
            else:
                moved_out += base
        effects.append(
            {
                "bucket_id": bucket_id,
                "name": name,
                "kind": kind,
                "budget": budget,
                "period_start": start,
                "period_end": end,
                "spent_before": spent,
                "spent_after": quantize(spent + moved_in - moved_out),
                "moved_in": quantize(moved_in),
                "moved_out": quantize(moved_out),
                "outside_period": outside,
            }
        )
    return effects


def _total(plans, kind: TransactionType) -> Decimal:
    return quantize(
        sum((to_base(t.amount, t.exchange_rate) for t, _ in plans if t.type == kind), Decimal(0))
    )


def _summary(db: Session, hh: str, ch: Changes, n: int, moved_bill: RecurringBill | None) -> str:
    parts = []
    if ch.has_bucket:
        parts.append(f"Bucket → {_bucket_names(db, hh).get(ch.bucket_id) or 'No bucket'}")
    if ch.has_category:
        name = db.get(Category, ch.category_id).name if ch.category_id else "No category"
        parts.append(f"Category → {name}")
    if ch.payer is not None:
        who = (
            "Each their own share"
            if ch.payer.mode == OWN_SHARE
            else db.get(User, ch.payer.user_id).display_name
        )
        parts.append(f"Payer → {who}")
    if ch.payment_method is not None:
        parts.append(f"Method → {METHOD_LABELS.get(ch.payment_method, ch.payment_method)}")
    text = f"{' · '.join(parts)} · {n} {'transaction' if n == 1 else 'transactions'}"
    if moved_bill is not None:
        text += f" · {moved_bill.name} moved"
    return text[:200]


# --------------------------------------------------------------------- apply


def _apply(db: Session, batch: BulkBatch, ch: Changes, plans) -> None:
    """Write the plans and their undo rows. Does not commit."""
    occurrences = {}
    if ch.payer is not None and ch.payer.mode == SINGLE:
        ids = [t.id for t, _ in plans]
        occurrences = {
            o.transaction_id: o
            for o in db.query(BillOccurrence).filter(BillOccurrence.transaction_id.in_(ids))
        }
    for t, p in plans:
        row = BulkBatchRow(batch_id=batch.id, transaction_id=t.id)
        if ch.has_bucket:
            row.old_bucket_id, row.new_bucket_id = t.bucket_id, p.bucket_id
            t.bucket_id = p.bucket_id
        if ch.has_category:
            row.old_category_id, row.new_category_id = t.category_id, p.category_id
            t.category_id = p.category_id
        if ch.payer is not None:
            row.old_paid_by, row.new_paid_by = t.paid_by, p.paid_by
            row.old_payer_mode, row.new_payer_mode = t.payer_mode, p.payer_mode
            if p.absorb_cent:
                absorb_own_share_cent(t.amount, t.splits)  # R17; undo keeps it (U8)
            t.paid_by, t.payer_mode = p.paid_by, p.payer_mode
            occ = occurrences.get(t.id)
            if occ is not None and p.payer_mode == SINGLE:  # R18
                row.occurrence_id, row.old_occurrence_paid_by = occ.id, occ.paid_by
                occ.paid_by = p.paid_by
        if ch.payment_method is not None:
            row.old_payment_method, row.new_payment_method = t.payment_method, p.payment_method
            t.payment_method = p.payment_method
        db.add(row)
    # R12, R20: recurring_bill_id, the entry's transaction_id and match
    # suggestions are never touched.


def run_bulk(
    db: Session,
    *,
    household_id: str,
    user_id: str,
    select: Selection,
    changes: Changes,
    move_bill: bool = False,
    dry_run: bool = True,
    expected_count: int | None = None,
    today: date | None = None,
) -> dict:
    """Preview or apply ``changes`` to ``select``; the BulkResult shape."""
    hh = household_id
    today = today or local_today()
    target = _check_changes(db, hh, changes)
    bill = _check_move_bill(db, hh, select, changes, move_bill, target)
    rows = _select_rows(db, hh, select, lock=not dry_run)
    matched = len(rows)
    if expected_count is not None and select.kind != "ids" and expected_count != matched:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"The selection changed: {matched} now match. Preview again.",
        )

    ctx = RowContext(
        takers=_takers(db, [t.id for t in rows]),
        fuel_category_id=fuel_category_id(db, hh),
        target_takes_income=bool(
            target is not None and target.show_income and target.status == BucketStatus.active
        ),
    )
    plans: list[tuple[Transaction, RowPlan]] = []
    skipped: list[dict] = []
    unchanged = 0
    for t in rows:
        plan = plan_row(t, changes, ctx)
        if isinstance(plan, Skip):
            skipped.append({"id": t.id, "code": plan.code, "reason": plan.reason})
        elif plan.changed:
            plans.append((t, plan))
        else:
            unchanged += 1

    names = _bucket_names(db, hh)
    bill_moves = bill is not None and bill.bucket_id != changes.bucket_id
    total_out = _total(plans, TransactionType.expense)
    total_in = _total(plans, TransactionType.income)
    result = {
        "dry_run": dry_run,
        "batch_id": None,
        "matched": matched,
        "changed": len(plans),
        "unchanged": unchanged,
        "total_out": total_out,
        "total_in": total_in,
        "skipped": skipped,
        "buckets": _bucket_effects(db, hh, plans, today) if changes.has_bucket else [],
        "bill": None
        if bill is None
        else {
            "id": bill.id,
            "name": bill.name,
            "bucket_before": names.get(bill.bucket_id),
            "bucket_after": names.get(changes.bucket_id),
        },
        "undo_until": None,
    }
    if dry_run or not (plans or bill_moves):
        db.rollback()  # R21: nothing was written; release any locks
        return result

    now = utcnow_naive()
    batch = BulkBatch(
        household_id=hh,
        created_by=user_id,
        created_at=now,
        selection=select.kind,
        fields=",".join(changes.fields),
        summary=_summary(db, hh, changes, len(plans), bill if bill_moves else None),
        row_count=len(plans),
        total_out=total_out,
        total_in=total_in,
        bill_id=bill.id if bill is not None else None,
        bill_bucket_old=bill.bucket_id if bill is not None else None,
        bill_bucket_new=changes.bucket_id if bill is not None else None,
        bill_moved=bill_moves,
    )
    db.add(batch)
    db.flush()
    _apply(db, batch, changes, plans)
    if bill_moves:
        bill.bucket_id = changes.bucket_id  # R11: entries read the item's bucket
    db.commit()
    result.update(batch_id=batch.id, undo_until=now + UNDO_WINDOW)
    return result


# ---------------------------------------------------------------------- undo


def _restore(db: Session, t: Transaction, row: BulkBatchRow, fields: tuple[str, ...]) -> None:
    if "bucket" in fields:
        t.bucket_id = row.old_bucket_id
    if "category" in fields:
        t.category_id = row.old_category_id
    if "payer" in fields:
        t.paid_by, t.payer_mode = row.old_paid_by, row.old_payer_mode
        if row.occurrence_id is not None:
            occ = db.get(BillOccurrence, row.occurrence_id)
            if occ is not None and occ.transaction_id == t.id:
                occ.paid_by = row.old_occurrence_paid_by  # U6
    if "method" in fields:
        t.payment_method = row.old_payment_method
    # U8: the own-share cent stays where R17 put it.


def undo_batch(db: Session, *, household_id: str, user_id: str, batch_id: str) -> dict:
    """Restore every row of a batch that still holds the batch's values.
    The batch row is locked, so of two concurrent undos one gets 409."""
    hh = household_id
    batch = (
        db.query(BulkBatch)
        .filter(BulkBatch.id == batch_id, BulkBatch.household_id == hh)
        .with_for_update()
        .first()
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="Bulk change not found.")
    if batch.undone_at is not None:
        raise HTTPException(status_code=409, detail="This change was already undone.")
    now = utcnow_naive()
    if not can_undo(batch, now):
        raise HTTPException(status_code=409, detail="Changes can be undone for 24 hours.")

    fields = tuple(f for f in batch.fields.split(",") if f)
    rows = db.query(BulkBatchRow).filter(BulkBatchRow.batch_id == batch.id).all()
    ids = [r.transaction_id for r in rows]
    txns = {t.id: t for t in _load(db.query(Transaction).filter(Transaction.id.in_(ids)), True)}
    ctx = UndoContext(
        takers=_takers(db, ids),
        bucket_ids=set(_bucket_names(db, hh)),
        category_ids={c for (c,) in db.query(Category.id).filter(Category.household_id == hh)},
        member_ids=household_member_ids(db, hh),
    )
    restored, skipped = 0, []
    for row in rows:
        t = txns[row.transaction_id]
        problem = undo_problem(t, row, fields, ctx)
        if problem is not None:
            skipped.append({"id": t.id, "code": problem.code, "reason": problem.reason})
            continue
        _restore(db, t, row, fields)
        row.restored = True
        restored += 1

    bill_restored = False
    if batch.bill_moved and batch.bill_id is not None:  # U7
        bill = db.get(RecurringBill, batch.bill_id)
        old_exists = batch.bill_bucket_old is None or batch.bill_bucket_old in ctx.bucket_ids
        if bill is not None and bill.bucket_id == batch.bill_bucket_new and old_exists:
            bill.bucket_id = batch.bill_bucket_old
            bill_restored = True

    batch.undone_at, batch.undone_by = now, user_id  # set even when rows are skipped
    db.commit()
    return {"restored": restored, "skipped": skipped, "bill_restored": bill_restored}


# ------------------------------------------------------------- recent, history


def _user_names(db: Session, ids) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.query(User.id, User.display_name).filter(User.id.in_(ids)).all())


def recent_batches(db: Session, household_id: str, limit: int = 10) -> list[dict]:
    batches = (
        db.query(BulkBatch)
        .filter(BulkBatch.household_id == household_id)
        .order_by(BulkBatch.created_at.desc(), BulkBatch.id)
        .limit(limit)
        .all()
    )
    names = _user_names(db, (b.created_by for b in batches))
    now = utcnow_naive()
    return [
        {
            "id": b.id,
            "created_at": b.created_at,
            "created_by": names.get(b.created_by),
            "summary": b.summary,
            "row_count": b.row_count,
            "undone_at": b.undone_at,
            "can_undo": can_undo(b, now),
        }
        for b in batches
    ]


def bulk_history_events(db: Session, household_id: str, txn_id: str) -> list[dict]:
    """The bulk changes (and their undos) that touched one transaction."""
    pairs = (
        db.query(BulkBatchRow, BulkBatch)
        .join(BulkBatch, BulkBatchRow.batch_id == BulkBatch.id)
        .filter(BulkBatchRow.transaction_id == txn_id, BulkBatch.household_id == household_id)
        .order_by(BulkBatch.created_at)
        .all()
    )
    if not pairs:
        return []
    buckets = _bucket_names(db, household_id)
    categories = dict(
        db.query(Category.id, Category.name).filter(Category.household_id == household_id).all()
    )
    users = _user_names(
        db,
        {r.old_paid_by for r, _ in pairs}
        | {r.new_paid_by for r, _ in pairs}
        | {b.created_by for _, b in pairs}
        | {b.undone_by for _, b in pairs},
    )

    def bucket(v):
        return buckets.get(v, "a deleted bucket") if v else "No bucket"

    def category(v):
        return categories.get(v, "a deleted category") if v else "No category"

    def payer(user_id, mode):
        if mode == OWN_SHARE:
            return "Each their own share"
        return users.get(user_id, "a former member") if user_id else "No payer"

    now = utcnow_naive()
    events = []
    for row, batch in pairs:
        parts = []
        for field in batch.fields.split(","):
            if field == "bucket":
                parts.append(f"Bucket: {bucket(row.old_bucket_id)} → {bucket(row.new_bucket_id)}")
            elif field == "category":
                parts.append(
                    f"Category: {category(row.old_category_id)} → {category(row.new_category_id)}"
                )
            elif field == "payer":
                parts.append(
                    f"Payer: {payer(row.old_paid_by, row.old_payer_mode)} → "
                    f"{payer(row.new_paid_by, row.new_payer_mode)}"
                )
            elif field == "method":
                parts.append(
                    f"Method: {METHOD_LABELS.get(row.old_payment_method, row.old_payment_method)}"
                    f" → {METHOD_LABELS.get(row.new_payment_method, row.new_payment_method)}"
                )
        events.append(
            {
                "at": batch.created_at,
                "kind": "bulk_change",
                "by": users.get(batch.created_by),
                "text": "; ".join(parts),
                "batch_id": batch.id,
                "can_undo": can_undo(batch, now),
            }
        )
        if batch.undone_at is not None:
            events.append(
                {
                    "at": batch.undone_at,
                    "kind": "bulk_undone",
                    "by": users.get(batch.undone_by),
                    "text": "Change undone" if row.restored else "Undo left this one as it was",
                    "batch_id": batch.id,
                    "can_undo": False,
                }
            )
    return events


# ---------------------------------------------------------------- duplicates


def dismiss_duplicates(db: Session, *, household_id: str, user_id: str, ids: list[str]) -> None:
    """ "Keep both": store every pair of ``ids`` (smaller id first), once, for
    the whole household. Every id must be an active transaction of it (404)."""
    wanted = sorted(set(ids))
    if len(wanted) < 2:
        raise HTTPException(status_code=400, detail="Choose at least two transactions.")
    found = {
        i
        for (i,) in db.query(Transaction.id).filter(
            Transaction.id.in_(wanted),
            Transaction.household_id == household_id,
            Transaction.active(),
        )
    }
    if len(found) != len(wanted):
        raise HTTPException(status_code=404, detail="Transaction not found")
    # Twice at most: if another member's "Keep both" stored one of these pairs
    # between our read and our commit, read again and add only what's missing,
    # so no pair of a three-row group is lost to the race.
    for _attempt in range(2):
        existing = set(
            db.query(DuplicateDismissal.first_id, DuplicateDismissal.second_id)
            .filter(
                DuplicateDismissal.first_id.in_(wanted), DuplicateDismissal.second_id.in_(wanted)
            )
            .all()
        )
        for first, second in combinations(wanted, 2):
            if (first, second) not in existing:
                db.add(
                    DuplicateDismissal(
                        household_id=household_id,
                        first_id=first,
                        second_id=second,
                        created_by=user_id,
                    )
                )
        try:
            db.commit()
            return
        except IntegrityError:
            db.rollback()
