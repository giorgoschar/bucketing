"""
Background scheduler for auto-pay bills and bill-due notifications.
Runs a daily job at midnight+5min.
"""
import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def auto_mark_paid_job() -> None:
    """
    Mark fixed-amount auto-pay bill occurrences as paid when they are due.
    Variable-amount auto-pay bills are skipped (user must enter the amount manually).
    Also fires bill_due notifications for occurrences coming up in 3 days,
    and bill_overdue notifications for overdue unpaid occurrences.
    """
    from app.database import SessionLocal
    from app.models import (
        BillOccurrence,
        HouseholdMember,
        NotificationType,
        OccurrenceStatus,
        RecurringBill,
        Transaction,
        TransactionSplit,
        TransactionType,
    )
    from app.notification_service import create_notification, send_push_for_notification

    db = SessionLocal()
    try:
        today = date.today()
        occs = (
            db.query(BillOccurrence)
            .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
            .filter(
                BillOccurrence.status == OccurrenceStatus.unpaid,
                BillOccurrence.due_date <= today,
                BillOccurrence.transaction_id.is_(None),
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
                # Create per-member split records if the bill has splits configured
                if bill.splits:
                    for s in bill.splits:
                        db.add(TransactionSplit(
                            transaction_id=txn.id,
                            user_id=s.user_id,
                            amount=s.amount,
                        ))

            occ.status = OccurrenceStatus.paid
            occ.paid_at = datetime.utcnow()
            occ.paid_by = bill.paid_by_default
            count += 1

            # Notify all household members about the auto-payment
            members = (
                db.query(HouseholdMember)
                .filter(HouseholdMember.household_id == bill.household_id)
                .all()
            )
            for m in members:
                notif = create_notification(
                    db,
                    household_id=bill.household_id,
                    user_id=m.user_id,
                    type=NotificationType.bill_auto_paid,
                    title=f"Auto-paid: {bill.name}",
                    body=f"€{pay_amount:.2f} marked as paid",
                    link="/bills",
                )
                send_push_for_notification(db, notif)

        if count:
            db.commit()
            logger.info("Auto-paid %d bill occurrence(s)", count)

        # ----------------------------------------------------------------
        # Notify: bill due soon (exactly 3 days out)
        # ----------------------------------------------------------------
        due_soon_date = today + timedelta(days=3)
        due_soon_occs = (
            db.query(BillOccurrence)
            .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
            .filter(
                BillOccurrence.status == OccurrenceStatus.unpaid,
                BillOccurrence.due_date == due_soon_date,
                RecurringBill.is_active.is_(True),
            )
            .all()
        )
        for occ in due_soon_occs:
            bill = occ.bill
            members = (
                db.query(HouseholdMember)
                .filter(HouseholdMember.household_id == bill.household_id)
                .all()
            )
            for m in members:
                notif = create_notification(
                    db,
                    household_id=bill.household_id,
                    user_id=m.user_id,
                    type=NotificationType.bill_due,
                    title=f"Bill due in 3 days: {bill.name}",
                    body=f"€{occ.amount or bill.amount:.2f} due on {occ.due_date}",
                    link="/bills",
                )
                send_push_for_notification(db, notif)

        # ----------------------------------------------------------------
        # Notify: overdue bills (due before today, still unpaid)
        # ----------------------------------------------------------------
        overdue_occs = (
            db.query(BillOccurrence)
            .join(RecurringBill, RecurringBill.id == BillOccurrence.bill_id)
            .filter(
                BillOccurrence.status == OccurrenceStatus.unpaid,
                BillOccurrence.due_date < today,
                RecurringBill.is_active.is_(True),
                RecurringBill.is_auto_pay.is_(False),
            )
            .all()
        )
        for occ in overdue_occs:
            bill = occ.bill
            members = (
                db.query(HouseholdMember)
                .filter(HouseholdMember.household_id == bill.household_id)
                .all()
            )
            for m in members:
                notif = create_notification(
                    db,
                    household_id=bill.household_id,
                    user_id=m.user_id,
                    type=NotificationType.bill_overdue,
                    title=f"Overdue bill: {bill.name}",
                    body=f"Was due on {occ.due_date}",
                    link="/bills",
                )
                send_push_for_notification(db, notif)

        db.commit()
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
