"""A transaction's history, derived from what the database already holds
(2c spec §5.2). There is no audit log and no "Added by". Task 10 adds the
bulk changes."""

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models import BillOccurrence, CashMovement, ItemDirection, Transaction, User

_NEVER = datetime.combine(date.min, datetime.min.time())


def transaction_history(db: Session, txn: Transaction) -> list[dict]:
    """Events newest first: created, entry_linked, cash_taken."""
    names: dict[str, str | None] = {}

    def name(user_id):
        if not user_id:
            return None
        if user_id not in names:
            user = db.get(User, user_id)
            names[user_id] = user.display_name if user else None
        return names[user_id]

    def event(at, kind, by, text):
        return {"at": at, "kind": kind, "by": by, "text": text, "batch_id": None, "can_undo": False}

    events = [event(txn.created_at, "created", None, "Added")]
    occurrences = db.query(BillOccurrence).filter(
        BillOccurrence.transaction_id == txn.id, BillOccurrence.paid_at.isnot(None)
    )
    for occ in occurrences:
        verb = "Received for" if occ.bill.direction == ItemDirection.in_.value else "Paid for"
        text = f"{verb} {occ.bill.name} · {occ.due_date:%b %Y}"
        events.append(event(occ.paid_at, "entry_linked", name(occ.paid_by), text))
    for mv in db.query(CashMovement).filter(CashMovement.transaction_id == txn.id):
        source = "their stash" if mv.stash_owner_id else "the bank"
        text = f"Cash taken from {source}" + (" (since removed)" if mv.deleted_at else "")
        events.append(event(mv.created_at, "cash_taken", name(mv.user_id), text))
    events.sort(key=lambda e: e["at"] or _NEVER, reverse=True)
    return events
