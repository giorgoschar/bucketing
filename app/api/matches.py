"""
/api/v1/matches — "Looks like Cosmote · Oct · €38.90" (spec §3.5). Link marks
the entry done with that transaction; Not this dismisses it for good. Nothing
is ever linked without one of these taps.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.planning_models import EntryOut, MatchOut
from app.api_auth import require_api_auth
from app.core.database import get_db
from app.core.money import quantize
from app.models import MatchSuggestion
from app.services.bills import EntryStateError
from app.services.matching import dismiss_suggestion, link_suggestion, open_suggestions
from app.services.money import to_base
from app.services.planning import entry_for
from app.templates import format_currency

router = APIRouter(prefix="/matches", tags=["matches"])


def _match_out(db: Session, s: MatchSuggestion) -> MatchOut:
    txn, occ = s.transaction, s.occurrence
    amount = quantize(to_base(txn.amount, txn.exchange_rate))
    label = (
        f"Looks like {occ.bill.name} · {occ.due_date.strftime('%b')} · "
        f"{format_currency(txn.amount, txn.currency)}"
    )
    return MatchOut(
        id=s.id,
        label=label,
        transaction_id=txn.id,
        transaction_date=txn.transaction_date,
        transaction_amount=amount,
        merchant=txn.merchant,
        notes=txn.notes,
        entry=entry_for(db, occ),
    )


def _suggestion_or_404(db: Session, match_id: str, hh_id: str) -> MatchSuggestion:
    s = db.get(MatchSuggestion, match_id)
    if not s or s.household_id != hh_id:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return s


@router.get("", response_model=list[MatchOut])
def list_matches(auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    """Open suggestions, for Needs attention."""
    user, hh_id = auth
    return [_match_out(db, s) for s in open_suggestions(db, hh_id)]


@router.post("/{match_id}/link", response_model=EntryOut)
def link(match_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    s = _suggestion_or_404(db, match_id, hh_id)
    try:
        occ = link_suggestion(db, s)
    except EntryStateError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from None
    db.commit()
    return entry_for(db, occ)


@router.post("/{match_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(match_id: str, auth=Depends(require_api_auth), db: Session = Depends(get_db)):
    user, hh_id = auth
    dismiss_suggestion(_suggestion_or_404(db, match_id, hh_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
