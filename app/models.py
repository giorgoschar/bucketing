import uuid
from datetime import datetime, date

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date,
    ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.orm import relationship
import enum

from app.database import Base


def gen_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TransactionType(str, enum.Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"


class BucketType(str, enum.Enum):
    day2day = "day2day"
    trip = "trip"
    bills = "bills"
    savings = "savings"
    custom = "custom"


class BucketStatus(str, enum.Enum):
    active = "active"
    archived = "archived"


class MemberRole(str, enum.Enum):
    owner = "owner"
    member = "member"


class BillFrequency(str, enum.Enum):
    monthly = "monthly"
    custom = "custom"


class OccurrenceStatus(str, enum.Enum):
    unpaid = "unpaid"
    paid = "paid"
    skipped = "skipped"


# ---------------------------------------------------------------------------
# Users & Households
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    username = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String, nullable=False)
    avatar_color = Column(String(7), default="#6366f1")  # hex color
    created_at = Column(DateTime, default=datetime.utcnow)

    memberships = relationship("HouseholdMember", back_populates="user")
    paid_transactions = relationship("Transaction", back_populates="paid_by_user")
    splits = relationship("TransactionSplit", back_populates="user")
    invitations_created = relationship("Invitation", foreign_keys="Invitation.created_by", back_populates="created_by_user")


class Household(Base):
    __tablename__ = "households"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String(100), nullable=False)
    default_currency = Column(String(3), default="EUR")
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("HouseholdMember", back_populates="household")
    buckets = relationship("Bucket", back_populates="household")
    categories = relationship("Category", back_populates="household")
    recurring_bills = relationship("RecurringBill", back_populates="household")
    invitations = relationship("Invitation", back_populates="household")


class HouseholdMember(Base):
    __tablename__ = "household_members"

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(SAEnum(MemberRole), default=MemberRole.member, nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)

    household = relationship("Household", back_populates="members")
    user = relationship("User", back_populates="memberships")


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    token = Column(String, unique=True, nullable=False, index=True, default=gen_id)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)
    used_by = Column(String, ForeignKey("users.id"), nullable=True)

    household = relationship("Household", back_populates="invitations")
    created_by_user = relationship("User", foreign_keys=[created_by], back_populates="invitations_created")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=True)  # null = system default
    name = Column(String(50), nullable=False)
    color = Column(String(7), default="#6366f1")  # hex
    icon = Column(String(10), default="📦")  # emoji
    is_default = Column(Boolean, default=False)

    household = relationship("Household", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category")
    recurring_bills = relationship("RecurringBill", back_populates="category")


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------

class Bucket(Base):
    __tablename__ = "buckets"

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    type = Column(SAEnum(BucketType), default=BucketType.custom, nullable=False)
    color = Column(String(7), default="#6366f1")
    icon = Column(String(10), default="🪣")
    status = Column(SAEnum(BucketStatus), default=BucketStatus.active, nullable=False)
    budget = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    show_income = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    household = relationship("Household", back_populates="buckets")
    transactions = relationship("Transaction", back_populates="bucket")
    recurring_bills = relationship("RecurringBill", back_populates="bucket")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=gen_id)
    bucket_id = Column(String, ForeignKey("buckets.id", ondelete="CASCADE"), nullable=False)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="EUR")
    exchange_rate = Column(Float, default=1.0)  # rate to household default currency
    type = Column(SAEnum(TransactionType), default=TransactionType.expense, nullable=False)
    paid_by = Column(String, ForeignKey("users.id"), nullable=True)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    notes = Column(Text, nullable=True)
    transaction_date = Column(Date, default=date.today, nullable=False)
    receipt_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    bucket = relationship("Bucket", back_populates="transactions")
    paid_by_user = relationship("User", back_populates="paid_transactions")
    category = relationship("Category", back_populates="transactions")
    splits = relationship("TransactionSplit", back_populates="transaction", cascade="all, delete-orphan")
    bill_occurrence = relationship("BillOccurrence", back_populates="transaction", uselist=False)


class TransactionSplit(Base):
    __tablename__ = "transaction_splits"

    id = Column(String, primary_key=True, default=gen_id)
    transaction_id = Column(String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)  # this person's share
    is_settled = Column(Boolean, default=False)
    settled_at = Column(DateTime, nullable=True)

    transaction = relationship("Transaction", back_populates="splits")
    user = relationship("User", back_populates="splits")


# ---------------------------------------------------------------------------
# Recurring Bills
# ---------------------------------------------------------------------------

class RecurringBill(Base):
    __tablename__ = "recurring_bills"

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    bucket_id = Column(String, ForeignKey("buckets.id"), nullable=True)
    name = Column(String(100), nullable=False)
    amount = Column(Float, nullable=True)  # null = variable (e.g. electricity)
    currency = Column(String(3), default="EUR")
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    frequency = Column(SAEnum(BillFrequency), default=BillFrequency.monthly, nullable=False)
    interval_months = Column(Integer, default=1)  # every N months
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # null = indefinite
    total_occurrences = Column(Integer, nullable=True)  # null = indefinite
    paid_by_default = Column(String, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_auto_pay = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    household = relationship("Household", back_populates="recurring_bills")
    bucket = relationship("Bucket", back_populates="recurring_bills")
    category = relationship("Category", back_populates="recurring_bills")
    occurrences = relationship("BillOccurrence", back_populates="bill", cascade="all, delete-orphan")
    splits = relationship("RecurringBillSplit", back_populates="bill", cascade="all, delete-orphan")


class BillOccurrence(Base):
    __tablename__ = "bill_occurrences"

    id = Column(String, primary_key=True, default=gen_id)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="CASCADE"), nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=True)  # overrides bill.amount for variable bills
    status = Column(SAEnum(OccurrenceStatus), default=OccurrenceStatus.unpaid, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    paid_by = Column(String, ForeignKey("users.id"), nullable=True)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=True)

    bill = relationship("RecurringBill", back_populates="occurrences")
    transaction = relationship("Transaction", back_populates="bill_occurrence")


class RecurringBillSplit(Base):
    __tablename__ = "recurring_bill_splits"

    id = Column(String, primary_key=True, default=gen_id)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)

    bill = relationship("RecurringBill", back_populates="splits")
    user = relationship("User")
