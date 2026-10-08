"""API: manage your own personal ingest tokens (JWT auth only).

The plaintext token appears in the create response and nowhere else.
"""

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.services import (
    issue_personal_token,
    list_personal_tokens,
    revoke_personal_token,
    token_dict,
)

router = APIRouter(prefix="/settings/tokens", tags=["settings"])


class TokenIn(BaseModel):
    name: str
    default_bucket_id: str | None = None
    # Opt-in: shares category and bucket names with the Shortcut so it can ask
    # for a category. Fixed at creation; to change it, create a new token.
    allow_classify: bool = False


@router.get("")
def list_tokens(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    return [token_dict(t) for t in list_personal_tokens(db, user_id=user.id, household_id=hh_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_token(
    body: TokenIn, response: Response, auth=Depends(require_api_auth), db: Session = Depends(get_db)
):
    user, hh_id = auth
    record, raw = issue_personal_token(
        db,
        user_id=user.id,
        household_id=hh_id,
        name=body.name,
        default_bucket_id=body.default_bucket_id,
        allow_classify=body.allow_classify,
    )
    db.commit()
    db.refresh(record)
    # Shown once: only the hash is stored, so it cannot be retrieved later.
    response.headers["Cache-Control"] = "no-store"
    return {**token_dict(record), "token": raw}


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    revoke_personal_token(db, token_id=token_id, user_id=user.id, household_id=hh_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
