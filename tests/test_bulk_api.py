"""POST /api/v1/transactions/bulk (2c spec §5.3-5.4; §9 items 1-9)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.clock import utcnow_naive
from app.models import (
    BillOccurrence,
    Bucket,
    BulkBatch,
    BulkBatchRow,
    CashMovement,
    Category,
    MatchSuggestion,
    OccurrenceStatus,
    RecurringBill,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services.budgets import bucket_spent
from app.services.bulk import BILL_EVENT_BUCKET, BILL_IN_ITEM, NO_BUCKET_NAME
from app.services.bulk_rules import BILL_KEEPS_BUCKET
from app.services.cash import FROM_BANK, link_take
from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.test_api import api  # noqa: F401


def codes(body) -> dict[str, str]:
    return {s["id"]: s["code"] for s in body["skipped"]}


@pytest.mark.parametrize(
    "target", ["foreign_id", "missing_id", "bucket", "category", "payer", "bill"]
)
def test_r01_foreign_or_missing_reference_is_404_and_nothing_changes(
    env,
    db,
    make_household,
    target,  # noqa: F811
):
    other = make_household(name="Other", username="other")
    theirs = Transaction(
        household_id=other.household_id,
        bucket_id=other.bucket_id,
        amount=Decimal("12.00"),
        type=TransactionType.expense,
        transaction_date=env.today,
    )
    their_cat = Category(household_id=other.household_id, name="Theirs")
    their_bill = RecurringBill(
        household_id=other.household_id,
        name="Their bill",
        amount=Decimal("9"),
        currency="EUR",
        start_date=env.today,
        is_active=True,
    )
    db.add_all([theirs, their_cat, their_bill])
    db.commit()
    mine = env.add("12.00")

    select, changes = {"ids": [mine]}, {"bucket_id": env.bills}
    if target == "foreign_id":
        select = {"ids": [mine, theirs.id]}
    elif target == "missing_id":
        select = {"ids": [mine, "no-such-id"]}
    elif target == "bucket":
        changes = {"bucket_id": other.bucket_id}
    elif target == "category":
        changes = {"category_id": their_cat.id}
    elif target == "payer":
        changes = {"payer": {"mode": "single", "user_id": other.user_id}}
    else:
        select = {"bill_id": their_bill.id}

    r = env.bulk(select, changes)
    assert r.status_code == 404, r.text
    assert env.row(mine).bucket_id == env.day
    assert env.row(theirs.id).bucket_id == other.bucket_id
    assert db.query(BulkBatch).count() == 0


def test_r02_own_deleted_id_is_skipped_not_404(env, db):  # noqa: F811
    gone = env.add("5.00", deleted_at=utcnow_naive())
    live = env.add("6.00")
    body = env.bulk({"ids": [gone, live]}, {"bucket_id": env.bills}).json()
    assert body["matched"] == 2 and body["changed"] == 1
    assert codes(body) == {gone: "deleted"}
    assert env.row(gone).bucket_id == env.day and env.row(live).bucket_id == env.bills


def test_r03_archived_target_bucket_is_400(env, db):  # noqa: F811
    a = env.add()
    r = env.bulk({"ids": [a]}, {"bucket_id": env.old})
    assert r.status_code == 400 and "archived" in r.json()["detail"]
    assert env.row(a).bucket_id == env.day


def test_r04_r07_null_bucket_and_income_rules(env, db):  # noqa: F811
    income = env.add("1500.00", type=TransactionType.income, bucket_id=env.day)
    plain = env.add("20.00")
    transfer = env.add("50.00", type=TransactionType.transfer)
    bill_paid = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)

    r = env.bulk({"ids": [income, plain, transfer, bill_paid, fixed]}, {"bucket_id": None})
    assert r.status_code == 200, r.text  # the CHECK is never hit: no IntegrityError
    body = r.json()
    assert body["changed"] == 1 and body["unchanged"] == 1
    assert codes(body) == {
        plain: "needs_bucket",
        transfer: "needs_bucket",
        bill_paid: "needs_bucket",
    }
    reasons = {s["id"]: s["reason"] for s in body["skipped"]}
    assert reasons[bill_paid] == BILL_KEEPS_BUCKET
    assert env.row(income).bucket_id is None and env.row(fixed).bucket_id is None
    assert env.row(bill_paid).bucket_id == env.bills

    # A bucket-less Fixed cost may move into a monthly bucket.
    assert env.bulk({"ids": [fixed]}, {"bucket_id": env.bills}).json()["changed"] == 1
    assert env.row(fixed).bucket_id == env.bills

    # Income into a bucket that doesn't track income is skipped; the expense moves.
    loose = env.add("100.00", type=TransactionType.income, bucket_id=None)
    body = env.bulk({"ids": [loose, plain]}, {"bucket_id": env.box}).json()
    assert codes(body) == {loose: "income_bucket"} and body["changed"] == 1
    assert env.row(plain).bucket_id == env.box and env.row(loose).bucket_id is None


def test_r07_single_put_rules_are_unchanged(env, db):  # noqa: F811
    bill_paid = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)

    def put(txn_id, bucket_id):
        body = {"amount": "38.90", "type": "expense", "bucket_id": bucket_id}
        return env.client.put(f"/api/v1/transactions/{txn_id}", headers=env.headers, json=body)

    assert put(bill_paid, None).status_code == 400
    assert put(fixed, None).status_code == 200


def test_r08_event_bucket_preview_matches_bucket_spent(env, db):  # noqa: F811
    a, b = env.add("40.00"), env.add("60.00")
    early = env.add("25.00", days_ago=20)  # before the trip's start_date
    trip = db.get(Bucket, env.trip)
    before = bucket_spent(db, trip, env.today)

    preview = env.bulk({"ids": [a, b, early]}, {"bucket_id": env.trip}, dry_run=True).json()
    effect = next(e for e in preview["buckets"] if e["bucket_id"] == env.trip)
    assert effect["kind"] == "event"
    assert effect["period_start"] == (env.today - timedelta(days=10)).isoformat()
    assert effect["spent_before"] == pytest.approx(float(before))
    assert effect["spent_after"] - effect["spent_before"] == pytest.approx(100.00)
    assert effect["moved_in"] == pytest.approx(100.00) and effect["outside_period"] == 1

    assert env.bulk({"ids": [a, b, early]}, {"bucket_id": env.trip}).json()["changed"] == 3
    db.expire_all()
    after = bucket_spent(db, db.get(Bucket, env.trip), env.today)
    assert float(after) == pytest.approx(effect["spent_after"])


def test_r09_move_bill_needs_bill_selection_and_bucket_change(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    by_ids = env.bulk({"ids": [pay]}, {"bucket_id": env.day}, move_bill=True)
    no_bucket = env.bulk({"bill_id": env.cosmote}, {"category_id": env.utilities}, move_bill=True)
    assert by_ids.status_code == 400 and no_bucket.status_code == 400
    assert env.row(pay).bucket_id == env.bills


def test_r10_move_bill_refuses_event_bucket_and_in_items(env, db):  # noqa: F811
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    event = env.bulk({"bill_id": env.cosmote}, {"bucket_id": env.trip}, move_bill=True)
    assert event.status_code == 400 and event.json()["detail"] == BILL_EVENT_BUCKET
    in_item = env.bulk({"bill_id": env.salary}, {"bucket_id": env.day}, move_bill=True)
    assert in_item.status_code == 400 and in_item.json()["detail"] == BILL_IN_ITEM
    assert db.get(RecurringBill, env.cosmote).bucket_id == env.bills


def test_r11_move_bill_moves_the_item_and_its_entries(env, db):  # noqa: F811
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote, days_ago=31)
    db.add(
        BillOccurrence(
            bill_id=env.cosmote,
            due_date=env.today + timedelta(days=5),
            status=OccurrenceStatus.unpaid,
        )
    )
    db.commit()

    preview = env.bulk(
        {"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True, dry_run=True
    ).json()
    assert preview["matched"] == 2
    assert preview["bill"] == {
        "id": env.cosmote,
        "name": "Cosmote",
        "bucket_before": "Bills",
        "bucket_after": "Day to day",
    }
    r = env.bulk({"bill_id": env.cosmote}, {"bucket_id": env.day}, move_bill=True, expected_count=2)
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 2

    entries = env.client.get(
        "/api/v1/recurring/entries",
        headers=env.headers,
        params={"from": env.today.isoformat(), "to": (env.today + timedelta(days=10)).isoformat()},
    ).json()
    assert {e["bucket_id"] for e in entries if e["item_id"] == env.cosmote} == {env.day}
    db.expire_all()
    batch = db.query(BulkBatch).one()
    assert batch.bill_moved and batch.bill_bucket_old == env.bills
    assert batch.bill_bucket_new == env.day and batch.selection == "bill"


def test_r12_r18_links_stay_and_entry_payer_follows(env, db):  # noqa: F811
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

    body = env.bulk({"ids": [pay]}, {"payer": {"mode": "single", "user_id": env.maria}}).json()
    assert body["changed"] == 1
    db.expire_all()
    occ = db.get(BillOccurrence, occ.id)
    assert occ.paid_by == env.maria and occ.transaction_id == pay
    t = env.row(pay)
    assert t.recurring_bill_id == env.cosmote and t.paid_by == env.maria
    stored = db.query(BulkBatchRow).one()
    assert stored.occurrence_id == occ.id and stored.old_occurrence_paid_by == env.me


def test_r13_r15_cash_takes(env, db):  # noqa: F811
    cash = env.add("30.00", payment_method="cash", paid_by=env.me)
    link_take(db, db.get(Transaction, cash), env.me, FROM_BANK, "EUR")
    db.commit()
    take = db.query(CashMovement).filter_by(transaction_id=cash).one()
    take_id, take_amount = take.id, take.amount

    payer = env.bulk({"ids": [cash]}, {"payer": {"mode": "single", "user_id": env.maria}}).json()
    method = env.bulk({"ids": [cash]}, {"payment_method": "card"}).json()
    assert codes(payer) == {cash: "cash_take"} and codes(method) == {cash: "cash_take"}
    db.expire_all()
    mv = db.get(CashMovement, take_id)
    assert mv.deleted_at is None and mv.transaction_id == cash
    assert mv.user_id == env.me and mv.amount == take_amount
    assert env.row(cash).payment_method == "cash" and env.row(cash).paid_by == env.me

    nobody = env.add("8.00", paid_by=None)
    alone = env.bulk({"ids": [nobody]}, {"payment_method": "cash"}).json()
    assert codes(alone) == {nobody: "cash_needs_payer"}
    both = env.bulk(
        {"ids": [nobody]},
        {"payment_method": "cash", "payer": {"mode": "single", "user_id": env.maria}},
    ).json()
    assert both["changed"] == 1
    assert env.row(nobody).paid_by == env.maria and env.row(nobody).payment_method == "cash"


def test_r17_r19_own_share_cent_and_fuel(env, db):  # noqa: F811
    shared = env.add("100.00")
    db.add_all(
        [
            TransactionSplit(transaction_id=shared, user_id=env.me, amount=Decimal("33.33")),
            TransactionSplit(transaction_id=shared, user_id=env.maria, amount=Decimal("66.66")),
        ]
    )
    db.commit()
    assert env.bulk({"ids": [shared]}, {"payer": {"mode": "own_share"}}).json()["changed"] == 1
    db.expire_all()
    splits = db.query(TransactionSplit).filter_by(transaction_id=shared).all()
    assert sum(s.amount for s in splits) == Decimal("100.00")
    assert env.row(shared).paid_by is None and env.row(shared).payer_mode == "own_share"

    fuel = env.add(
        "70.00",
        category_id=env.fuel,
        fuel_price_per_litre=Decimal("1.75"),
        fuel_litres=Decimal("40.000"),
    )
    body = env.bulk({"ids": [fuel]}, {"category_id": env.groceries}).json()
    assert codes(body) == {fuel: "fuel_data"} and env.row(fuel).category_id == env.fuel


def test_r20_r21_dry_run_writes_nothing_and_suggestions_stay(env, db):  # noqa: F811
    pay = env.add("38.90")
    occ = BillOccurrence(bill_id=env.cosmote, due_date=env.today, status=OccurrenceStatus.unpaid)
    db.add(occ)
    db.flush()
    db.add(MatchSuggestion(household_id=env.hid, transaction_id=pay, occurrence_id=occ.id))
    db.commit()
    changes = {
        "bucket_id": env.bills,
        "category_id": env.utilities,
        "payer": {"mode": "single", "user_id": env.maria},
        "payment_method": "transfer",
    }

    def snapshot():
        t = env.row(pay)
        return (
            t.bucket_id,
            t.category_id,
            t.paid_by,
            t.payment_method,
            db.query(BulkBatch).count(),
            db.query(BulkBatchRow).count(),
            db.query(MatchSuggestion).filter_by(dismissed=False).count(),
        )

    before = snapshot()
    preview = env.bulk({"ids": [pay]}, changes, dry_run=True).json()
    assert preview["dry_run"] is True and preview["batch_id"] is None and preview["changed"] == 1
    assert snapshot() == before

    assert env.bulk({"ids": [pay]}, changes).json()["changed"] == 1
    db.expire_all()
    suggestion = db.query(MatchSuggestion).one()
    assert suggestion.dismissed is False and suggestion.transaction_id == pay
    assert db.get(BillOccurrence, occ.id).transaction_id is None
    assert env.row(pay).recurring_bill_id is None


def test_limits_shape_and_auth(env, db):  # noqa: F811
    a = env.add()
    too_many = [f"id-{i}" for i in range(1001)]
    assert env.bulk({"ids": too_many}, {"bucket_id": env.bills}).status_code == 400
    assert env.bulk({"ids": [a]}, {}).status_code == 400
    two_keys = {"ids": [a], "bill_id": env.cosmote}
    assert env.bulk(two_keys, {"bucket_id": env.bills}).status_code == 422
    assert env.bulk({}, {"bucket_id": env.bills}).status_code == 422
    assert env.bulk({"ids": [a]}, {"payer": None}).status_code == 400
    assert env.bulk({"ids": [a]}, {"payment_method": "cheque"}).status_code == 400
    # A fresh client: no Bearer token and no cookies from the API login.
    anonymous = TestClient(env.client.app)
    assert anonymous.post(URL, json={"select": {"ids": [a]}, "changes": {}}).status_code == 401


def test_expected_count_mismatch_is_409_with_no_writes(env, db):  # noqa: F811
    pay = env.add("38.90", bucket_id=env.bills, recurring_bill_id=env.cosmote)
    r = env.bulk({"bill_id": env.cosmote}, {"bucket_id": env.day}, expected_count=2)
    assert r.status_code == 409
    assert r.json()["detail"] == "The selection changed: 1 now match. Preview again."
    assert env.row(pay).bucket_id == env.bills and db.query(BulkBatch).count() == 0


def test_unchanged_rows_are_not_stored_and_zero_changes_make_no_batch(env, db):  # noqa: F811
    a, b = env.add(), env.add(bucket_id=env.bills)
    body = env.bulk({"ids": [a, b]}, {"bucket_id": env.bills}).json()
    assert body["changed"] == 1 and body["unchanged"] == 1 and body["undo_until"]
    batch = db.query(BulkBatch).one()
    assert body["batch_id"] == batch.id and batch.row_count == 1 and batch.fields == "bucket"
    assert db.query(BulkBatchRow).count() == 1
    again = env.bulk({"ids": [a, b]}, {"bucket_id": env.bills}).json()
    assert again["changed"] == 0 and again["batch_id"] is None
    assert db.query(BulkBatch).count() == 1


def test_totals_and_budget_effect_use_base_currency(env, db):  # noqa: F811
    usd = env.add("100.00", currency="USD", exchange_rate=Decimal("0.9"))
    eur = env.add("10.00")
    inc = env.add("50.00", type=TransactionType.income, bucket_id=None)
    body = env.bulk({"ids": [usd, eur, inc]}, {"bucket_id": env.bills}, dry_run=True).json()
    assert body["total_out"] == pytest.approx(100.00)  # 90 + 10, base currency
    assert body["total_in"] == pytest.approx(50.00)
    bills = next(e for e in body["buckets"] if e["bucket_id"] == env.bills)
    assert bills["moved_in"] == pytest.approx(100.00)
    assert bills["spent_after"] - bills["spent_before"] == pytest.approx(100.00)
    assert bills["budget"] == pytest.approx(300.00)


def test_no_bucket_effect_is_fixed_costs_this_month(env, db):  # noqa: F811
    fixed = env.add("38.90", bucket_id=None, recurring_bill_id=env.cosmote)
    body = env.bulk({"ids": [fixed]}, {"bucket_id": env.bills}, dry_run=True).json()
    none = next(e for e in body["buckets"] if e["bucket_id"] is None)
    assert none["name"] == NO_BUCKET_NAME and none["budget"] is None
    assert none["spent_before"] == pytest.approx(38.90) and none["spent_after"] == pytest.approx(0)
