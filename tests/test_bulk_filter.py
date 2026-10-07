"""Bulk by filter (2c spec §5.3 select.filter; §9 items 1 and 9) and
"Keep both" (§5.2 duplicates/dismiss)."""

from decimal import Decimal

from app.models import BulkBatch, DuplicateDismissal, Transaction, TransactionType
from app.services.duplicates import drop_dismissed, find_household_duplicates
from tests.bulk_fixtures import env  # noqa: F401
from tests.test_api import api  # noqa: F401

DISMISS = "/api/v1/transactions/duplicates/dismiss"


def test_filter_selects_what_the_feed_filter_matches(env, db):  # noqa: F811
    a = env.add("38.90", notes="Cosmote October")
    b = env.add("38.90", merchant="COSMOTE")
    other = env.add("12.00", notes="Bakery")
    body = env.bulk({"filter": {"q": "cosmote"}}, {"bucket_id": env.bills}, dry_run=True).json()
    assert body["matched"] == 2
    r = env.bulk({"filter": {"q": "cosmote"}}, {"bucket_id": env.bills}, expected_count=2)
    assert r.status_code == 200, r.text
    assert env.row(a).bucket_id == env.bills and env.row(b).bucket_id == env.bills
    assert env.row(other).bucket_id == env.day
    assert db.query(BulkBatch).one().selection == "filter"


def test_r01_filter_never_touches_another_household(env, db, make_household):  # noqa: F811
    other = make_household(name="Other", username="other")
    theirs = Transaction(
        household_id=other.household_id,
        bucket_id=other.bucket_id,
        amount=Decimal("38.90"),
        type=TransactionType.expense,
        notes="Cosmote October",
        transaction_date=env.today,
    )
    db.add(theirs)
    db.commit()
    mine = env.add("38.90", notes="Cosmote October")
    body = env.bulk({"filter": {"q": "Cosmote"}}, {"category_id": env.utilities}).json()
    assert body["matched"] == 1
    assert env.row(mine).category_id == env.utilities
    assert env.row(theirs.id).category_id is None


def test_filter_limits_and_errors(env, db):  # noqa: F811
    assert env.bulk({"filter": {}}, {"bucket_id": env.bills}).status_code == 400
    assert env.bulk({"filter": {"bucket": env.day}}, {"bucket_id": env.bills}).status_code == 422
    assert env.bulk({"filter": {"from_date": "07/10"}}, {"bucket_id": env.bills}).status_code == 400

    env.add("5.00", notes="lunch")
    drift = env.bulk({"filter": {"q": "lunch"}}, {"bucket_id": env.bills}, expected_count=3)
    assert drift.status_code == 409 and db.query(BulkBatch).count() == 0

    db.add_all(
        Transaction(
            household_id=env.hid,
            bucket_id=env.day,
            amount=Decimal("1.00"),
            type=TransactionType.expense,
            notes="bulk seed",
            transaction_date=env.today,
        )
        for _ in range(1001)
    )
    db.commit()
    big = env.bulk({"filter": {"q": "bulk seed"}}, {"bucket_id": env.bills}, dry_run=True)
    assert big.status_code == 400 and "Narrow the filter" in big.json()["detail"]


def test_dismiss_stores_every_pair_once(env, db):  # noqa: F811
    a, b, c = env.add("9.99"), env.add("9.99"), env.add("9.99")
    r = env.client.post(DISMISS, headers=env.headers, json={"ids": [c, a, b]})
    assert r.status_code == 204, r.text
    pairs = {(d.first_id, d.second_id) for d in db.query(DuplicateDismissal)}
    lo, mid, hi = sorted([a, b, c])
    assert pairs == {(lo, mid), (lo, hi), (mid, hi)}


def test_dismiss_is_idempotent(env, db):  # noqa: F811
    a, b = env.add("9.99"), env.add("9.99")
    for _ in range(2):
        assert (
            env.client.post(DISMISS, headers=env.headers, json={"ids": [a, b]}).status_code == 204
        )
    assert db.query(DuplicateDismissal).count() == 1


def test_dismiss_refuses_foreign_inactive_and_single_ids(env, db, make_household):  # noqa: F811
    from app.core.clock import utcnow_naive

    other = make_household(name="Other", username="other")
    theirs = Transaction(
        household_id=other.household_id,
        bucket_id=other.bucket_id,
        amount=Decimal("9.99"),
        type=TransactionType.expense,
        transaction_date=env.today,
    )
    db.add(theirs)
    db.commit()
    a = env.add("9.99")
    gone = env.add("9.99", deleted_at=utcnow_naive())

    def post(ids):
        return env.client.post(DISMISS, headers=env.headers, json={"ids": ids})

    assert post([a, theirs.id]).status_code == 404
    assert post([a, gone]).status_code == 404
    assert post([a]).status_code == 422
    assert db.query(DuplicateDismissal).count() == 0


def test_drop_dismissed_hides_a_pair_but_not_a_partly_dismissed_group(env, db):  # noqa: F811
    a, b = env.add("7.50"), env.add("7.50")
    x, y, z = env.add("4.20"), env.add("4.20"), env.add("4.20")
    env.client.post(DISMISS, headers=env.headers, json={"ids": [a, b]})
    env.client.post(DISMISS, headers=env.headers, json={"ids": [x, y]})
    groups = drop_dismissed(db, env.hid, find_household_duplicates(db, env.hid))
    assert [sorted(t.id for t in g["transactions"]) for g in groups] == [sorted([x, y, z])]


# ------------------------------------------------- fix round 1: unbounded filters


def test_month_without_year_is_400_in_the_feed_filter(env, db):  # noqa: F811
    import pytest
    from fastapi import HTTPException

    from app.services.transaction_filter import TransactionFilter, apply_filter

    q = db.query(Transaction).filter(Transaction.household_id == env.hid)
    with pytest.raises(HTTPException) as exc:
        apply_filter(q, TransactionFilter(month=5), db, env.hid)
    assert exc.value.status_code == 400 and exc.value.detail == "Pick a year for the month."
    # With a year it is a real month range.
    assert apply_filter(q, TransactionFilter(year=2026, month=5), db, env.hid).count() == 0


def test_month_without_year_is_400_in_bulk_and_writes_nothing(env, db):  # noqa: F811
    a = env.add()
    r = env.bulk({"filter": {"month": 5}}, {"bucket_id": env.bills})
    assert r.status_code == 400, r.text
    assert env.row(a).bucket_id == env.day and db.query(BulkBatch).count() == 0


def test_is_empty_counts_only_constraining_fields():
    from app.services.transaction_filter import TransactionFilter

    assert TransactionFilter(month=5).is_empty()
    assert TransactionFilter(q="  ", no_bucket=False).is_empty()
    assert not TransactionFilter(year=2026).is_empty()
    assert not TransactionFilter(year=2026, month=5).is_empty()


def test_filter_that_constrains_nothing_is_400(env, db, monkeypatch):  # noqa: F811
    from app.services.transaction_filter import TransactionFilter

    a = env.add()
    assert env.bulk({"filter": {"q": "   "}}, {"bucket_id": env.bills}).status_code == 400
    # Even if is_empty() missed a field, a filter that adds no WHERE clause is refused.
    monkeypatch.setattr(TransactionFilter, "is_empty", lambda self: False)
    r = env.bulk({"filter": {"q": "   "}}, {"bucket_id": env.bills})
    assert r.status_code == 400 and r.json()["detail"] == "Choose what to change first."
    assert env.row(a).bucket_id == env.day and db.query(BulkBatch).count() == 0
