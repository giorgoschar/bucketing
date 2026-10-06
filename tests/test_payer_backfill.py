"""
Repairing expenses saved without a payer ("Unassigned").

Bill payments made before bills recorded a payer have ``paid_by`` NULL. Two
tools fix them: a bill-level backfill ("Also apply to past payments with no
payer") and bulk "Set payer" on /transactions/search?missing_payer=1.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.clock import local_today
from app.models import (
    BillOccurrence,
    OccurrenceStatus,
    PayerMode,
    RecurringBillSplit,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.schemas import OWN_SHARE_CHOICE
from app.services.bills import backfill_bill_payer
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member


@pytest.fixture()
def duo(db, authed):
    partner = _add_member(db, authed.household_id, "flatmate")
    db.commit()
    authed.partner_id = partner.id
    return authed


def _expense(
    db,
    ctx,
    amount,
    *,
    paid_by=None,
    splits=(),
    notes=None,
    days_ago=0,
    household_id=None,
    bucket_id=None,
    type=TransactionType.expense,
):
    t = Transaction(
        bucket_id=bucket_id or ctx.bucket_id,
        household_id=household_id or ctx.household_id,
        amount=amount,
        currency="EUR",
        type=type,
        paid_by=paid_by,
        notes=notes,
        transaction_date=local_today() - timedelta(days=days_ago),
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


def _paid_occurrence(db, bill, txn, months_ago):
    occ = BillOccurrence(
        bill_id=bill.id,
        due_date=local_today() - timedelta(days=31 * months_ago),
        status=OccurrenceStatus.paid,
        transaction_id=txn.id,
    )
    db.add(occ)
    db.commit()
    return occ


# ---------------------------------------------------------------------------
# backfill_bill_payer
# ---------------------------------------------------------------------------


def test_backfill_single_sets_the_default_payer_on_this_bill_only(db, duo, make_bill):
    spotify, _ = make_bill(
        duo.household_id,
        duo.bucket_id,
        amount=10,
        occurrence=False,
        name="Spotify",
        paid_by=duo.user_id,
    )
    other, _ = make_bill(duo.household_id, duo.bucket_id, amount=50, occurrence=False, name="Gym")
    old1 = _expense(db, duo, 10)
    old2 = _expense(db, duo, 10)
    already = _expense(db, duo, 10, paid_by=duo.partner_id)
    gone = _expense(db, duo, 10)
    gone.deleted_at = gone.created_at
    gym = _expense(db, duo, 50)
    loose = _expense(db, duo, 10)  # no payer, but not a payment of this bill
    occs = [
        _paid_occurrence(db, spotify, t, i + 1) for i, t in enumerate([old1, old2, already, gone])
    ]
    _paid_occurrence(db, other, gym, 1)

    assert backfill_bill_payer(db, spotify).updated == 2
    db.commit()
    db.expire_all()
    assert db.get(Transaction, old1.id).paid_by == duo.user_id
    assert db.get(Transaction, old2.id).paid_by == duo.user_id
    assert db.get(Transaction, already.id).paid_by == duo.partner_id
    assert db.get(Transaction, gone.id).paid_by is None
    assert db.get(Transaction, gym.id).paid_by is None
    assert db.get(Transaction, loose.id).paid_by is None
    assert db.get(BillOccurrence, occs[0].id).paid_by == duo.user_id


def test_backfill_single_without_default_payer_does_nothing(db, duo, make_bill):
    bill, _ = make_bill(duo.household_id, duo.bucket_id, occurrence=False, paid_by=None)
    t = _expense(db, duo, 45)
    _paid_occurrence(db, bill, t, 1)
    assert backfill_bill_payer(db, bill).updated == 0
    assert db.get(Transaction, t.id).paid_by is None


def test_backfill_own_share_keeps_matching_splits_and_fills_missing_ones(db, duo, make_bill):
    rent, _ = make_bill(duo.household_id, duo.bucket_id, amount=1100, occurrence=False, name="Rent")
    rent.payer_mode = PayerMode.own_share.value
    db.add(RecurringBillSplit(bill_id=rent.id, user_id=duo.user_id, amount=800))
    db.add(RecurringBillSplit(bill_id=rent.id, user_id=duo.partner_id, amount=300))
    db.commit()
    kept = _expense(db, duo, 1100, splits=[(duo.user_id, 700), (duo.partner_id, 400)])
    bare = _expense(db, duo, 1100)
    partial = _expense(db, duo, 1100, splits=[(duo.partner_id, 550)])
    for i, t in enumerate([kept, bare, partial]):
        _paid_occurrence(db, rent, t, i + 1)

    result = backfill_bill_payer(db, rent)
    # Only "partial" had splits of its own that were replaced.
    assert (result.updated, result.resplit) == (3, 1)
    db.commit()
    db.expire_all()

    def splits(t):
        return {s.user_id: Decimal(str(s.amount)) for s in db.get(Transaction, t.id).splits}

    for t in (kept, bare, partial):
        assert db.get(Transaction, t.id).payer_mode == "own_share"
        assert db.get(Transaction, t.id).paid_by is None
    assert splits(kept) == {duo.user_id: Decimal("700"), duo.partner_id: Decimal("400")}
    assert splits(bare) == {duo.user_id: Decimal("800"), duo.partner_id: Decimal("300")}
    assert splits(partial) == {duo.user_id: Decimal("800"), duo.partner_id: Decimal("300")}


def test_backfill_own_share_without_bill_splits_does_nothing(db, duo, make_bill):
    rent, _ = make_bill(duo.household_id, duo.bucket_id, amount=1100, occurrence=False)
    rent.payer_mode = PayerMode.own_share.value
    db.commit()
    t = _expense(db, duo, 1100)
    _paid_occurrence(db, rent, t, 1)
    assert backfill_bill_payer(db, rent).updated == 0
    assert db.get(Transaction, t.id).payer_mode == "single"


def test_backfilled_rent_clears_unassigned_in_insights(db, duo, make_bill):
    from app.services import get_insights_summary

    rent, _ = make_bill(duo.household_id, duo.bucket_id, amount=1100, occurrence=False)
    rent.payer_mode = PayerMode.own_share.value
    db.add(RecurringBillSplit(bill_id=rent.id, user_id=duo.user_id, amount=800))
    db.add(RecurringBillSplit(bill_id=rent.id, user_id=duo.partner_id, amount=300))
    db.commit()
    _paid_occurrence(db, rent, _expense(db, duo, 1100), 1)
    assert "unassigned" in get_insights_summary(db, duo.household_id, None, None)["paid_by"]

    backfill_bill_payer(db, rent)
    db.commit()
    s = get_insights_summary(db, duo.household_id, None, None)
    assert "unassigned" not in s["paid_by"]
    assert s["paid_by"][duo.user_id]["paid"] == Decimal("800")
    assert s["paid_by"][duo.partner_id]["paid"] == Decimal("300")


def _bill_form(bill, **extra):
    return {
        "name": bill.name,
        "amount": str(bill.amount),
        "start_date": bill.start_date.isoformat(),
        "frequency": "monthly",
        "interval_months": "1",
        **extra,
    }


def test_html_bill_edit_applies_to_past_and_reports_the_count(client, db, duo, make_bill):
    bill, _ = make_bill(
        duo.household_id, duo.bucket_id, amount=10, occurrence=False, name="Spotify", auto_pay=False
    )
    t = _expense(db, duo, 10)
    _paid_occurrence(db, bill, t, 1)

    r = client.post(
        f"/bills/{bill.id}/edit",
        headers=duo.headers,
        data=_bill_form(bill, paid_by_default=duo.user_id, apply_to_past="on"),
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/bills?backfilled=1"
    db.expire_all()
    assert db.get(Transaction, t.id).paid_by == duo.user_id
    assert "Updated 1 past payment that had no payer" in client.get(r.headers["location"]).text


def test_html_bill_edit_without_the_box_leaves_the_past_alone(client, db, duo, make_bill):
    bill, _ = make_bill(
        duo.household_id, duo.bucket_id, amount=10, occurrence=False, auto_pay=False
    )
    t = _expense(db, duo, 10)
    _paid_occurrence(db, bill, t, 1)
    r = client.post(
        f"/bills/{bill.id}/edit",
        headers=duo.headers,
        data=_bill_form(bill, paid_by_default=duo.user_id),
    )
    assert r.headers["location"] == "/bills"
    db.expire_all()
    assert db.get(Transaction, t.id).paid_by is None


def test_html_bill_edit_to_own_share_backfills_with_new_splits(client, db, duo, make_bill):
    bill, _ = make_bill(
        duo.household_id, duo.bucket_id, amount=1100, occurrence=False, name="Rent", auto_pay=False
    )
    t = _expense(db, duo, 1100)
    _paid_occurrence(db, bill, t, 1)
    r = client.post(
        f"/bills/{bill.id}/edit",
        headers=duo.headers,
        data=_bill_form(
            bill,
            paid_by_default=OWN_SHARE_CHOICE,
            apply_to_past="on",
            **{f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300"},
        ),
    )
    assert r.headers["location"] == "/bills?backfilled=1", r.text
    db.expire_all()
    txn = db.get(Transaction, t.id)
    assert txn.payer_mode == "own_share"
    assert sorted(float(s.amount) for s in txn.splits) == [300.0, 800.0]


def test_bill_edit_page_has_the_apply_to_past_box(client, db, duo, make_bill):
    bill, _ = make_bill(duo.household_id, duo.bucket_id, occurrence=False)
    page = client.get(f"/bills/{bill.id}/edit").text
    assert 'name="apply_to_past"' in page
    assert "Also apply to past payments with no payer" in page


def test_api_bill_update_applies_to_past(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    bill, _ = make_bill(hh.household_id, hh.bucket_id, amount=10, occurrence=False, auto_pay=False)
    t = _expense(db, hh, 10)
    _paid_occurrence(db, bill, t, 1)
    r = client.put(
        f"/api/v1/bills/{bill.id}",
        headers=headers,
        json={
            "name": bill.name,
            "amount": "10",
            "start_date": bill.start_date.isoformat(),
            "bucket_id": hh.bucket_id,
            "paid_by_default": hh.user_id,
            "apply_to_past": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["backfilled"] == 1
    db.expire_all()
    assert db.get(Transaction, t.id).paid_by == hh.user_id


# ---------------------------------------------------------------------------
# Bulk "Set payer" on search
# ---------------------------------------------------------------------------


def test_bulk_payer_assigns_a_member(client, db, duo):
    a = _expense(db, duo, 10, notes="a")
    b = _expense(db, duo, 20, notes="b")
    untouched = _expense(db, duo, 30, notes="c")
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [a.id, b.id],
            "payer": duo.partner_id,
            "return_query": "missing_payer=1&page=2",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"] == (
        "/transactions/search?missing_payer=1&page=2&updated=2&skipped=0"
    )
    db.expire_all()
    assert db.get(Transaction, a.id).paid_by == duo.partner_id
    assert db.get(Transaction, b.id).paid_by == duo.partner_id
    assert db.get(Transaction, untouched.id).paid_by is None


def test_bulk_own_share_skips_rows_without_matching_splits(client, db, duo):
    good = _expense(db, duo, 1100, splits=[(duo.user_id, 800), (duo.partner_id, 300)])
    bare = _expense(db, duo, 1100)
    short = _expense(db, duo, 1100, splits=[(duo.user_id, 800)])
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [good.id, bare.id, short.id],
            "payer": OWN_SHARE_CHOICE,
            "return_query": "missing_payer=1",
        },
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("updated=1&skipped=2")
    db.expire_all()
    assert db.get(Transaction, good.id).payer_mode == "own_share"
    assert db.get(Transaction, bare.id).payer_mode == "single"
    assert db.get(Transaction, short.id).payer_mode == "single"

    page = client.get(r.headers["location"]).text
    assert "1 updated, 2 skipped: no split defined" in page


def test_bulk_payer_rejects_ids_from_another_household(client, db, duo, make_household):
    other = make_household(name="Other")
    theirs = _expense(db, other, 10, household_id=other.household_id, bucket_id=other.bucket_id)
    mine = _expense(db, duo, 10)
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [mine.id, theirs.id],
            "payer": duo.user_id,
        },
    )
    assert r.status_code == 404
    db.expire_all()
    assert db.get(Transaction, theirs.id).paid_by is None
    assert db.get(Transaction, mine.id).paid_by is None


def test_bulk_payer_rejects_a_payer_from_another_household(client, db, duo, make_household):
    other = make_household(name="Other")
    mine = _expense(db, duo, 10)
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [mine.id],
            "payer": other.user_id,
        },
    )
    assert r.status_code in (400, 403, 404)
    assert db.get(Transaction, mine.id).paid_by is None


def test_bulk_payer_only_touches_expenses(client, db, duo):
    income = _expense(db, duo, 10, type=TransactionType.income)
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [income.id],
            "payer": duo.user_id,
        },
    )
    assert r.status_code == 404
    assert db.get(Transaction, income.id).paid_by is None


def test_bulk_payer_needs_csrf(client, db, duo):
    t = _expense(db, duo, 10)
    r = client.post("/transactions/bulk-payer", data={"ids": [t.id], "payer": duo.user_id})
    assert r.status_code == 403
    assert db.get(Transaction, t.id).paid_by is None


def test_bulk_payer_drops_unknown_return_query_keys(client, db, duo):
    t = _expense(db, duo, 10)
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [t.id],
            "payer": duo.user_id,
            "return_query": "missing_payer=1&next=https://evil.example",
        },
    )
    assert r.headers["location"] == "/transactions/search?missing_payer=1&updated=1&skipped=0"


def test_search_has_no_payer_filter_and_row_checkboxes(client, db, duo):
    for i in range(30):
        _expense(db, duo, 10 + i, notes=f"orphan {i}")
    page = client.get("/transactions/search?missing_payer=1").text
    assert 'name="missing_payer"' in page
    assert 'name="missing_payer" value="1" checked' in page
    assert 'name="ids"' in page
    assert 'action="/transactions/bulk-payer"' in page
    assert "Each paid their own share" in page
    # Pagination keeps the filter.
    assert "missing_payer=1&amp;page=2" in page or "missing_payer=1&page=2" in page


# ---------------------------------------------------------------------------
# "Unassigned" links to the fix-up view
# ---------------------------------------------------------------------------


def test_unassigned_rows_link_to_the_missing_payer_search(client, db, duo):
    _expense(db, duo, 20)
    link = "/transactions/search?missing_payer=1"
    assert link in client.get("/dashboard").text
    assert link in client.get(f"/buckets/{duo.bucket_id}").text
    assert link in client.get("/insights").text


# ---------------------------------------------------------------------------
# Replaced splits are reported; a cent of rounding is absorbed
# ---------------------------------------------------------------------------


def _rent_bill(db, duo, make_bill):
    rent, _ = make_bill(
        duo.household_id, duo.bucket_id, amount=1100, occurrence=False, name="Rent", auto_pay=False
    )
    rent.payer_mode = PayerMode.own_share.value
    db.add(RecurringBillSplit(bill_id=rent.id, user_id=duo.user_id, amount=800))
    db.add(RecurringBillSplit(bill_id=rent.id, user_id=duo.partner_id, amount=300))
    db.commit()
    return rent


def test_backfill_keeps_splits_a_cent_short_and_absorbs_the_cent(db, duo, make_bill):
    rent = _rent_bill(db, duo, make_bill)
    t = _expense(db, duo, 1100, splits=[(duo.user_id, 700), (duo.partner_id, Decimal("399.99"))])
    _paid_occurrence(db, rent, t, 1)
    result = backfill_bill_payer(db, rent)
    db.commit()
    db.expire_all()
    assert (result.updated, result.resplit) == (1, 0)
    assert {s.user_id: Decimal(str(s.amount)) for s in db.get(Transaction, t.id).splits} == {
        duo.user_id: Decimal("700.01"),
        duo.partner_id: Decimal("399.99"),
    }


def test_html_backfill_reports_replaced_splits(client, db, duo, make_bill):
    rent = _rent_bill(db, duo, make_bill)
    t = _expense(db, duo, 1100, splits=[(duo.partner_id, 300)])  # "you owe me 300"
    _paid_occurrence(db, rent, t, 1)
    r = client.post(
        f"/bills/{rent.id}/edit",
        headers=duo.headers,
        data=_bill_form(
            rent,
            paid_by_default=OWN_SHARE_CHOICE,
            apply_to_past="on",
            **{f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300"},
        ),
    )
    assert r.headers["location"] == "/bills?backfilled=1&resplit=1", r.text
    page = client.get(r.headers["location"]).text
    assert "Updated 1 past payment that had no payer" in page
    assert "1 of them had splits that did not add up to its amount" in page


def test_api_backfill_reports_replaced_splits(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "flatmate")
    db.commit()
    hh.partner_id = partner.id
    rent = _rent_bill(db, hh, make_bill)
    _paid_occurrence(db, rent, _expense(db, hh, 1100, splits=[(partner.id, 300)]), 1)
    r = client.put(
        f"/api/v1/bills/{rent.id}",
        headers=headers,
        json={
            "name": rent.name,
            "amount": "1100",
            "start_date": rent.start_date.isoformat(),
            "bucket_id": hh.bucket_id,
            "payer_mode": "own_share",
            "apply_to_past": True,
            "splits": [
                {"user_id": hh.user_id, "amount": "800"},
                {"user_id": partner.id, "amount": "300"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert (r.json()["backfilled"], r.json()["resplit"]) == (1, 1)


def test_bulk_own_share_absorbs_a_cent_of_rounding(client, db, duo):
    t = _expense(db, duo, 1100, splits=[(duo.user_id, 800), (duo.partner_id, Decimal("299.99"))])
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [t.id],
            "payer": OWN_SHARE_CHOICE,
        },
    )
    assert r.headers["location"].endswith("updated=1&skipped=0")
    db.expire_all()
    assert sum(Decimal(str(s.amount)) for s in db.get(Transaction, t.id).splits) == Decimal("1100")


# ---------------------------------------------------------------------------
# Bulk "Set payer" says why a row was skipped
# ---------------------------------------------------------------------------


def _cash_expense(db, ctx, *, paid_by, splits=()):
    t = _expense(db, ctx, 20, paid_by=paid_by, splits=splits)
    t.payment_method = "cash"
    db.commit()
    return t


def test_bulk_payer_moves_anyones_cash_expense(client, db, duo):
    """There are no private pockets: a cash expense is reassigned like any other."""
    theirs = _cash_expense(db, duo, paid_by=duo.partner_id)
    plain = _expense(db, duo, 10)
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [theirs.id, plain.id],
            "payer": duo.user_id,
        },
    )
    assert r.headers["location"].endswith("updated=2&skipped=0")
    page = client.get(r.headers["location"]).text
    assert "2 updated" in page and "skipped:" not in page


def test_bulk_own_share_reports_take_skips(client, db, duo):
    from app.models import CashMovement

    halves = [(duo.user_id, 10), (duo.partner_id, 10)]
    taken = _cash_expense(db, duo, paid_by=duo.user_id, splits=halves)
    db.add(
        CashMovement(
            household_id=duo.household_id,
            user_id=duo.user_id,
            kind="take",
            amount=20,
            currency="EUR",
            movement_date=taken.transaction_date,
            transaction_id=taken.id,
        )
    )
    bare = _expense(db, duo, 30)
    db.commit()
    r = client.post(
        "/transactions/bulk-payer",
        headers=duo.headers,
        data={
            "ids": [taken.id, bare.id],
            "payer": OWN_SHARE_CHOICE,
        },
    )
    assert r.headers["location"].endswith("updated=0&skipped=1&skipped_take=1")
    page = client.get(r.headers["location"]).text
    assert (
        "0 updated, 1 skipped: no split defined, 1 skipped: cash was taken for it, "
        "so it stays paid by whoever took it"
    ) in page
