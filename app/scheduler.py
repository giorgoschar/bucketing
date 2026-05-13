"""
Background scheduler for auto-pay bills.
Runs a daily job at midnight+5min to auto-mark fixed-amount auto-pay bills as paid.
"""
import logging
from datetime import date, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def auto_mark_paid_job() -> None:
    """
    Mark fixed-amount auto-pay bill occurrences as paid when they are due.
    Variable-amount auto-pay bills are skipped (user must enter the amount manually).
    """
    from app.database import SessionLocal
    from app.models import (
        BillOccurrence,
        OccurrenceStatus,
        RecurringBill,
        Transaction,
        TransactionType,
    )

    db = SessionLocal()
    try:
        today = date.today()
        occs = (
            db.query(BillOccurrence)
            .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
            .filter(
                BillOccurrence.status == OccurrenceStatus.unpaid,
                BillOccurrence.due_date <= today,
                RecurringBill.is_auto_pay.is_(True),
                RecurringBill.is_active.is_(True),
                # Fixed-amount bill OR occurrence has a pre-set amount (variable standing order)
                (RecurringBill.amount.isnot(None) | BillOccurrence.amount.isnot(None)),
            )
            .all()
        )

        count = 0
        for occ in occs:
            bill = occ.bill
            pay_amount = occ.amount or bill.amount  # occurrence amount takes precedence
            if bill.bucket_id:
                txn = Transaction(
                    bucket_id=bill.bucket_id,
                    household_id=bill.household_id,
                    amount=pay_amount,
                    currency=bill.currency,
                    type=TransactionType.expense,
                    paid_by=bill.paid_by_default,
                    category_id=bill.category_id,
                    notes=f"Auto-pay: {bill.name}",
                    transaction_date=occ.due_date,
                )
                db.add(txn)
                db.flush()
                occ.transaction_id = txn.id

            occ.status = OccurrenceStatus.paid
            occ.paid_at = datetime.utcnow()
            occ.paid_by = bill.paid_by_default
            count += 1

        if count:
            db.commit()
            logger.info("Auto-paid %d bill occurrence(s)", count)
    except Exception:
        logger.exception("auto_mark_paid_job failed")
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    """Start the background scheduler and run an immediate catch-up job."""
    # Daily at 00:05 UTC
    scheduler.add_job(
        auto_mark_paid_job,
        CronTrigger(hour=0, minute=5),
        id="auto_mark_paid_daily",
        replace_existing=True,
    )
    # Run immediately on startup to catch any bills missed while server was down
    scheduler.add_job(
        auto_mark_paid_job,
        id="auto_mark_paid_startup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
