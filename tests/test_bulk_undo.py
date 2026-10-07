"""Undo of a bulk change (2c spec §5.3-5.4 U1-U8; §9 item 10), the recent
list, and the bulk events in a transaction's history."""

from datetime import UTC, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core import clock
from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    Bucket,
    BulkBatch,
    Category,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionSplit,
)
from app.services.bulk import (
    UNDO_WINDOW,
    bulk_history_events,
    can_undo,
    undo_batch,
)
from app.services.cash import FROM_BANK, link_take
from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.test_api import api  # noqa: F401


def apply(env, select, changes, **extra) -> str:  # noqa: F811
    r = env.bulk(select, changes, **extra)
    assert r.status_code == 200, r.text
    return r.json()["batch_id"]


def undo(env, batch_id):  # noqa: F811
    return env.client.post(f"{URL}/{batch_id}/undo", headers=env.headers)


def codes(body) -> dict[str, str]:
    return {s["id"]: s["code"] for s in body["skipped"]}


def test_u01_deleted_since_is_skipped(env, db):  # noqa: F811
    a, b = env.add(), env.add()
    batch = apply(env, {"ids": [a, b]}, {"bucket_id": env.bills})
    assert env.client.delete(f"/api/v1/transactions/{a}", headers=env.headers).status_code == 204
    body = undo(env, batch).json()
    assert body["restored"] == 1 and codes(body) == {a: "deleted_since"}
    assert env.row(b).bucket_id == env.day


def test_u02_changed_since_is_skipped_others_restored(env, db):  # noqa: F811
    a, b, c = env.add("10.00"), env.add("11.00"), env.add("12.00")
    batch = apply(env, {"ids": [a, b, c]}, {"bucket_id": env.bills})
    put = env.client.put(
        f"/api/v1/transactions/{a}",
        headers=env.headers,
        json={"amount": "10.00", "type": "expense", "bucket_id": env.box},
    )
    assert put.status_code == 200, put.text
    body = undo(env, batch).json()
    assert body["restored"] == 2 and codes(body) == {a: "changed_since"}
    assert env.row(a).bucket_id == env.box
    assert env.row(b).bucket_id == env.day and env.row(c).bucket_id == env.day
    db.expire_all()
    assert db.get(BulkBatch, batch).undone_at is not None  # set even with skips


def test_u03_old_target_gone_is_skipped(env, db):  # noqa: F811
    temp = Bucket(household_id=env.hid, name="Temp")
    snacks = Category(household_id=env.hid, name="Snacks")
    db.add_all([temp, snacks])
    db.commit()
    a = env.add(bucket_id=temp.id)
    b = env.add(category_id=snacks.id)
    by_bucket = apply(env, {"ids": [a]}, {"bucket_id": env.bills})
    by_category = apply(env, {"ids": [b]}, {"category_id": env.groceries})
    db.delete(db.get(Bucket, temp.id))
    db.delete(db.get(Category, snacks.id))
    db.commit()
    assert codes(undo(env, by_bucket).json()) == {a: "target_gone"}
    assert codes(undo(env, by_category).json()) == {b: "target_gone"}
    assert env.row(a).bucket_id == env.bills and env.row(b).category_id == env.groceries


def test_u04_fixed_cost_whose_item_was_deleted_is_skipped(env, db):  # noqa: F811
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)
    batch = apply(env, {"ids": [fixed]}, {"bucket_id": env.bills})
    db.delete(db.get(RecurringBill, env.cosmote))  # FK SET NULL clears recurring_bill_id
    db.commit()
    assert env.row(fixed).recurring_bill_id is None
    r = undo(env, batch)
    assert r.status_code == 200, r.text  # never an IntegrityError from the CHECK
    assert codes(r.json()) == {fixed: "needs_bucket"}
    assert env.row(fixed).bucket_id == env.bills


def test_u05_take_and_split_rules_against_old_values(env, db):  # noqa: F811
    # (a) Payer me -> Maria; since then Maria took cash for it: restoring me is refused.
    a = env.add("20.00")
    batch_a = apply(env, {"ids": [a]}, {"payer": {"mode": "single", "user_id": env.maria}})
    t = db.get(Transaction, a)
    t.payment_method = "cash"
    link_take(db, t, env.maria, FROM_BANK, "EUR")
    db.commit()
    assert codes(undo(env, batch_a).json()) == {a: "cash_take"}

    # (b) Method card -> cash; since then a take was linked: back to card is refused.
    b = env.add("15.00")
    batch_b = apply(env, {"ids": [b]}, {"payment_method": "cash"})
    link_take(db, db.get(Transaction, b), env.me, FROM_BANK, "EUR")
    db.commit()
    assert codes(undo(env, batch_b).json()) == {b: "cash_take"}

    # (c) Own share -> single; since then the shares were removed: own share is refused.
    c = env.add("100.00", paid_by=None, payer_mode="own_share")
    db.add_all(
        [
            TransactionSplit(transaction_id=c, user_id=env.me, amount=Decimal("50")),
            TransactionSplit(transaction_id=c, user_id=env.maria, amount=Decimal("50")),
        ]
    )
    db.commit()
    batch_c = apply(env, {"ids": [c]}, {"payer": {"mode": "single", "user_id": env.me}})
    db.query(TransactionSplit).filter_by(transaction_id=c).delete()
    db.commit()
    assert codes(undo(env, batch_c).json()) == {c: "no_split"}


