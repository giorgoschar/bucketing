"""
Cash: a private stash at home, and the wallet each member carries.

Nobody keeps a wallet balance. Cash taken into a wallet counts as spent,
logged or not; the optional "Still have €X" says what is left, and that
carries into the next month instead.

Movements (:class:`app.models.CashMovement`, kinds :class:`app.models.CashKind`),
each one member's (``user_id``):

* ``stash_in``   cash added to your own stash (saved, received, or an ATM
                 withdrawal kept at home);
* ``take``       cash into your wallet, from a stash (``stash_owner_id``: your
                 own or another member's) or from the bank (an ATM; NULL);
* ``put_back``   cash from your wallet back into your own stash;
* ``still_have`` optional: what was in your wallet on that date;
* ``out``        legacy, no longer offered: cash that left the wallet without
                 a logged expense; with a category it counts as spending there.

The stash is private::

    stash(owner) = stash_in(owner) - takes from owner's stash + put_back(owner)

Only its owner sees the balance, the stash_ins and put_backs and the stash
history, which includes other members' takes from it ("Bob took €50").
Another member may take from it into their own wallet without seeing the
balance. Their take is never refused, even past what the stash holds: a
refusal would reveal the balance (:func:`require_stash_covers`). The stash
then goes negative and its owner is warned. Their takes stay in the owner's
history even after they delete them. A take from someone else's stash is not
a debt: nothing reaches settle-up. Household owners get no special access;
each member logs and deletes only their own movements.

The wallet, per member and calendar month M, is visible to the household::

    spent(M)          = carried(M) + taken(M) - put_back(M) - still_have_end(M)  (floored at 0)
    carried(M)        = still_have_end(M-1)
    not_yet_logged(M) = spent(M) - logged(M) - outs(M)                          (floored at 0)
    still_have_end(M) = the latest ``still_have`` dated within M, plus what was
                        taken and minus what was put back, given out or logged
                        after it (floored at 0); 0 when M has none

``logged`` is the active cash expenses (``payment_method='cash'``) credited to
the member through :func:`app.services.money.paid_for`: the whole amount when
they paid, their own split for an own-share expense. A still_have rolled
forward to the month end carries into the next month only, so never entering
one simply means everything taken in a month was spent that month.

Cash logged (or put back) in a later month can only have come from cash taken
earlier, so a month whose terms come out negative uses up the not-yet-logged
cash of the months before it, latest first, instead of being floored away:
take 100 in January, log 60 then and 40 in February, and January's not yet
logged is 0, not 40 counted again on top of February's 40. A still_have stops
it: what the wallet held then is known, so nothing reaches past it, not even
cash logged after it beyond what it held (that came from an unrecorded top-up).

Insights show the household's not-yet-logged cash as "Cash (not yet logged)".
A period that covers only part of a month counts the part of that month's
not-yet-logged cash that came from takes dated inside it (what was carried in
dates from the 1st), so consecutive periods add up to the month.

"I took this from my stash" (:func:`withdraw_and_spend`, or ``took_cash`` on a
cash expense, single payer only) records a ``take`` into the payer's wallet,
from their own stash or the bank, linked to the expense by ``transaction_id``.
A linked pair nets out of the wallet: neither side enters the formula, while
the expense counts like any other and the take still comes out of the stash.
Deleting the expense soft-deletes the take; editing it keeps the take in step.
The take stays its taker's: the expense keeps them as its payer, and only they
may change what it took out of their stash (:func:`sync_linked_take`).

Currency: movements live in the household currency. There is no FX source for
cash, so the routes force ``currency`` to the household default (the API rejects
a different one); cash expenses enter in base currency (``to_base``).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.clock import local_today, utcnow_naive
from app.core.money import ZERO, quantize
from app.models import (
    CashKind,
    CashMovement,
    HouseholdMember,
    PaymentMethod,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services.money import paid_for, to_base

STASH_IN = CashKind.stash_in.value
TAKE = CashKind.take.value
PUT_BACK = CashKind.put_back.value
STILL_HAVE = CashKind.still_have.value
OUT = CashKind.out.value

KINDS = tuple(k.value for k in CashKind)
# What can be logged now; ``out`` is legacy and only ever read.
LOGGABLE = (STASH_IN, TAKE, PUT_BACK, STILL_HAVE)
# The kinds that move a wallet (the month formula's terms).
WALLET_KINDS = (TAKE, PUT_BACK, STILL_HAVE, OUT)

# Where "I took this from my stash" took the cash from.
FROM_STASH = "stash"
FROM_BANK = "bank"
TAKE_SOURCES = (FROM_STASH, FROM_BANK)

# Pseudo-category key and label for not-yet-logged cash in category
# breakdowns (insights and /me).
NOT_LOGGED_CASH = "__cash_not_logged__"
NOT_LOGGED_CASH_LABEL = {"name": "Cash (not yet logged)", "icon": "💵", "color": "#a8a29e"}

# Never says how much is in someone else's stash.
OWN_STASH_SHORT = "Not enough cash in your stash."

# An expense cash was taken for ("I took this from my stash").
TAKE_KEEPS_PAYER = ("Cash was taken for this expense, so it stays paid by whoever took it "
                    "(or switch it away from cash).")
TAKE_AMOUNT_TAKERS = ("Cash was taken from a stash for this expense: only the person who "
                      "took it can change the amount.")


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

def _first(d: date) -> date:
    return d.replace(day=1)


def _next_month(first: date) -> date:
    return date(first.year + first.month // 12, first.month % 12 + 1, 1)


def _prev_month(first: date) -> date:
    return date(first.year - (first.month == 1), (first.month - 2) % 12 + 1, 1)


def _month_end(first: date) -> date:
    return _next_month(first) - timedelta(days=1)


def _months(first: date, last: date) -> list[date]:
    out, m = [], _first(first)
    while m <= last:
        out.append(m)
        m = _next_month(m)
    return out


# ---------------------------------------------------------------------------
# The stash
# ---------------------------------------------------------------------------

def _stash_rows(owner_id: str):
    """Filter: the movements that make up ``owner_id``'s stash."""
    return or_(
        and_(CashMovement.user_id == owner_id, CashMovement.kind.in_((STASH_IN, PUT_BACK))),
        and_(CashMovement.kind == TAKE, CashMovement.stash_owner_id == owner_id),
    )


