"""Which alert types a member gets, per household (2d §7.6). Everything is on
by default; a NotificationMute row turns one type off for in-app and push.
``general`` (sign-in alerts, test pushes) can never be muted."""

from typing import NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import NotificationMute, NotificationType


class AlertType(NamedTuple):
    type: str
    group: str
    label: str


ALERT_TYPES: tuple[AlertType, ...] = (
    AlertType(NotificationType.bill_due.value, "Bills", "Due in 3 days"),
    AlertType(NotificationType.bill_overdue.value, "Bills", "Overdue"),
    AlertType(NotificationType.bill_auto_paid.value, "Bills", "Paid automatically"),
    AlertType(NotificationType.contract_expiring.value, "Bills", "Contract ending"),
    AlertType(NotificationType.bill_drift.value, "Bills", "Amount changed"),
    AlertType(NotificationType.budget_warning.value, "Budgets", "Budget limit reached"),
    AlertType(NotificationType.stock_low.value, "Pantry", "Running low"),
    AlertType(NotificationType.price_drop.value, "Pantry", "Price drops"),
    AlertType(NotificationType.month_review.value, "Insights", "Month ready to review"),
    AlertType(NotificationType.ingest_created.value, "Apple Pay", "Each new purchase"),
)
MUTABLE = frozenset(a.type for a in ALERT_TYPES)


def muted_types(db: Session, user_id: str, household_id: str) -> set[str]:
    return {
        t
        for (t,) in db.query(NotificationMute.type).filter_by(
            user_id=user_id, household_id=household_id
        )
    }


def is_muted(db: Session, *, user_id: str, household_id: str, type) -> bool:
    value = NotificationType(type).value
    if value not in MUTABLE:
        return False
    return (
        db.query(NotificationMute.type)
        .filter_by(user_id=user_id, household_id=household_id, type=value)
        .first()
        is not None
    )


def set_muted(db: Session, user_id: str, household_id: str, disabled: list[str]) -> None:
    """Replace this member's muted set for the household. Raises ValueError
    for an unknown type or ``general``. Does not commit."""
    wanted = set()
    for value in disabled:
        if value == NotificationType.general.value:
            raise ValueError("General alerts can't be turned off.")
        if value not in MUTABLE:
            raise ValueError(f"Unknown alert type '{value}'.")
        wanted.add(value)
    # A concurrent PUT can insert the same primary key between our delete and
    # insert; redo the replacement once inside a savepoint so it is idempotent.
    for attempt in (0, 1):
        try:
            with db.begin_nested():
                db.query(NotificationMute).filter_by(
                    user_id=user_id, household_id=household_id
                ).delete(synchronize_session=False)
                for value in sorted(wanted):
                    db.add(NotificationMute(user_id=user_id, household_id=household_id, type=value))
            return
        except IntegrityError:
            if attempt:
                raise
