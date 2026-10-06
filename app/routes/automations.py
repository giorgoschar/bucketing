"""
Settings → Automations: personal ingest tokens for the iOS Shortcut
(Apple Pay → expense) and the setup guide.

A member only ever sees and manages their own tokens. The plaintext of a new
token is rendered once, in the POST response (never in a redirect URL).
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_auth, require_csrf
from app.core.config import settings
from app.core.database import get_db
from app.models import Bucket, BucketStatus
from app.services import (
    base_ctx,
    issue_personal_token,
    list_personal_tokens,
    revoke_personal_token,
)
from app.templates import templates

router = APIRouter(prefix="/settings/automations", dependencies=[Depends(require_csrf)])


def _render(
    request: Request,
    db: Session,
    user,
    hh_id: str,
    *,
    new_token: str | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    ctx = base_ctx(db, user, hh_id)
    buckets = (
        db.query(Bucket)
        .filter(Bucket.household_id == hh_id, Bucket.status == BucketStatus.active)
        .order_by(Bucket.created_at)
        .all()
    )
    ctx.update(
        {
            "request": request,
            "user": user,
            "tokens": list_personal_tokens(db, user_id=user.id, household_id=hh_id),
            "active_buckets": buckets,
            "bucket_names": {b.id: b.name for b in buckets},
            "new_token": new_token,
            "error": error,
            # APP_BASE_URL first: behind the proxy request.base_url is http://.
            "ingest_url": f"{(settings.app_base_url or str(request.base_url)).rstrip('/')}"
            "/api/v1/ingest/apple-pay",
        }
    )
    response = templates.TemplateResponse("settings/automations.html", ctx, status_code=status_code)
    # The page may carry a freshly issued plaintext token: never cache it.
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("", response_class=HTMLResponse)
def automations_page(request: Request, db: Session = Depends(get_db), auth=Depends(require_auth)):
    user, hh_id = auth
    return _render(request, db, user, hh_id)


@router.post("/tokens", response_class=HTMLResponse)
def create_token(
    request: Request,
    name: str = Form(...),
    default_bucket_id: str = Form(""),
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    user, hh_id = auth
    try:
        _, raw = issue_personal_token(
            db,
            user_id=user.id,
            household_id=hh_id,
            name=name,
            default_bucket_id=default_bucket_id or None,
        )
    except HTTPException as exc:
        db.rollback()
        return _render(request, db, user, hh_id, error=str(exc.detail), status_code=exc.status_code)
    db.commit()
    return _render(request, db, user, hh_id, new_token=raw)


@router.post("/tokens/{token_id}/revoke", response_class=HTMLResponse)
def revoke_token(token_id: str, db: Session = Depends(get_db), auth=Depends(require_auth)):
    user, hh_id = auth
    revoke_personal_token(db, token_id=token_id, user_id=user.id, household_id=hh_id)
    db.commit()
    return RedirectResponse("/settings/automations", status_code=302)
