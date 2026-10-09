"""Response models for the planning endpoints (spec §6.3).

The services keep money as Decimal; on the wire it is a JSON number, as the
older dict endpoints already send it, so the generated TypeScript types say
``number``. Projections carry their name (``still_to_come``, ``projected``,
``net_projected``, ``pace``) and ``estimated`` marks a "≈" amount.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_id: str
    name: str
    direction: str
    due_date: date
    status: str  # expected | done | skipped
    amount: Money | None
    estimated: bool
    currency: str
    bucket_id: str | None
    category_id: str | None
    transaction_id: str | None
    overdue: bool
    infrequent: bool
    payment_method: str
    usage: Money | None = None  # in the item's usage_unit
    usage_unit: str | None = None


class SplitOut(BaseModel):
    user_id: str
    amount: Money


class RecurringItemOut(BaseModel):
    id: str
    name: str
    direction: str
    amount: Money | None
    currency: str
    category_id: str | None
    bucket_id: str | None
    rule_kind: str
    interval_months: int
    rule_day: int | None
    rule_month: int | None
    rule_adjust: str
    rule_days: int | None
    rule_weekday: int | None
    rule_interval_weeks: int | None
    start_date: date
    end_date: date | None
    total_occurrences: int | None
    contract_end_date: date | None
    paid_by_default: str | None
    payer_mode: str
    payment_method: str
    is_auto_pay: bool
    is_active: bool
    notes: str | None
    usage_unit: str | None = None
    splits: list[SplitOut]
    next_entry: EntryOut | None
    # Paid or skipped-with-amount occurrences, or linked transactions: locks direction and currency.
    has_history: bool


class MatchOut(BaseModel):
    id: str
    label: str  # "Looks like Cosmote · Oct · €38.90"
    transaction_id: str
    transaction_date: date
    transaction_amount: Money
    merchant: str | None
    notes: str | None
    entry: EntryOut


class MonthRowOut(BaseModel):
    so_far: Money
    still_to_come: Money
    projected: Money


class BucketMonthRowOut(MonthRowOut):
    bucket_id: str
    name: str
    budget: Money | None


class BucketsMonthOut(MonthRowOut):
    rows: list[BucketMonthRowOut]


class MonthPictureOut(BaseModel):
    month: str
    income: MonthRowOut
    fixed: MonthRowOut
    buckets: BucketsMonthOut
    net_projected: Money
    events_spent: Money
    cash: Money
    estimated: bool


class UpcomingDayOut(BaseModel):
    date: date
    entries: list[EntryOut]
    net_this_month: Money


class YearMonthOut(BaseModel):
    month: str
    income: Money
    out: Money
    estimated: bool


class YearOut(BaseModel):
    months: list[YearMonthOut]
    infrequent_monthly_average: Money
    estimated: bool


class BudgetRowOut(BaseModel):
    bucket_id: str
    name: str
    kind: str  # monthly | event
    budget: Money | None
    spent: Money
    pct: Money | None
    period_start: date | None
    period_end: date | None
    days_left: int | None
    archive_suggested: bool


class PaceOut(BaseModel):
    bucket_id: str
    name: str
    budget: Money
    spent: Money
    pct: Money
    pace: Money | None
    over_pace: bool


class CategoryUsualOut(BaseModel):
    category_id: str | None
    name: str
    icon: str
    color: str
    this_month: Money
    usual: Money | None
    flagged: bool
