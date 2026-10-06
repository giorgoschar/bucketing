"""
Scheduler regression tests.

These cover the duplicate auto-pay bug: `entrypoint.sh` runs
`uvicorn --workers 2`, and every worker starts its own BackgroundScheduler, so
the daily job and the startup catch-up job can run concurrently and repeatedly.
"""

import threading
from datetime import UTC, timedelta

import pytest

from app.models import (
    BillOccurrence,
    Notification,
    OccurrenceStatus,
    Transaction,
)
from app.scheduler import today_local


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    """Run the real scheduler job against the test database."""
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def test_autopay_creates_one_transaction(db, make_household, make_bill, run_job):
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)

    run_job()

    txns = db.query(Transaction).all()
    assert len(txns) == 1
    assert float(txns[0].amount) == 45.0
    occ = db.query(BillOccurrence).one()
    assert occ.status == OccurrenceStatus.paid
    assert occ.transaction_id == txns[0].id


def test_autopay_is_idempotent_across_reruns(db, make_household, make_bill, run_job):
    """Server restarts fire the catch-up job again; it must not re-charge."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)

    for _ in range(5):
        run_job()

    assert db.query(Transaction).count() == 1
    assert db.query(Notification).count() == 1


def test_autopay_is_safe_under_concurrent_workers(db, make_household, make_bill, run_job):
    """The regression: two workers entering the job simultaneously.

    Before the fix this produced two transactions and double-charged the
    household.
    """
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=800, paid_by=hh.user_id)

    barrier = threading.Barrier(2)
    errors = []

    def worker():
        try:
            barrier.wait()
            run_job()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    txns = db.query(Transaction).all()
    assert len(txns) == 1, f"double-charged: {[float(t.amount) for t in txns]}"
    assert sum(float(t.amount) for t in txns) == 800.0


def test_variable_bill_without_amount_is_not_paid(db, make_household, make_bill, run_job):
    """A variable bill with no amount anywhere needs manual entry."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=None, paid_by=hh.user_id)

    run_job()

    assert db.query(Transaction).count() == 0
    assert db.query(BillOccurrence).one().status == OccurrenceStatus.unpaid


def test_variable_bill_uses_preset_occurrence_amount(db, make_household, make_bill, run_job):
    """Standing-order mode: the amount set on the occurrence is used."""
    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=None, occ_amount=73.5, paid_by=hh.user_id)

    run_job()

    txn = db.query(Transaction).one()
    assert float(txn.amount) == 73.5


def test_future_bills_are_not_paid_early(db, make_household, make_bill, run_job):
    hh = make_household()
    make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=45,
        due=today_local() + timedelta(days=5),
        paid_by=hh.user_id,
    )

    run_job()

    assert db.query(Transaction).count() == 0


def test_inactive_bill_is_skipped(db, make_household, make_bill, run_job):
    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)
    bill.is_active = False
    db.commit()

    run_job()

    assert db.query(Transaction).count() == 0


def test_overdue_reminder_does_not_repeat(db, make_household, make_bill, run_job):
    """An overdue bill used to re-notify on every run, forever."""
    hh = make_household()
    make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=30,
        auto_pay=False,
        due=today_local() - timedelta(days=3),
    )

    for _ in range(4):
        run_job()

    overdue = db.query(Notification).filter(Notification.title.like("Overdue%")).all()
    assert len(overdue) == 1


def test_overdue_reminder_repeats_at_next_milestone(db, make_household, make_bill, run_job):
    """Distinct milestones (3 then 7 days late) are separate reminders."""
    hh = make_household()
    make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=30,
        auto_pay=False,
        due=today_local() - timedelta(days=3),
    )
    run_job()

    # Move the due date so "today" is now 7 days past it.
    occ = db.query(BillOccurrence).one()
    occ.due_date = today_local() - timedelta(days=7)
    db.commit()
    run_job()

    overdue = db.query(Notification).filter(Notification.title.like("Overdue%")).all()
    assert len(overdue) == 2


def test_due_soon_notification_is_sent_once(db, make_household, make_bill, run_job):
    hh = make_household()
    make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=30,
        auto_pay=False,
        due=today_local() + timedelta(days=3),
    )

    run_job()
    run_job()

    due = db.query(Notification).filter(Notification.title.like("Bill due%")).all()
    assert len(due) == 1


def test_job_survives_a_bill_with_no_amount_in_notification(db, make_household, make_bill, run_job):
    """A None amount used to raise TypeError formatting the notification body."""
    hh = make_household()
    make_bill(
        hh.household_id,
        hh.bucket_id,
        amount=None,
        auto_pay=False,
        due=today_local() + timedelta(days=3),
    )

    run_job()  # must not raise

    due = db.query(Notification).filter(Notification.title.like("Bill due%")).all()
    assert len(due) == 1
    assert "Amount not set" in (due[0].body or "")


