"""
Bucket and household settlement calculations.
"""
import hashlib
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.money import ZERO, quantize, to_decimal
from app.models import (
    Bucket,
    HouseholdMember,
    PayerMode,
    Settlement,
    Transaction,
    TransactionSplit,
    TransactionType,
    User,
)
from app.services.money import base_amount_expr, paid_for, shares_for


class SettlementChanged(Exception):
    """The outstanding transfers differ from the ones the client displayed."""


def settlement_fingerprint(rows: list[dict]) -> str:
    """Stable short hash of the suggested transfers a page/client displayed.

    Settle-up forms post it back; the server recomputes and refuses when it no
    longer matches, so a double submit (or a stale tab) cannot record the same
    payment twice and reverse the debt.
    """
    parts = sorted(f"{r['from_id']}|{r['to_id']}|{quantize(to_decimal(r['amount']))}" for r in rows)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]


def _takes_part():
    """Filter: expenses that can create a debt in settle-up (see compute_bucket_net)."""
    return (
        Transaction.active(),
        Transaction.type == TransactionType.expense,
        Transaction.exclude_from_settlement.is_(False),
        or_(Transaction.paid_by.isnot(None), Transaction.payer_mode == PayerMode.own_share.value),
    )


def bucket_participants(db: Session, bucket_ids) -> dict[str, set[str]]:
    """Who takes part in settle-up in each bucket: every payer and split member
    of an expense that can create a debt, and both sides of every payment
    recorded against the bucket. An unsplit expense there is shared equally
    between them (see :func:`compute_bucket_net`)."""
    bucket_ids = list(bucket_ids)
    out: dict[str, set[str]] = defaultdict(set)
    if not bucket_ids:
        return out
    payers = (
        db.query(Transaction.bucket_id, Transaction.paid_by)
        .filter(Transaction.bucket_id.in_(bucket_ids), Transaction.paid_by.isnot(None),
                *_takes_part())
        .distinct()
    )
    split_users = (
        db.query(Transaction.bucket_id, TransactionSplit.user_id)
        .join(TransactionSplit, TransactionSplit.transaction_id == Transaction.id)
        .filter(Transaction.bucket_id.in_(bucket_ids), *_takes_part())
        .distinct()
    )
    for bid, uid in [*payers.all(), *split_users.all()]:
        out[bid].add(uid)
    for bid, from_id, to_id in (
        db.query(Settlement.bucket_id, Settlement.from_user_id, Settlement.to_user_id)
        .filter(Settlement.bucket_id.in_(bucket_ids))
        .all()
    ):
        out[bid].update((from_id, to_id))
    return out


def settlement_members(db: Session, household_id: str) -> dict[str, set[str]]:
    """``{bucket_id: members}`` for the household's settlement-enabled buckets
    where settle-up has someone to settle with (two or more participants).

    The members an unsplit expense in that bucket is shared between, which
    insights, /me and the trip summary use too (``member_ids`` of
    :func:`app.services.money.shares_for`, via
    :func:`app.services.money.shared_between`), so every view charges such an
    expense the way settle-up does.
    """
    buckets = [
        bid for (bid,) in db.query(Bucket.id).filter(
            Bucket.household_id == household_id, Bucket.enable_settlement.is_(True),
        )
    ]
    return {
        bid: members for bid, members in bucket_participants(db, buckets).items()
        if len(members) >= 2
    }


