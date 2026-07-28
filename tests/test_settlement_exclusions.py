"""
Expenses that settle-up must leave alone.

Two of them, and the first was a live bug: an expense saved without a payer had
its shares charged to members while the money was credited to nobody. The nets
stopped summing to zero and both members showed as owing — apparently to a
third person who does not exist. Reported as "shared expenses look like we owe
someone else".
"""
from datetime import date

import pytest

from app.models import (
    Bucket, Transaction, TransactionSplit, TransactionType,
)
from app.services import (
    compute_bucket_net, get_bucket_settlement, get_household_settlement,
    get_member_balances, get_settlement_exclusions,
)
from tests.test_settlement_balance import pair, _expense  # noqa: F401


def _shared(db, ctx, amount, payer, *, excluded=False, when=None):
    t = Transaction(
        bucket_id=ctx.bucket_id, household_id=ctx.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=when or date.today(),
        paid_by=payer, exclude_from_settlement=excluded,
    )
    db.add(t)
    db.flush()
    half = amount / 2
    db.add(TransactionSplit(transaction_id=t.id, user_id=ctx.user_id, amount=half))
    db.add(TransactionSplit(transaction_id=t.id, user_id=ctx.partner_id, amount=half))
    db.commit()
    return t


# ---------------------------------------------------------------------------
# No payer recorded
# ---------------------------------------------------------------------------

def test_expense_with_no_payer_creates_no_debt(db, pair):
    """The reported bug: 100 shared 50/50 with nobody marked as having paid."""
    _shared(db, pair, 100, None)

    net = compute_bucket_net(db, pair.bucket_id)
    assert round(sum(net.values()), 2) == 0.0, "nets must sum to zero"
    assert get_bucket_settlement(db, pair.bucket_id) == []
    assert all(b["net"] == 0.0 for b in get_member_balances(db, pair.household_id))


def test_a_payer_still_produces_the_debt(db, pair):
    """The fix must not silence real debts."""
    _shared(db, pair, 100, pair.user_id)

    rows = get_bucket_settlement(db, pair.bucket_id)
    assert len(rows) == 1
    assert rows[0]["from_id"] == pair.partner_id
    assert rows[0]["to_id"] == pair.user_id
    assert rows[0]["amount"] == 50.0


def test_an_unpayable_expense_does_not_skew_a_real_one(db, pair):
    """Mixing the two: only the attributed expense moves the balance."""
    _shared(db, pair, 100, pair.user_id)
    _shared(db, pair, 400, None)

    net = compute_bucket_net(db, pair.bucket_id)
    assert round(sum(net.values()), 2) == 0.0
    assert net[pair.user_id] == 50.0
    assert net[pair.partner_id] == -50.0


def test_unsplit_expense_with_no_payer_is_ignored(db, pair):
    _expense(db, pair, 80, None)
    assert compute_bucket_net(db, pair.bucket_id) == {}


# ---------------------------------------------------------------------------
# Explicitly excluded
# ---------------------------------------------------------------------------

def test_excluded_expense_creates_no_debt(db, pair):
    _shared(db, pair, 100, pair.user_id, excluded=True)
    assert get_bucket_settlement(db, pair.bucket_id) == []


def test_excluding_one_leaves_the_rest_intact(db, pair):
    _shared(db, pair, 100, pair.user_id)
    _shared(db, pair, 900, pair.user_id, excluded=True)

    rows = get_household_settlement(db, pair.household_id)
    assert len(rows) == 1
    assert rows[0]["amount"] == 50.0


def test_excluded_expense_still_counts_as_spending(db, pair):
    """The distinction that makes the flag worth having."""
    from app.services import get_month_summary

    _shared(db, pair, 100, pair.user_id, excluded=True)
    today = date.today()
    summary = get_month_summary(db, pair.household_id, today.year, today.month)
    assert summary["total_spent"] == 100.0


# ---------------------------------------------------------------------------
# Reporting what was left out
# ---------------------------------------------------------------------------

