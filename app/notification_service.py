"""
Notification service: create DB notification rows and deliver web push messages.
"""
import base64
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Notification, NotificationType, PushSubscription


def _build_vapid(private_key_str: str):
    """Return a py_vapid.Vapid instance from any common key format.

    pywebpush >=2 calls Vapid.from_string() for *every* str key — it has no
    PEM-detection branch.  from_string() assumes base64url-DER, so it fails
    for both PEM and raw-scalar formats.  We therefore build the Vapid object
    ourselves and pass the instance directly; pywebpush uses non-str values
    as a pre-built Vapid object without any further parsing.

    Supported formats
    -----------------
    - PEM  (starts with "-----BEGIN")
    - Raw base64url P-256 scalar (32 bytes) — output of most VAPID generators
    - Base64url-DER — fall-through to Vapid.from_string()
    """
    from py_vapid import Vapid  # local import keeps startup fast

    if private_key_str.startswith("-----BEGIN"):
        return Vapid.from_pem(private_key_str.encode("utf-8"))

    try:
        padding = "=" * ((4 - len(private_key_str) % 4) % 4)
        key_bytes = base64.urlsafe_b64decode(private_key_str + padding)
        if len(key_bytes) == 32:
            # Raw P-256 private scalar → build EC key → PEM → Vapid
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            ec_key = ec.derive_private_key(int.from_bytes(key_bytes, "big"), ec.SECP256R1())
            pem = ec_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
            return Vapid.from_pem(pem)
    except Exception:
        pass

    # Assume base64url-DER; let py_vapid parse it directly
    return Vapid.from_string(private_key=private_key_str)

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

    private_key = _build_vapid(settings.vapid_private_key)

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