def compute_bucket_net(db: Session, bucket_id: str) -> dict[str, Decimal]:
    """Per-user net position inside one bucket, before debt simplification.

    net > 0 → is owed money; net < 0 → owes money. Split out from
    get_bucket_settlement so household-wide settlement can sum raw nets across
    buckets and simplify once, rather than trying to add up already-simplified
    per-bucket transfers (which does not compose).
    """
    txns = (
        db.query(Transaction)
        .filter(
            Transaction.active(),
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

    # Only expenses that can actually create a debt take part. An expense with
    # no payer recorded has nobody to owe: charging its shares to members while
    # crediting nobody invented a phantom creditor outside the household, so
    # both members showed as owing money to no one. Skipping it leaves the
    # spending in every other report and only keeps it out of settle-up.
    # Own-share expenses have no single payer but are fully paid, so they stay
    # (and net to zero: everyone paid exactly their share).
    txns = [
        t for t in txns
        if not t.exclude_from_settlement
        and (t.paid_by or t.payer_mode == PayerMode.own_share.value)
    ]

    # Everyone involved: payers, split members and settlement parties.
    user_ids = bucket_participants(db, [bucket_id]).get(bucket_id, set())

    if len(user_ids) < 2:
        return {}

    # actually_paid[uid] = total they fronted
    # owes[uid] = total they should cover
    actually_paid: dict[str, Decimal] = defaultdict(Decimal)
    owes: dict[str, Decimal] = defaultdict(Decimal)

    for t in txns:
        for uid, paid in paid_for(t, user_ids).items():
            actually_paid[uid] += paid
        # shares_for() always accounts for the full amount, including any part
        # not covered by explicit splits, so the nets below sum to zero.
        for uid, share in shares_for(t, user_ids).items():
            owes[uid] += share

    net: dict[str, Decimal] = defaultdict(Decimal)
    for uid in user_ids:
        net[uid] = actually_paid[uid] - owes[uid]

    # Offset by payments already made. A settlement from A to B means A has
    # handed over cash, so A owes that much less and B is owed that much less.
    # Without this the computed balance never reset and the same debt was shown
    # forever, however many times it had been paid.
    for st in recorded:
        amount = to_decimal(st.amount)
        net[st.from_user_id] += amount
        net[st.to_user_id] -= amount

    return dict(net)


def simplify_debts(db: Session, net: dict[str, Decimal]) -> list[dict]:
    """Turn per-user net positions into the fewest transfers that clear them."""
    net = {uid: quantize(v) for uid, v in net.items()}
    user_ids = set(net)
    if len(user_ids) < 2:
        return []

    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    # Greedy settlement: pair largest creditor with largest debtor
    creditors = sorted([(uid, v) for uid, v in net.items() if v > Decimal("0.005")], key=lambda x: -x[1])
    debtors   = sorted([(uid, -v) for uid, v in net.items() if v < Decimal("-0.005")], key=lambda x: -x[1])

    settlements = []
    ci, di = 0, 0
    while ci < len(creditors) and di < len(debtors):
        cuid, camt = creditors[ci]
        duid, damt = debtors[di]
        amount = quantize(min(camt, damt))
        if amount > Decimal("0.01"):
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
            creditors[ci] = (cuid, quantize(camt - damt))
            di += 1
        elif damt > camt:
            debtors[di] = (duid, quantize(damt - camt))
            ci += 1
        else:
            ci += 1
            di += 1

    return settlements


def get_bucket_settlement(db: Session, bucket_id: str) -> list[dict]:
    """Who owes whom inside a single bucket (all-time), debt-simplified."""
    return simplify_debts(db, compute_bucket_net(db, bucket_id))


def get_settlement_exclusions(db: Session, household_id: str) -> dict:
    """Spending inside settlement-enabled buckets that settle-up ignores.

    Two reasons an expense sits out: no payer was recorded (there is nobody to
    owe, so it cannot produce a debt), or it was explicitly excluded. Both are
    invisible in the balances themselves, and an unexplained gap between "we
    spent this" and "we owe this" is exactly what makes settle-up look broken.
    """
    rows = (
        db.query(
            Transaction.exclude_from_settlement,
            func.count(Transaction.id),
            func.sum(base_amount_expr()),
        )
        .join(Bucket, Bucket.id == Transaction.bucket_id)
        .filter(
            Transaction.active(),
            Transaction.household_id == household_id,
            Transaction.type == TransactionType.expense,
            Bucket.enable_settlement.is_(True),
            or_(
                Transaction.missing_payer(),
                Transaction.exclude_from_settlement.is_(True),
            ),
        )
        .group_by(Transaction.exclude_from_settlement)
        .all()
    )

    out = {
        "no_payer_count": 0, "no_payer_total": ZERO,
        "excluded_count": 0, "excluded_total": ZERO,
    }
    for excluded, count, total in rows:
        prefix = "excluded" if excluded else "no_payer"
        out[f"{prefix}_count"] = int(count or 0)
        out[f"{prefix}_total"] = quantize(total or 0)
    out["any"] = bool(out["no_payer_count"] or out["excluded_count"])
    return out


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

    net: dict[str, Decimal] = defaultdict(Decimal)
    for (bucket_id,) in buckets:
        for uid, value in compute_bucket_net(db, bucket_id).items():
            net[uid] += value

    # Household-scoped payments (bucket_id NULL) offset the combined position.
    for st in (
        db.query(Settlement)
        .filter(Settlement.household_id == household_id, Settlement.bucket_id.is_(None))
        .all()
    ):
        amount = to_decimal(st.amount)
        net[st.from_user_id] += amount
        net[st.to_user_id] -= amount

    return simplify_debts(db, net)


def record_household_settlement(
    db: Session,
    household_id: str,
    *,
    bucket_id: str | None = None,
    created_by: str | None = None,
    from_user_id: str | None = None,
    to_user_id: str | None = None,
    amount: Decimal | None = None,
    note: str | None = None,
    expected: str | None = None,
) -> list[Settlement]:
    """Record debt payment(s) and return the rows created. Callers must commit.

    Household-wide by default; pass ``bucket_id`` to settle a single bucket's
    balance instead (the rows are then recorded against that bucket).

    With no from/to/amount, settles everything currently outstanding: one row
    per suggested transfer. Passing them records a single (possibly partial)
    payment instead.

    ``expected`` is the ``settlement_fingerprint`` of the transfers the client
    displayed; when given and the outstanding transfers no longer match,
    ``SettlementChanged`` is raised and nothing is recorded.
    """
    outstanding = (
        get_bucket_settlement(db, bucket_id) if bucket_id
        else get_household_settlement(db, household_id)
    )
    if expected is not None and settlement_fingerprint(outstanding) != expected.strip():
        raise SettlementChanged("Balances changed since this page was loaded — review and try again.")

    if from_user_id and to_user_id:
        if amount is None:
            amount = next(
                (r["amount"] for r in outstanding
                 if r["from_id"] == from_user_id and r["to_id"] == to_user_id),
                None,
            )
            if amount is None:
                return []
        pairs = [(from_user_id, to_user_id, to_decimal(amount))]
    else:
        pairs = [(r["from_id"], r["to_id"], r["amount"]) for r in outstanding]

    created = []
    for payer, payee, value in pairs:
        if value <= 0:
            continue
        row = Settlement(
            household_id=household_id,
            bucket_id=bucket_id,     # None: household-scoped
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
            "amount":      quantize(r.amount),
            "note":        r.note,
            "bucket_name": buckets[r.bucket_id].name if r.bucket_id in buckets else None,
            "created_at":  r.created_at,
        }
        for r in rows
    ]


def get_member_balances(db: Session, household_id: str) -> list[dict]:
    """Each member's net position across the household, for a per-person view."""
    net: dict[str, Decimal] = defaultdict(Decimal)
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
        net[st.from_user_id] += to_decimal(st.amount)
        net[st.to_user_id] -= to_decimal(st.amount)

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
            "net":     quantize(net.get(m.id, ZERO)),
        }
        for m in members
    ]


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
            "amount":     quantize(r.amount),
            "note":       r.note,
            "created_at": r.created_at,
        }
        for r in rows
    ]
