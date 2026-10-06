"""
Notification and web push routes.
"""
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.database import get_db
from app.models import Notification, PushSubscription

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_csrf)])


# ---------------------------------------------------------------------------
# In-app notifications (JSON — consumed by HTMX / Alpine polling)
# ---------------------------------------------------------------------------

@router.get("/notifications", response_class=JSONResponse)
def list_notifications(
    request: Request,
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    PAGE_SIZE = 50
    base_q = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.household_id == hh_id,
        )
    )
    unread = base_q.filter(Notification.is_read.is_(False)).count()
    items = (
        base_q
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(PAGE_SIZE)
        .all()
    )
    total = base_q.count()
    has_more = (offset + PAGE_SIZE) < total
    return {
        "unread": unread,
        "has_more": has_more,
        "offset": offset,
        "items": [
            {
                "id":         n.id,
                "type":       n.type.value,
                "title":      n.title,
                "body":       n.body,
                "link":       n.link,
                "is_read":    n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in items
        ],
    }


@router.post("/notifications/read-all", response_class=JSONResponse)
def mark_all_read(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.household_id == hh_id,
        Notification.is_read.is_(False),
    ).update({"is_read": True})
    db.commit()
    return {"unread": 0}


@router.post("/notifications/{notification_id}/read", response_class=JSONResponse)
def mark_one_read(
    notification_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Web Push
# ---------------------------------------------------------------------------

@router.get("/push/vapid-public-key", response_class=JSONResponse)
def vapid_public_key():
    from app.config import settings
    if not settings.vapid_public_key:
        raise HTTPException(status_code=404, detail="VAPID not configured")
    return {"public_key": settings.vapid_public_key}


_PUSH_HOSTS = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
_PUSH_HOST_SUFFIXES = (".notify.windows.com", ".push.apple.com")


def _is_allowed_push_endpoint(endpoint: str) -> bool:
    """Only the browser vendors' push services; the server POSTs to this URL,
    so anything else would be a server-side request forgery primitive."""
    try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        # Credentials, or an explicit non-default port, have no place here.
        if parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    return parsed.scheme == "https" and (host in _PUSH_HOSTS or host.endswith(_PUSH_HOST_SUFFIXES))


@router.post("/push/subscribe", response_class=JSONResponse)
async def push_subscribe(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    try:
        body = await request.json()
        endpoint = body["endpoint"]
        p256dh   = body["keys"]["p256dh"]
        auth_key = body["keys"]["auth"]
    except (KeyError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid subscription payload") from None

    if not isinstance(endpoint, str) or len(endpoint) > 2000:
        raise HTTPException(status_code=422, detail="Invalid subscription endpoint")
    if not _is_allowed_push_endpoint(endpoint):
        raise HTTPException(status_code=400, detail="Push service not allowed")

    # Upsert: update keys if this user already registered this endpoint.
    # Scoping by user_id matters — the previous lookup matched on endpoint
    # alone, so any authenticated user could re-point somebody else's
    # subscription at their own account and receive that person's pushes.
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint,
        PushSubscription.user_id == user.id,
    ).first()
    if existing:
        existing.p256dh       = p256dh
        existing.auth         = auth_key
        existing.household_id = hh_id
    else:
        # Endpoints are globally unique. If another account already holds this
        # one we neither take it over nor delete their row (data is kept).
        if db.query(PushSubscription.id).filter(PushSubscription.endpoint == endpoint).first():
            raise HTTPException(status_code=409, detail="Endpoint already registered to another account")
        db.add(PushSubscription(
            user_id=user.id,
            household_id=hh_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth_key,
        ))
    db.commit()
    return {"ok": True}


@router.delete("/push/subscribe", response_class=JSONResponse)
async def push_unsubscribe(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, _ = auth
    try:
        body = await request.json()
        endpoint = body["endpoint"]
    except (KeyError, ValueError):
        raise HTTPException(status_code=422, detail="Invalid payload") from None

    db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint,
        PushSubscription.user_id == user.id,
    ).delete()
    db.commit()
    return {"ok": True}


@router.post("/push/test", response_class=JSONResponse)
async def push_test(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Send a test push notification to the current device only."""
    from app.config import settings as app_settings
    from app.models import NotificationType
    from app.services.notifications import create_notification, send_push_for_notification

    user, hh_id = auth

    # Check VAPID is configured
    if not app_settings.vapid_private_key or not app_settings.vapid_public_key:
        return JSONResponse(
            {"sent": False, "error": "VAPID keys are not configured on the server."},
            status_code=200,
        )

    # Parse optional endpoint from body to target only the current device
    endpoint: str | None = None
    try:
        body = await request.json()
        endpoint = body.get("endpoint") or None
    except (ValueError, AttributeError) as exc:
        # Empty / non-JSON / non-object body: fall back to all devices.
        logger.warning("push/test: ignoring unparseable request body (%s)", type(exc).__name__)

    if endpoint:
        target_sub = db.query(PushSubscription).filter(
            PushSubscription.endpoint == endpoint,
            PushSubscription.user_id == user.id,
        ).first()
        if not target_sub:
            return JSONResponse(
                {"sent": False, "error": "Subscription not found for this device. Try re-enabling notifications."},
                status_code=200,
            )
        target_subs = [target_sub]
    else:
        target_subs = db.query(PushSubscription).filter(PushSubscription.user_id == user.id).all()
        if not target_subs:
            return JSONResponse(
                {"sent": False, "error": "No push subscription found for this device. Enable notifications first."},
                status_code=200,
            )

    notif = create_notification(
        db,
        household_id=hh_id,
        user_id=user.id,
        type=NotificationType.general,
        title="Test notification 🎉",
        body="Push notifications are working correctly.",
        link="/settings",
    )
    try:
        sent_count = send_push_for_notification(db, notif, target_subs=target_subs)
        db.commit()
        if sent_count > 0:
            return {"sent": True, "error": None}
        return {"sent": False, "error": "Push was attempted but delivery failed. Check server logs for details."}
    except Exception as exc:
        # Don't echo the raw exception — VAPID/pywebpush errors can carry key
        # material and internal endpoints. The details go to the server log.
        logger.exception("push/test failed: %s", exc)
        db.commit()  # still save the in-app notif
        return {"sent": False, "error": "Push delivery failed. Check the server logs for details."}