def test_exclusions_report_counts_both_reasons(db, pair):
    _shared(db, pair, 100, None)
    _shared(db, pair, 60, None)
    _shared(db, pair, 30, pair.user_id, excluded=True)
    _shared(db, pair, 500, pair.user_id)      # normal, must not be reported

    ex = get_settlement_exclusions(db, pair.household_id)
    assert ex["no_payer_count"] == 2
    assert ex["no_payer_total"] == 160.0
    assert ex["excluded_count"] == 1
    assert ex["excluded_total"] == 30.0
    assert ex["any"] is True


def test_nothing_to_report_when_everything_is_attributed(db, pair):
    _shared(db, pair, 100, pair.user_id)
    ex = get_settlement_exclusions(db, pair.household_id)
    assert ex["any"] is False
    assert ex["no_payer_count"] == 0


def test_only_settlement_enabled_buckets_are_reported(db, pair):
    """A payerless expense in a bucket nobody settles is not a problem."""
    other = Bucket(household_id=pair.household_id, name="Solo", enable_settlement=False)
    db.add(other)
    db.flush()
    db.add(Transaction(
        bucket_id=other.id, household_id=pair.household_id, amount=70,
        currency="EUR", exchange_rate=1, type=TransactionType.expense,
        transaction_date=date.today(), paid_by=None,
    ))
    db.commit()

    assert get_settlement_exclusions(db, pair.household_id)["any"] is False


def test_exclusions_are_currency_converted(db, pair):
    db.add(Transaction(
        bucket_id=pair.bucket_id, household_id=pair.household_id, amount=200,
        currency="USD", exchange_rate=0.5, type=TransactionType.expense,
        transaction_date=date.today(), paid_by=None,
    ))
    db.commit()
    assert get_settlement_exclusions(db, pair.household_id)["no_payer_total"] == 100.0


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_settle_up_page_explains_the_gap(client, db, pair):
    _shared(db, pair, 100, None)
    r = client.get("/settlement")
    assert r.status_code == 200
    assert "no payer recorded" in r.text


def test_edit_form_saves_the_exclusion(client, db, pair):
    t = _shared(db, pair, 100, pair.user_id)
    r = client.post(f"/transactions/{t.id}/edit", data={
        "bucket_id": pair.bucket_id, "transaction_date": date.today().isoformat(),
        "amount": "100", "currency": "EUR", "type": "expense",
        "paid_by": pair.user_id, "exclude_from_settlement": "on",
    }, headers=pair.headers)
    assert r.status_code == 302

    db.expire_all()
    assert db.get(Transaction, t.id).exclude_from_settlement is True
    assert get_bucket_settlement(db, pair.bucket_id) == []


def test_edit_form_can_clear_the_exclusion(client, db, pair):
    t = _shared(db, pair, 100, pair.user_id, excluded=True)
    r = client.post(f"/transactions/{t.id}/edit", data={
        "bucket_id": pair.bucket_id, "transaction_date": date.today().isoformat(),
        "amount": "100", "currency": "EUR", "type": "expense",
        "paid_by": pair.user_id,
    }, headers=pair.headers)
    assert r.status_code == 302

    db.expire_all()
    assert db.get(Transaction, t.id).exclude_from_settlement is False


def test_shared_expense_defaults_the_payer_to_the_submitter(client, db, pair):
    """Belt and braces behind the wizard's preselected payer: an offline replay
    or API client that omits paid_by must not create an unsettleable expense."""
    r = client.post("/transactions", data={
        "bucket_id": pair.bucket_id, "transaction_date": date.today().isoformat(),
        "amount": "100", "currency": "EUR", "type": "expense",
        "is_shared": "on",
        f"split_{pair.user_id}": "50",
        f"split_{pair.partner_id}": "50",
    }, headers=pair.headers, follow_redirects=False)
    assert r.status_code in (200, 302)

    txn = db.query(Transaction).filter(Transaction.amount == 100).one()
    assert txn.paid_by == pair.user_id


def test_missing_payer_filter_lists_them(client, db, pair):
    _shared(db, pair, 137.77, None)
    _shared(db, pair, 502.13, pair.user_id)

    r = client.get("/transactions/search?missing_payer=1")
    assert r.status_code == 200
    assert "137.77" in r.text
    assert "502.13" not in r.text
