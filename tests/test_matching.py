"""Match suggestions (spec §3.5): window edges, tolerance, Greek names,
dismissal, every source, and never a link without a tap."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import (
    BillOccurrence,
    MatchSuggestion,
    OccurrenceStatus,
    Transaction,
    TransactionType,
)
from app.services import delete_transaction
from app.services.bills import EntryStateError
from app.services.matching import (
    dismiss_suggestion,
    find_match,
    link_suggestion,
    names_similar,
    open_suggestions,
    suggest_for_transaction,
    suggest_recent,
)
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_ingest import ingest  # noqa: F401  (fixture)

DUE = date(2026, 10, 10)


def _txn(db, hh, amount, when, *, kind=TransactionType.expense, merchant=None, bucket=True):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id if bucket else None,
        amount=Decimal(str(amount)),
        currency="EUR",
        type=kind,
        paid_by=hh.user_id,
        transaction_date=when,
        merchant=merchant,
    )
    db.add(t)
    db.commit()
    return t


def _bill(make_bill, hh, amount=38.90, name="Cosmote", due=DUE, **kw):
    return make_bill(
        hh.household_id, hh.bucket_id, amount=amount, auto_pay=False, due=due, name=name, **kw
    )


@pytest.mark.parametrize(
    "offset,matches", [(-4, False), (-3, True), (0, True), (7, True), (8, False)]
)
def test_window_is_three_days_early_to_seven_days_late(
    db, make_household, make_bill, offset, matches
):
    hh = make_household()
    _, occ = _bill(make_bill, hh)
    t = _txn(db, hh, "38.90", DUE + timedelta(days=offset))
    assert (find_match(db, t) == occ) is matches


@pytest.mark.parametrize("amount,matches", [("44.73", True), ("33.07", True), ("44.80", False)])
def test_fixed_amount_within_15_percent(db, make_household, make_bill, amount, matches):
    hh = make_household()
    _bill(make_bill, hh, name="Phone")
    t = _txn(db, hh, amount, DUE)
    assert (find_match(db, t) is not None) is matches


def test_variable_amount_within_50_percent_of_the_estimate(db, make_household, make_bill):
    hh = make_household()
    bill, _ = _bill(make_bill, hh, amount=None, name="Power")
    for months, amount in ((3, 60), (2, 70), (1, 80)):
        db.add(
            BillOccurrence(
                bill_id=bill.id,
                due_date=DUE - timedelta(days=30 * months),
                amount=Decimal(amount),
                status=OccurrenceStatus.paid,
            )
        )
    db.commit()
    assert find_match(db, _txn(db, hh, "104", DUE)) is not None
    assert find_match(db, _txn(db, hh, "106", DUE)) is None


def test_greek_names_match_without_accents_or_case():
    t = Transaction(merchant="ΔΕΉ ONLINE ΠΛΗΡΩΜΉ", notes=None)
    assert names_similar("Δεη", t)
    assert names_similar("ΔΕΗ πληρωμη", Transaction(merchant="δεη", notes=None))
    assert not names_similar("Ύδρευση", t)


def test_a_similar_name_matches_whatever_the_amount(db, make_household, make_bill):
    hh = make_household()
    _, occ = _bill(make_bill, hh, name="Cosmote")
    t = _txn(db, hh, "120", DUE, merchant="COSMOTE E-SHOP")
    assert find_match(db, t) == occ


def test_income_matches_in_entries_only(db, make_household, make_bill):
    hh = make_household()
    _bill(make_bill, hh, amount=1500, name="Rent paid")
    salary, s_occ = make_bill(
        hh.household_id, None, amount=1500, auto_pay=False, due=DUE, name="Pay"
    )
    salary.direction = "in"
    db.commit()
    t = _txn(db, hh, "1500", DUE, kind=TransactionType.income, bucket=False)
    assert find_match(db, t) == s_occ


def test_paused_items_and_done_entries_are_never_suggested(db, make_household, make_bill):
    hh = make_household()
    bill, occ = _bill(make_bill, hh)
    bill.is_active = False
    db.commit()
    assert find_match(db, _txn(db, hh, "38.90", DUE)) is None
    bill.is_active = True
    occ.status = OccurrenceStatus.paid
    db.commit()
    assert find_match(db, _txn(db, hh, "38.90", DUE)) is None


def test_dismissal_persists_through_the_daily_pass(db, make_household, make_bill):
    hh = make_household()
    _bill(make_bill, hh)
    t = _txn(db, hh, "38.90", DUE)
    s = suggest_for_transaction(db, t)
    dismiss_suggestion(s)
    db.commit()
    assert suggest_recent(db, DUE) == 0
    assert open_suggestions(db, hh.household_id) == []
    assert db.query(MatchSuggestion).count() == 1


def test_link_marks_done_and_links_the_transaction(db, make_household, make_bill):
    hh = make_household()
    bill, occ = _bill(make_bill, hh)
    t = _txn(db, hh, "38.90", DUE)
    s = suggest_for_transaction(db, t)
    link_suggestion(db, s)
    db.commit()
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.paid
    assert db.get(BillOccurrence, occ.id).transaction_id == t.id
    assert db.get(Transaction, t.id).recurring_bill_id == bill.id
    assert open_suggestions(db, hh.household_id) == []


def test_stale_suggestions_refuse_to_link_and_drop_out(db, make_household, make_bill):
    hh = make_household()
    _, occ = _bill(make_bill, hh)
    first = suggest_for_transaction(db, _txn(db, hh, "38.90", DUE))
    second = suggest_for_transaction(db, _txn(db, hh, "38.90", DUE + timedelta(days=1)))
    db.commit()
    link_suggestion(db, first)
    db.commit()
    with pytest.raises(EntryStateError):
        link_suggestion(db, second)
    db.rollback()
    assert open_suggestions(db, hh.household_id) == []

    _, occ2 = _bill(make_bill, hh, name="Water", amount=20, due=DUE + timedelta(days=20))
    t = _txn(db, hh, "20", DUE + timedelta(days=20))
    s = suggest_for_transaction(db, t)
    db.commit()
    delete_transaction(db, t)
    with pytest.raises(EntryStateError):
        link_suggestion(db, s)


def test_api_create_suggests_but_never_links(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    today = local_today()
    _, occ = make_bill(hh.household_id, hh.bucket_id, amount=38.90, auto_pay=False, due=today)
    body = {"amount": "38.90", "bucket_id": hh.bucket_id, "client_id": "offline-1"}
    assert client.post("/api/v1/transactions", headers=headers, json=body).status_code == 201
    assert client.post("/api/v1/transactions", headers=headers, json=body).status_code == 200
    assert db.query(MatchSuggestion).count() == 1
    db.expire_all()
    assert db.get(BillOccurrence, occ.id).status == OccurrenceStatus.unpaid
    assert db.query(Transaction).one().recurring_bill_id is None


def test_apple_pay_ingest_suggests(client, db, ingest, make_bill):  # noqa: F811
    hh = ingest.hh
    make_bill(hh.household_id, hh.bucket_id, amount=12.50, auto_pay=False, due=local_today())
    r = client.post(
        "/api/v1/ingest/apple-pay",
        json={"merchant": "Sklavenitis", "amount": "12,50"},
        headers=ingest.headers,
    )
    assert r.status_code == 201, r.text
    assert db.query(MatchSuggestion).count() == 1


def test_daily_job_suggests_for_the_last_14_days(
    db, make_household, make_bill, monkeypatch, SessionLocal
):
    import app.core.database as database
    import app.scheduler as scheduler

    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    hh = make_household()
    today = local_today()
    make_bill(
        hh.household_id, hh.bucket_id, amount=30, auto_pay=False, due=today - timedelta(days=2)
    )
    _txn(db, hh, "30", today - timedelta(days=1))
    scheduler.planning_daily_job()
    assert db.query(MatchSuggestion).count() == 1
