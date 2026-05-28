"""
Notification service: create DB notification rows and deliver web push messages.
"""
import base64
import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Notification, NotificationType, PushSubscription

logger = logging.getLogger(__name__)


def _build_vapid(private_key_str: str):
    """Return a py_vapid.Vapid instance from any common key format.

    pywebpush >=2 uses the Vapid object directly when a non-str value is
    passed, skipping its own key parsing entirely.

    Normalisation applied first
    ---------------------------
    - Strip surrounding whitespace (trailing newline from env var managers)
    - Replace literal \\n sequences with real newlines — Coolify and similar
      platforms serialise multi-line env-var values with backslash-n rather
      than real newline bytes, which breaks PEM splitlines() parsing.

    Supported formats (after normalisation)
    ----------------------------------------
    - PEM  (contains "-----BEGIN") — loaded via cryptography directly,
      bypassing Vapid.from_pem()'s internal DER conversion that fails on
      literal-\\n input
    - Raw base64url P-256 scalar (32 bytes) — output of most VAPID generators
    - Base64url-DER (PKCS8 or SEC1) — fall-through to Vapid.from_string()
    """
    from py_vapid import Vapid  # local import keeps startup fast

    # Normalise: strip whitespace; convert literal \n (Coolify stores
    # multi-line env-var values with backslash-n, not real newlines).
    private_key_str = private_key_str.strip().replace("\\n", "\n")

    # ── PEM format ────────────────────────────────────────────────────────────
    if "-----BEGIN" in private_key_str:
        try:
            from cryptography.hazmat.primitives.serialization import (
                load_pem_private_key,
            )
            ec_key = load_pem_private_key(
                private_key_str.encode("utf-8"), password=None
            )
            return Vapid(private_key=ec_key)
        except Exception:
            logger.exception("_build_vapid: PEM key loading failed")
            raise

    # ── Raw base64url P-256 scalar (32 bytes) ─────────────────────────────────
    try:
        padding = "=" * ((4 - len(private_key_str) % 4) % 4)
        key_bytes = base64.urlsafe_b64decode(private_key_str + padding)
        if len(key_bytes) == 32:
            # from_raw() avoids a PEM round-trip and the load_der_private_key
            # call inside Vapid.from_pem() which fails on some cryptography
            # versions when given SEC1 DER.
            return Vapid.from_raw(private_key_str.encode())
    except Exception:
        logger.exception("_build_vapid: failed to parse key as 32-byte raw scalar")

    # ── Fall-back: base64url-DER (PKCS8 / SEC1) ───────────────────────────────
    try:
        return Vapid.from_string(private_key=private_key_str)
    except Exception:
        logger.exception(
            "_build_vapid: all parsing attempts failed (key prefix: %r)",
            private_key_str[:12],
        )
        raise


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


def send_push_for_notification(db: Session, notification: Notification, target_subs=None) -> int:
    """Send a web push message to subscriptions of notification.user_id.

    Pass target_subs to restrict delivery to a specific list of PushSubscription
    objects (e.g. just the current device for test notifications).
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

    if target_subs is not None:
        subs = target_subs
    else:
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
