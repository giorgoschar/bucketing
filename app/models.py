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
from sqlalchemy.orm import relationship

from app.clock import local_today, utcnow_naive
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
    that left the wallet without a logged expense.
    """
    stash_in = "stash_in"
    take = "take"
    put_back = "put_back"
    still_have = "still_have"
    out = "out"


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


class NotificationType(str, enum.Enum):
    bill_due           = "bill_due"
    bill_overdue       = "bill_overdue"
    bill_auto_paid     = "bill_auto_paid"
    contract_expiring  = "contract_expiring"
    bill_drift         = "bill_drift"       # bill cost moved vs its own history
    budget_warning     = "budget_warning"   # bucket spend crossed a budget threshold
    ingest_created     = "ingest_created"   # an expense arrived via the Apple Pay Shortcut
    general            = "general"
    stock_low          = "stock_low"        # a stock item fell to its minimum
    price_drop         = "price_drop"       # tracked product ≥10% under its 30-day median
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
        from app.crypto import decrypt_str
        return decrypt_str(self.totp_secret) if self.totp_secret else None

    def set_totp_secret(self, secret: str | None) -> None:
        from app.crypto import encrypt_str
        self.totp_secret = encrypt_str(secret) if secret else None

    memberships = relationship("HouseholdMember", back_populates="user")
    paid_transactions = relationship("Transaction", back_populates="paid_by_user")
    splits = relationship("TransactionSplit", back_populates="user")
    invitations_created = relationship("Invitation", foreign_keys="Invitation.created_by", back_populates="created_by_user")


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
    created_by_user = relationship("User", foreign_keys=[created_by], back_populates="invitations_created")


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
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=True)  # null = system default
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
    created_at = Column(DateTime, default=utcnow_naive)

    household = relationship("Household", back_populates="buckets")
    transactions = relationship("Transaction", back_populates="bucket")
    recurring_bills = relationship("RecurringBill", back_populates="bucket")


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

# Expenses and transfers need a bucket; income may have none. The enum is
# stored by name ('income'), on SQLite and in the Postgres enum alike.
BUCKET_UNLESS_INCOME_SQL = "bucket_id IS NOT NULL OR type = 'income'"


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_household_date", "household_id", "transaction_date"),
        Index("ix_transactions_bucket_id", "bucket_id"),
        Index("ix_transactions_deleted_at", "deleted_at"),
        Index("ix_transactions_paid_by", "paid_by"),
        Index("ix_transactions_category_id", "category_id"),
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
    payment_method = Column(String(16), default=PaymentMethod.card.value,
                            server_default=PaymentMethod.card.value, nullable=False)
    merchant = Column(String(200), nullable=True)
    payer_mode = Column(String(16), default=PayerMode.single.value,
                        server_default=PayerMode.single.value, nullable=False)
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
    splits = relationship("TransactionSplit", back_populates="transaction", cascade="all, delete-orphan")
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
    transaction_id = Column(String, ForeignKey("transactions.id", ondelete="SET NULL"),
                            nullable=True)
    created_at = Column(DateTime, default=utcnow_naive)
    deleted_at = Column(DateTime, nullable=True)

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
    transaction_id = Column(String, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
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
    __table_args__ = (
        Index("ix_recurring_bills_household_id", "household_id"),
    )

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
    payer_mode = Column(String(16), default=PayerMode.single.value,
                        server_default=PayerMode.single.value, nullable=False)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    is_auto_pay = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive)

    household = relationship("Household", back_populates="recurring_bills")
    bucket = relationship("Bucket", back_populates="recurring_bills")
    category = relationship("Category", back_populates="recurring_bills")
    occurrences = relationship("BillOccurrence", back_populates="bill", cascade="all, delete-orphan")
    splits = relationship("RecurringBillSplit", back_populates="bill", cascade="all, delete-orphan")


class BillOccurrence(Base):
    __tablename__ = "bill_occurrences"
    __table_args__ = (
        UniqueConstraint('bill_id', 'due_date', name='uq_bill_occurrence'),
        Index("ix_bill_occurrences_bill_status", "bill_id", "due_date", "status"),
    )

    id = Column(String, primary_key=True, default=gen_id)
    bill_id = Column(String, ForeignKey("recurring_bills.id", ondelete="CASCADE"), nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 4), nullable=True)  # overrides bill.amount for variable bills
    status = Column(SAEnum(OccurrenceStatus), default=OccurrenceStatus.unpaid, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    paid_by = Column(String, ForeignKey("users.id"), nullable=True)
    transaction_id = Column(String, ForeignKey("transactions.id"), nullable=True)

    bill = relationship("RecurringBill", back_populates="occurrences")
    transaction = relationship("Transaction", back_populates="bill_occurrence")


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

    id           = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    # Case-insensitive substring, stored lowercased.
    pattern      = Column(String(200), nullable=False)
    category_id  = Column(String, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    match_count  = Column(Integer, default=0, nullable=False)
    created_by   = Column(String, ForeignKey("users.id"), nullable=True)
    created_at   = Column(DateTime, default=utcnow_naive)

    household = relationship("Household")
    category  = relationship("Category")


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
    __table_args__ = (
        Index("ix_settlements_household_bucket", "household_id", "bucket_id"),
    )

    id           = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    bucket_id    = Column(String, ForeignKey("buckets.id", ondelete="CASCADE"), nullable=True)
    from_user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id   = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Always stored in the household's default currency, matching the balances
    # it offsets (see services.base_amount_expr).
    amount       = Column(Numeric(12, 4), nullable=False)
    note         = Column(Text, nullable=True)
    created_by   = Column(String, ForeignKey("users.id"), nullable=True)
    created_at   = Column(DateTime, default=utcnow_naive)

    household = relationship("Household")
    bucket    = relationship("Bucket")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user   = relationship("User", foreign_keys=[to_user_id])


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

    id           = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id      = Column(String, ForeignKey("users.id",      ondelete="CASCADE"), nullable=False, index=True)
    type         = Column(SAEnum(NotificationType), nullable=False)
    title        = Column(String(200), nullable=False)
    body         = Column(Text, nullable=True)
    link         = Column(String, nullable=True)
    # NULL for ad-hoc notifications (NULLs do not collide in a UNIQUE index);
    # set to a stable key for anything emitted by the scheduler.
    dedupe_key   = Column(String(200), nullable=True)
    is_read      = Column(Boolean, default=False, nullable=False)
    created_at   = Column(DateTime, default=utcnow_naive)

    household = relationship("Household")
    user      = relationship("User")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id           = Column(String, primary_key=True, default=gen_id)
    user_id      = Column(String, ForeignKey("users.id",      ondelete="CASCADE"), nullable=False, index=True)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    endpoint     = Column(Text, nullable=False, unique=True)
    p256dh       = Column(Text, nullable=False)
    auth         = Column(Text, nullable=False)
    created_at   = Column(DateTime, default=utcnow_naive)

    user = relationship("User")


# ---------------------------------------------------------------------------
# API Refresh Tokens (JWT — mobile / external clients)
# ---------------------------------------------------------------------------

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
    )

    id           = Column(String, primary_key=True, default=gen_id)
    user_id      = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    household_id = Column(String, nullable=False)
    token_hash   = Column(String, nullable=False, unique=True)  # SHA-256 hex of the raw token
    expires_at   = Column(DateTime, nullable=False)
    revoked      = Column(Boolean, default=False, nullable=False)
    # User.session_version at issue; a later bump (logout, password or 2FA
    # change) makes the token unusable even if it was not revoked.
    session_version = Column(Integer, default=0, server_default="0", nullable=False)
    created_at   = Column(DateTime, default=utcnow_naive)

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
    __table_args__ = (
        Index("ix_personal_api_tokens_user_household", "user_id", "household_id"),
    )

    id                = Column(String, primary_key=True, default=gen_id)
    user_id           = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    household_id      = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    name              = Column(String(60), nullable=False)
    token_hash        = Column(String(64), nullable=False, unique=True)
    prefix            = Column(String(12), nullable=False)
    scopes            = Column(String(100), nullable=False, default="ingest", server_default="ingest")
    default_bucket_id = Column(String, ForeignKey("buckets.id", ondelete="SET NULL"), nullable=True)
    last_used_at      = Column(DateTime, nullable=True)
    created_at        = Column(DateTime, default=utcnow_naive)
    revoked_at        = Column(DateTime, nullable=True)

    user           = relationship("User")
    default_bucket = relationship("Bucket")

    @property
    def scope_list(self) -> list[str]:
        return [s.strip() for s in (self.scopes or "").split(",") if s.strip()]


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
            "uq_products_household_barcode", "household_id", "barcode",
            unique=True, postgresql_where=text("barcode IS NOT NULL"),
        ),
        Index("ix_products_household_id", "household_id"),
    )

    id            = Column(String, primary_key=True, default=gen_id)
    household_id  = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    name          = Column(String(200), nullable=False)
    brand         = Column(String(100), nullable=True)
    barcode       = Column(String(32), nullable=True)
    posokanei_id  = Column(String(64), nullable=True)
    unit          = Column(String(20), nullable=True)
    unit_quantity = Column(Numeric(10, 3), nullable=True)
    category_id   = Column(String, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    image_url     = Column(String(500), nullable=True)
    created_at    = Column(DateTime, default=utcnow_naive)
    archived_at   = Column(DateTime, nullable=True)

    stock_item = relationship("StockItem", back_populates="product", uselist=False)
    snapshots  = relationship("PriceSnapshot", back_populates="product")


class StockItem(Base):
    __tablename__ = "stock_items"
    __table_args__ = (
        Index("ix_stock_items_household_id", "household_id"),
    )

    id           = Column(String, primary_key=True, default=gen_id)
    household_id = Column(String, ForeignKey("households.id", ondelete="CASCADE"), nullable=False)
    product_id   = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True)
    quantity     = Column(Numeric(10, 2), default=0, nullable=False)
    min_quantity = Column(Numeric(10, 2), default=1, nullable=False)
    track_price  = Column(Boolean, default=True, nullable=False)
    updated_at   = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    product   = relationship("Product", back_populates="stock_item")
    movements = relationship("StockMovement", back_populates="stock_item")


class StockMovement(Base):
    """Consumption/purchase log; drives run-out prediction."""
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_item_created", "stock_item_id", "created_at"),
    )

    id            = Column(String, primary_key=True, default=gen_id)
    stock_item_id = Column(String, ForeignKey("stock_items.id", ondelete="CASCADE"), nullable=False)
    delta         = Column(Numeric(10, 2), nullable=False)
    reason        = Column(String(12), nullable=False)  # StockReason value
    created_at    = Column(DateTime, default=utcnow_naive)
    created_by    = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    stock_item = relationship("StockItem", back_populates="movements")


class PriceSnapshot(Base):
    """One retailer's price for a product on a day (from PosoKanei)."""
    __tablename__ = "price_snapshots"
    __table_args__ = (
        UniqueConstraint("product_id", "retailer", "snapshot_date", name="uq_price_snapshot"),
        Index("ix_price_snapshots_product_date", "product_id", "snapshot_date"),
    )

    id            = Column(String, primary_key=True, default=gen_id)
    product_id    = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    retailer      = Column(String(40), nullable=False)
    price         = Column(Numeric(10, 2), nullable=False)
    unit_price    = Column(Numeric(10, 4), nullable=True)
    is_discount   = Column(Boolean, default=False, nullable=False)
    snapshot_date = Column(Date, nullable=False)

    product = relationship("Product", back_populates="snapshots")
