"""Bulk changes to transactions (2c spec §5.3): preview and apply. Task 4
adds undo and the recent list, and Task 5 adds "Keep both" for duplicates.

app.api includes this router ahead of app.api.transactions, so the literal
/transactions/bulk is never read as /transactions/{txn_id}.
"""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.api.planning_models import Money
from app.api_auth import require_api_auth
from app.core.database import get_db
from app.services.bulk import Selection, run_bulk
from app.services.bulk_rules import Changes, Payer

router = APIRouter(prefix="/transactions", tags=["transactions"])

SELECT_KEYS = ("ids", "bill_id")


class PayerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "own_share"]
    user_id: str | None = None


class ChangesIn(BaseModel):
    """A key sent as null means "none"; an absent key leaves the field."""

    model_config = ConfigDict(extra="forbid")

    bucket_id: str | None = None
    category_id: str | None = None
    payer: PayerIn | None = None
    payment_method: str | None = None

    def to_changes(self) -> Changes:
        sent = self.model_fields_set
        if "payer" in sent and self.payer is None:
            raise HTTPException(status_code=400, detail="The payer can't be cleared in bulk.")
        if "payment_method" in sent and self.payment_method is None:
            raise HTTPException(status_code=400, detail="Choose a payment method.")
        return Changes(
            has_bucket="bucket_id" in sent,
            bucket_id=self.bucket_id,
            has_category="category_id" in sent,
            category_id=self.category_id,
            payer=Payer(self.payer.mode, self.payer.user_id) if self.payer else None,
            payment_method=self.payment_method,
        )


class SelectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = None
    bill_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        given = [k for k in SELECT_KEYS if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError(f"select needs exactly one of: {', '.join(SELECT_KEYS)}")
        return self

    def to_selection(self) -> Selection:
        return Selection(ids=self.ids, bill_id=self.bill_id)


class BulkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    select: SelectIn
    changes: ChangesIn
    move_bill: bool = False
    dry_run: bool = True
    expected_count: int | None = Field(default=None, ge=0)


class SkippedOut(BaseModel):
    id: str
    code: str
    reason: str


class BucketEffectOut(BaseModel):
    bucket_id: str | None  # None: "No bucket (Fixed costs)" this month
    name: str
    kind: str  # monthly | event | fixed
    budget: Money | None
    period_start: date | None
    period_end: date | None
    spent_before: Money
    spent_after: Money
    moved_in: Money
    moved_out: Money
    outside_period: int


class BillMoveOut(BaseModel):
    id: str
    name: str
    bucket_before: str | None  # bucket names; None: no bucket
    bucket_after: str | None


class BulkResult(BaseModel):
    dry_run: bool
    batch_id: str | None
    matched: int
    changed: int
    unchanged: int
    total_out: Money
    total_in: Money
    skipped: list[SkippedOut]
    buckets: list[BucketEffectOut]
    bill: BillMoveOut | None
    undo_until: datetime | None


@router.post("/bulk", response_model=BulkResult)
def bulk_change(
    body: BulkIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Preview (``dry_run``, the default) or apply one change to a selection.
    Apply re-checks ``expected_count`` (409 on drift) and writes all or nothing."""
    user, hh_id = auth
    return run_bulk(
        db,
        household_id=hh_id,
        user_id=user.id,
        select=body.select.to_selection(),
        changes=body.changes.to_changes(),
        move_bill=body.move_bill,
        dry_run=body.dry_run,
        expected_count=body.expected_count,
    )
