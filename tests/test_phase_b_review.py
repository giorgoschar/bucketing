"""Phase B S3 (spec §3.3-§3.5, §6 "Review", "List", "Scheduler")."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core.clock import utcnow_naive
from app.models import (
    Household,
    MonthReview,
    Notification,
    NotificationMute,
    NotificationType,
    Transaction,
    TransactionType,
)
from app.services.cash import STASH_IN, TAKE, add_movement
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

D = Decimal
NOW = date(2026, 10, 3)
URL = "/api/v1/insights/statements"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    import app.api.insights as api_insights

    monkeypatch.setattr(api_insights, "local_today", lambda: NOW)


def _txn(db, hh, amount, day, *, type=TransactionType.expense, **kw):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=None if type == TransactionType.income else hh.bucket_id,
        amount=D(str(amount)),
        type=type,
        paid_by=hh.user_id,
        transaction_date=day,
        **kw,
    )
    db.add(t)
    db.flush()
    return t


def _review(client, headers, month):
    return client.post(f"{URL}/{month}/review", headers=headers)


# ------------------------------------------------------------------ review


def test_review_marks_the_month_and_is_idempotent(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 9, 5))
    db.commit()
    first = _review(client, headers, "2026-09")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["month"] == "2026-09"
    assert body["reviewed_by"] == hh.user_id and body["reviewed_at"]
    assert body["closed"] is True and body["days_left"] is None
    again = _review(client, headers, "2026-09").json()
    assert again["reviewed_at"] == body["reviewed_at"]
    db.expire_all()
    assert db.query(MonthReview).count() == 1


def test_the_first_reviewer_is_kept(client, db, api):  # noqa: F811
    headers, hh = api
    first = _review(client, headers, "2026-09").json()
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    db.expire_all()
    row = db.query(MonthReview).one()
    # A second member's later call (simulated at the service) changes nothing.
    from app.services.statement import mark_reviewed

    again = mark_reviewed(db, hh.household_id, "2026-09", flat.id)
    db.commit()
    assert again.reviewed_by == hh.user_id == first["reviewed_by"]
    assert again.reviewed_at == row.reviewed_at
    assert db.query(MonthReview).count() == 1


def test_a_lost_race_on_the_unique_constraint_is_not_an_error(client, db, api):  # noqa: F811
    """Review Focus 4: the other request inserted between our read and insert."""
    import app.services.statement as statement

    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    winner = MonthReview(
        household_id=hh.household_id,
        month="2026-09",
        reviewed_at=datetime(2026, 10, 2, 7, 0, tzinfo=UTC).replace(tzinfo=None),
        reviewed_by=flat.id,
    )
    db.add(winner)
    db.commit()

    real = statement.get_review
    calls = {"n": 0}

    def blind_first(db_, household_id, month):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db_, household_id, month)

    statement.get_review = blind_first
    try:
        r = _review(client, headers, "2026-09")
    finally:
        statement.get_review = real
    assert r.status_code == 200, r.text
    assert r.json()["reviewed_by"] == flat.id
    db.expire_all()
    assert db.query(MonthReview).count() == 1


def test_two_concurrent_reviews_leave_one_row(client, db, api, SessionLocal):  # noqa: F811
    import threading

    from app.services.statement import mark_reviewed

    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    barrier = threading.Barrier(2)
    errors = []

    def press(user_id):
        s = SessionLocal()
        try:
            barrier.wait(timeout=5)
            mark_reviewed(s, hh.household_id, "2026-09", user_id)
            s.commit()
        except Exception as exc:  # pragma: no cover - the failure being tested for
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=press, args=(u,)) for u in (hh.user_id, flat.id)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors, errors
    db.expire_all()
    assert db.query(MonthReview).count() == 1


def test_another_households_month_is_untouched(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other")
    assert _review(client, headers, "2026-09").status_code == 200
    db.expire_all()
    rows = db.query(MonthReview).all()
    assert [r.household_id for r in rows] == [hh.household_id]
    assert other.household_id not in {r.household_id for r in rows}


def test_review_rejects_bad_current_future_and_anonymous(client, db, api):  # noqa: F811
    headers, hh = api
    assert _review(client, headers, "nope").status_code == 400
    assert _review(client, headers, "2026-10").status_code == 404
    assert _review(client, headers, "2027-01").status_code == 404
    assert client.post(f"{URL}/2026-09/review").status_code == 401
    db.expire_all()
    assert db.query(MonthReview).count() == 0


# -------------------------------------------------------------------- list


def test_list_runs_from_the_first_month_with_data_with_zeros_between(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 3000, date(2026, 6, 2), type=TransactionType.income)
    _txn(db, hh, 40, date(2026, 6, 9))
    _txn(db, hh, 25, date(2026, 9, 9))
    _txn(db, hh, 99, date(2026, 10, 1))  # this month: not listed
    db.commit()
    body = client.get(URL, headers=headers).json()
    assert [m["month"] for m in body["months"]] == ["2026-09", "2026-08", "2026-07", "2026-06"]
    by = {m["month"]: m for m in body["months"]}
    assert by["2026-06"]["in"] == 3000.0 and by["2026-06"]["net"] == 2960.0
    assert (by["2026-08"]["in"], by["2026-08"]["out"], by["2026-08"]["net"]) == (0.0, 0.0, 0.0)
    assert by["2026-09"]["label"] == "September 2026"
    assert by["2026-09"]["reviewed_at"] is None and by["2026-09"]["closed"] is False
    assert by["2026-06"]["closed"] is True  # past its window
    assert set(by["2026-09"]) == {"month", "label", "in", "out", "net", "reviewed_at", "closed"}


def test_list_starts_at_a_cash_movement_too(client, db, api):  # noqa: F811
    headers, hh = api
    add_movement(db, hh.household_id, hh.user_id, TAKE, D("30"), "EUR", date(2026, 8, 3))
    months = client.get(URL, headers=headers).json()["months"]
    assert [m["month"] for m in months] == ["2026-09", "2026-08"]
    assert months[1]["out"] == 30.0


def test_list_is_capped_at_120_months_newest_first(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 5, date(2014, 1, 5))
    _txn(db, hh, 7, date(2026, 9, 5))
    db.commit()
    months = client.get(URL, headers=headers).json()["months"]
    assert len(months) == 120
    assert months[0]["month"] == "2026-09" and months[-1]["month"] == "2016-10"


def test_list_totals_equal_each_statement(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 3000, date(2026, 7, 1), type=TransactionType.income)
    _txn(db, hh, 80, date(2026, 7, 3), currency="USD", exchange_rate=D("0.9"))
    add_movement(db, hh.household_id, hh.user_id, TAKE, D("45"), "EUR", date(2026, 8, 2))
    _txn(db, hh, 12.5, date(2026, 8, 20))
    _txn(db, hh, 7.25, date(2026, 9, 20))
    db.commit()
    months = client.get(URL, headers=headers).json()["months"]
    assert len(months) == 3
    for row in months:
        s = client.get(f"{URL}/{row['month']}", headers=headers).json()["totals"]
        assert (row["in"], row["out"], row["net"]) == (s["in"], s["out"], s["net"]), row["month"]


def test_review_is_last_month_in_the_window_unreviewed_with_data(client, db, api, monkeypatch):  # noqa: F811
    import app.api.insights as api_insights

    headers, hh = api
    _txn(db, hh, 10, date(2026, 9, 5))
    db.commit()
    body = client.get(URL, headers=headers).json()
    assert body["review"] == {"month": "2026-09", "label": "September 2026", "days_left": 3}
    # reviewed: gone
    _review(client, headers, "2026-09")
    assert client.get(URL, headers=headers).json()["review"] is None
    # outside the window: gone, even though the month is still listed
    db.query(MonthReview).delete()
    db.commit()
    monkeypatch.setattr(api_insights, "local_today", lambda: date(2026, 10, 6))
    body = client.get(URL, headers=headers).json()
    assert body["review"] is None and body["months"][0]["month"] == "2026-09"


def test_no_review_when_last_month_has_no_data(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 7, 5))
    db.commit()
    body = client.get(URL, headers=headers).json()
    assert body["review"] is None
    assert [m["month"] for m in body["months"]] == ["2026-09", "2026-08", "2026-07"]


def test_a_household_whose_first_data_is_this_month(client, db, api):  # noqa: F811
    """Review Focus 5: no review, an empty list."""
    headers, hh = api
    _txn(db, hh, 10, date(2026, 10, 1))
    db.commit()
    assert client.get(URL, headers=headers).json() == {"review": None, "months": []}
    nobody = client.get(URL, headers=headers)
    assert nobody.status_code == 200


def test_list_isolation_and_no_stash(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other")
    _txn(db, other, 555, date(2026, 5, 5))
    _txn(db, hh, 10, date(2026, 9, 5))
    add_movement(db, hh.household_id, hh.user_id, STASH_IN, D("777.77"), "EUR", date(2026, 9, 1))
    db.commit()
    resp = client.get(URL, headers=headers)
    assert "777" not in resp.text
    assert [m["month"] for m in resp.json()["months"]] == ["2026-09"]
    assert resp.json()["months"][0]["out"] == 10.0
    assert client.get(URL).status_code == 401


def _count(db, fn):
    statements = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        fn()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    return len(statements)


def test_list_query_count_is_bounded(client, db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 8, 5))
    db.commit()
    small = _count(db, lambda: client.get(URL, headers=headers))
    for n in range(36):
        y, m = divmod(2023 * 12 + n, 12)
        for k in range(5):
            _txn(db, hh, 5 + k, date(y, m + 1, 1 + k))
    add_movement(db, hh.household_id, hh.user_id, TAKE, D("45"), "EUR", date(2024, 3, 2))
    db.commit()
    large = _count(db, lambda: client.get(URL, headers=headers))
    assert small == large, (small, large)
    assert len(client.get(URL, headers=headers).json()["months"]) > 36


# --------------------------------------------------------------- scheduler


def _stage(db, today):
    from app.scheduler import _notify_month_review

    _notify_month_review(db, today)
    db.expire_all()


def _notes(db, **filters):
    return db.query(Notification).filter_by(type=NotificationType.month_review, **filters).all()


def _september(db, hh):
    _txn(db, hh, 3000, date(2026, 9, 1), type=TransactionType.income)
    _txn(db, hh, 2240, date(2026, 9, 9))
    db.commit()


def test_sent_once_on_day_one_to_every_member_with_the_right_text(db, api):  # noqa: F811
    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    _september(db, hh)
    _stage(db, date(2026, 10, 1))
    _stage(db, date(2026, 10, 1))
    _stage(db, date(2026, 10, 2))
    notes = _notes(db)
    assert sorted(n.user_id for n in notes) == sorted([hh.user_id, flat.id])
    n = notes[0]
    assert n.title == "September is ready to review"
    assert n.body == "In €3,000 · Out €2,240 · Net +€760"
    assert n.link == "/app/insights/statements/2026-09"
    assert n.dedupe_key == f"month_review:{hh.household_id}:2026-09"
    assert n.household_id == hh.household_id


def test_body_shows_cents_and_a_negative_net(db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 120.5, date(2026, 9, 9))
    db.commit()
    _stage(db, date(2026, 10, 2))
    assert _notes(db)[0].body == "In €0 · Out €120.50 · Net -€120.50"


def test_not_sent_after_day_five(db, api):  # noqa: F811
    headers, hh = api
    _september(db, hh)
    _stage(db, date(2026, 10, 6))
    _stage(db, date(2026, 10, 20))
    assert _notes(db) == []
    _stage(db, date(2026, 10, 5))
    assert len(_notes(db)) == 1


def test_not_sent_when_reviewed(db, api):  # noqa: F811
    headers, hh = api
    _september(db, hh)
    db.add(MonthReview(household_id=hh.household_id, month="2026-09", reviewed_at=utcnow_naive()))
    db.commit()
    _stage(db, date(2026, 10, 1))
    assert _notes(db) == []


def test_not_sent_for_a_household_with_no_data_in_that_month(db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 8, 9))
    _txn(db, hh, 10, date(2026, 10, 1))  # this month does not count
    db.commit()
    _stage(db, date(2026, 10, 2))
    assert _notes(db) == []


def test_a_muted_member_gets_nothing(db, api):  # noqa: F811
    headers, hh = api
    flat, _ = _add_member_user(db, hh.household_id, "flatmate")
    _september(db, hh)
    db.add(NotificationMute(user_id=flat.id, household_id=hh.household_id, type="month_review"))
    db.commit()
    _stage(db, date(2026, 10, 1))
    assert [n.user_id for n in _notes(db)] == [hh.user_id]


def test_the_turn_of_the_year(db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 70, date(2025, 12, 20))
    db.commit()
    _stage(db, date(2026, 1, 3))
    [n] = _notes(db)
    assert n.title == "December is ready to review"
    assert n.link == "/app/insights/statements/2025-12"


def test_one_household_failing_does_not_stop_the_next(db, api, make_household, monkeypatch):  # noqa: F811
    import app.services.insights as insights

    headers, hh = api
    other = make_household(name="Other")
    _september(db, hh)
    _txn(db, other, 55, date(2026, 9, 9))
    db.commit()
    real = insights.in_out_by_month

    def flaky(db_, household_id, *a, **kw):
        if household_id == min(hh.household_id, other.household_id):
            raise RuntimeError("boom")
        return real(db_, household_id, *a, **kw)

    monkeypatch.setattr(insights, "in_out_by_month", flaky)
    _stage(db, date(2026, 10, 1))
    sent = {n.household_id for n in _notes(db)}
    assert sent == {hh.household_id, other.household_id} - {
        min(hh.household_id, other.household_id)
    }


def test_a_household_whose_first_data_is_this_month_gets_no_notification(db, api):  # noqa: F811
    headers, hh = api
    _txn(db, hh, 10, date(2026, 10, 1))
    db.commit()
    _stage(db, date(2026, 10, 1))
    assert _notes(db) == []


def test_the_daily_job_runs_the_stage(db, api, SessionLocal, monkeypatch):  # noqa: F811
    import app.core.database as database
    import app.scheduler as scheduler

    headers, hh = api
    _september(db, hh)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    monkeypatch.setattr(scheduler, "today_local", lambda: date(2026, 10, 1))
    scheduler.auto_mark_paid_job()
    db.expire_all()
    assert len(_notes(db)) == 1


def test_no_stash_amount_in_the_notification(db, api):  # noqa: F811
    headers, hh = api
    _september(db, hh)
    add_movement(db, hh.household_id, hh.user_id, STASH_IN, D("777.77"), "EUR", date(2026, 9, 1))
    _stage(db, date(2026, 10, 1))
    n = _notes(db)[0]
    assert "777" not in json.dumps([n.title, n.body])


def test_archived_households_are_skipped(db, api):  # noqa: F811
    headers, hh = api
    _september(db, hh)
    db.get(Household, hh.household_id).archived_at = utcnow_naive()
    db.commit()
    _stage(db, date(2026, 10, 1))
    assert _notes(db) == []
