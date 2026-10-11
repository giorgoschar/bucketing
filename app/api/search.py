"""/api/v1/search: one box over entries, recurring items and the pantry
(Phase C spec §4.1)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from limits import parse
from sqlalchemy.orm import Session

from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.ratelimit import limiter
from app.services.category_rules import has_control_char
from app.services.search import MAX_QUERY, MIN_QUERY, SearchOut, search

router = APIRouter(prefix="/search", tags=["search"])

SEARCH_RATE = "60/minute"


@router.get(
    "",
    response_model=SearchOut,
    responses={
        400: {"description": "q is shorter than 2 or longer than 100 characters"},
        429: {"description": "More than 60 searches a minute for this user"},
    },
)
def search_everything(
    q: str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    user, hh_id = auth
    # Per user and after authentication: an anonymous caller never spends it.
    if not limiter.limiter.hit(parse(SEARCH_RATE), "search", user.id):
        raise HTTPException(status_code=429, detail="Too many searches. Try again in a minute.")
    text = q.strip()
    if not MIN_QUERY <= len(text) <= MAX_QUERY:
        raise HTTPException(
            status_code=400,
            detail=f"Search for {MIN_QUERY} to {MAX_QUERY} characters.",
        )
    if has_control_char(text):
        raise HTTPException(
            status_code=400, detail="Search text cannot contain control characters."
        )
    return search(db, hh_id, text)
