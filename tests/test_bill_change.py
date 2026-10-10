"""Phase A S2 (spec §3.4): the comparison rule, as a table of cases, and the
entry points it reads."""

import itertools
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    OccurrenceStatus,
    PayerMode,
    RecurringBill,
    Transaction,
    TransactionType,
)
from app.services.bill_change import (
    ABS_GATE,
    ALERT_WINDOW_DAYS,
    PCT_GATE,
    RECENT_N,
    Point,
    assess,
    assess_item,
    entry_points,
    is_monthly,
)

D = Decimal


_ids = itertools.count(1)


def pt(due, amount, usage=None, period=None, paid_at=None):
    return Point(
        entry_id=f"e{next(_ids):04d}",
        due_date=due,
        amount=D(str(amount)),
        usage=None if usage is None else D(str(usage)),
        transaction_id=None,
        period=period,
        paid_at=paid_at,
    )


def series(*amounts, start=date(2026, 5, 14)):
    """Monthly points on the 14th, oldest first; an amount may be (amount, usage)."""
    out = []
    for i, a in enumerate(amounts):
        amount, usage = a if isinstance(a, tuple) else (a, None)
        month = start.month - 1 + i
        out.append(pt(date(start.year + month // 12, month % 12 + 1, 14), amount, usage))
    return out


def test_constants():
    assert (PCT_GATE, ABS_GATE, RECENT_N, ALERT_WINDOW_DAYS) == (D("20"), D("10"), 3, 35)


# ------------------------------------------------------------ the baseline


def test_recent_basis_uses_the_median_of_the_last_three_before_the_latest():
    points = series(10, 100, 50, 60, 90)  # prior three: 100, 50, 60 -> median 60
    ch = assess(points, monthly=True)
    assert ch is not None
    assert ch.basis == "recent" and ch.usual == D("60.00")
    assert ch.entry_id == points[-1].entry_id and ch.amount == D("90.00")
    assert ch.delta == D("30.00") and ch.pct == 50 and ch.direction == "up"
    assert ch.reason is None and ch.reason_pct is None


def test_median_not_mean():
    # Mean of 40, 40, 400 is 160, the median is 40; 90 vs 40 changes, vs 160 it falls.
    assert assess(series(40, 40, 400, 90), monthly=True).usual == D("40.00")


def test_last_year_basis_when_the_same_month_a_year_earlier_exists():
    points = [
        pt(date(2025, 9, 14), 60),
        pt(date(2026, 6, 14), 70),
        pt(date(2026, 7, 14), 70),
        pt(date(2026, 8, 14), 70),
        pt(date(2026, 9, 14), 84),
    ]
    ch = assess(points, monthly=True)
    assert ch.basis == "last_year" and ch.usual == D("60.00")
    assert ch.delta == D("24.00") and ch.pct == 40 and ch.direction == "up"


def test_last_year_is_the_baseline_even_when_recent_would_alert():
    """Review Focus 1: electricity at 84 in January after 40 in October, 80 last January."""
    points = [
        pt(date(2025, 1, 14), 80),
        pt(date(2025, 10, 14), 40),
        pt(date(2025, 11, 14), 50),
        pt(date(2025, 12, 14), 70),
        pt(date(2026, 1, 14), 84),
    ]
    assert assess(points, monthly=True) is None


def test_without_last_january_the_same_bill_compares_with_the_last_three():
    points = [
        pt(date(2025, 10, 14), 40),
        pt(date(2025, 11, 14), 50),
        pt(date(2025, 12, 14), 70),
        pt(date(2026, 1, 14), 84),
    ]
    ch = assess(points, monthly=True)
    assert ch.basis == "recent" and ch.usual == D("50.00") and ch.pct == 68


def test_last_year_below_the_gates_does_not_fall_back_to_recent():
    points = [
        pt(date(2025, 1, 14), 80),
        pt(date(2025, 10, 14), 10),
        pt(date(2025, 11, 14), 10),
        pt(date(2025, 12, 14), 10),
        pt(date(2026, 1, 14), 84),
    ]
    assert assess(points, monthly=True) is None


def test_a_weekly_item_never_uses_last_year():
    points = [
        pt(date(2025, 9, 14), 20),
        pt(date(2026, 8, 17), 50),
        pt(date(2026, 8, 24), 50),
        pt(date(2026, 8, 31), 50),
        pt(date(2026, 9, 14), 52),
    ]
    assert assess(points, monthly=False) is None  # recent: 52 vs 50
    ch = assess(points[:-1] + [pt(date(2026, 9, 14), 80)], monthly=False)
    assert ch.basis == "recent" and ch.usual == D("50.00")
    # The same series on a monthly item compares with Sept 2025.
    assert assess(points, monthly=True).basis == "last_year"


@pytest.mark.parametrize("n_prior", [0, 1, 2])
def test_fewer_than_three_prior_entries_is_no_result(n_prior):
    assert assess(series(*([50] * n_prior), 500), monthly=True) is None


def test_no_points_is_no_result():
    assert assess([], monthly=True) is None


def test_only_the_latest_entry_is_assessed():
    # An old spike followed by a calm latest entry is no change.
    assert assess(series(50, 50, 50, 200, 52), monthly=True) is None


def test_usual_of_zero_is_no_result():
    assert assess(series(0, 0, 0, 50), monthly=True) is None
    last_year = [pt(date(2025, 9, 14), 0), pt(date(2026, 9, 14), 50)]
    assert assess(last_year, monthly=True) is None


# ------------------------------------------------------------------- gates


def test_both_gates_exactly_at_the_limit_alert():
    ch = assess(series(50, 50, 50, 60), monthly=True)  # +20 %, +10
    assert ch is not None and ch.pct == 20 and ch.delta == D("10.00")


def test_percentage_gate_failing_alone():
    assert assess(series(1000, 1000, 1000, 1190), monthly=True) is None  # 19 %, +190


def test_absolute_gate_failing_alone():
    assert assess(series(20, 20, 20, 29.99), monthly=True) is None  # +49.95 %, +9.99
    assert assess(series(5, 5, 5, 9), monthly=True) is None  # +80 %, +4


def test_gates_use_the_unrounded_percentage():
    # 19.6 % rounds to 20 for display but fails the 20 % gate.
    assert assess(series(500, 500, 500, 598), monthly=True) is None


def test_down():
    ch = assess(series(100, 100, 100, 60), monthly=True)
    assert ch.direction == "down" and ch.delta == D("-40.00") and ch.pct == -40


def test_pct_rounds_half_up_at_the_edge():
    assert assess(series(200, 200, 200, 241), monthly=True).pct == 21  # 20.5 %
    assert assess(series(200, 200, 200, 159), monthly=True).pct == -21  # -20.5 %
    assert assess(series(40, 40, 40, 90.1), monthly=True).pct == 125  # 125.25 %


# ------------------------------------------------------------------ reason


def test_reason_usage():
    points = series((60, 300), (60, 300), (60, 300), (80, 400))  # 0.20 a kWh both
    ch = assess(points, monthly=True)
    assert ch.reason == "usage" and ch.reason_pct == 33


def test_reason_price():
    points = series((60, 300), (60, 300), (60, 300), (84, 300))  # price +40 %
    ch = assess(points, monthly=True)
    assert ch.reason == "price" and ch.reason_pct == 40


def test_reason_with_a_drop_is_signed():
    points = series((60, 300), (60, 300), (60, 300), (30, 150))
    ch = assess(points, monthly=True)
    assert ch.direction == "down" and ch.reason == "usage" and ch.reason_pct == -50


def test_reason_larger_change_wins_and_a_tie_is_usage():
    # usage +20 %, price (84 / 360 vs 60 / 300 = 0.2333 vs 0.2) +16.7 %: usage.
    ch = assess(series((60, 300), (60, 300), (60, 300), (84, 360)), monthly=True)
    assert ch.reason == "usage" and ch.reason_pct == 20
    # usage +10 %, price +27 %: price.
    ch = assess(series((60, 300), (60, 300), (60, 300), (84, 330)), monthly=True)
    assert ch.reason == "price" and ch.reason_pct == 27


def test_reason_on_last_year_uses_that_entry():
    points = [pt(date(2025, 9, 14), 60, 300), pt(date(2026, 9, 14), 90, 300)]
    ch = assess(points, monthly=True)
    assert ch.basis == "last_year" and ch.reason == "price" and ch.reason_pct == 50


def test_no_reason_when_a_baseline_entry_lacks_usage():
    points = series((60, 300), 60, (60, 300), (84, 300))
    ch = assess(points, monthly=True)
    assert ch is not None and ch.reason is None and ch.reason_pct is None


def test_no_reason_when_the_latest_entry_lacks_usage():
    ch = assess(series((60, 300), (60, 300), (60, 300), 84), monthly=True)
    assert ch is not None and ch.reason is None


def test_usage_on_one_side_only_has_no_reason_and_no_error():
    assert assess(series(60, 60, 60, (84, 300)), monthly=True).reason is None
    assert assess(series((60, 300), (60, 300), (60, 300), 84), monthly=True).reason is None


def test_usage_of_zero_never_divides():
    # Latest usage 0.
    ch = assess(series((60, 300), (60, 300), (60, 300), (84, 0)), monthly=True)
    assert ch is not None and ch.reason is None
    # A baseline entry with usage 0.
    ch = assess(series((60, 0), (60, 300), (60, 300), (84, 300)), monthly=True)
    assert ch is not None and ch.reason is None
    # Last-year baseline usage 0.
    points = [pt(date(2025, 9, 14), 60, 0), pt(date(2026, 9, 14), 84, 300)]
    ch = assess(points, monthly=True)
    assert ch is not None and ch.basis == "last_year" and ch.reason is None


# --------------------------------------------------------- items and points


def _item(db, hh, **over):
    fields = dict(
        household_id=hh.household_id,
        name="Electricity",
        amount=None,
        currency="EUR",
        start_date=date(2025, 1, 1),
        interval_months=1,
        is_active=True,
    )
    fields.update(over)
    item = RecurringBill(**fields)
    db.add(item)
    db.flush()
    return item


def _done(db, item, due, amount=None, *, usage=None, txn=None, status=OccurrenceStatus.paid):
    occ = BillOccurrence(
        bill_id=item.id,
        due_date=due,
        amount=amount,
        usage=usage,
        status=status,
        transaction_id=txn.id if txn else None,
    )
    db.add(occ)
    db.flush()
    return occ


def _txn(db, hh, amount, *, rate=None, **over):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=D(str(amount)),
        currency="EUR",
        exchange_rate=rate,
        type=TransactionType.expense,
        transaction_date=date(2026, 1, 1),
        paid_by=hh.user_id,
        **over,
    )
    db.add(t)
    db.flush()
    return t


def test_entry_points_are_done_entries_oldest_first(db, make_household):
    hh = make_household()
    item = _item(db, hh)
    _done(db, item, date(2026, 3, 14), 30)
    _done(db, item, date(2026, 1, 14), 10, usage=100)
    _done(db, item, date(2026, 2, 14), 20, status=OccurrenceStatus.unpaid)
    _done(db, item, date(2026, 4, 14), 40, status=OccurrenceStatus.skipped)
    db.commit()
    pts = entry_points(db, item)
    assert [p.due_date for p in pts] == [date(2026, 1, 14), date(2026, 3, 14)]
    assert pts[0].amount == D("10") and pts[0].usage == D("100") and pts[1].usage is None


def test_amount_falls_back_to_the_transaction_then_the_item(db, make_household):
    hh = make_household()
    item = _item(db, hh, amount=D("45"))
    t = _txn(db, hh, 80)
    t2 = _txn(db, hh, 10, rate=D("2"))  # base amount 20
    _done(db, item, date(2026, 1, 14), 99, txn=t)  # the entry amount wins
    _done(db, item, date(2026, 2, 14), None, txn=t)  # the transaction
    _done(db, item, date(2026, 3, 14), None, txn=t2)  # converted to base
    _done(db, item, date(2026, 4, 14), None)  # the item
    db.commit()
    pts = entry_points(db, item)
    assert [p.amount for p in pts] == [D("99"), D("80"), D("20"), D("45")]
    assert pts[1].transaction_id == t.id and pts[3].transaction_id is None


def test_an_entry_with_no_amount_anywhere_is_left_out(db, make_household):
    hh = make_household()
    item = _item(db, hh, amount=None)
    _done(db, item, date(2026, 1, 14), None)
    _done(db, item, date(2026, 2, 14), 12)
    db.commit()
    assert [p.amount for p in entry_points(db, item)] == [D("12")]


def test_a_deleted_transaction_is_not_the_amount(db, make_household):
    hh = make_household()
    item = _item(db, hh, amount=D("45"))
    t = _txn(db, hh, 80, deleted_at=utcnow_naive())
    _done(db, item, date(2026, 1, 14), None, txn=t)
    db.commit()
    assert [p.amount for p in entry_points(db, item)] == [D("45")]


def test_own_share_uses_the_whole_payment_not_one_members_share(db, make_household):
    hh = make_household()
    item = _item(db, hh, amount=None, payer_mode=PayerMode.own_share.value)
    t = _txn(db, hh, 90, payer_mode=PayerMode.own_share.value)
    from app.models import TransactionSplit

    db.add(TransactionSplit(transaction_id=t.id, user_id=hh.user_id, amount=D("30")))
    _done(db, item, date(2026, 1, 14), None, txn=t)
    db.commit()
    [p] = entry_points(db, item)
    assert p.amount == D("90")


def test_entry_points_does_not_return_another_items_entries(db, make_household):
    hh = make_household()
    a, b = _item(db, hh), _item(db, hh, name="Water")
    _done(db, a, date(2026, 1, 14), 10)
    _done(db, b, date(2026, 1, 14), 99)
    db.commit()
    assert [p.amount for p in entry_points(db, a)] == [D("10")]


def test_entry_points_runs_two_queries(db, make_household):
    from sqlalchemy import event

    hh = make_household()
    item = _item(db, hh, amount=D("5"))
    t = _txn(db, hh, 8)
    for m in range(1, 7):
        _done(db, item, date(2026, m, 14), None, txn=t if m % 2 else None)
    db.commit()
    db.refresh(item)  # loaded now, so only the two reads are counted
    statements = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        entry_points(db, item)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    assert len(statements) == 2, statements


def test_is_monthly(db, make_household):
    hh = make_household()
    assert is_monthly(_item(db, hh, rule_kind="monthly_day", rule_day=3))
    assert is_monthly(_item(db, hh, rule_kind="yearly", rule_day=3, rule_month=2))
    assert not is_monthly(_item(db, hh, rule_kind="weekly", rule_weekday=1))


def test_assess_item_skips_income_and_assesses_paused(db, make_household):
    hh = make_household()
    pts = series(50, 50, 50, 90)
    income = _item(db, hh, name="Salary", direction="in")
    assert assess_item(income, pts) is None
    paused = _item(db, hh, name="Old", is_active=False)
    assert assess_item(paused, pts) is not None
    weekly = _item(db, hh, name="Weekly", rule_kind="weekly", rule_weekday=1)
    assert assess_item(weekly, pts).basis == "recent"


def test_a_reason_tie_goes_to_usage():
    # usage +20 % and price +20 % exactly.
    ch = assess(series((60, 300), (60, 300), (60, 300), (86.4, 360)), monthly=True)
    assert ch.reason == "usage" and ch.reason_pct == 20


def test_two_entries_in_last_years_month_use_the_later_one():
    points = [
        pt(date(2025, 9, 5), 100),
        pt(date(2025, 9, 20), 60),
        pt(date(2026, 9, 14), 84),
    ]
    ch = assess(points, monthly=True)
    assert ch.basis == "last_year" and ch.usual == D("60.00")


def test_last_year_matches_on_the_period_when_a_business_day_shift_crossed_a_month():
    # November 2025's entry was moved back to 31 Oct; November 2026's is due 2 Nov.
    points = [
        pt(date(2025, 10, 31), 60, period="2025-11"),
        pt(date(2026, 7, 14), 200),
        pt(date(2026, 8, 14), 200),
        pt(date(2026, 9, 14), 200),
        pt(date(2026, 11, 2), 84, period="2026-11"),
    ]
    ch = assess(points, monthly=True)
    assert ch.basis == "last_year" and ch.usual == D("60.00")
    # Without period keys the due-date months decide: no match, so the last 3.
    bare = [Point(p.entry_id, p.due_date, p.amount, p.usage, None) for p in points]
    assert assess(bare, monthly=True).basis == "recent"


def test_latest_is_deterministic_for_equal_due_dates():
    d = date(2026, 9, 1)
    base = series(50, 50, 50, 50, start=date(2026, 1, 14))
    # The later-paid point is created first, so its id sorts lower: only paid_at puts it last.
    late = pt(d, 50, paid_at=datetime(2026, 9, 1, 9))  # noqa: DTZ001
    early = pt(d, 90, paid_at=datetime(2026, 9, 1, 8))  # noqa: DTZ001
    for order in ([early, late], [late, early]):
        assert assess(base + order, monthly=True) is None  # the later payment (50) is latest
    # Same paid_at: the id decides, whatever the input order.
    a, b = pt(d, 90), pt(d, 50)
    first = assess(base + [a, b], monthly=True)
    second = assess(base + [b, a], monthly=True)
    assert (first is None) == (second is None)


def test_a_deleted_transaction_is_not_linked(db, make_household):
    hh = make_household()
    item = _item(db, hh, amount=D("45"))
    gone = _txn(db, hh, 80, deleted_at=utcnow_naive())
    live = _txn(db, hh, 70)
    _done(db, item, date(2026, 1, 14), 5, txn=gone)  # has its own amount
    _done(db, item, date(2026, 2, 14), None, txn=live)
    db.commit()
    pts = entry_points(db, item)
    assert pts[0].amount == D("5") and pts[0].transaction_id is None
    assert pts[1].transaction_id == live.id
