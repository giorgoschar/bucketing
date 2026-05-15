"""
Notification service: create DB notification rows and deliver web push messages.
"""
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Notification, NotificationType, PushSubscription

logger = logging.getLogger(__name__)


def create_notification(
    db: Session,
    *,
    household_id: str,
    user_id: str,
    type: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    notif = Notification(
        household_id=household_id,
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
    )
    db.add(notif)
    db.flush()  # get the id without committing
    return notif


def send_push_for_notification(db: Session, notification: Notification) -> None:
    """Send a web push message to all subscriptions of notification.user_id."""
    from app.config import settings

    if not settings.vapid_private_key or not settings.vapid_public_key:
        return  # VAPID keys not configured — skip silently

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush not installed — skipping push delivery")
        return

    subs = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == notification.user_id)
        .all()
    )

    payload = json.dumps({
        "title": notification.title,
        "body":  notification.body or "",
        "link":  notification.link or "/",
    })

    dead_ids: list[str] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": f"mailto:{settings.vapid_claims_email}"},
            )
        except WebPushException as exc:
            # 410 Gone = subscription expired/revoked → remove it
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                dead_ids.append(sub.id)
            else:
                logger.warning("Push failed for sub %s: %s", sub.id, exc)
        except Exception:
            logger.exception("Unexpected push error for sub %s", sub.id)

    for dead_id in dead_ids:
        db.query(PushSubscription).filter(PushSubscription.id == dead_id).delete()


def get_unread_count(db: Session, *, user_id: str, household_id: str) -> int:
    return (
        db.query(Notification)
        .filter(
            Notification.user_id == user_id,
            Notification.household_id == household_id,
            Notification.is_read.is_(False),
        )
        .count()
    )
