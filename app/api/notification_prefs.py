"""/api/v1/settings/notifications: alert types on or off for the caller in
this household (2d §7.6). Push subscriptions themselves stay on the cookie
routes /push/* (app/routes/notifications.py)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.models import PushSubscription
from app.services.notification_prefs import ALERT_TYPES, muted_types, set_muted

router = APIRouter(prefix="/settings/notifications", tags=["settings"])


class AlertTypeOut(BaseModel):
    type: str
    group: str  # Bills | Budgets | Pantry | Apple Pay
    label: str
    enabled: bool


class NotificationPrefsOut(BaseModel):
    types: list[AlertTypeOut]
    push_devices: int  # the caller's push subscriptions in this household


class NotificationPrefsIn(BaseModel):
    disabled: list[str]


def _prefs(db: Session, user_id: str, hh_id: str) -> NotificationPrefsOut:
    muted = muted_types(db, user_id, hh_id)
    devices = db.query(PushSubscription).filter_by(user_id=user_id, household_id=hh_id).count()
    return NotificationPrefsOut(
        types=[
            AlertTypeOut(type=a.type, group=a.group, label=a.label, enabled=a.type not in muted)
            for a in ALERT_TYPES
        ],
        push_devices=devices,
    )


@router.get("", response_model=NotificationPrefsOut)
def get_prefs(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return _prefs(db, user.id, hh_id)


@router.put("", response_model=NotificationPrefsOut)
def put_prefs(
    body: NotificationPrefsIn, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    user, hh_id = auth
    try:
        set_muted(db, user.id, hh_id, body.disabled)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    db.commit()
    return _prefs(db, user.id, hh_id)
