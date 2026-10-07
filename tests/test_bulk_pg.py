"""Bulk changes on Postgres (2c spec §5.3): only a Postgres run proves these.

SQLite ignores FOR UPDATE, so the apply path's with_for_update(of=Transaction)
next to joinedload(Transaction.splits) and the batch lock in undo only mean
something here. Run with TEST_DATABASE_URL pointing at a disposable Postgres
(see tests/conftest.py)."""

import threading
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models import TransactionSplit
from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.conftest import TEST_DATABASE_URL
from tests.test_api import api  # noqa: F401

pytestmark = pytest.mark.skipif(
    not (TEST_DATABASE_URL or "").startswith("postgresql"),
    reason="needs TEST_DATABASE_URL=postgresql://...",
)


def test_apply_locks_rows_with_splits_joined(env, db):  # noqa: F811
    """A plain FOR UPDATE here fails on Postgres: "FOR UPDATE cannot be applied
    to the nullable side of an outer join"."""
    shared = env.add("100.00")
    db.add_all(
        [
            TransactionSplit(transaction_id=shared, user_id=env.me, amount=Decimal("33.33")),
            TransactionSplit(transaction_id=shared, user_id=env.maria, amount=Decimal("66.66")),
        ]
    )
    db.commit()
    plain = env.add("5.00")
    r = env.bulk({"ids": [shared, plain]}, {"bucket_id": env.bills, "payer": {"mode": "own_share"}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 1 and r.json()["skipped"][0]["code"] == "no_split"
    by_filter = env.bulk({"filter": {"min_amount": "1"}}, {"category_id": env.groceries})
    assert by_filter.status_code == 200, by_filter.text


def test_concurrent_undos_one_wins(env, db):  # noqa: F811
    batch = env.bulk({"ids": [env.add(), env.add()]}, {"bucket_id": env.bills}).json()["batch_id"]
    clients = [TestClient(env.client.app), TestClient(env.client.app)]
    barrier = threading.Barrier(2)
    statuses = []

    def run(c):
        barrier.wait()
        statuses.append(c.post(f"{URL}/{batch}/undo", headers=env.headers).status_code)

    threads = [threading.Thread(target=run, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(statuses) == [200, 409]


def test_dismissal_order_matches_the_check(env, db):  # noqa: F811
    """Python's sorted() and Postgres' text collation must agree on "smaller
    id first", or the CHECK first_id < second_id rejects the insert."""
    ids = [env.add("3.30") for _ in range(4)]
    r = env.client.post(
        "/api/v1/transactions/duplicates/dismiss", headers=env.headers, json={"ids": ids}
    )
    assert r.status_code == 204, r.text
