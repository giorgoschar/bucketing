"""Sign-in alerts: notify every household member (in-app + web push) when
someone signs in, or gets the password right but the 2FA code wrong.

A household is a couple of people, so a sign-in nobody recognises is worth an
interruption — and telling every member means a hijacked account is noticed
even if the attacker clears the victim's own notifications.

Alerts never break a login: any failure is logged and swallowed.
"""

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.clock import utcnow_naive
from app.core.ratelimit import client_key
from app.models import HouseholdMember, NotificationType, User

logger = logging.getLogger(__name__)

# First match wins, so more specific tokens come first (Chrome's UA also says
# "Safari", Edge's also says "Chrome", iPad's may say "Macintosh").
_OS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Macintosh", "Mac"),
    ("Windows", "Windows"),
    ("Linux", "Linux"),
)
_BROWSERS = (
    ("Edg/", "Edge"),
    ("FxiOS", "Firefox"),
    ("Firefox/", "Firefox"),
    ("CriOS", "Chrome"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)


def describe_device(user_agent: str | None) -> str:
    """'Safari on iPhone'-style label from a User-Agent header."""
    ua = user_agent or ""
    os_name = next((name for token, name in _OS if token in ua), None)
    browser = next((name for token, name in _BROWSERS if token in ua), None)
    if os_name and browser:
        return f"{browser} on {os_name}"
    return os_name or browser or "unknown device"


def _where(request: Request) -> str:
    return f"{describe_device(request.headers.get('user-agent'))} · IP {client_key(request)}"


def _notify_household(
    db: Session, household_id: str, *, title: str, body: str, dedupe_key: str | None = None
) -> None:
    from app.services.notifications import create_notification, send_push_for_notification

    try:
        member_ids = [
            row.user_id
            for row in db.query(HouseholdMember.user_id).filter(
                HouseholdMember.household_id == household_id
            )
        ]
        notifs = [
            create_notification(
                db,
                household_id=household_id,
                user_id=uid,
                type=NotificationType.general,
                title=title[:200],
                body=body,
                link="/settings",
                dedupe_key=dedupe_key,
            )
            for uid in member_ids
        ]
        db.commit()
        for notif in notifs:
            send_push_for_notification(db, notif)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Sign-in alert for household %s failed", household_id)


def alert_sign_in(
    db: Session, request: Request, user: User, household_id: str, *, method: str | None = None
) -> None:
    """Someone completed password + second factor for `user`.

    `method` names an unusual second factor, e.g. "a backup code (5 left)".
    """
    via = f" using {method}" if method else ""
    _notify_household(
        db,
        household_id,
        title=f"New sign-in: {user.display_name}",
        body=(
            f"Signed in{via} · {_where(request)}. "
            f"If this wasn't {user.display_name}, change the password in Settings."
        ),
    )


def alert_failed_second_factor(
    db: Session, request: Request, user: User, household_id: str
) -> None:
    """The password for `user` was right but the 2FA or backup code was wrong.

    Only reachable after a correct password, so it means someone knows it.
    At most one alert per user per hour: lockout caps attempts, but not to one.
    """
    _notify_household(
        db,
        household_id,
        title=f"Wrong 2FA code for {user.display_name}",
        body=(
            f"Someone entered the correct password but a wrong 2FA code · {_where(request)}. "
            f"If this wasn't {user.display_name}, change the password now."
        ),
        dedupe_key=f"2fa-fail:{user.id}:{utcnow_naive():%Y%m%d%H}",
    )
