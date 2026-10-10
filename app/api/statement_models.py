"""Response models for the month statements (Phase B spec §3.2-§3.4)."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.api.planning_models import Money


class StatementPreviousOut(BaseModel):
    month: str
    in_: Money = Field(alias="in")
    out: Money
    net: Money


class StatementTotalsOut(BaseModel):
    in_: Money = Field(alias="in")
    out: Money
    net: Money
    previous: StatementPreviousOut | None


class PlannedSideOut(BaseModel):
    planned: Money
    actual: Money


class OpenEntryOut(BaseModel):
    entry_id: str
    item_id: str
    name: str
    direction: str
    due_date: date
    amount: Money | None
    estimated: bool
    status: str  # expected


class StatementPlannedOut(BaseModel):
    in_: PlannedSideOut = Field(alias="in")
    out: PlannedSideOut
    open: list[OpenEntryOut]


class BudgetOverOut(BaseModel):
    bucket_id: str
    name: str
    budget: Money
    spent: Money
    over: Money


class BillChangedOut(BaseModel):
    item_id: str
    name: str
    entry_id: str
    due_date: date
    amount: Money
    usual: Money
    basis: str  # last_year | recent
    direction: str  # up | down
    pct: int
    reason: str | None  # usage | price
    reason_pct: int | None


class CashLeftOut(BaseModel):
    member_id: str
    name: str
    not_yet_logged: Money


class CategoryOverOut(BaseModel):
    category_id: str | None
    name: str
    icon: str
    amount: Money
    usual: Money


class BiggestOut(BaseModel):
    transaction_id: str
    date: date
    label: str
    category: str | None
    amount: Money


class StatementOut(BaseModel):
    month: str
    label: str
    reviewed_at: datetime | None
    reviewed_on: date | None  # reviewed_at on the household's calendar
    reviewed_by: str | None  # a user id
    reviewed_by_name: str | None  # display name, else username
    closed: bool
    days_left: int | None
    totals: StatementTotalsOut
    planned: StatementPlannedOut
    budgets_over: list[BudgetOverOut]
    bills_changed: list[BillChangedOut]
    cash: list[CashLeftOut]
    categories_over: list[CategoryOverOut]
    biggest: list[BiggestOut]


class StatementReviewOut(BaseModel):
    month: str
    label: str
    days_left: int


class StatementMonthOut(BaseModel):
    month: str
    label: str
    in_: Money = Field(alias="in")
    out: Money
    net: Money
    reviewed_at: datetime | None
    reviewed_on: date | None
    reviewed_by: str | None
    reviewed_by_name: str | None
    closed: bool


class StatementListOut(BaseModel):
    review: StatementReviewOut | None
    months: list[StatementMonthOut]
