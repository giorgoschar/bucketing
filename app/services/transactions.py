"""
Transaction creation and soft deletion (shared by the HTML and JSON API routes).
"""

import logging
import os
import shutil
import uuid

from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    CashMovement,
    Household,
    HouseholdMember,
    OccurrenceStatus,
    PayerMode,
    PaymentMethod,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.schemas import (
    BUCKET_REQUIRED,
    OWN_SHARE_TAKE,
    SplitIn,
    TransactionCreate,
    TransactionUpdate,
    absorb_own_share_cent,
    own_share_problem,
)
from app.services.cash import FROM_STASH, has_linked_take, link_take, sync_linked_take
from app.services.fuel import fuel_fields
from app.services.money import equal_split
from app.validators import (
    require_category,
    require_member,
    require_receipt_content,
    require_takes_income,
    validate_split_users,
)

logger = logging.getLogger(__name__)

TAKE_NOT_PAYER = "Only the person who paid can take the cash for it."

UPLOADS_DIR = "uploads"
TRASH_DIRNAME = ".trash"

# Where bucket-less income is listed (it has no bucket page to return to).
INCOME_LIST_URL = "/transactions/search?type=income"


def last_payment_method(db: Session, household_id: str, user_id: str) -> str:
    """How ``user_id`` paid their most recent expense (the newest one they
    paid for), else card: the expense wizard starts on it. Bill payments do
    not count: auto-pay records them in the background, always by card."""
    method = (
        db.query(Transaction.payment_method)
        .filter(
            Transaction.household_id == household_id,
            Transaction.active(),
            Transaction.type == TransactionType.expense,
            Transaction.paid_by == user_id,
            ~Transaction.bill_occurrence.has(),
        )
        .order_by(Transaction.created_at.desc())
        .limit(1)
        .scalar()
    )
    return method or PaymentMethod.card.value


def after_save_url(bucket_id: str | None) -> str:
    """Where an HTML form goes after saving, editing or deleting a
    transaction: its bucket, or the income list for bucket-less income."""
    return f"/buckets/{bucket_id}" if bucket_id else INCOME_LIST_URL


def delete_transaction(db: Session, txn: Transaction, uploads_dir: str | None = None) -> None:
    """Soft-delete a transaction. Never removes the row, its splits or its receipt.

    The row is marked deleted and committed first; only then is the receipt
    moved to <uploads>/.trash/ (purged 30 days after *deletion* by the
    scheduler). If the move fails the row stays deleted and the file stays in
    uploads/ (not lost). receipt_path keeps the bare filename for restore.
    """
    uploads_dir = uploads_dir or UPLOADS_DIR
    txn.deleted_at = utcnow_naive()
    # A take made for the expense ("I took this from my stash") goes with it.
    db.query(CashMovement).filter(
        CashMovement.transaction_id == txn.id,
        CashMovement.active(),
    ).update({CashMovement.deleted_at: txn.deleted_at}, synchronize_session=False)
    # A deleted payment puts its entry back to expected (spec §3.3).
    db.query(BillOccurrence).filter(BillOccurrence.transaction_id == txn.id).update(
        {
            BillOccurrence.status: OccurrenceStatus.unpaid,
            BillOccurrence.paid_at: None,
            BillOccurrence.paid_by: None,
            BillOccurrence.transaction_id: None,
        },
        synchronize_session=False,
    )
    db.commit()
    if not txn.receipt_path:
        return
    name = os.path.basename(txn.receipt_path)
    src = os.path.join(uploads_dir, name)
    if not os.path.isfile(src):
        return
    trash = os.path.join(uploads_dir, TRASH_DIRNAME)
    dest = os.path.join(trash, name)
    try:
        os.makedirs(trash, exist_ok=True)
        shutil.move(src, dest)
        # Retention counts from deletion, not from when the file was uploaded.
        os.utime(dest, None)
    except OSError:
        logger.warning(
            "Could not move receipt %s to trash for transaction %s", name, txn.id, exc_info=True
        )


# ---------------------------------------------------------------------------
# Transaction creation (shared by the HTML and JSON API routes)
# ---------------------------------------------------------------------------

MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".heic", ".heif"}


