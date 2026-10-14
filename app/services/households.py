"""Household membership rules shared by the /api/v1 household routes."""

from sqlalchemy.orm import Session

from app.core.clock import utcnow_naive
from app.models import HouseholdMember, Invitation, MemberRole, User


class HouseholdError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def valid_invite(db: Session, token: str) -> Invitation:
    """The same checks as the old /join/{token} page: known, unused, not expired
    (and, new here, its household not archived)."""
    invite = db.query(Invitation).filter_by(token=token).first()
    if not invite or invite.used_at or invite.household.archived_at:
        raise HouseholdError(404, "This invite link is not valid.")
    if invite.expires_at and invite.expires_at < utcnow_naive():
        raise HouseholdError(410, "This invite link has expired.")
    return invite


def accept_invite(db: Session, user: User, token: str) -> Invitation:
    """Add `user` to the invite's household as a member and burn the invite."""
    invite = valid_invite(db, token)
    if (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id, household_id=invite.household_id)
        .first()
    ):
        raise HouseholdError(409, "You are already in this household.")
    # Compare-and-set so two simultaneous accepts cannot both win a single-use link.
    won = (
        db.query(Invitation)
        .filter(Invitation.id == invite.id, Invitation.used_at.is_(None))
        .update({Invitation.used_at: utcnow_naive(), Invitation.used_by: user.id})
    )
    if not won:
        db.rollback()
        raise HouseholdError(404, "This invite link is not valid.")
    db.add(
        HouseholdMember(household_id=invite.household_id, user_id=user.id, role=MemberRole.member)
    )
    db.commit()
    return invite
