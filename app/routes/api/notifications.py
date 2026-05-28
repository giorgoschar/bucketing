"""
API notifications routes — in-app notifications (already JSON in the web app, migrated here).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.database import get_db
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])

PAGE_SIZE = 50


@router.get("")
def list_notifications(
    offset: int = Query(0, ge=0),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    base_q = db.query(Notification).filter(
        Notification.user_id      == user.id,
        Notification.household_id == hh_id,
    )
    unread = base_q.filter(Notification.is_read.is_(False)).count()
    total  = base_q.count()
    items  = (
        base_q
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(PAGE_SIZE)
        .all()
    )
    return {
        "unread":   unread,
        "total":    total,
        "has_more": (offset + PAGE_SIZE) < total,
        "offset":   offset,
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


@router.post("/read-all")
def mark_all_read(
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    db.query(Notification).filter(
        Notification.user_id      == user.id,
        Notification.household_id == hh_id,
        Notification.is_read.is_(False),
    ).update({"is_read": True})
    db.commit()
    return {"unread": 0}


@router.post("/{notification_id}/read")
def mark_one_read(
    notification_id: str,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    n = db.query(Notification).filter_by(
        id=notification_id, user_id=user.id, household_id=hh_id
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    db.commit()
    return {"id": n.id, "is_read": True}