class DuplicateTransaction(Exception):
    """A transaction with this client_id already exists (offline replay)."""

    def __init__(self, existing: Transaction):
        super().__init__("transaction already submitted")
        self.existing = existing


class DeletedTransactionReplay(Exception):
    """The client_id matches a soft-deleted transaction; never resurrect it."""


def _find_by_client_id(db: Session, household_id: str, client_id: str) -> Transaction | None:
    """Deliberately includes soft-deleted rows: a replay of a deleted expense
    must not become a second row."""
    return (
        db.query(Transaction)
        .filter(Transaction.household_id == household_id, Transaction.client_id == client_id)
        .first()
    )


def _store_receipt(receipt: UploadFile, uploads_dir: str) -> str:
    """Validate and save an uploaded receipt; return the stored filename."""
    ext = os.path.splitext(receipt.filename or "")[1].lower()
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_RECEIPT_EXTENSIONS))}",
        )
    content = receipt.file.read(MAX_RECEIPT_SIZE + 1)
    if len(content) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")
    require_receipt_content(ext, content)
    os.makedirs(uploads_dir, exist_ok=True)
    filename = f"{uuid.uuid4()}{ext}"
    with open(os.path.join(uploads_dir, filename), "wb") as f:
        f.write(content)
    return filename


def _resolve_splits(
    db: Session,
    household_id: str,
    data: TransactionCreate,
    payer_mode: str,
    paid_by: str | None,
    is_shared: bool,
) -> list[SplitIn]:
    """The splits to store: the ones given, or an equal split.

    A shared expense whose split amounts were left blank ("Leave blank for
    equal split") used to store no splits at all, so insights and /me charged
    the whole amount to the payer while settle-up split it equally. The equal
    split is now written out across the current members, so every view reads
    the same shares. Only for single-payer expenses: own share needs explicit
    amounts (the schema rejects blank ones), and a one-person household has
    nothing to split.
    """
    if data.splits or not is_shared:
        return list(data.splits)
    if data.type.value != "expense" or payer_mode != PayerMode.single.value:
        return []
    member_ids = [
        uid
        for (uid,) in db.query(HouseholdMember.user_id).filter(
            HouseholdMember.household_id == household_id
        )
    ]
    if len(member_ids) < 2:
        return []
    return [
        SplitIn(user_id=uid, amount=amount)
        for uid, amount in equal_split(data.amount, member_ids, paid_by).items()
    ]


