"""
Duplicate detection.

Two people logging the same dinner is the most common data-quality problem in a
shared tracker. These surface likely repeats; they never block or delete
anything, because a genuine repeat (two coffees the same day) is legitimate.
"""
from datetime import date, timedelta

import pytest

from app.models import Bucket, Transaction, TransactionType
from app.services import find_duplicate_candidates, find_household_duplicates


def _expense(db, authed, amount, when=None, notes=None, bucket_id=None):
    txn = Transaction(
        bucket_id=bucket_id or authed.bucket_id,
        household_id=authed.household_id,
        amount=amount, currency="EUR", exchange_rate=1,
        type=TransactionType.expense,
        transaction_date=when or date.today(),
        notes=notes, paid_by=authed.user_id,
    )
    db.add(txn)
    db.commit()
    return txn


# ---------------------------------------------------------------------------
# Candidate lookup (entry-time check)
# ---------------------------------------------------------------------------

def test_same_amount_same_day_is_flagged(db, authed):
    _expense(db, authed, 42.50, notes="Dinner")
    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50, transaction_date=date.today()
    )
    assert len(matches) == 1


def test_within_window_is_flagged(db, authed):
    _expense(db, authed, 42.50, date.today() - timedelta(days=2))
    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50, transaction_date=date.today()
    )
    assert len(matches) == 1


def test_outside_window_is_not_flagged(db, authed):
    _expense(db, authed, 42.50, date.today() - timedelta(days=10))
    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50, transaction_date=date.today()
    )
    assert matches == []


def test_different_amount_is_not_flagged(db, authed):
    _expense(db, authed, 42.50)
    matches = find_duplicate_candidates(
        db, authed.household_id, amount=99.00, transaction_date=date.today()
    )
    assert matches == []


def test_cross_bucket_duplicate_is_flagged(db, authed):
    """Two people often file the same expense in different buckets."""
    other = Bucket(household_id=authed.household_id, name="Other")
    db.add(other)
    db.flush()
    _expense(db, authed, 42.50, bucket_id=other.id, notes="Dinner")
    db.commit()

    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50,
        transaction_date=date.today(), bucket_id=authed.bucket_id,
    )
    assert len(matches) == 1


def test_excludes_the_transaction_being_edited(db, authed):
    txn = _expense(db, authed, 42.50)
    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50,
        transaction_date=date.today(), exclude_id=txn.id,
    )
    assert matches == []


def test_income_is_not_matched(db, authed):
    db.add(Transaction(
        bucket_id=authed.bucket_id, household_id=authed.household_id,
        amount=42.50, currency="EUR", exchange_rate=1,
        type=TransactionType.income, transaction_date=date.today(),
    ))
    db.commit()
    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50, transaction_date=date.today()
    )
    assert matches == []


def test_other_households_are_never_matched(db, authed, make_household):
    victim = make_household(name="Victim", username="dupvictim")
    db.add(Transaction(
        bucket_id=victim.bucket_id, household_id=victim.household_id,
        amount=42.50, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date.today(),
    ))
    db.commit()

    matches = find_duplicate_candidates(
        db, authed.household_id, amount=42.50, transaction_date=date.today()
    )
    assert matches == []


# ---------------------------------------------------------------------------
# Household scan (review page)
# ---------------------------------------------------------------------------

def test_scan_finds_a_pair(db, authed):
    _expense(db, authed, 60.00, notes="Groceries")
    _expense(db, authed, 60.00, notes="Groceries again")
    groups = find_household_duplicates(db, authed.household_id)
    assert len(groups) == 1
    assert len(groups[0]["transactions"]) == 2


def test_scan_ignores_isolated_transactions(db, authed):
    _expense(db, authed, 10.00)
    _expense(db, authed, 20.00)
    _expense(db, authed, 30.00)
    assert find_household_duplicates(db, authed.household_id) == []


def test_scan_splits_clusters_by_date_gap(db, authed):
    """Same amount every month is a subscription, not a duplicate."""
    for months in range(3):
        _expense(db, authed, 9.99, date.today() - timedelta(days=30 * months))
    assert find_household_duplicates(db, authed.household_id) == []


def test_scan_groups_three_way_duplicate(db, authed):
    for _ in range(3):
        _expense(db, authed, 25.00)
    groups = find_household_duplicates(db, authed.household_id)
    assert len(groups) == 1
    assert len(groups[0]["transactions"]) == 3


def test_scan_respects_lookback(db, authed):
    old = date.today() - timedelta(days=200)
    _expense(db, authed, 15.00, old)
    _expense(db, authed, 15.00, old)
    assert find_household_duplicates(db, authed.household_id, since_days=90) == []


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_check_endpoint_returns_matches(client, db, authed):
    _expense(db, authed, 42.50, notes="Dinner")
    r = client.get(
        f"/transactions/check-duplicate?amount=42.50&transaction_date={date.today()}"
    )
    assert r.status_code == 200
    dups = r.json()["duplicates"]
    assert len(dups) == 1
    assert dups[0]["notes"] == "Dinner"


def test_check_endpoint_handles_blank_input(client, authed):
    r = client.get("/transactions/check-duplicate?amount=&transaction_date=")
    assert r.status_code == 200
    assert r.json()["duplicates"] == []


def test_check_endpoint_handles_bad_date(client, authed):
    r = client.get("/transactions/check-duplicate?amount=10&transaction_date=nonsense")
    assert r.status_code == 200
    assert r.json()["duplicates"] == []


def test_duplicates_page_empty_state(client, authed):
    r = client.get("/transactions/duplicates")
    assert r.status_code == 200
    assert "Nothing looks duplicated" in r.text


def test_duplicates_page_lists_groups(client, db, authed):
    _expense(db, authed, 60.00, notes="Groceries")
    _expense(db, authed, 60.00, notes="Groceries again")

    r = client.get("/transactions/duplicates")
    assert r.status_code == 200
    assert "possible duplicate" in r.text.lower()
    assert "Groceries again" in r.text


def test_duplicates_page_is_household_scoped(client, db, authed, make_household):
    victim = make_household(name="Victim", username="dupvictim2")
    for _ in range(2):
        db.add(Transaction(
            bucket_id=victim.bucket_id, household_id=victim.household_id,
            amount=77.00, currency="EUR", exchange_rate=1,
            type=TransactionType.expense, transaction_date=date.today(),
            notes="VictimSecret",
        ))
    db.commit()

    r = client.get("/transactions/duplicates")
    assert "VictimSecret" not in r.text
