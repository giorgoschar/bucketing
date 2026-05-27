"""
Notification service: create DB notification rows and deliver web push messages.
"""
import base64
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Notification, NotificationType, PushSubscription


def _normalize_vapid_private_key(key_str: str) -> str:
    """Convert a VAPID private key to PEM format if needed.

    Most VAPID key generators (web tools, Node.js web-push) emit the private
    key as a base64url-encoded raw P-256 scalar (32 bytes).  pywebpush 2.x
    expects either a PEM string or a base64url-encoded DER block; it cannot
    handle the raw-bytes format, so we detect that case and convert on the fly.
    """
    if not key_str or key_str.startswith("-----BEGIN"):
        return key_str
    try:
        padding = "=" * ((4 - len(key_str) % 4) % 4)
        key_bytes = base64.urlsafe_b64decode(key_str + padding)
        if len(key_bytes) == 32:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            private_key = ec.derive_private_key(
                int.from_bytes(key_bytes, "big"),
                ec.SECP256R1(),
            )
            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("utf-8")
    except Exception:
        pass  # fall through and let pywebpush try its own parsing
    return key_str

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


def send_push_for_notification(db: Session, notification: Notification) -> int:
    """Send a web push message to all subscriptions of notification.user_id.

    Returns the number of subscriptions successfully notified.
    """
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

    private_key = _normalize_vapid_private_key(settings.vapid_private_key)

    dead_ids: list[str] = []
    sent_count = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload.encode("utf-8"),
                vapid_private_key=private_key,
                vapid_claims={"sub": f"mailto:{settings.vapid_claims_email}"},
            )
            sent_count += 1
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

    return sent_count


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