def test_bill_splits_are_copied_onto_the_transaction(db, make_household, make_bill, run_job):
    from app.models import RecurringBillSplit, TransactionSplit

    hh = make_household()
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=100, paid_by=hh.user_id)
    db.add(RecurringBillSplit(bill_id=bill.id, user_id=hh.user_id, amount=100))
    db.commit()

    run_job()

    splits = db.query(TransactionSplit).all()
    assert len(splits) == 1
    assert float(splits[0].amount) == 100.0


# ---------------------------------------------------------------------------
# Calendar timezone
# ---------------------------------------------------------------------------


def test_today_local_follows_configured_timezone(monkeypatch):
    """Bill due dates are local calendar dates, so "today" must be local too.

    Using the UTC date meant that between local midnight and the UTC offset a
    bill due today was not yet considered due.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import app.core.config as config
    import app.scheduler as scheduler

    monkeypatch.setattr(config.settings, "app_timezone", "Pacific/Kiritimati")  # UTC+14
    ahead = scheduler.today_local()
    monkeypatch.setattr(config.settings, "app_timezone", "Pacific/Midway")  # UTC-11
    behind = scheduler.today_local()

    assert ahead == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert behind == datetime.now(ZoneInfo("Pacific/Midway")).date()
    # 25 hours apart, so the two zones are never on the same calendar day.
    assert ahead != behind


def test_unknown_timezone_falls_back_to_utc(monkeypatch):
    from datetime import datetime

    import app.core.config as config
    import app.scheduler as scheduler

    monkeypatch.setattr(config.settings, "app_timezone", "Not/AZone")
    assert scheduler.today_local() == datetime.now(UTC).date()


def test_bill_due_today_local_is_paid(db, make_household, make_bill, run_job, monkeypatch):
    """Regression: a bill due on the local calendar date must be auto-paid."""
    import app.core.config as config
    from app.models import Transaction

    monkeypatch.setattr(config.settings, "app_timezone", "Europe/Athens")

    from app.scheduler import today_local

    hh = make_household()
    make_bill(hh.household_id, hh.bucket_id, amount=45, due=today_local(), paid_by=hh.user_id)

    run_job()
    assert db.query(Transaction).count() == 1


# ---------------------------------------------------------------------------
# Phase 6: daily price refresh, low-stock and price-drop alerts
# ---------------------------------------------------------------------------


def _stock_fixtures():
    from decimal import Decimal

    from app.integrations.posokanei import (
        PosokaneiUnavailable,
        PriceStats,
        ProductSummary,
        RetailerPrice,
    )

    def summary(pid, price="1.50"):
        return ProductSummary(
            id=pid,
            name="Milk",
            brand=None,
            barcode=None,
            unit=None,
            unit_quantity=None,
            image_url=None,
            retailer_prices=[
                RetailerPrice("lidl", "Lidl", Decimal(price), None, False, None, None)
            ],
            price_stats=PriceStats(Decimal(price), Decimal(price), Decimal(price)),
        )

    class Fake:
        def __init__(self, fail=False):
            self.fail = fail
            self.calls = []

        def get(self, pid, include_history=True):
            self.calls.append(pid)
            if self.fail:
                raise PosokaneiUnavailable("down")
            return summary(pid)

    return Fake


@pytest.fixture()
def fake_posokanei(monkeypatch):
    from app.integrations import posokanei

    Fake = _stock_fixtures()
    client = Fake()
    monkeypatch.setattr(posokanei, "_client", client)
    return client


def _stock_item(db, hh, name="Milk", posokanei_id="p-1", qty="1", min_qty="1", track=True):
    from decimal import Decimal

    from app.services import stock as stock_svc

    item = stock_svc.add_product(
        db,
        hh.household_id,
        hh.user_id,
        name=name,
        posokanei_id=posokanei_id,
        quantity=Decimal(qty),
        min_quantity=Decimal(min_qty),
    )
    item.track_price = track
    db.commit()
    return item


def test_price_refresh_snapshots_tracked_products_once_a_day(
    db, make_household, run_job, fake_posokanei
):
    from app.models import PriceSnapshot
    from app.services import stock as stock_svc

    hh = make_household()
    tracked = _stock_item(db, hh, "Milk", "p-1")
    _stock_item(db, hh, "Untracked", "p-2", track=False)
    _stock_item(db, hh, "Manual", None)
    archived = _stock_item(db, hh, "Gone", "p-3")
    stock_svc.archive_product(db, hh.household_id, archived.id)
    db.commit()

    run_job()
    run_job()

    assert fake_posokanei.calls == ["p-1"]  # skipped when today's snapshot exists
    snaps = db.query(PriceSnapshot).all()
    assert [(s.product_id, s.retailer, s.snapshot_date) for s in snaps] == [
        (tracked.product_id, "lidl", today_local())
    ]


def test_price_refresh_down_logs_and_job_continues(
    db, make_household, make_bill, run_job, monkeypatch, caplog
):
    from app.integrations import posokanei
    from app.models import PriceSnapshot

    Fake = _stock_fixtures()
    down = Fake(fail=True)
    monkeypatch.setattr(posokanei, "_client", down)
    hh = make_household()
    for n in range(5):
        _stock_item(db, hh, f"P{n}", f"p-{n}")
    make_bill(hh.household_id, hh.bucket_id, amount=45, paid_by=hh.user_id)

    with caplog.at_level("WARNING"):
        run_job()

    assert db.query(PriceSnapshot).count() == 0
    assert len(down.calls) == 3  # gives up after 3 straight failures
    assert "PosoKanei unavailable" in caplog.text
    # Other stages still ran.
    assert db.query(Transaction).count() == 1


def test_stock_low_notifies_when_crossing_once_a_day(db, make_household, run_job, fake_posokanei):
    from decimal import Decimal

    from app.models import NotificationType
    from app.services import stock as stock_svc

    hh = make_household()
    item = _stock_item(db, hh, "Coffee", None, qty="2", min_qty="1")
    stock_svc.adjust_stock(db, hh.household_id, item.id, Decimal("-1"), hh.user_id)  # 2 → 1
    db.commit()

    run_job()
    run_job()

    notes = db.query(Notification).filter_by(type=NotificationType.stock_low).all()
    assert len(notes) == 1
    assert notes[0].dedupe_key == f"stock_low:{item.id}:{today_local()}"
    assert "Coffee" in notes[0].title


def test_stock_low_is_quiet_when_it_was_already_low(db, make_household, run_job, fake_posokanei):
    from app.models import NotificationType

    hh = make_household()
    _stock_item(db, hh, "Salt", None, qty="0", min_qty="1")  # no recent movement
    run_job()
    assert db.query(Notification).filter_by(type=NotificationType.stock_low).count() == 0


def test_price_drop_notifies_once(db, make_household, run_job, fake_posokanei):
    from datetime import timedelta
    from decimal import Decimal

    from app.models import NotificationType, PriceSnapshot

    hh = make_household()
    item = _stock_item(db, hh, "Feta", "p-9", qty="5", min_qty="1")
    today = today_local()
    for d in range(1, 15):
        db.add(
            PriceSnapshot(
                product_id=item.product_id,
                retailer="lidl",
                price=Decimal("2.00"),
                snapshot_date=today - timedelta(days=d),
            )
        )
    db.commit()
    # The refresh stage stores today's 1.50 (fake), i.e. 25% under the median.

    run_job()
    run_job()

    notes = db.query(Notification).filter_by(type=NotificationType.price_drop).all()
    assert len(notes) == 1
    assert notes[0].dedupe_key == f"price_drop:{item.product_id}:{today}"
    assert "Feta" in notes[0].title


def test_no_price_drop_for_a_normal_price(db, make_household, run_job, fake_posokanei):
    from datetime import timedelta
    from decimal import Decimal

    from app.models import NotificationType, PriceSnapshot

    hh = make_household()
    item = _stock_item(db, hh, "Feta", "p-9", qty="5", min_qty="1")
    today = today_local()
    for d in range(1, 15):
        db.add(
            PriceSnapshot(
                product_id=item.product_id,
                retailer="lidl",
                price=Decimal("1.55"),
                snapshot_date=today - timedelta(days=d),
            )
        )
    db.commit()
    run_job()
    assert db.query(Notification).filter_by(type=NotificationType.price_drop).count() == 0


def test_dead_product_ids_do_not_starve_the_refresh(db, make_household, run_job, monkeypatch):
    """404s are per-product misses: skipped, never counted as an outage."""
    from app.integrations import posokanei
    from app.integrations.posokanei import PosokaneiNotFound
    from app.models import PriceSnapshot

    Fake = _stock_fixtures()

    class Mixed(Fake):
        def get(self, pid, include_history=True):
            if pid.startswith("dead"):
                self.calls.append(pid)
                raise PosokaneiNotFound(pid)
            return super().get(pid, include_history)

    client = Mixed()
    monkeypatch.setattr(posokanei, "_client", client)
    hh = make_household()
    for n in range(3):
        _stock_item(db, hh, f"Dead {n}", f"dead-{n}")
    good = _stock_item(db, hh, "Good", "zz-good")  # sorts last by id/name either way

    run_job()

    assert "zz-good" in client.calls
    snaps = db.query(PriceSnapshot).all()
    assert [(s.product_id, s.snapshot_date) for s in snaps] == [(good.product_id, today_local())]


def test_refresh_order_is_oldest_snapshot_first(db, make_household, run_job, monkeypatch):
    from datetime import timedelta
    from decimal import Decimal

    from app.integrations import posokanei
    from app.models import PriceSnapshot

    Fake = _stock_fixtures()
    client = Fake()
    monkeypatch.setattr(posokanei, "_client", client)
    hh = make_household()
    recent = _stock_item(db, hh, "Recent", "p-recent")
    stale = _stock_item(db, hh, "Stale", "p-stale")
    _stock_item(db, hh, "Never", "p-never")
    today = today_local()
    for item, age in ((recent, 1), (stale, 20)):
        db.add(
            PriceSnapshot(
                product_id=item.product_id,
                retailer="lidl",
                price=Decimal("1"),
                snapshot_date=today - timedelta(days=age),
            )
        )
    db.commit()

    run_job()

    assert client.calls == ["p-never", "p-stale", "p-recent"]
