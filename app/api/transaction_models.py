"""Response models for the Activity endpoints (2c spec §5.1-5.2).

Money is a JSON number (planning_models.Money), so the generated TypeScript
types say ``number``.
"""

from datetime import date, datetime

from pydantic import BaseModel

from app.api.planning_models import Money


class TransactionSplitOut(BaseModel):
    user_id: str
    amount: Money
    is_settled: bool


class TransactionOut(BaseModel):
    id: str
    bucket_id: str | None
    household_id: str
    amount: Money
    currency: str | None
    exchange_rate: float
    type: str
    paid_by: str | None
    payer_mode: str | None
    category_id: str | None
    notes: str | None
    transaction_date: date | None
    receipt_path: str | None
    payment_method: str
    merchant: str | None
    fuel_price_per_litre: Money | None
    fuel_litres: Money | None
    exclude_from_forecast: bool
    exclude_from_settlement: bool
    recurring_bill_id: str | None
    created_at: datetime | None
    splits: list[TransactionSplitOut]
    has_take: bool  # a cash take is linked to it (swipe and bulk keep it cash)
    missing_payer: bool  # an expense with a single payer not yet recorded


class TransactionPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[TransactionOut]
    # Each date on this page -> its net over the WHOLE filter (income -
    # expenses, base currency, transfers excluded), so it is right across pages.
    day_totals: dict[str, Money]


class CountsOut(BaseModel):
    no_payer: int
    duplicate_groups: int


class DuplicateGroupOut(BaseModel):
    amount: Money
    transactions: list[TransactionOut]


class DuplicatesOut(BaseModel):
    groups: list[DuplicateGroupOut]


class HistoryEventOut(BaseModel):
    at: datetime
    kind: str  # created | entry_linked | cash_taken | bulk_change | bulk_undone
    by: str | None
    text: str
    batch_id: str | None = None
    can_undo: bool = False


class HistoryOut(BaseModel):
    events: list[HistoryEventOut]
