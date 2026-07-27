"""
Transaction search.

Free text previously matched notes only, so a scanned receipt whose merchant
landed in the category or bucket name was unfindable, and a bare amount could
not be searched at all.
"""
from datetime import date

import pytest

from app.models import (
    Bucket, Category, Transaction, TransactionSplit, TransactionType,
)


@pytest.fixture()
def corpus(db, authed, make_household):
    """A small set of transactions spanning buckets, categories and people."""
    groceries = Category(household_id=authed.household_id, name="Groceries")
    fuel = Category(household_id=authed.household_id, name="Fuel")
    db.add_all([groceries, fuel])
    travel = Bucket(household_id=authed.household_id, name="Florence 2026")
    db.add(travel)
    db.flush()

    rows = [
        # (bucket, category, amount, notes)
        (authed.bucket_id, groceries.id, 42.50, "Lidl weekly shop"),
        (authed.bucket_id, fuel.id, 80.00, "Shell station"),
        (travel.id, groceries.id, 15.25, "Airport snacks"),
        (travel.id, None, 250.00, "Hotel"),
    ]
    for bucket_id, cat_id, amount, notes in rows:
        db.add(Transaction(
            bucket_id=bucket_id, household_id=authed.household_id,
            amount=amount, currency="EUR", exchange_rate=1,
            type=TransactionType.expense, category_id=cat_id,
            transaction_date=date(2026, 6, 15), notes=notes,
            paid_by=authed.user_id,
        ))
    db.commit()

    authed.travel_bucket_id = travel.id
    authed.groceries_id = groceries.id
    return authed


def _search(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/transactions/search?{qs}")
    assert r.status_code == 200, r.text[:200]
    return r.text


def test_matches_notes(client, corpus):
    body = _search(client, q="Lidl")
    assert "Lidl weekly shop" in body
    assert "Hotel" not in body


def test_matches_category_name(client, corpus):
    """Searching a category name used to return nothing."""
    body = _search(client, q="Fuel")
    assert "Shell station" in body
    assert "Hotel" not in body


def test_matches_bucket_name(client, corpus):
    body = _search(client, q="Florence")
    assert "Hotel" in body
    assert "Lidl weekly shop" not in body


def test_matches_person_name(client, corpus):
    body = _search(client, q=corpus.username.title())
    assert "Lidl weekly shop" in body


def test_matches_exact_amount(client, corpus):
    """A bare number could not be searched at all before."""
    body = _search(client, q="42.50")
    assert "Lidl weekly shop" in body
    assert "Hotel" not in body


def test_amount_range_lower_bound(client, corpus):
    body = _search(client, min_amount="100")
    assert "Hotel" in body
    assert "Lidl weekly shop" not in body


def test_amount_range_upper_bound(client, corpus):
    body = _search(client, max_amount="50")
    assert "Lidl weekly shop" in body
    assert "Airport snacks" in body
    assert "Hotel" not in body


def test_amount_range_both_bounds(client, corpus):
    body = _search(client, min_amount="40", max_amount="100")
    assert "Lidl weekly shop" in body
    assert "Shell station" in body
    assert "Hotel" not in body
    assert "Airport snacks" not in body


def test_filter_by_person_includes_splits(client, db, corpus, make_household):
    """A split participant counts as involved, not just the payer."""
    other = make_household(name="Other", username="splitmate")
    txn = db.query(Transaction).filter(Transaction.notes == "Hotel").one()
    db.add(TransactionSplit(transaction_id=txn.id, user_id=other.user_id, amount=125))
    db.commit()

    body = _search(client, paid_by=other.user_id)
    assert "Hotel" in body
    assert "Lidl weekly shop" not in body


def test_combined_filters_narrow(client, corpus):
    body = _search(client, q="Groceries", bucket_id=corpus.travel_bucket_id)
    assert "Airport snacks" in body
    assert "Lidl weekly shop" not in body


def test_search_is_scoped_to_household(client, db, corpus, make_household):
    victim = make_household(name="Victim", username="searchvictim")
    db.add(Transaction(
        bucket_id=victim.bucket_id, household_id=victim.household_id,
        amount=42.50, currency="EUR", exchange_rate=1,
        type=TransactionType.expense, transaction_date=date(2026, 6, 15),
        notes="SecretDinner",
    ))
    db.commit()

    assert "SecretDinner" not in _search(client, q="42.50")
    assert "SecretDinner" not in _search(client, q="Secret")


def test_empty_search_shows_no_results(client, corpus):
    body = _search(client)
    assert "Lidl weekly shop" not in body


def test_bad_amount_is_rejected(client, corpus):
    r = client.get("/transactions/search?min_amount=abc")
    assert r.status_code == 400


def test_nonsense_query_returns_nothing_gracefully(client, corpus):
    body = _search(client, q="zzzzzznomatch")
    assert "Lidl weekly shop" not in body
    assert "Hotel" not in body
