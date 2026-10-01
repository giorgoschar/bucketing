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

from app.clock import utcnow_naive
from app.models import (
    Transaction,
    TransactionSplit,
)
from app.schemas import TransactionCreate, TransactionUpdate
from app.validators import (
    require_category,
    require_member,
    require_receipt_content,
    validate_split_users,
)

logger = logging.getLogger(__name__)

UPLOADS_DIR = "uploads"
TRASH_DIRNAME = ".trash"


def delete_transaction(db: Session, txn: Transaction, uploads_dir: str | None = None) -> None:
    """Soft-delete a transaction. Never removes the row, its splits or its receipt.

    The row is marked deleted and committed first; only then is the receipt
    moved to <uploads>/.trash/ (purged 30 days after *deletion* by the
    scheduler). If the move fails the row stays deleted and the file stays in
    uploads/ (not lost). receipt_path keeps the bare filename for restore.
    """
    uploads_dir = uploads_dir or UPLOADS_DIR
    txn.deleted_at = utcnow_naive()
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
        logger.warning("Could not move receipt %s to trash for transaction %s",
                       name, txn.id, exc_info=True)


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
        .filter(Transaction.household_id == household_id,
                Transaction.client_id == client_id)
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
) -> Transaction:
    """Create a transaction (and its splits/receipt) from validated input.

    ``data`` has already passed field validation (see app.schemas); this adds
    the checks that need the database: client_id idempotency, and that the
    category, payer and split users all belong to ``household_id``. Raises
    DuplicateTransaction / DeletedTransactionReplay for client_id replays.
    ``is_shared`` marks a shared expense with no explicit payer (the submitter
    is the default payer, so settle-up has someone to credit).
    """
    uploads_dir = uploads_dir or UPLOADS_DIR

    def _raise_if_replay() -> None:
        existing = _find_by_client_id(db, household_id, data.client_id)
        if existing is not None:
            if existing.deleted_at is not None:
                raise DeletedTransactionReplay()
            raise DuplicateTransaction(existing)

    if data.client_id:
        _raise_if_replay()

    paid_by = require_member(db, data.paid_by, household_id)
    category_id = require_category(db, data.category_id, household_id)
    if data.splits:
        validate_split_users([s.user_id for s in data.splits], household_id, db)

    # A shared expense with no payer is unusable: settle-up would charge the
    # shares to members with nobody credited for fronting the money.
    if not paid_by and data.type.value == "expense" and (is_shared or data.splits):
        paid_by = user.id

    receipt_path = None
    if receipt is not None and receipt.filename:
        receipt_path = _store_receipt(receipt, uploads_dir)

    txn = Transaction(
        bucket_id=bucket.id,
        household_id=household_id,
        amount=data.amount,
        currency=data.currency,
        exchange_rate=data.exchange_rate,
        type=data.type,
        paid_by=paid_by,
        category_id=category_id,
        notes=data.notes,
        transaction_date=data.transaction_date,
        receipt_path=receipt_path,
        payment_method=data.payment_method,
        merchant=data.merchant,
        client_id=data.client_id,
        exclude_from_forecast=data.exclude_from_forecast,
        exclude_from_settlement=data.exclude_from_settlement,
    )
    try:
        db.add(txn)
        db.flush()
        for s in data.splits:
            db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=s.amount))
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
    return txn


def update_transaction(
    db: Session,
    txn: Transaction,
    *,
    household_id: str,
    user,
    data: TransactionUpdate,
) -> Transaction:
    """Apply a validated edit (see app.schemas.TransactionUpdate). Callers commit.

    Mirrors create_transaction's database checks: bucket, category, payer and
    split users must belong to ``household_id``; a split expense always keeps a
    payer (the existing one, else the editor) so settle-up never drops it.
    """
    from app.validators import require_bucket

    require_bucket(db, data.bucket_id, household_id)
    paid_by = require_member(db, data.paid_by, household_id)
    category_id = require_category(db, data.category_id, household_id)
    if data.splits:
        validate_split_users([s.user_id for s in data.splits], household_id, db)
    if not paid_by and data.type.value == "expense" and data.splits:
        paid_by = txn.paid_by or user.id

    txn.bucket_id = data.bucket_id
    txn.amount = data.amount
    txn.currency = data.currency
    txn.exchange_rate = data.exchange_rate
    txn.type = data.type
    txn.paid_by = paid_by
    txn.category_id = category_id
    txn.notes = data.notes
    txn.payment_method = data.payment_method
    txn.merchant = data.merchant
    txn.exclude_from_forecast = data.exclude_from_forecast
    txn.exclude_from_settlement = data.exclude_from_settlement
    if data.transaction_date is not None:
        txn.transaction_date = data.transaction_date

    db.query(TransactionSplit).filter_by(transaction_id=txn.id).delete(synchronize_session=False)
    db.expire(txn, ["splits"])
    for s in data.splits:
        db.add(TransactionSplit(transaction_id=txn.id, user_id=s.user_id, amount=s.amount))
    return txn
