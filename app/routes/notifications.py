"""
Notification and web push routes.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import require_auth
from app.database import get_db
from app.models import Notification, PushSubscription
from app.notification_service import get_unread_count

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# In-app notifications (JSON — consumed by HTMX / Alpine polling)
# ---------------------------------------------------------------------------

@router.get("/notifications", response_class=JSONResponse)
def list_notifications(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    items = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.household_id == hh_id,
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    unread = sum(1 for n in items if not n.is_read)
    return {
        "unread": unread,
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
        raise HTTPException(status_code=422, detail="Invalid subscription payload")

    # Upsert: update keys if endpoint already stored
    existing = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint
    ).first()
    if existing:
        existing.p256dh       = p256dh
        existing.auth         = auth_key
        existing.user_id      = user.id
        existing.household_id = hh_id
    else:
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
        raise HTTPException(status_code=422, detail="Invalid payload")

    db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint,
        PushSubscription.user_id == user.id,
    ).delete()
    db.commit()
    return {"ok": True}
