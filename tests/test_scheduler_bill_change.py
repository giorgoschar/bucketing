"""Phase A S3 (spec §3.7): the daily bill-change alert, on app.services.bill_change."""

from datetime import date, timedelta

import pytest

from app.models import (
    BillOccurrence,
    HouseholdMember,
    MemberRole,
    Notification,
    NotificationMute,
    NotificationType,
    OccurrenceStatus,
    RecurringBill,
)
from app.scheduler import today_local


@pytest.fixture()
def run_job(monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    return scheduler.auto_mark_paid_job


def _bill(db, hh, name="Electricity", **over):
    fields = dict(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        name=name,
        amount=None,
        currency="EUR",
        start_date=date(2020, 1, 1),
        interval_months=1,
        is_auto_pay=False,
        is_active=True,
        usage_unit="kWh",
    )
    fields.update(over)
    bill = RecurringBill(**fields)
    db.add(bill)
    db.flush()
    return bill


def _entry(db, bill, due, amount, usage=None):
    occ = BillOccurrence(
        bill_id=bill.id, due_date=due, amount=amount, usage=usage, status=OccurrenceStatus.paid
    )
    db.add(occ)
    db.flush()
    return occ


def _recent(db, bill, amounts, usages=None, age_days=2):
    """Entries 30 days apart; the latest ``age_days`` ago. Returns them."""
    n = len(amounts)
    return [
        _entry(
            db,
            bill,
            today_local() - timedelta(days=age_days + 30 * (n - 1 - i)),
            a,
            None if usages is None else usages[i],
        )
        for i, a in enumerate(amounts)
    ]


def _notes(db):
    return db.query(Notification).filter(Notification.type == NotificationType.bill_drift).all()


def test_recent_basis_title_body_and_link(db, authed, run_job):
    bill = _bill(db, authed)
    _recent(db, bill, [60, 61, 62, 84])
    db.commit()
    run_job()
    [note] = _notes(db)
    assert note.title == "Electricity was €84, usually €61"
    assert note.body == "Usual from the last 3 payments: €61."
    assert note.link == f"/app/insights/bills/{bill.id}"


def test_last_year_basis_body(db, authed, run_job):
    bill = _bill(db, authed)
    [*_, latest] = _recent(db, bill, [70, 70, 70, 90])
    _entry(db, bill, date(latest.due_date.year - 1, latest.due_date.month, 10), 60)
    db.commit()
    run_job()
    [note] = _notes(db)
    assert note.title == "Electricity was €90, usually €60"
    assert note.body == "Same month last year: €60."


def test_a_seasonal_bill_does_not_alert(db, authed, run_job):
    """Review Focus 1: 84 after 40, 50, 70 with 80 the same month last year."""
    bill = _bill(db, authed)
    [*_, latest] = _recent(db, bill, [40, 50, 70, 84])
    _entry(db, bill, date(latest.due_date.year - 1, latest.due_date.month, 10), 80)
    db.commit()
    run_job()
    assert _notes(db) == []


def test_cents_are_shown_when_the_amount_is_not_whole(db, authed, run_job):
    bill = _bill(db, authed, currency="EUR")
    _recent(db, bill, [60, 60, 60, 84.5])
    db.commit()
    run_job()
    [note] = _notes(db)
    assert note.title == "Electricity was €84.50, usually €60"


@pytest.mark.parametrize(
    ("amounts", "usages", "tail"),
    [
        ([60, 60, 60, 80], [300, 300, 300, 400], " You used 33% more kWh."),
        ([60, 60, 60, 84], [300, 300, 300, 300], " The price per kWh went up 40%."),
        ([60, 60, 60, 30], [300, 300, 300, 150], " You used 50% less kWh."),
        ([60, 60, 60, 36], [300, 300, 300, 300], " The price per kWh went down 40%."),
    ],
)
def test_reason_sentence(db, authed, run_job, amounts, usages, tail):
    bill = _bill(db, authed)
    _recent(db, bill, amounts, usages)
    db.commit()
    run_job()
    [note] = _notes(db)
    assert note.body == "Usual from the last 3 payments: €60." + tail


def test_no_reason_when_usage_is_missing_or_zero(db, authed, run_job):
    bill = _bill(db, authed)
    _recent(db, bill, [60, 60, 60, 84], [300, 300, 300, 0])
    db.commit()
    run_job()
    [note] = _notes(db)
    assert note.body == "Usual from the last 3 payments: €60."


def test_every_member_is_notified_once_and_a_muted_member_not_at_all(
    db, authed, run_job, make_household
):
    other = make_household(name="Second", username="second")
    db.add(
        HouseholdMember(
            household_id=authed.household_id, user_id=other.user_id, role=MemberRole.member
        )
    )
    third = make_household(name="Third", username="third")
    db.add(
        HouseholdMember(
            household_id=authed.household_id, user_id=third.user_id, role=MemberRole.member
        )
    )
    db.add(
        NotificationMute(
            user_id=third.user_id,
            household_id=authed.household_id,
            type=NotificationType.bill_drift.value,
        )
    )
    bill = _bill(db, authed)
    _recent(db, bill, [60, 60, 60, 84])
    db.commit()
    for _ in range(3):
        run_job()
    users = sorted(n.user_id for n in _notes(db) if n.household_id == authed.household_id)
    assert users == sorted([authed.user_id, other.user_id])


def test_an_entry_already_notified_under_the_old_key_is_not_notified_again(db, authed, run_job):
    bill = _bill(db, authed)
    *_, latest = _recent(db, bill, [60, 60, 60, 84])
    db.add(
        Notification(
            household_id=authed.household_id,
            user_id=authed.user_id,
            type=NotificationType.bill_drift,
            title="Electricity is 40% up",
            body="old wording",
            link="/bills",
            dedupe_key=f"bill_drift:{latest.id}",
        )
    )
    db.commit()
    run_job()
    [note] = _notes(db)
    assert note.title == "Electricity is 40% up"


def test_a_newer_entry_notifies_again(db, authed, run_job):
    bill = _bill(db, authed)
    _recent(db, bill, [60, 60, 60, 84], age_days=40)
    db.commit()
    run_job()
    assert _notes(db) == []  # 40 days old: outside the window
    _entry(db, bill, today_local() - timedelta(days=1), 120)
    db.commit()
    run_job()
    assert len(_notes(db)) == 1


def test_the_35_day_window(db, authed, run_job):
    inside = _bill(db, authed, name="Inside")
    outside = _bill(db, authed, name="Outside")
    _recent(db, inside, [50, 50, 50, 90], age_days=35)
    _recent(db, outside, [50, 50, 50, 90], age_days=36)
    db.commit()
    run_job()
    assert [n.title for n in _notes(db)] == ["Inside was €90, usually €50"]


def test_income_paused_and_weekly_rules(db, authed, run_job):
    income = _bill(db, authed, name="Salary", direction="in")
    paused = _bill(db, authed, name="Paused", is_active=False)
    for b in (income, paused):
        _recent(db, b, [50, 50, 50, 90])
    weekly = _bill(db, authed, name="Weekly", rule_kind="weekly", rule_weekday=1)
    [*_, latest] = _recent(db, weekly, [50, 50, 50, 90])
    _entry(db, weekly, date(latest.due_date.year - 1, latest.due_date.month, 10), 89)
    db.commit()
    run_job()
    # The weekly item skips last_year (89 would be "no change") and compares with recent.
    assert [n.title for n in _notes(db)] == ["Weekly was €90, usually €50"]
    assert "Usual from the last 3 payments" in _notes(db)[0].body


def test_a_non_euro_currency_symbol(db, authed, run_job):
    bill = _bill(db, authed, currency="USD")
    _recent(db, bill, [60, 60, 60, 84])
    db.commit()
    run_job()
    assert _notes(db)[0].title == "Electricity was $84, usually $60"


def test_the_old_drift_constants_are_gone():
    import app.scheduler as scheduler

    assert not [n for n in dir(scheduler) if n.startswith("DRIFT_")]


def test_one_failing_item_does_not_lose_the_others(db, authed, run_job, monkeypatch):
    import app.services.bill_change as bc

    good = _bill(db, authed, name="Good")
    bad = _bill(db, authed, name="Bad")
    also_good = _bill(db, authed, name="Also good")
    for b in (good, bad, also_good):
        _recent(db, b, [60, 60, 60, 84])
    db.commit()
    real = bc.change_title

    def flaky(name, change, currency):
        if name == "Bad":
            raise RuntimeError("boom")
        return real(name, change, currency)

    monkeypatch.setattr(bc, "change_title", flaky)
    run_job()
    assert sorted(n.title.split(" was")[0] for n in _notes(db)) == ["Also good", "Good"]
