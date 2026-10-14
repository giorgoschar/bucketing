"""Household membership rules shared by the /api/v1 household routes."""

from sqlalchemy.orm import Session

from app.auth import invalidate_user_sessions, security_logger, verify_totp
from app.core.clock import utcnow_naive
from app.core.config import settings
from app.models import Household, HouseholdMember, Invitation, MemberRole, User
from app.seed import seed_categories
from app.services.personal_tokens import revoke_user_tokens


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


def owner_membership(db: Session, user: User, hh_id: str) -> HouseholdMember:
    """The caller's owner membership of `hh_id`; 403 for anyone else (the old routes' check)."""
    m = db.query(HouseholdMember).filter_by(user_id=user.id, household_id=hh_id).first()
    if not m or m.role != MemberRole.owner:
        raise HouseholdError(403, "Only the household owner can do this")
    return m


def _member(db: Session, user_id: str, hh_id: str) -> HouseholdMember:
    m = db.query(HouseholdMember).filter_by(user_id=user_id, household_id=hh_id).first()
    if not m:
        raise HouseholdError(404, "Member not found")
    return m


def create_household(db: Session, user: User, name: str, currency: str) -> Household:
    name = name.strip()
    if not name:
        raise HouseholdError(400, "Give the household a name.")
    if currency not in settings.currencies:
        raise HouseholdError(400, "Unsupported currency.")
    household = Household(name=name, default_currency=currency)
    db.add(household)
    db.flush()
    db.add(HouseholdMember(household_id=household.id, user_id=user.id, role=MemberRole.owner))
    db.commit()
    seed_categories(db, household.id)
    return household


def leave_household(db: Session, user: User, hh_id: str, confirm_name: str) -> str | None:
    """Leave `hh_id`. An owner must hand over or remove the others first; the last member must
    type the household name, and leaving archives it. Returns another household of the user's, if any."""
    mine = _member(db, user.id, hh_id)
    others = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.household_id == hh_id, HouseholdMember.user_id != user.id)
        .count()
    )
    if mine.role == MemberRole.owner and others > 0:
        raise HouseholdError(
            400, "You are the owner. Transfer ownership or remove the other members before leaving."
        )
    household = db.get(Household, hh_id)
    if others == 0 and confirm_name.strip() != household.name:
        raise HouseholdError(
            400, "You are the last member. Type the household name exactly to confirm leaving."
        )
    db.delete(mine)
    revoke_user_tokens(db, user.id, hh_id)  # so rejoining later does not revive them
    if others == 0:
        household.archived_at = (
            utcnow_naive()
        )  # archived, never deleted (scripts/purge_household.py)
    db.commit()
    remaining = db.query(HouseholdMember).filter_by(user_id=user.id).first()
    return remaining.household_id if remaining else None


def transfer_ownership(db: Session, owner: User, hh_id: str, member_id: str) -> None:
    mine = owner_membership(db, owner, hh_id)
    if member_id == owner.id:
        raise HouseholdError(400, "Already the owner.")
    target = _member(db, member_id, hh_id)
    mine.role = MemberRole.member
    target.role = MemberRole.owner
    db.commit()
    security_logger.info("Ownership of household %s transferred (new app)", hh_id)


def reset_member_2fa(db: Session, owner: User, hh_id: str, member_id: str, owner_code: str) -> None:
    """Account recovery for a member: clears their 2FA and passkey and signs them out everywhere.
    Needs the owner's own authenticator code."""
    owner_membership(db, owner, hh_id)
    if member_id == owner.id:
        raise HouseholdError(400, "Use Security settings to change your own 2FA.")
    if not owner.totp_secret or not verify_totp(db, owner, owner_code):
        raise HouseholdError(400, "Invalid authenticator code.")
    _member(db, member_id, hh_id)
    target = db.get(User, member_id)
    if not target:
        raise HouseholdError(404, "Member not found")
    target.totp_secret = None
    target.totp_enabled = False
    target.totp_backup_codes = None
    target.last_totp_step = None
    target.oidc_subject = None  # re-linked after the member re-enrolls 2FA
    invalidate_user_sessions(db, target)
    revoke_user_tokens(db, target.id)
    db.commit()
    security_logger.info(
        "Owner '%s' reset 2FA for a member of household %s (new app)", owner.username, hh_id
    )