def test_u06_restores_values_and_entry_payer(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote, paid_by=env.me)
    occ = BillOccurrence(
        bill_id=env.cosmote,
        due_date=env.today,
        status=OccurrenceStatus.paid,
        paid_by=env.me,
        paid_at=utcnow_naive(),
        transaction_id=pay,
    )
    db.add(occ)
    db.commit()
    batch = apply(
        env,
        {"ids": [pay]},
        {"payer": {"mode": "single", "user_id": env.maria}, "category_id": env.utilities},
    )
    body = undo(env, batch).json()
    assert body == {"restored": 1, "skipped": [], "bill_restored": False}
    t = env.row(pay)
    assert t.paid_by == env.me and t.category_id is None
    assert t.recurring_bill_id == env.cosmote
    assert db.get(BillOccurrence, occ.id).paid_by == env.me


def test_u07_bill_move_restored_only_if_untouched(env, db):  # noqa: F811
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    first = apply(env, {"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True)
    assert undo(env, first).json()["bill_restored"] is True
    db.expire_all()
    assert db.get(RecurringBill, env.cosmote).bucket_id == env.bills

    second = apply(env, {"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True)
    db.get(RecurringBill, env.cosmote).bucket_id = env.box  # someone moved it since
    db.commit()
    assert undo(env, second).json()["bill_restored"] is False
    db.expire_all()
    assert db.get(RecurringBill, env.cosmote).bucket_id == env.box


def test_u08_own_share_cent_is_kept(env, db):  # noqa: F811
    shared = env.add("100.00")
    db.add_all(
        [
            TransactionSplit(transaction_id=shared, user_id=env.me, amount=Decimal("33.33")),
            TransactionSplit(transaction_id=shared, user_id=env.maria, amount=Decimal("66.66")),
        ]
    )
    db.commit()
    batch = apply(env, {"ids": [shared]}, {"payer": {"mode": "own_share"}})
    assert undo(env, batch).json()["restored"] == 1
    db.expire_all()
    t = env.row(shared)
    assert t.payer_mode == "single" and t.paid_by == env.me
    assert sum(s.amount for s in t.splits) == Decimal("100.00")


def test_second_undo_is_409(env, db):  # noqa: F811
    batch = apply(env, {"ids": [env.add()]}, {"bucket_id": env.bills})
    assert undo(env, batch).status_code == 200
    again = undo(env, batch)
    assert again.status_code == 409 and again.json()["detail"] == "This change was already undone."


def test_undo_window_is_24_hours(env, db, monkeypatch):  # noqa: F811
    batch_id = apply(env, {"ids": [env.add()]}, {"bucket_id": env.bills})
    created = db.get(BulkBatch, batch_id).created_at
    assert can_undo(db.get(BulkBatch, batch_id), created + UNDO_WINDOW)
    # The service, not HTTP: a 24 h jump would also expire the access token.
    late = (created + UNDO_WINDOW + timedelta(seconds=1)).replace(tzinfo=UTC)
    monkeypatch.setattr(clock, "utcnow", lambda: late)
    with pytest.raises(HTTPException) as exc:
        undo_batch(db, household_id=env.hid, user_id=env.me, batch_id=batch_id)
    assert exc.value.status_code == 409
    assert exc.value.detail == "Changes can be undone for 24 hours."


def test_another_households_batch_is_404(env, db, make_household):  # noqa: F811
    batch_id = apply(env, {"ids": [env.add()]}, {"bucket_id": env.bills})
    other = make_household(name="Other", username="other")
    with pytest.raises(HTTPException) as exc:
        undo_batch(db, household_id=other.household_id, user_id=other.user_id, batch_id=batch_id)
    assert exc.value.status_code == 404
    assert undo(env, "no-such-batch").status_code == 404


def test_recent_list_newest_first_and_route_order(env, db):  # noqa: F811
    a = env.add()
    first = apply(env, {"ids": [a]}, {"bucket_id": env.bills})
    second = apply(env, {"ids": [a]}, {"category_id": env.groceries})
    undo(env, first)
    r = env.client.get(URL, headers=env.headers, params={"limit": 10})
    assert r.status_code == 200, r.text  # not "Transaction not found"
    rows = r.json()
    assert [x["id"] for x in rows] == [second, first]
    assert rows[0]["summary"] == "Category → Groceries · 1 transaction"
    assert rows[0]["created_by"] == env.hh.username.title() and rows[0]["can_undo"] is True
    assert rows[1]["undone_at"] is not None and rows[1]["can_undo"] is False
    assert env.client.get(URL, headers=env.headers, params={"limit": 51}).status_code == 422


def test_bulk_history_events(env, db):  # noqa: F811
    a = env.add()
    batch = apply(env, {"ids": [a]}, {"bucket_id": env.bills})
    undo(env, batch)
    events = bulk_history_events(db, env.hid, a)
    assert [e["kind"] for e in events] == ["bulk_change", "bulk_undone"]
    assert events[0]["text"] == "Bucket: Day to day → Bills"
    assert events[0]["batch_id"] == batch and events[0]["can_undo"] is False
    assert events[1]["text"] == "Change undone"