def stash_balance(db: Session, household_id: str, owner_id: str) -> Decimal:
    """What is in ``owner_id``'s stash now (all time, whatever the dates).

    Only ever shown to the owner (see the module docstring).
    """
    rows = db.query(CashMovement.kind, CashMovement.amount).filter(
        CashMovement.household_id == household_id, CashMovement.active(),
        _stash_rows(owner_id),
    )
    total = ZERO
    for kind, amount in rows:
        total += -Decimal(amount) if kind == TAKE else Decimal(amount)
    return quantize(total)


def require_stash_covers(
    db: Session, household_id: str, owner_id: str, amount: Decimal, actor_id: str,
    *, freed: Decimal = ZERO,
) -> None:
    """400 unless ``owner_id``'s stash holds ``amount`` (plus ``freed``: what an
    edited take already had out of it).

    Only checked when ``actor_id`` owns the stash. Someone else's take is never
    refused: accept-or-refuse would let them find the balance by trying
    amounts. Their take may push the stash below zero, which only its owner
    sees (the stash card warns them).
    """
    if actor_id != owner_id:
        return
    if stash_balance(db, household_id, owner_id) + freed < Decimal(amount):
        raise HTTPException(status_code=400, detail=OWN_STASH_SHORT)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def add_movement(
    db: Session,
    household_id: str,
    user_id: str,
    kind: str,
    amount: Decimal,
    currency: str,
    movement_date: date,
    category_id: str | None = None,
    note: str | None = None,
    *,
    stash_owner_id: str | None = None,
    transaction_id: str | None = None,
    commit: bool = True,
) -> CashMovement:
    """Store a cash movement (and commit, unless ``commit=False``).

    Low level: callers check membership, amounts and the stash (see
    :func:`record_movement`). Only a ``take`` has a stash owner and only a
    legacy ``out`` a category.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    mv = CashMovement(
        household_id=household_id, user_id=user_id, kind=kind,
        stash_owner_id=stash_owner_id if kind == TAKE else None,
        amount=amount, currency=currency, movement_date=movement_date,
        category_id=(category_id or None) if kind == OUT else None,
        note=(note or "").strip() or None, transaction_id=transaction_id,
    )
    db.add(mv)
    if commit:
        db.commit()
        db.refresh(mv)
    else:
        db.flush()
    return mv


def _member_ids(db: Session, household_id: str) -> list[str]:
    return [uid for (uid,) in db.query(HouseholdMember.user_id)
            .filter(HouseholdMember.household_id == household_id)]


def record_movement(
    db: Session,
    *,
    household_id: str,
    actor_id: str,
    kind: str,
    amount: Decimal,
    currency: str,
    when: date,
    note: str | None = None,
    stash_owner_id: str | None = None,
) -> CashMovement:
    """Log one of the actor's own movements (the cash page and the API).

    A ``take`` from a stash (``stash_owner_id``, any member's) needs the stash
    to hold the amount. Raises HTTPException 400 for a kind that cannot be
    logged, a stash outside the household or a take bigger than its stash.
    """
    if kind not in LOGGABLE:
        raise HTTPException(status_code=400, detail=f"Kind must be one of: {', '.join(LOGGABLE)}.")
    owner = stash_owner_id if kind == TAKE else None
    if owner:
        if owner not in _member_ids(db, household_id):
            raise HTTPException(status_code=400, detail="That stash is not in this household.")
        require_stash_covers(db, household_id, owner, amount, actor_id)
    return add_movement(db, household_id, actor_id, kind, amount, currency, when, note=note,
                        stash_owner_id=owner)


def delete_movement(db: Session, movement: CashMovement) -> None:
    """Soft delete: the row stays, it just stops counting."""
    movement.deleted_at = utcnow_naive()
    db.commit()


def delete_own_movement(db: Session, household_id: str, actor_id: str, movement_id: str) -> None:
    """Delete one of the actor's movements (the cash page and the API).

    404 for a movement the actor may not see, 403 for one they may see but
    is not theirs (another member's take from their stash), 400 when deleting
    an addition would leave their stash below zero.
    """
    mv = (
        db.query(CashMovement)
        .filter(CashMovement.id == movement_id, CashMovement.household_id == household_id,
                CashMovement.active(), _visible_to(actor_id))
        .first()
    )
    if not mv:
        raise HTTPException(status_code=404, detail="Cash movement not found")
    if mv.user_id != actor_id:
        raise HTTPException(status_code=403, detail="You can only delete your own cash movements.")
    if mv.kind in (STASH_IN, PUT_BACK) and stash_balance(db, household_id, actor_id) < mv.amount:
        raise HTTPException(status_code=400, detail="That would leave your stash below zero.")
    delete_movement(db, mv)


# ---------------------------------------------------------------------------
# "I took this from my stash": a take linked to its cash expense
# ---------------------------------------------------------------------------

def _linked(db: Session, txn_id: str):
    return db.query(CashMovement).filter(
        CashMovement.transaction_id == txn_id, CashMovement.active(),
    )


def has_linked_take(db: Session, txn_id: str) -> bool:
    return db.query(_linked(db, txn_id).exists()).scalar()


def link_take(
    db: Session, txn: Transaction, taker_id: str, source: str, currency: str,
) -> CashMovement:
    """Record the take a cash expense was paid with, into ``taker_id``'s
    wallet from their stash (``source`` "stash") or the bank. Does not commit.
    """
    amount = quantize(to_base(txn.amount, txn.exchange_rate))
    owner = taker_id if source == FROM_STASH else None
    if owner:
        require_stash_covers(db, txn.household_id, owner, amount, taker_id)
    return add_movement(
        db, txn.household_id, taker_id, TAKE, amount, currency, txn.transaction_date,
        note="Taken for an expense", stash_owner_id=owner, transaction_id=txn.id, commit=False,
    )


def linked_taker(db: Session, txn_id: str) -> str | None:
    """Whose wallet the cash for an expense was taken into (None: no take)."""
    mv = _linked(db, txn_id).first()
    return mv.user_id if mv else None


def sync_linked_take(db: Session, txn: Transaction, actor_id: str) -> None:
    """Keep a linked take in step with its expense. Does not commit.

    A deleted expense, or one no longer paid in cash, drops the take (soft
    delete); otherwise the take follows the expense's base amount and date,
    as long as its stash still covers a bigger amount (400 otherwise, see
    :func:`require_stash_covers`).

    The take stays its taker's: the expense keeps them as its payer (400,
    :data:`TAKE_KEEPS_PAYER`), and only they may change what it took out of
    their stash (403 whatever the amount, so nobody else can move or probe
    the balance).
    """
    rows = _linked(db, txn.id).all()
    if not rows:
        return
    still_cash = (
        txn.deleted_at is None
        and txn.type == TransactionType.expense
        and txn.payment_method == PaymentMethod.cash.value
    )
    for mv in rows:
        if not still_cash:
            mv.deleted_at = utcnow_naive()
            continue
        if txn.paid_by != mv.user_id:
            raise HTTPException(status_code=400, detail=TAKE_KEEPS_PAYER)
        amount = quantize(to_base(txn.amount, txn.exchange_rate))
        if mv.stash_owner_id and amount != mv.amount and actor_id != mv.stash_owner_id:
            raise HTTPException(status_code=403, detail=TAKE_AMOUNT_TAKERS)
        if mv.stash_owner_id and amount > mv.amount:
            require_stash_covers(db, txn.household_id, mv.stash_owner_id, amount, actor_id,
                                 freed=Decimal(mv.amount))
        mv.amount = amount
        mv.movement_date = txn.transaction_date


def withdraw_and_spend(
    db: Session,
    *,
    user,
    household_id: str,
    bucket,
    amount,
    source: str = FROM_STASH,
    when: date | None = None,
    category_id: str | None = None,
    notes: str | None = None,
    merchant: str | None = None,
    currency: str | None = None,
) -> Transaction:
    """Take cash for one purchase in one step.

    Creates the cash expense (paid by ``user``) and the matching ``take``
    into their wallet from their stash or the bank (``source``), linked, in
    one database transaction. Validation is the expense's
    (``TransactionCreate``); raises ``ValidationError`` / ``HTTPException``
    like :func:`app.services.transactions.create_transaction`.
    """
    from app.schemas import TransactionCreate
    from app.services.transactions import create_transaction

    data = TransactionCreate(
        bucket_id=bucket.id, amount=amount, currency=currency or "EUR",
        type=TransactionType.expense, paid_by=user.id, category_id=category_id,
        notes=notes, merchant=merchant, transaction_date=when,
        payment_method=PaymentMethod.cash.value, took_cash=True, take_from=source,
    )
    return create_transaction(db, household_id=household_id, bucket=bucket, user=user, data=data)


# ---------------------------------------------------------------------------
# Reading movements: each member sees their own, plus takes from their stash
# ---------------------------------------------------------------------------

def _visible_to(viewer_id: str):
    """Filter: the viewer's own movements and other members' takes from
    the viewer's stash. Nothing of anyone else's stash, ever."""
    return or_(
        CashMovement.user_id == viewer_id,
        and_(CashMovement.kind == TAKE, CashMovement.stash_owner_id == viewer_id),
    )


def list_movements(
    db: Session,
    household_id: str,
    viewer_id: str,
    *,
    member_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
) -> list[CashMovement]:
    """Movements ``viewer_id`` may see, newest first (see :func:`_visible_to`);
    ``member_id`` narrows them to that member's. Active ones, plus other
    members' deleted takes from the viewer's stash, so a take can't vanish
    from the stash owner's history by being deleted (``deleted_at`` is set)."""
    q = db.query(CashMovement).filter(
        CashMovement.household_id == household_id,
        or_(
            CashMovement.active(),
            and_(
                CashMovement.kind == TAKE,
                CashMovement.stash_owner_id == viewer_id,
                CashMovement.user_id != viewer_id,
            ),
        ),
        _visible_to(viewer_id),
    )
    if member_id:
        q = q.filter(CashMovement.user_id == member_id)
    if start:
        q = q.filter(CashMovement.movement_date >= start)
    if end:
        q = q.filter(CashMovement.movement_date <= end)
    return (
        q.order_by(CashMovement.movement_date.desc(), CashMovement.created_at.desc())
        .limit(limit)
        .all()
    )


# ---------------------------------------------------------------------------
# The ledger: wallet movements + credited cash expenses, grouped per member
# ---------------------------------------------------------------------------

@dataclass
class _Ledger:
    # member -> rows
    movements: dict = field(default_factory=lambda: defaultdict(list))
    expenses: dict = field(default_factory=lambda: defaultdict(list))  # (date, created_at, amount)
    # First day of the latest month with any row (None when empty).
    last: date | None = None

    def note(self, day: date) -> None:
        if day and (self.last is None or day > self.last):
            self.last = _first(day)


def _load_ledger(
    db: Session,
    household_id: str,
    start: date,
    member_ids: set[str] | None = None,
) -> _Ledger:
    """Wallet movements and cash expenses dated from the month before
    ``start`` (for carried) onwards, in two queries. Later months are loaded
    too: cash logged after a month can use up that month's not-yet-logged cash.

    A linked take and its expense are left out on both sides.
    """
    ledger = _Ledger()
    mq = db.query(CashMovement).filter(
        CashMovement.household_id == household_id,
        CashMovement.active(),
        CashMovement.kind.in_(WALLET_KINDS),
        CashMovement.movement_date >= _prev_month(_first(start)),
        CashMovement.transaction_id.is_(None),
    )
    if member_ids is not None:
        mq = mq.filter(CashMovement.user_id.in_(member_ids))
    for mv in mq.all():
        ledger.movements[mv.user_id].append(mv)
        ledger.note(mv.movement_date)

    linked = exists().where(
        CashMovement.transaction_id == Transaction.id, CashMovement.active(),
    )
    tq = (
        db.query(Transaction)
        .filter(
            Transaction.household_id == household_id,
            Transaction.active(),
            Transaction.type == TransactionType.expense,
            Transaction.payment_method == PaymentMethod.cash.value,
            Transaction.transaction_date >= _prev_month(_first(start)),
            ~linked,
        )
        .options(joinedload(Transaction.splits))
    )
    if member_ids is not None:
        tq = tq.filter(or_(
            Transaction.paid_by.in_(member_ids),
            Transaction.splits.any(TransactionSplit.user_id.in_(member_ids)),
        ))
    for t in tq.all():
        for uid, amount in paid_for(t).items():
            if amount and (member_ids is None or uid in member_ids):
                ledger.expenses[uid].append((t.transaction_date, t.created_at, amount))
                ledger.note(t.transaction_date)
    return ledger


# Sort key for rows without a created_at (naive UTC, like the column).
_NEVER = datetime.combine(date.min, datetime.min.time())


def _latest_still_have(rows: list[CashMovement], first: date, last: date) -> CashMovement | None:
    found = [m for m in rows if m.kind == STILL_HAVE and first <= m.movement_date <= last]
    if not found:
        return None
    return max(found, key=lambda m: (m.movement_date, m.created_at or _NEVER))


def _after(row_date: date, row_created, mark: CashMovement) -> bool:
    if row_date != mark.movement_date:
        return row_date > mark.movement_date
    return (row_created or _NEVER) > (mark.created_at or _NEVER)


def _still_have_end(movements: list, expenses: list, first: date) -> Decimal | None:
    """The month's ``still_have_end``, not yet floored: its latest still_have
    rolled forward to the month end (plus takes, minus put backs, outs and
    logged cash after it). Below 0 when more left the wallet after it than it
    held (an unrecorded top-up). None when the month has no still_have."""
    last = _month_end(first)
    mark = _latest_still_have(movements, first, last)
    if mark is None:
        return None
    total = Decimal(mark.amount)
    for m in movements:
        if (first <= m.movement_date <= last and m.kind != STILL_HAVE
                and _after(m.movement_date, m.created_at, mark)):
            total += Decimal(m.amount) if m.kind == TAKE else -Decimal(m.amount)
    total -= sum((a for d, c, a in expenses if first <= d <= last and _after(d, c, mark)), ZERO)
    return total


def _floored(value: Decimal | None) -> Decimal | None:
    return None if value is None else max(value, ZERO)


def _breakdown(ledger: _Ledger, member_id: str, months: list[date]) -> list[dict]:
    """Apply the module formula month by month (``months`` consecutive).

    The months after ``months`` up to the ledger's last are worked out as well,
    so that cash logged later can use up earlier not-yet-logged cash (see the
    module docstring); only the rows for ``months`` are returned.
    """
    if not months:
        return []
    movements = ledger.movements.get(member_id, [])
    expenses = ledger.expenses.get(member_id, [])
    span = _months(months[0], max(months[-1], ledger.last or months[-1]))
    out = []
    for first in span:
        last = _month_end(first)
        prev_end = _floored(_still_have_end(movements, expenses, _prev_month(first)))
        raw_end = _still_have_end(movements, expenses, first)
        end = _floored(raw_end)
        # What left the wallet after this month's still_have beyond what it
        # held came from cash never recorded, not from earlier months: it is
        # added back so it cannot reach past the still_have.
        excess = -raw_end if raw_end is not None and raw_end < 0 else ZERO
        in_month = [m for m in movements if first <= m.movement_date <= last]

        def total(kind, rows=in_month):
            return sum((Decimal(m.amount) for m in rows if m.kind == kind), ZERO)

        carried = prev_end if prev_end is not None else ZERO
        taken, put_back, outs = total(TAKE), total(PUT_BACK), total(OUT)
        labelled = sum((Decimal(m.amount) for m in in_month
                        if m.kind == OUT and m.category_id), ZERO)
        logged = sum((a for d, _c, a in expenses if first <= d <= last), ZERO)
        spent = carried + taken - put_back - (end if end is not None else ZERO)
        out.append({
            "month":        first,
            "carried":      quantize(carried),
            "taken":        quantize(taken),
            "put_back":     quantize(put_back),
            "still_have":   quantize(end) if end is not None else None,
            "spent":        quantize(max(spent, ZERO)),
            "logged":       quantize(logged),
            "outs":         quantize(outs),
            "labelled_out": quantize(labelled),
            # Before the shortfall pass below; may be negative.
            "not_yet_logged": spent - logged - outs + excess,
            "_after_mark":  prev_end is not None,
        })

    # Latest month first: a month that logged (or put back) more than it had
    # takes the shortfall from the not-yet-logged cash of the month before,
    # unless a still_have closed that month.
    shortfall = ZERO
    for row in reversed(out):
        value = row["not_yet_logged"] - shortfall
        row["not_yet_logged"] = quantize(max(value, ZERO))
        shortfall = ZERO if row.pop("_after_mark") else max(-value, ZERO)
    return out[:len(months)]


def _not_logged_within(row: dict, movements: list, start: date | None, end: date | None) -> Decimal:
    """The part of a month's not-yet-logged cash that falls in [start, end].

    The whole of it when the period covers the month; otherwise the share of
    it that came from sources dated in the period: the month's takes on their
    own dates, and what was carried in on the 1st.
    """
    first, last = row["month"], _month_end(row["month"])
    if (start is None or start <= first) and (end is None or end >= last):
        return row["not_yet_logged"]
    sources = [(first, row["carried"])] + [
        (m.movement_date, Decimal(m.amount)) for m in movements
        if m.kind == TAKE and first <= m.movement_date <= last
    ]
    total = sum((a for _d, a in sources), ZERO)
    inside = sum((a for d, a in sources
                  if (start is None or d >= start) and (end is None or d <= end)), ZERO)
    return row["not_yet_logged"] * inside / total if total else ZERO


def _earliest(db: Session, household_id: str, member_ids: set[str] | None) -> date | None:
    """The first date anything happened to a wallet: a movement or a cash expense."""
    mq = db.query(func.min(CashMovement.movement_date)).filter(
        CashMovement.household_id == household_id, CashMovement.active(),
        CashMovement.kind.in_(WALLET_KINDS),
    )
    tq = db.query(func.min(Transaction.transaction_date)).filter(
        Transaction.household_id == household_id, Transaction.active(),
        Transaction.type == TransactionType.expense,
        Transaction.payment_method == PaymentMethod.cash.value,
    )
    if member_ids is not None:
        mq = mq.filter(CashMovement.user_id.in_(member_ids))
        tq = tq.filter(or_(
            Transaction.paid_by.in_(member_ids),
            Transaction.splits.any(TransactionSplit.user_id.in_(member_ids)),
        ))
    found = [d for d in (mq.scalar(), tq.scalar()) if d is not None]
    return min(found) if found else None


def _span(
    db: Session, household_id: str, start: date | None, end: date | None,
    member_ids: set[str] | None,
) -> list[date]:
    """The calendar months overlapping [start, end]; open ends run from the
    first wallet movement or cash expense to the current month. Empty when
    there is nothing to count."""
    if start is None:
        start = _earliest(db, household_id, member_ids)
        if start is None:
            return []
    end = end or max(local_today(), start)
    if start > end:
        return []
    return _months(start, end)


def monthly_breakdown(
    db: Session, household_id: str, member_id: str, first_month: date, last_month: date,
) -> list[dict]:
    """The formula's terms for each month from ``first_month`` to ``last_month``.

    Rows: ``month`` (first day), ``carried``, ``taken``, ``put_back``,
    ``still_have`` (None when not entered), ``spent``, ``logged``, ``outs``,
    ``labelled_out`` (outs with a category), ``not_yet_logged``. ``put_back``
    is stash activity: callers show it to the member only (see
    :func:`wallet_summaries`).
    """
    months = _months(_first(first_month), _first(last_month))
    if not months:
        return []
    ledger = _load_ledger(db, household_id, months[0], {member_id})
    return _breakdown(ledger, member_id, months)


def not_yet_logged(db: Session, household_id: str, member_id: str, month_start: date) -> Decimal:
    """Cash the member spent in the month that no cash expense explains yet."""
    return monthly_breakdown(db, household_id, member_id, month_start, month_start)[0][
        "not_yet_logged"]


_SUM_KEYS = ("taken", "put_back", "spent", "logged", "outs", "labelled_out", "not_yet_logged")


def wallet_summaries(
    db: Session,
    household_id: str,
    member_ids: list[str],
    start: date | None,
    end: date | None,
    *,
    viewer_id: str | None = None,
) -> dict[str, dict]:
    """Each member's wallet over the calendar months overlapping [start, end].

    The formula's terms summed over those months, plus ``carried`` (into the
    first month) and ``still_have`` (the last month's, None if not entered).
    Household-visible, except that a put back is stash activity: for anyone
    but the member themselves (``viewer_id``) ``taken`` is net of it (floored
    at 0) and ``put_back`` is left out.
    """
    wanted = set(member_ids)
    months = _span(db, household_id, start, end, wanted)
    ledger = _load_ledger(db, household_id, months[0], wanted) if months else None
    result = {}
    for uid in member_ids:
        rows = _breakdown(ledger, uid, months) if ledger else []
        sums = {k: quantize(sum((r[k] for r in rows), ZERO)) for k in _SUM_KEYS}
        sums["carried"] = rows[0]["carried"] if rows else ZERO
        sums["still_have"] = rows[-1]["still_have"] if rows else None
        if uid != viewer_id:
            # Floored: below 0 it would be the put back itself.
            sums["taken"] = quantize(max(sums["taken"] - sums.pop("put_back"), ZERO))
        result[uid] = sums
    return result


def wallet_summary(
    db: Session, household_id: str, member_id: str, start: date | None, end: date | None,
    *, viewer_id: str | None = None,
) -> dict:
    """One member's :func:`wallet_summaries` entry."""
    return wallet_summaries(db, household_id, [member_id], start, end,
                            viewer_id=viewer_id)[member_id]


# ---------------------------------------------------------------------------
# Insights: not-yet-logged cash and labelled outs as spending
# ---------------------------------------------------------------------------

@dataclass
class CashSpend:
    """Cash spending that is not a logged expense, for one period and scope.

    ``not_logged`` maps (year, month) to not-yet-logged cash; ``outs`` holds
    the labelled legacy ``out`` movements dated in the period as (date,
    category_id, amount).
    """
    not_logged: dict = field(default_factory=dict)
    outs: list = field(default_factory=list)

    @property
    def not_logged_total(self) -> Decimal:
        return quantize(sum(self.not_logged.values(), ZERO))

    @property
    def outs_total(self) -> Decimal:
        return quantize(sum((a for _d, _c, a in self.outs), ZERO))

    @property
    def total(self) -> Decimal:
        return quantize(self.not_logged_total + self.outs_total)

    def by_month(self) -> dict:
        totals: dict = defaultdict(Decimal, self.not_logged)
        for d, _c, a in self.outs:
            totals[(d.year, d.month)] += a
        return dict(totals)

    def by_category(self, not_logged_key) -> dict:
        totals: dict = defaultdict(Decimal)
        if self.not_logged_total:
            totals[not_logged_key] = self.not_logged_total
        for _d, cid, a in self.outs:
            totals[cid] += a
        return dict(totals)

    def by_category_month(self, not_logged_key) -> dict:
        totals: dict = defaultdict(Decimal)
        for (y, m), a in self.not_logged.items():
            totals[(not_logged_key, y, m)] += a
        for d, cid, a in self.outs:
            totals[(cid, d.year, d.month)] += a
        return dict(totals)


def cash_scope(db: Session, household_id: str, person: str | None) -> list[str]:
    """The members whose cash an insights view includes: everyone, or the
    Person filter's member."""
    return [person] if person else _member_ids(db, household_id)


def cash_spending(
    db: Session,
    household_id: str,
    start: date | None,
    end: date | None,
    scope: list[str],
    *,
    include_not_logged: bool = True,
    category_ids: list | None = None,
) -> CashSpend:
    """Not-yet-logged cash per month and labelled outs for the members in
    ``scope`` in [start, end].

    Not-yet-logged cash is a monthly figure: a month the period covers counts
    in full, a month it covers only part of counts the part taken inside the
    period (see :func:`_not_logged_within`), so a partial window is not set
    against a whole month of cash. Labelled outs count on their own dates, and
    only for ``category_ids`` when given (not-yet-logged cash has no category,
    so a category filter drops it via ``include_not_logged=False``).
    """
    spend = CashSpend()
    if not scope:
        return spend
    member_ids = set(scope)
    months = _span(db, household_id, start, end, member_ids)
    if not months:
        return spend
    ledger = _load_ledger(db, household_id, months[0], member_ids)
    not_logged: dict = defaultdict(Decimal)
    for uid in scope:
        movements = ledger.movements.get(uid, [])
        if include_not_logged:
            for row in _breakdown(ledger, uid, months):
                part = (_not_logged_within(row, movements, start, end)
                        if row["not_yet_logged"] else ZERO)
                if part:
                    not_logged[(row["month"].year, row["month"].month)] += part
        for mv in movements:
            if mv.kind != OUT or not mv.category_id:
                continue
            if (start and mv.movement_date < start) or (end and mv.movement_date > end):
                continue
            if category_ids and mv.category_id not in category_ids:
                continue
            spend.outs.append((mv.movement_date, mv.category_id, Decimal(mv.amount)))
    spend.not_logged = dict(not_logged)
    return spend


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def parse_month(raw: str | None) -> tuple[date, date, str]:
    """``YYYY-MM`` (default: the current local month) -> (first day, last day, normalised)."""
    from calendar import monthrange

    if raw:
        try:
            y, m = (int(p) for p in raw.split("-"))
            first = date(y, m, 1)
        except (ValueError, TypeError):
            raise ValueError("Month must be YYYY-MM.") from None
    else:
        today = local_today()
        first = today.replace(day=1)
    last = first.replace(day=monthrange(first.year, first.month)[1])
    return first, last, first.strftime("%Y-%m")