def create_transaction(
    db: Session,
    *,
    household_id: str,
    bucket,
    user,
    data: TransactionCreate,
    receipt: UploadFile | None = None,
    is_shared: bool = False,
    uploads_dir: str | None = None,
    ingest_token_id: str | None = None,
) -> Transaction:
    """Create a transaction (and its splits/receipt) from validated input.

    ``data`` has already passed field validation (see app.schemas); this adds
    the checks that need the database: client_id idempotency, and that the
    category, payer and split users all belong to ``household_id``. Raises
    DuplicateTransaction / DeletedTransactionReplay for client_id replays.
    ``is_shared`` marks a shared expense with no explicit payer (the submitter
    is the default payer, so settle-up has someone to credit); left without
    split amounts it is split equally across the household (see
    :func:`_resolve_splits`). An own-share expense (``data.payer_mode``) never
    gets a payer: its splits are what each member paid, and the schema has
    already checked they cover the total. ``bucket`` may be None for income
    only (HTTP 400 otherwise); income in a bucket needs it active with "Track
    income" on (HTTP 400), or it would never be counted. A fuel expense's
    litres are worked out here from its price (app.services.fuel).
    ``ingest_token_id`` marks an expense an Apple Pay token created; it is
    written in this same commit.
    """
    uploads_dir = uploads_dir or UPLOADS_DIR
    if bucket is None and data.type != TransactionType.income:
        raise HTTPException(status_code=400, detail=BUCKET_REQUIRED)
    if bucket is not None and data.type == TransactionType.income:
        require_takes_income(bucket)

    def _raise_if_replay() -> None:
        existing = _find_by_client_id(db, household_id, data.client_id)
        if existing is not None:
            if existing.deleted_at is not None:
                raise DeletedTransactionReplay()
            raise DuplicateTransaction(existing)

    if data.client_id:
        _raise_if_replay()

    payer_mode = data.payer_mode or PayerMode.single.value
    paid_by = require_member(db, data.paid_by, household_id)
    category_id = require_category(db, data.category_id, household_id)
    if data.splits:
        validate_split_users([s.user_id for s in data.splits], household_id, db)

    # A shared expense with no payer is unusable: settle-up would charge the
    # shares to members with nobody credited for fronting the money. Cash
    # likewise: it has to come out of someone's wallet (app.services.cash).
    is_cash = data.payment_method == PaymentMethod.cash.value
    if payer_mode == PayerMode.own_share.value:
        paid_by = None
    elif not paid_by and data.type.value == "expense" and (is_shared or data.splits or is_cash):
        paid_by = user.id
    took_cash = is_cash and data.took_cash and data.type.value == "expense"
    if took_cash and paid_by != user.id:
        # The take goes into the submitter's wallet (from their stash).
        raise HTTPException(status_code=400, detail=TAKE_NOT_PAYER)
    splits = _resolve_splits(db, household_id, data, payer_mode, paid_by, is_shared)
    fuel_price, fuel_litres = fuel_fields(
        db,
        household_id,
        category_id=category_id,
        txn_type=data.type,
        amount=data.amount,
        price=data.fuel_price_per_litre,
    )

    receipt_path = None
    if receipt is not None and receipt.filename:
        receipt_path = _store_receipt(receipt, uploads_dir)

    txn = Transaction(
        bucket_id=bucket.id if bucket is not None else None,
        household_id=household_id,
        amount=data.amount,
        currency=data.currency,
        exchange_rate=data.exchange_rate,
        type=data.type,
        paid_by=paid_by,
        payer_mode=payer_mode,
        category_id=category_id,
        notes=data.notes,
        transaction_date=data.transaction_date,
        receipt_path=receipt_path,
        payment_method=data.payment_method,
        merchant=data.merchant,
        fuel_price_per_litre=fuel_price,
        fuel_litres=fuel_litres,
        client_id=data.client_id,
        exclude_from_forecast=data.exclude_from_forecast,
        exclude_from_settlement=data.exclude_from_settlement,
        # Set before the insert so the marker commits with the expense (O-3).
        ingest_token_id=ingest_token_id,
    )
    try:
        db.add(txn)
        db.flush()
        for s in splits:
            db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=s.amount))
        if took_cash:
            # "I took this from my stash": the matching take, linked, in the
            # same database transaction (see app.services.cash).
            link_take(
                db,
                txn,
                user.id,
                data.take_from or FROM_STASH,
                db.get(Household, household_id).default_currency,
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        if receipt_path:
            try:
                os.remove(os.path.join(uploads_dir, receipt_path))
            except OSError:
                pass
        if isinstance(exc, IntegrityError) and data.client_id:
            # Lost a race against a concurrent create with the same client_id:
            # answer as the idempotent replay it is.
            _raise_if_replay()
        raise
    db.refresh(txn)
    _suggest_match(db, txn)
    return txn


def _suggest_match(db: Session, txn: Transaction) -> None:
    """Look for an expected entry this new transaction may pay (spec §3.5).

    Every source creates through create_transaction (forms, API, Apple Pay
    ingest, offline replay, cash), so this is the one hook. A failure here
    never fails the save.
    """
    from app.services.matching import suggest_for_transaction

    try:
        if suggest_for_transaction(db, txn) is not None:
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Match suggestion for transaction %s failed", txn.id)


def update_transaction(
    db: Session,
    txn: Transaction,
    *,
    household_id: str,
    user,
    data: TransactionUpdate,
    is_shared: bool | None = None,
) -> Transaction:
    """Apply a validated edit (see app.schemas.TransactionUpdate). Callers commit.

    Mirrors create_transaction's database checks: bucket (optional for income
    only; income moved into one needs "Track income" on), category, payer and
    split users must belong to ``household_id``; a split expense always keeps a
    payer (the existing one, else the editor) so settle-up never drops it.
    ``data.payer_mode`` of None keeps the stored mode; the own-share rules are
    re-checked against the resolved mode (HTTP 400), since the schema can only
    check them when the mode was given. ``is_shared`` is the form's shared
    toggle: True splits blank shares equally, False drops the split (the form
    still posts its hidden split inputs), None (the API, older forms) stores
    ``data.splits`` as given.
    """
    from app.validators import require_bucket

    payer_mode = data.payer_mode or txn.payer_mode or PayerMode.single.value
    if payer_mode == PayerMode.own_share.value:
        problem = (
            "Each paid their own share is only for expenses."
            if data.type.value != "expense"
            else own_share_problem(data.amount, (s.amount for s in data.splits))
        )
        if problem:
            raise HTTPException(status_code=400, detail=problem)
        absorb_own_share_cent(data.amount, data.splits)

    # Only income, and a Fixed cost (an expense paid for a recurring item
    # with no bucket, spec §3.4.2), may go without a bucket. A bill payment
    # that has a bucket keeps one.
    fixed_cost = (
        txn.recurring_bill_id is not None
        and txn.bucket_id is None
        and data.type == TransactionType.expense
    )
    if not data.bucket_id and data.type != TransactionType.income and not fixed_cost:
        raise HTTPException(status_code=400, detail=BUCKET_REQUIRED)
    bucket = require_bucket(db, data.bucket_id, household_id, optional=True)
    # Income moved into a bucket (or an entry turned into income) must land
    # where it is counted; income already in its bucket stays editable even
    # after that bucket stopped tracking income or was archived.
    if (
        bucket is not None
        and data.type == TransactionType.income
        and (txn.type != TransactionType.income or txn.bucket_id != bucket.id)
    ):
        require_takes_income(bucket)
    paid_by = require_member(db, data.paid_by, household_id)
    category_id = require_category(db, data.category_id, household_id)
    if data.splits:
        validate_split_users([s.user_id for s in data.splits], household_id, db)
    is_cash = data.payment_method == PaymentMethod.cash.value
    if payer_mode == PayerMode.own_share.value:
        paid_by = None
    elif not paid_by and data.type.value == "expense" and (is_shared or data.splits or is_cash):
        paid_by = txn.paid_by or user.id
    if payer_mode == PayerMode.own_share.value and is_cash and has_linked_take(db, txn.id):
        raise HTTPException(status_code=400, detail=OWN_SHARE_TAKE)
    if is_shared is False and payer_mode != PayerMode.own_share.value:
        splits = []
    else:
        splits = _resolve_splits(db, household_id, data, payer_mode, paid_by, bool(is_shared))
    # The litres always follow the (possibly new) amount; another category
    # or type clears both fields. An omitted price keeps the stored one only
    # while the currency stays: it is a price in that currency.
    if "fuel_price_per_litre" in data.model_fields_set:
        price = data.fuel_price_per_litre
    elif data.currency == txn.currency:
        price = txn.fuel_price_per_litre
    else:
        price = None
    fuel_price, fuel_litres = fuel_fields(
        db,
        household_id,
        category_id=category_id,
        txn_type=data.type,
        amount=data.amount,
        price=price,
    )

    txn.bucket_id = data.bucket_id
    txn.amount = data.amount
    txn.currency = data.currency
    txn.exchange_rate = data.exchange_rate
    txn.type = data.type
    txn.paid_by = paid_by
    txn.payer_mode = payer_mode
    txn.category_id = category_id
    txn.notes = data.notes
    txn.payment_method = data.payment_method
    txn.merchant = data.merchant
    txn.fuel_price_per_litre = fuel_price
    txn.fuel_litres = fuel_litres
    txn.exclude_from_forecast = data.exclude_from_forecast
    txn.exclude_from_settlement = data.exclude_from_settlement
    if data.transaction_date is not None:
        txn.transaction_date = data.transaction_date

    db.query(TransactionSplit).filter_by(transaction_id=txn.id).delete(synchronize_session=False)
    db.expire(txn, ["splits"])
    for s in splits:
        db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=s.amount))
    # A linked take follows the amount and date, and goes away when the
    # expense is no longer paid in cash.
    sync_linked_take(db, txn, user.id)
    return txn
