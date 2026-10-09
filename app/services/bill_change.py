"""When did a recurring bill change? (Phase A spec §3.4)

One rule, used by the history endpoint, the Bills list and the daily alert.
``entry_points`` reads an item's done entries; ``assess`` is pure and judges the
latest one against a baseline: the same month a year earlier when there is one
(a seasonal bill is compared with its own season), else the median of the three
entries before it. Both gates must pass, and a usage reading, when every entry
involved has one, says whether the usage or the price per unit moved.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from sqlalchemy.orm import Session

from app.core.money import quantize
from app.models import (
    BillOccurrence,
    ItemDirection,
    OccurrenceStatus,
    RecurringBill,
    RuleKind,
    Transaction,
)
from app.services.money import to_base

PCT_GATE = Decimal("20")  # |change| in percent, at least
ABS_GATE = Decimal("10")  # |change| in household currency, at least
RECENT_N = 3  # entries before the latest that form the "recent" baseline
ALERT_WINDOW_DAYS = 35  # the latest entry must be this recent to alert (list, Home, push)

_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class Point:
    """One done entry of an item."""

    entry_id: str
    due_date: date
    amount: Decimal  # the entry amount, in the household currency
    usage: Decimal | None
    transaction_id: str | None


@dataclass(frozen=True)
class Change:
    """The latest done entry against its baseline (fields as in spec §3.4)."""

    entry_id: str
    amount: Decimal
    usual: Decimal
    basis: str  # "last_year" | "recent"
    delta: Decimal
    pct: int
    direction: str  # "up" | "down"
    reason: str | None  # "usage" | "price"
    reason_pct: int | None


def _whole(value: Decimal) -> int:
    """A percentage at the edge: a whole number, half rounded away from zero."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def is_monthly(item: RecurringBill) -> bool:
    """True when the item's rule gives at most one entry a month (not weekly)."""
    return item.rule_kind != RuleKind.weekly.value


# ---------------------------------------------------------------- reading


def entry_points_by_item(db: Session, items: Iterable[RecurringBill]) -> dict[str, list[Point]]:
    """Each item's done entries, oldest first. Two queries however many items.

    The amount is the entry amount: ``occ.amount``; else the linked
    transaction's amount converted to base (the whole payment, never one
    member's share); else the item's amount. An entry with none of them has
    nothing to compare and is left out.
    """
    by_id = {i.id: i for i in items}
    out: dict[str, list[Point]] = {i: [] for i in by_id}
    if not by_id:
        return out
    occs = (
        db.query(BillOccurrence)
        .filter(
            BillOccurrence.bill_id.in_(list(by_id)),
            BillOccurrence.status == OccurrenceStatus.paid,
        )
        .order_by(BillOccurrence.due_date, BillOccurrence.id)
        .all()
    )
    txn_ids = {o.transaction_id for o in occs if o.amount is None and o.transaction_id}
    txns = (
        {
            t.id: t
            for t in db.query(Transaction).filter(
                Transaction.id.in_(txn_ids), Transaction.deleted_at.is_(None)
            )
        }
        if txn_ids
        else {}
    )
    for occ in occs:
        item = by_id[occ.bill_id]
        txn = txns.get(occ.transaction_id) if occ.transaction_id else None
        if occ.amount is not None:
            amount = Decimal(occ.amount)
        elif txn is not None:
            amount = to_base(txn.amount, txn.exchange_rate)
        elif item.amount is not None:
            amount = Decimal(item.amount)
        else:
            continue
        out[item.id].append(
            Point(
                entry_id=occ.id,
                due_date=occ.due_date,
                amount=amount,
                usage=None if occ.usage is None else Decimal(occ.usage),
                transaction_id=occ.transaction_id,
            )
        )
    return out


def entry_points(db: Session, item: RecurringBill) -> list[Point]:
    """``item``'s done entries, oldest first (see :func:`entry_points_by_item`)."""
    return entry_points_by_item(db, [item])[item.id]


# ---------------------------------------------------------------- judging


def _reason(latest: Point, usual: Decimal, baseline: list[Point]):
    """``("usage" | "price", signed whole percent)`` or ``(None, None)``."""
    if not (latest.usage and latest.usage > 0):
        return None, None
    if not baseline or any(not (p.usage and p.usage > 0) for p in baseline):
        return None, None
    base_usage = median(p.usage for p in baseline)
    usage_pct = (latest.usage - base_usage) / base_usage * _HUNDRED
    base_price = usual / base_usage
    if base_price <= 0:
        return None, None
    price_pct = (latest.amount / latest.usage - base_price) / base_price * _HUNDRED
    if abs(usage_pct) >= abs(price_pct):
        return "usage", _whole(usage_pct)
    return "price", _whole(price_pct)


def assess(points: list[Point], *, monthly: bool) -> Change | None:
    """Judge the latest of ``points`` (done entries, oldest first), or None.

    ``monthly`` is False for weekly rules, which never use the last-year
    baseline. Pure: no database.
    """
    if not points:
        return None
    ordered = sorted(points, key=lambda p: p.due_date)
    latest, before = ordered[-1], ordered[:-1]
    baseline: list[Point] = []
    basis = "recent"
    if monthly:
        same_month = [
            p
            for p in before
            if (p.due_date.year, p.due_date.month)
            == (latest.due_date.year - 1, latest.due_date.month)
        ]
        if same_month:
            baseline, basis = [same_month[-1]], "last_year"
    if not baseline:
        if len(before) < RECENT_N:
            return None
        baseline = before[-RECENT_N:]
        usual = Decimal(median(p.amount for p in baseline))
    else:
        usual = baseline[0].amount
    if usual <= 0:
        return None
    delta = latest.amount - usual
    pct = delta / usual * _HUNDRED
    if abs(pct) < PCT_GATE or abs(delta) < ABS_GATE:
        return None
    reason, reason_pct = _reason(latest, usual, baseline)
    return Change(
        entry_id=latest.entry_id,
        amount=quantize(latest.amount),
        usual=quantize(usual),
        basis=basis,
        delta=quantize(delta),
        pct=_whole(pct),
        direction="up" if delta > 0 else "down",
        reason=reason,
        reason_pct=reason_pct,
    )


def assess_item(item: RecurringBill, points: list[Point]) -> Change | None:
    """:func:`assess` for an item: income items are never assessed, paused ones are."""
    if item.direction == ItemDirection.in_.value:
        return None
    return assess(points, monthly=is_monthly(item))


__all__ = [
    "ABS_GATE",
    "ALERT_WINDOW_DAYS",
    "PCT_GATE",
    "RECENT_N",
    "Change",
    "Point",
    "assess",
    "assess_item",
    "entry_points",
    "entry_points_by_item",
    "is_monthly",
]
