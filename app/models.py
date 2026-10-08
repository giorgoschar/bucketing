import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    and_,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship, validates

from app.core.clock import local_today, utcnow_naive
from app.core.database import Base
from app.core.schedule import RuleAdjust, RuleKind  # noqa: F401  (re-exported)


def gen_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TransactionType(str, enum.Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"


class PaymentMethod(str, enum.Enum):
    """How an expense was paid. Stored as a plain VARCHAR (no DB enum type) so
    adding a member never needs ALTER TYPE; validated in app.schemas."""

    card = "card"
    cash = "cash"
    apple_pay = "apple_pay"
    transfer = "transfer"
    other = "other"


class PayerMode(str, enum.Enum):
    """Who fronted an expense. Stored as a plain VARCHAR like PaymentMethod.

    ``single``: one member (``paid_by``) paid the whole amount — or nobody is
    recorded yet. ``own_share``: every member paid their own split directly
    (rent paid 800 / 300 straight to the landlord), so ``paid_by`` is NULL and
    the splits are both what each person owes and what each person paid.
    """

    single = "single"
    own_share = "own_share"


class CashKind(str, enum.Enum):
    """What a cash movement is (see app.services.cash). Plain VARCHAR like
    PaymentMethod.

    ``stash_in``: cash added to the member's own stash. ``take``: cash into
    their wallet, from a stash (``stash_owner_id``) or the bank (NULL).
    ``put_back``: wallet back into their own stash. ``still_have``: what was
    in their wallet on that date. ``out``: legacy, no longer offered: cash
    that left the wallet without a logged expense. ``stash_count``: a
    recount of the member's own stash, stored as the signed correction
    (counted minus the balance then), so it may be negative or zero.
    """

    stash_in = "stash_in"
    take = "take"
    put_back = "put_back"
    still_have = "still_have"
    out = "out"
    stash_count = "stash_count"


class BucketType(str, enum.Enum):
    day2day = "day2day"
    trip = "trip"
    bills = "bills"
    savings = "savings"
    custom = "custom"


class BucketKind(str, enum.Enum):
    """What a bucket's budget means (spec §4.1). Plain VARCHAR like PaymentMethod."""

    monthly = "monthly"  # per calendar month, resets on the 1st
    event = "event"  # a total over start_date..end_date


def kind_for_type(bucket_type) -> str:
    """The kind an old-app bucket type stands for: a trip is an event, every
    other type is monthly."""
    if BucketType(bucket_type) == BucketType.trip:
        return BucketKind.event.value
    return BucketKind.monthly.value


class ItemDirection(str, enum.Enum):
    """Which way a recurring item's money goes. Plain VARCHAR like PaymentMethod."""

    out = "out"  # bills: DEH, Cosmote, rent paid
    in_ = "in"  # salaries, rent received


def default_payment_method(direction: str | None) -> str:
    """How an item's payments are recorded when nobody picks a method (2d §7.0):
    transfer for income (what Mark received always recorded), card otherwise."""
    if direction == ItemDirection.in_.value:
        return PaymentMethod.transfer.value
    return PaymentMethod.card.value


def _item_payment_method_default(context) -> str:
    return default_payment_method(context.get_current_parameters().get("direction"))


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


class NotificationType(str, enum.Enum):
    bill_due = "bill_due"
    bill_overdue = "bill_overdue"
    bill_auto_paid = "bill_auto_paid"
    contract_expiring = "contract_expiring"
    bill_drift = "bill_drift"  # bill cost moved vs its own history
    budget_warning = "budget_warning"  # bucket spend crossed a budget threshold
    ingest_created = "ingest_created"  # an expense arrived via the Apple Pay Shortcut
    general = "general"
    stock_low = "stock_low"  # a stock item fell to its minimum
    price_drop = "price_drop"  # tracked product ≥10% under its 30-day median
    # WARNING: on PostgreSQL this is a native ENUM type (created in migration
    # 2c1adaf99fa2), so adding a member here REQUIRES a migration running
    # ALTER TYPE notificationtype ADD VALUE — otherwise inserts fail at runtime
    # with "invalid input value for enum notificationtype". SQLite renders it as
    # VARCHAR, so the test suite will not catch a missing one; see
    # test_migrations.py::test_notification_enum_members_are_all_migrated.


# ---------------------------------------------------------------------------
# Users & Households
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(254), unique=True, nullable=True, index=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    # Pocket ID subject ("sub"); set the first time this user signs in with a passkey.
    oidc_subject = Column(String(255), unique=True, nullable=True)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String, nullable=False)
    avatar_color = Column(String(7), default="#6366f1")  # hex color
    created_at = Column(DateTime, default=utcnow_naive)
    session_version = Column(Integer, default=0, nullable=False)
    # Per-account lockout (see app.auth.register_failed_login)
    failed_logins = Column(Integer, default=0, server_default="0", nullable=False)
    locked_until = Column(DateTime, nullable=True)
    # Fernet ciphertext ("enc:..."); legacy rows may still hold plaintext. Use
    # get_totp_secret()/set_totp_secret() rather than touching this directly.
    totp_secret = Column(String(512), nullable=True)
    # Last accepted 30s TOTP step — a code at or before it is a replay.
    last_totp_step = Column(BigInteger, nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    totp_backup_codes = Column(Text, nullable=True)  # JSON array of bcrypt-hashed codes

    def get_totp_secret(self) -> str | None:
        from app.core.crypto import decrypt_str

        return decrypt_str(self.totp_secret) if self.totp_secret else None

    def set_totp_secret(self, secret: str | None) -> None:
        from app.core.crypto import encrypt_str

        self.totp_secret = encrypt_str(secret) if secret else None

    memberships = relationship("HouseholdMember", back_populates="user")
    paid_transactions = relationship("Transaction", back_populates="paid_by_user")
    splits = relationship("TransactionSplit", back_populates="user")
    invitations_created = relationship(
        "Invitation", foreign_keys="Invitation.created_by", back_populates="created_by_user"
    )


class Household(Base):
    __tablename__ = "households"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String(100), nullable=False)
    default_currency = Column(String(3), default="EUR")
    created_at = Column(DateTime, default=utcnow_naive)
    # Set when the last member leaves. The household and all its data are kept;
    # only scripts/purge_household.py may hard-delete it.
    archived_at = Column(DateTime, nullable=True)

    members = relationship("HouseholdMember", back_populates="household")
    buckets = relationship("Bucket", back_populates="household")
    categories = relationship("Category", back_populates="household")
    recurring_bills = relationship("RecurringBill", back_populates="household")
    invitations = relationship("Invitation", back_populates="household")


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="uq_household_member"),
        Index("ix_household_members_household_id", "household_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(SAEnum(MemberRole), default=MemberRole.member, nullable=False)
    joined_at = Column(DateTime, default=utcnow_naive)

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
    created_by_user = relationship(
        "User", foreign_keys=[created_by], back_populates="invitations_created"
    )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

# ``Category.system_key`` of the built-in Fuel category (see app.seed).
FUEL_SYSTEM_KEY = "fuel"


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        Index("ix_categories_household_id", "household_id"),
        # One of each built-in category per household.
        UniqueConstraint("household_id", "system_key", name="uq_categories_household_system_key"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(
        String, ForeignKey("households.id", ondelete="CASCADE"), nullable=True
    )  # null = system default
    name = Column(String(50), nullable=False)
    color = Column(String(7), default="#6366f1")  # hex
    icon = Column(String(10), default="📦")  # emoji
    is_default = Column(Boolean, default=False)
    # Set on categories the app itself relies on (FUEL_SYSTEM_KEY unlocks the
    # litres fields). Such a category is locked: no rename, recolour, new icon
    # or delete, so the feature can always find it. NULL for everything else.
    system_key = Column(String(32), nullable=True)

    @property
    def is_locked(self) -> bool:
        return self.system_key is not None

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
    budget = Column(Numeric(12, 4), nullable=True)
    description = Column(Text, nullable=True)
    show_income = Column(Boolean, default=True, nullable=False)
    enable_settlement = Column(Boolean, default=False, nullable=False)
    # Trip buckets: the dates the trip runs. Savings buckets: goal_amount is the
    # target and end_date the date to hit it by. Both were previously types with
    # no behaviour attached — only filter labels.
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    goal_amount = Column(Numeric(12, 4), nullable=True)
    # monthly or event (spec §4.1). Follows ``type`` (see kind_for_type), so
    # the old app's forms keep it right without knowing about it.
    kind = Column(
        String(8),
        default=BucketKind.monthly.value,
        server_default=BucketKind.monthly.value,
        nullable=False,
    )
    created_at = Column(DateTime, default=utcnow_naive)

    @validates("type")
    def _kind_follows_type(self, _key, value):
        self.kind = kind_for_type(value)
        return value

    household = relationship("Household", back_populates="buckets")
    transactions = relationship("Transaction", back_populates="bucket")
    recurring_bills = relationship("RecurringBill", back_populates="bucket")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

# Expenses and transfers need a bucket; income may have none, and neither may
# an expense paid for a recurring item (a Fixed cost, spec §3.4). The enum is
# stored by name ('income'), on SQLite and in the Postgres enum alike.
BUCKET_UNLESS_INCOME_SQL = (
    "bucket_id IS NOT NULL OR type = 'income' OR recurring_bill_id IS NOT NULL"
)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_household_date", "household_id", "transaction_date"),
        Index("ix_transactions_bucket_id", "bucket_id"),
        Index("ix_transactions_deleted_at", "deleted_at"),
        Index("ix_transactions_paid_by", "paid_by"),
        Index("ix_transactions_category_id", "category_id"),
        Index("ix_transactions_recurring_bill_id", "recurring_bill_id"),
        # NULLs do not collide, so only offline submissions are constrained.
        UniqueConstraint("household_id", "client_id", name="uq_transaction_client_id"),
        # Only income may go without a bucket (see TransactionCreate).
        CheckConstraint(BUCKET_UNLESS_INCOME_SQL, name="ck_transactions_bucket_unless_income"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    # NULL only for income: a household that does not track income in buckets
    # logs it bucket-less (it then always counts as income, see insights).
    bucket_id = Column(String, ForeignKey("buckets.id", ondelete="CASCADE"), nullable=True)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 4), nullable=False)
    currency = Column(String(3), default="EUR")
    exchange_rate = Column(Numeric(12, 6), default=1.0)  # rate to household default currency
    type = Column(SAEnum(TransactionType), default=TransactionType.expense, nullable=False)
    paid_by = Column(String, ForeignKey("users.id"), nullable=True)
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    notes = Column(Text, nullable=True)
    transaction_date = Column(Date, default=local_today, nullable=False)
    receipt_path = Column(String, nullable=True)
    payment_method = Column(
        String(16),
        default=PaymentMethod.card.value,
        server_default=PaymentMethod.card.value,
        nullable=False,
    )
    merchant = Column(String(200), nullable=True)
    payer_mode = Column(
        String(16),
        default=PayerMode.single.value,
        server_default=PayerMode.single.value,
        nullable=False,
    )
    # Fuel expenses only (the household's FUEL_SYSTEM_KEY category): the price
    # per litre, in the transaction currency, and the litres the server works
    # out from it (amount / price). Both NULL for anything else.
    fuel_price_per_litre = Column(Numeric(8, 4), nullable=True)
    fuel_litres = Column(Numeric(10, 3), nullable=True)
    exclude_from_forecast = Column(Boolean, default=False, nullable=False)
    # Keep this expense out of the settle-up maths while still counting it as
    # household spending. For costs that are shared with people outside the
    # household, or that both members already consider square.
    exclude_from_settlement = Column(Boolean, default=False, nullable=False)
    # Client-generated id for offline submissions. A queued expense may be
    # retried after the response was lost, so the server must recognise the
    # repeat instead of creating a second transaction.
    client_id = Column(String(64), nullable=True)
    # The recurring item this expense pays or this income receives (spec
    # §3.3): set by Pay, Mark received and Link. A bucket-less expense needs it.
    recurring_bill_id = Column(
        String,
        ForeignKey(
            "recurring_bills.id", ondelete="SET NULL", name="fk_transactions_recurring_bill_id"
        ),
        nullable=True,
    )
    created_at = Column(DateTime, default=utcnow_naive)
    # Soft delete: set (naive UTC) instead of removing the row. Every read
    # query must filter with Transaction.active().
    deleted_at = Column(DateTime, nullable=True)

    @classmethod
    def active(cls):
        """Filter expression selecting transactions that are not soft-deleted."""
        return cls.deleted_at.is_(None)

    @classmethod
    def missing_payer(cls):
        """Filter expression for expenses nobody is credited with paying.

        An own-share expense has no ``paid_by`` by design; it is fully paid.
        """
        return and_(cls.payer_mode == PayerMode.single.value, cls.paid_by.is_(None))

    bucket = relationship("Bucket", back_populates="transactions")
    paid_by_user = relationship("User", back_populates="paid_transactions")
    category = relationship("Category", back_populates="transactions")
    splits = relationship(
        "TransactionSplit", back_populates="transaction", cascade="all, delete-orphan"
    )
    bill_occurrence = relationship("BillOccurrence", back_populates="transaction", uselist=False)


class CashMovement(Base):
    """Cash ledger entry: one member's stash or wallet (see app.services.cash
    and CashKind).

    ``user_id`` is whose stash or wallet it is (for a ``take``: the taker's
    wallet). ``stash_owner_id`` is the stash a ``take`` came out of, NULL for
    the bank. ``transaction_id`` links a ``take`` to the cash expense it was
    taken for ("I took this from my stash"). Amounts are in the household
    currency. Soft-deleted.
    """

    __tablename__ = "cash_movements"
    __table_args__ = (
        Index("ix_cash_movements_hh_user_date", "household_id", "user_id", "movement_date"),
        Index("ix_cash_movements_stash_owner_id", "stash_owner_id"),
        Index("ix_cash_movements_transaction_id", "transaction_id"),
        # The PWA's retry key (polish C5); not unique: the replay window is 24 h.
        Index("ix_cash_movements_hh_client_id", "household_id", "client_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    kind = Column(String(16), nullable=False)  # a CashKind value
    stash_owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    amount = Column(Numeric(12, 4), nullable=False)
    currency = Column(String(3), nullable=False, default="EUR")
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    note = Column(String(500), nullable=True)
    movement_date = Column(Date, default=local_today, nullable=False)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=utcnow_naive)
    deleted_at = Column(DateTime, nullable=True)
    # A client-generated uuid4 per cash save: a retry within 24 h returns the
    # movement it already made (polish C5).
    client_id = Column(String(36), nullable=True)

    @classmethod
    def active(cls):
        return cls.deleted_at.is_(None)


class TransactionSplit(Base):
    __tablename__ = "transaction_splits"
    __table_args__ = (
        Index("ix_transaction_splits_transaction_id", "transaction_id"),
        Index("ix_transaction_splits_user_id", "user_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 4), nullable=False)  # this person's share
    is_settled = Column(Boolean, default=False)
    settled_at = Column(DateTime, nullable=True)

    transaction = relationship("Transaction", back_populates="splits")
    user = relationship("User", back_populates="splits")


# ---------------------------------------------------------------------------
# Recurring Bills
# ---------------------------------------------------------------------------


class RecurringBill(Base):
    __tablename__ = "recurring_bills"
    __table_args__ = (Index("ix_recurring_bills_household_id", "household_id"),)

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    bucket_id = Column(String, ForeignKey("buckets.id"), nullable=True)
    name = Column(String(100), nullable=False)
    amount = Column(Numeric(12, 4), nullable=True)  # null = variable (e.g. electricity)
    currency = Column(String(3), default="EUR")
    category_id = Column(String, ForeignKey("categories.id"), nullable=True)
    frequency = Column(SAEnum(BillFrequency), default=BillFrequency.monthly, nullable=False)
    interval_months = Column(Integer, default=1)  # every N months
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # null = indefinite
    contract_end_date = Column(Date, nullable=True)  # telco/power contract expiry
    total_occurrences = Column(Integer, nullable=True)  # null = indefinite
    paid_by_default = Column(String, ForeignKey("users.id"), nullable=True)
    # own_share: each payment is recorded as everyone paying their default
    # split directly (see PayerMode); paid_by_default is then unused.
    payer_mode = Column(
        String(16),
        default=PayerMode.single.value,
        server_default=PayerMode.single.value,
        nullable=False,
    )
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_auto_pay = Column(Boolean, default=False, nullable=False)
    # Planning redesign (spec §3.1-3.2): which way the money goes and the
    # schedule rule (app.core.schedule). Rows from before it are out +
    # monthly_interval, whose dates are exactly the old generator's.
    direction = Column(
        String(8),
        default=ItemDirection.out.value,
        server_default=ItemDirection.out.value,
        nullable=False,
    )
    rule_kind = Column(
        String(24),
        default=RuleKind.monthly_interval.value,
        server_default=RuleKind.monthly_interval.value,
        nullable=False,
    )
    rule_day = Column(Integer, nullable=True)  # monthly_day, yearly
    rule_month = Column(Integer, nullable=True)  # yearly
    rule_adjust = Column(
        String(24),
        default=RuleAdjust.none.value,
        server_default=RuleAdjust.none.value,
        nullable=False,
    )
    rule_days = Column(Integer, nullable=True)  # easter_offset: days from Easter Sunday
    rule_weekday = Column(Integer, nullable=True)  # weekly: 0 = Monday
    rule_interval_weeks = Column(Integer, nullable=True)  # weekly
    # How a payment of this item is recorded when the payer picks none: one-tap
    # Pay, auto-pay, Mark received (2d §7.0). Plain VARCHAR like PaymentMethod.
    payment_method = Column(
        String(16),
        default=_item_payment_method_default,
        server_default=PaymentMethod.card.value,
        nullable=False,
    )
    created_at = Column(DateTime, default=utcnow_naive)

    @property
    def old_app_editable(self) -> bool:
        """The old app edits only out items on the legacy rule (spec §6.2)."""
        return (self.direction or ItemDirection.out.value) == ItemDirection.out.value and (
            self.rule_kind or RuleKind.monthly_interval.value
        ) == RuleKind.monthly_interval.value

    @classmethod
    def active_filter(cls):
        """Filter expression: not paused (spec §3.4.1). NULL counts as active."""
        return cls.is_active.isnot(False)

    household = relationship("Household", back_populates="recurring_bills")
    bucket = relationship("Bucket", back_populates="recurring_bills")
    category = relationship("Category", back_populates="recurring_bills")
    occurrences = relationship(
        "BillOccurrence", back_populates="bill", cascade="all, delete-orphan"
    )
    splits = relationship("RecurringBillSplit", back_populates="bill", cascade="all, delete-orphan")


class BillOccurrence(Base):
    __tablename__ = "bill_occurrences"
    __table_args__ = (
        UniqueConstraint("bill_id", "due_date", name="uq_bill_occurrence"),
        Index("ix_bill_occurrences_bill_status", "bill_id", "due_date", "status"),
        Index("ix_bill_occurrences_bill_period", "bill_id", "period"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="CASCADE"), nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 4), nullable=True)  # overrides bill.amount for variable bills
    status = Column(SAEnum(OccurrenceStatus), default=OccurrenceStatus.unpaid, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    paid_by = Column(String, ForeignKey("users.id"), nullable=True)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=True)
    # The rule's period for this entry, before business-day adjustment:
    # "YYYY-MM", "YYYY-Www" (weekly) or "YYYY" (app.core.schedule.period_key).
    # An item never gets two entries in one period. NULL on rows the old app
    # writes; generation reads those by their due date's month.
    period = Column(String(10), nullable=True)
    # When auto-pay settled this entry. Auto-pay never claims an entry it has
    # settled before, so an undone or deleted auto-payment stays undone.
    # Undo and delete leave it set.
    auto_paid_at = Column(DateTime, nullable=True)

    bill = relationship("RecurringBill", back_populates="occurrences")
    transaction = relationship("Transaction", back_populates="bill_occurrence")


class MatchSuggestion(Base):
    """ "Looks like Cosmote · Oct": a transaction that may be an expected entry
    (spec §3.5). Nothing is linked without a tap: Link marks the entry done,
    Not this sets ``dismissed`` and the pair is never suggested again."""

    __tablename__ = "match_suggestions"
    __table_args__ = (
        UniqueConstraint("transaction_id", "occurrence_id", name="uq_match_suggestion"),
        Index("ix_match_suggestions_household", "household_id", "dismissed"),
        Index("ix_match_suggestions_occurrence", "occurrence_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    occurrence_id = Column(
        String, ForeignKey("bill_occurrences.id", ondelete="CASCADE"), nullable=False
    )
    dismissed = Column(Boolean, default=False, server_default=text("false"), nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)

    transaction = relationship("Transaction")
    occurrence = relationship("BillOccurrence")


# ---------------------------------------------------------------------------
# Bulk changes and dismissed duplicates (2c spec §5.3-5.5)
# ---------------------------------------------------------------------------


class BulkBatch(Base):
    """One applied bulk change: what it set, on how many rows, and the
    recurring item it moved. Undone at most once, within 24 hours of
    ``created_at`` (app.services.bulk). Never purged."""

    __tablename__ = "bulk_batches"
    __table_args__ = (Index("ix_bulk_batches_household_created", "household_id", "created_at"),)

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    undone_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    undone_at = Column(DateTime, nullable=True)
    selection = Column(String(8), nullable=False)  # ids | filter | bill
    fields = Column(String(64), nullable=False)  # comma list: bucket,category,payer,method
    summary = Column(String(200), nullable=False)
    row_count = Column(Integer, nullable=False)
    total_out = Column(Numeric(12, 4), nullable=False)
    total_in = Column(Numeric(12, 4), nullable=False)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="SET NULL"), nullable=True)
    bill_bucket_old = Column(String, nullable=True)
    bill_bucket_new = Column(String, nullable=True)
    bill_moved = Column(Boolean, default=False, server_default=text("false"), nullable=False)

    rows = relationship("BulkBatchRow", back_populates="batch", cascade="all, delete-orphan")


class BulkBatchRow(Base):
    """The old and new values of one transaction in a batch. Plain strings
    with no FKs, so the history reads the same after a bucket, category or
    member is gone (undo then skips the row, U3)."""

    __tablename__ = "bulk_batch_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "transaction_id", name="uq_bulk_batch_row"),
        Index("ix_bulk_batch_rows_transaction_id", "transaction_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    batch_id = Column(String, ForeignKey("bulk_batches.id", ondelete="CASCADE"), nullable=False)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    old_bucket_id = Column(String, nullable=True)
    new_bucket_id = Column(String, nullable=True)
    old_category_id = Column(String, nullable=True)
    new_category_id = Column(String, nullable=True)
    old_paid_by = Column(String, nullable=True)
    new_paid_by = Column(String, nullable=True)
    old_payer_mode = Column(String(16), nullable=True)
    new_payer_mode = Column(String(16), nullable=True)
    old_payment_method = Column(String(16), nullable=True)
    new_payment_method = Column(String(16), nullable=True)
    # The bill entry whose paid_by followed a single payer (R18), and its old value.
    occurrence_id = Column(String, nullable=True)
    old_occurrence_paid_by = Column(String, nullable=True)
    restored = Column(Boolean, default=False, server_default=text("false"), nullable=False)

    batch = relationship("BulkBatch", back_populates="rows")


class DuplicateDismissal(Base):
    """ "Keep both": a pair the duplicate finder must not show again, for
    every member. Stored smaller id first, once."""

    __tablename__ = "duplicate_dismissals"
    __table_args__ = (
        UniqueConstraint("first_id", "second_id", name="uq_duplicate_dismissal"),
        CheckConstraint("first_id < second_id", name="ck_duplicate_dismissals_order"),
        Index("ix_duplicate_dismissals_household", "household_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    first_id = Column(String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    second_id = Column(String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)


class CategoryRule(Base):
    """User-defined "merchant contains X → category Y" mapping.

    Categorisation previously relied on a hardcoded Greek keyword list in
    receipt_parser.py plus fuzzy name matching, neither of which could learn.
    These rules are checked first and can be taught from a scan, so correcting
    a category once makes it stick.
    """

    __tablename__ = "category_rules"
    __table_args__ = (
        UniqueConstraint("household_id", "pattern", name="uq_category_rule"),
        Index("ix_category_rules_household", "household_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    # Case-insensitive substring, stored lowercased.
    pattern = Column(String(200), nullable=False)
    category_id = Column(String, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    match_count = Column(Integer, default=0, nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)

    household = relationship("Household")
    category = relationship("Category")


class Settlement(Base):
    """A recorded debt payment between two household members.

    get_bucket_settlement() derives who owes whom from expense splits, but the
    computed balance never reset because nothing recorded that a debt had
    actually been paid. Settlements are subtracted from the computed net, so
    partial payments work and the history stays auditable.

    Scoped to a bucket when bucket_id is set; a NULL bucket_id settles across
    the whole household.
    """

    __tablename__ = "settlements"
    __table_args__ = (Index("ix_settlements_household_bucket", "household_id", "bucket_id"),)

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    bucket_id = Column(String, ForeignKey("buckets.id", ondelete="CASCADE"), nullable=True)
    from_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Always stored in the household's default currency, matching the balances
    # it offsets (see services.base_amount_expr).
    amount = Column(Numeric(12, 4), nullable=False)
    note = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)

    household = relationship("Household")
    bucket = relationship("Bucket")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])


class RecurringBillSplit(Base):
    __tablename__ = "recurring_bill_splits"

    id = Column(String, primary_key=True, default=gen_id)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Numeric(12, 4), nullable=False)

    bill = relationship("RecurringBill", back_populates="splits")
    user = relationship("User")


# ---------------------------------------------------------------------------
# Notifications & Push Subscriptions
# ---------------------------------------------------------------------------


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # Guarantees a scheduled notification is only ever delivered once per
        # user, no matter how many times the job runs (restarts, extra workers).
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),
        Index("ix_notifications_user_household_created", "user_id", "household_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(
        String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(SAEnum(NotificationType), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    link = Column(String, nullable=True)
    # NULL for ad-hoc notifications (NULLs do not collide in a UNIQUE index);
    # set to a stable key for anything emitted by the scheduler.
    dedupe_key = Column(String(200), nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)

    household = relationship("Household")
    user = relationship("User")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)

    user = relationship("User")


class NotificationMute(Base):
    """An alert type one member turned off in one household (2d §7.6). A row
    means muted; the default is everything on. create_notification checks it,
    so muting stops both the in-app notification and the push."""

    __tablename__ = "notification_mutes"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), primary_key=True)
    # A NotificationType value as plain VARCHAR: never the native PG enum.
    type = Column(String(32), primary_key=True)


# ---------------------------------------------------------------------------
# API Refresh Tokens (JWT — mobile / external clients)
# ---------------------------------------------------------------------------


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    household_id = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True)  # SHA-256 hex of the raw token
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    # User.session_version at issue; a later bump (logout, password or 2FA
    # change) makes the token unusable even if it was not revoked.
    session_version = Column(Integer, default=0, server_default="0", nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)

    user = relationship("User")


# ---------------------------------------------------------------------------
# Personal API tokens (iOS Shortcut ingest)
# ---------------------------------------------------------------------------


class PersonalApiToken(Base):
    """A long-lived credential one member creates for one household.

    Only the SHA-256 of the token is stored; the plaintext (``pat_`` + 32
    url-safe chars) is shown once at creation. ``prefix`` is the first 12
    characters, for recognising a token in the list. Revocation sets
    ``revoked_at`` (rows are never deleted).
    """

    __tablename__ = "personal_api_tokens"
    __table_args__ = (Index("ix_personal_api_tokens_user_household", "user_id", "household_id"),)

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(60), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    prefix = Column(String(12), nullable=False)
    scopes = Column(String(100), nullable=False, default="ingest", server_default="ingest")
    default_bucket_id = Column(String, ForeignKey("buckets.id", ondelete="SET NULL"), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User")
    default_bucket = relationship("Bucket")

    @property
    def scope_list(self) -> list[str]:
        return [s.strip() for s in (self.scopes or "").split(",") if s.strip()]

    @property
    def can_classify(self) -> bool:
        return "classify" in self.scope_list


# Apple Pay ingest diagnostics (iOS Shortcut)
# ------------------------------------------


class IngestAttempt(Base):
    """One HTTP attempt on ``POST /api/v1/ingest/apple-pay``, kept for debugging.

    The Shortcut is configured by hand on the phone, so when a purchase does
    not arrive the useful question is "what did the phone actually send?".
    Attempts are recorded from every layer that can reject one — payload
    validation, auth, rate limit, the endpoint itself — and shown on
    Settings → Automations; the same lines go to the server log.

    ``household_id`` / ``token_id`` are nullable: an attempt carrying a token
    nobody can match is attributed to no one (it still lands in the server
    log). Rows are pruned per household by
    :func:`app.services.ingest.record_ingest_attempt`.
    """

    __tablename__ = "ingest_attempts"
    __table_args__ = (
        Index("ix_ingest_attempts_household_created", "household_id", "created_at"),
        Index("ix_ingest_attempts_prefix_created", "token_prefix", "created_at"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=True)
    token_id = Column(
        String, ForeignKey("personal_api_tokens.id", ondelete="SET NULL"), nullable=True
    )
    # First 12 characters of the token (same value the settings page shows),
    # kept even for unknown tokens so a pattern is recognisable in the log.
    token_prefix = Column(String(12), nullable=True)
    status = Column(Integer, nullable=False)
    # Why in one line: "created", "duplicate", or the rejection reason.
    detail = Column(String(500), nullable=True)
    # A summary of the request body, never the body: per known key its type
    # and a short preview, a count of unknown keys (compact JSON); or
    # "not a JSON object (<n> bytes, <content type>)".
    payload = Column(Text, nullable=True)
    content_type = Column(String(100), nullable=True)
    transaction_id = Column(
        String, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)

    @property
    def is_legacy(self) -> bool:
        """Written before the summary existed: the payload is the raw body."""
        from app.services.ingest import is_legacy_payload

        return is_legacy_payload(self.payload)

    @property
    def safe_payload(self) -> str | None:
        """The payload if it is a summary, else None (never a raw body)."""
        return None if self.is_legacy else self.payload

    @property
    def safe_detail(self) -> str | None:
        """The detail, except on a legacy row whose status could carry input."""
        from app.services.ingest import FIXED_DETAIL_STATUSES, LEGACY_DETAIL

        if self.is_legacy and self.status not in FIXED_DETAIL_STATUSES:
            return LEGACY_DETAIL
        return self.detail

    @property
    def safe_content_type(self) -> str | None:
        return None if self.is_legacy else self.content_type

    @property
    def payload_lines(self) -> list[str]:
        """The stored summary as ``key: preview`` lines (for the page)."""
        from app.services.ingest import summary_lines

        return summary_lines(self.payload)


# ---------------------------------------------------------------------------
# Stock & prices (Phase 6)
# ---------------------------------------------------------------------------


class StockReason(str, enum.Enum):
    buy = "buy"
    use = "use"
    adjust = "adjust"


class Product(Base):
    """A product the household keeps in stock, optionally linked to PosoKanei.

    Never hard-deleted from the UI: "remove" sets archived_at so the price
    history and consumption log that hang off it are preserved.
    """

    __tablename__ = "products"
    __table_args__ = (
        # Unique per household only when a barcode is set: a partial index on
        # Postgres; on SQLite a plain unique index behaves the same because
        # NULLs never collide.
        Index(
            "uq_products_household_barcode",
            "household_id",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
        Index("ix_products_household_id", "household_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    brand = Column(String(100), nullable=True)
    barcode = Column(String(32), nullable=True)
    posokanei_id = Column(String(64), nullable=True)
    unit = Column(String(20), nullable=True)
    unit_quantity = Column(Numeric(10, 3), nullable=True)
    category_id = Column(String, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    archived_at = Column(DateTime, nullable=True)

    stock_item = relationship("StockItem", back_populates="product", uselist=False)
    snapshots = relationship("PriceSnapshot", back_populates="product")


class StockItem(Base):
    __tablename__ = "stock_items"
    __table_args__ = (Index("ix_stock_items_household_id", "household_id"),)

    id = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(
        String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    quantity = Column(Numeric(10, 2), default=0, nullable=False)
    min_quantity = Column(Numeric(10, 2), default=1, nullable=False)
    track_price = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    product = relationship("Product", back_populates="stock_item")
    movements = relationship("StockMovement", back_populates="stock_item")


class StockMovement(Base):
    """Consumption/purchase log; drives run-out prediction."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_item_created", "stock_item_id", "created_at"),
        Index("ix_stock_movements_client_id", "client_id"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    stock_item_id = Column(String, ForeignKey("stock_items.id", ondelete="CASCADE"), nullable=False)
    delta = Column(Numeric(10, 2), nullable=False)
    reason = Column(String(12), nullable=False)  # StockReason value
    created_at = Column(DateTime, default=utcnow_naive)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # The PWA's queued ± stepper sends one per tap; a replay of the same id
    # within 24 h (same household) is not applied again (Pantry spec §4.8).
    client_id = Column(String(64), nullable=True)

    stock_item = relationship("StockItem", back_populates="movements")


class PriceSnapshot(Base):
    """One retailer's price for a product on a day: from PosoKanei, or one the
    user logged (``source='manual'``, polish C3)."""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("product_id", "retailer", "snapshot_date", name="uq_price_snapshot"),
        Index("ix_price_snapshots_product_date", "product_id", "snapshot_date"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    retailer = Column(String(40), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    unit_price = Column(Numeric(10, 4), nullable=True)
    is_discount = Column(Boolean, default=False, nullable=False)
    snapshot_date = Column(Date, nullable=False)
    source = Column(String(16), nullable=True, server_default="posokanei")  # or "manual"

    product = relationship("Product", back_populates="snapshots")


class ShoppingLine(Base):
    """A line on the household's shopping list (Plan › Pantry).

    With ``stock_item_id`` set it is a **tick** on a computed item (low or
    running out): picked up, not yet in the pantry; apply-ticked adds
    ``quantity`` to stock. Without it, a **one-off line** the user typed
    (``name`` required). ``checked_at`` is when it was ticked; a cleared line
    (``cleared_at``) is history. Nothing here touches transactions.
    """

    __tablename__ = "shopping_lines"
    __table_args__ = (
        Index("ix_shopping_lines_household_id", "household_id"),
        Index("ix_shopping_lines_stock_item_id", "stock_item_id"),
        # One active tick per stock item; cleared ticks and one-off lines
        # never collide.
        Index(
            "uq_shopping_lines_active_tick",
            "stock_item_id",
            unique=True,
            sqlite_where=text("cleared_at IS NULL AND stock_item_id IS NOT NULL"),
            postgresql_where=text("cleared_at IS NULL AND stock_item_id IS NOT NULL"),
        ),
    )

    id = Column(String(36), primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    stock_item_id = Column(String, ForeignKey("stock_items.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(200), nullable=True)
    quantity = Column(Numeric(10, 2), nullable=True)
    checked_at = Column(DateTime, nullable=True)
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=False)
    cleared_at = Column(DateTime, nullable=True)

    stock_item = relationship("StockItem")
