"""Per-row bulk rules (2c spec §5.4) on unsaved rows: no database needed.

Rows that can't take every requested change are skipped whole; rows that
already hold the targets are unchanged."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.models import PayerMode, Transaction, TransactionSplit, TransactionType
from app.services.bulk_rules import (
    BILL_KEEPS_BUCKET,
    Changes,
    Payer,
    RowContext,
    RowPlan,
    Skip,
    plan_row,
)

ME, MARIA = "user-me", "user-maria"
FUEL, GROCERIES = "cat-fuel", "cat-groceries"


def txn(**kw) -> Transaction:
    splits = kw.pop("splits", [])
    fields = dict(
        id="t1",
        type=TransactionType.expense,
        bucket_id="day",
        category_id=GROCERIES,
        amount=Decimal("100.00"),
        paid_by=ME,
        payer_mode=PayerMode.single.value,
        payment_method="card",
        recurring_bill_id=None,
        fuel_litres=None,
        deleted_at=None,
    )
    fields.update(kw)
    t = Transaction(**fields)
    t.splits = [TransactionSplit(user_id=u, amount=Decimal(a)) for u, a in splits]
    return t


def ctx(takers=None, takes_income=True) -> RowContext:
    return RowContext(takers=takers or {}, fuel_category_id=FUEL, target_takes_income=takes_income)


def skipped(result) -> Skip:
    assert isinstance(result, Skip), result
    return result


def planned(result) -> RowPlan:
    assert isinstance(result, RowPlan), result
    return result


def test_changes_fields_lists_only_requested_keys():
    ch = Changes(has_bucket=True, bucket_id=None, payment_method="cash")
    assert ch.fields == ("bucket", "method")


def test_r02_deleted_row_is_skipped():
    r = plan_row(
        txn(deleted_at=datetime(2026, 10, 1)),  # noqa: DTZ001
        Changes(has_bucket=True, bucket_id="b"),
        ctx(),
    )
    assert skipped(r).code == "deleted"


def test_r04_income_into_a_bucket_without_income_tracking_is_skipped():
    income = txn(type=TransactionType.income, bucket_id=None)
    ch = Changes(has_bucket=True, bucket_id="box")
    assert skipped(plan_row(income, ch, ctx(takes_income=False))).code == "income_bucket"
    assert planned(plan_row(income, ch, ctx(takes_income=True))).bucket_id == "box"


def test_r04_income_already_in_the_bucket_is_unchanged_not_skipped():
    income = txn(type=TransactionType.income, bucket_id="box")
    r = plan_row(income, Changes(has_bucket=True, bucket_id="box"), ctx(takes_income=False))
    assert planned(r).changed is False


def test_r05_income_to_no_bucket_is_allowed():
    r = planned(
        plan_row(txn(type=TransactionType.income), Changes(has_bucket=True, bucket_id=None), ctx())
    )
    assert r.bucket_id is None and r.changed


@pytest.mark.parametrize("kind", [TransactionType.expense, TransactionType.transfer])
def test_r06_expense_or_transfer_to_no_bucket_needs_a_bucket(kind):
    r = skipped(plan_row(txn(type=kind), Changes(has_bucket=True, bucket_id=None), ctx()))
    assert r.code == "needs_bucket" and r.reason != BILL_KEEPS_BUCKET


def test_r06_bill_linked_transfer_with_a_bucket_needs_a_bucket():
    t = txn(type=TransactionType.transfer, recurring_bill_id="salary")
    r = skipped(plan_row(t, Changes(has_bucket=True, bucket_id=None), ctx()))
    assert r.code == "needs_bucket"


def test_r07_bucketed_bill_payment_to_no_bucket_keeps_its_bucket():
    t = txn(recurring_bill_id="cosmote", bucket_id="bills")
    r = skipped(plan_row(t, Changes(has_bucket=True, bucket_id=None), ctx()))
    assert r.code == "needs_bucket" and r.reason == BILL_KEEPS_BUCKET


def test_r07_bucketless_fixed_cost_stays_or_moves_into_a_monthly_bucket():
    fixed = txn(recurring_bill_id="cosmote", bucket_id=None)
    assert (
        planned(plan_row(fixed, Changes(has_bucket=True, bucket_id=None), ctx())).changed is False
    )
    moved = planned(plan_row(fixed, Changes(has_bucket=True, bucket_id="bills"), ctx()))
    assert moved.changed and moved.bucket_id == "bills"


def test_r13_payer_change_on_a_row_with_a_take_is_skipped():
    cash = txn(payment_method="cash", paid_by=ME)
    takers = {"t1": ME}
    to_maria = plan_row(cash, Changes(payer=Payer("single", MARIA)), ctx(takers))
    assert skipped(to_maria).code == "cash_take"
    own = plan_row(cash, Changes(payer=Payer("own_share")), ctx(takers))
    assert skipped(own).code == "cash_take"
    same = plan_row(cash, Changes(payer=Payer("single", ME)), ctx(takers))
    assert planned(same).changed is False


def test_r14_method_away_from_cash_with_a_take_is_skipped():
    cash = txn(payment_method="cash", paid_by=ME)
    r = plan_row(cash, Changes(payment_method="card"), ctx({"t1": ME}))
    assert skipped(r).code == "cash_take"
    assert planned(plan_row(cash, Changes(payment_method="card"), ctx())).payment_method == "card"


def test_r15_cash_needs_a_payer():
    nobody = txn(paid_by=None)
    assert (
        skipped(plan_row(nobody, Changes(payment_method="cash"), ctx())).code == "cash_needs_payer"
    )
    both = planned(
        plan_row(nobody, Changes(payment_method="cash", payer=Payer("single", MARIA)), ctx())
    )
    assert both.payment_method == "cash" and both.paid_by == MARIA


@pytest.mark.parametrize("kind", [TransactionType.income, TransactionType.transfer])
def test_r16_own_share_only_for_expenses(kind):
    r = plan_row(txn(type=kind), Changes(payer=Payer("own_share")), ctx())
    assert skipped(r).code == "own_share_type"


def test_r17_own_share_needs_covering_splits():
    bare = plan_row(txn(), Changes(payer=Payer("own_share")), ctx())
    assert skipped(bare).code == "no_split"
    short = plan_row(
        txn(splits=[(ME, "30"), (MARIA, "30")]), Changes(payer=Payer("own_share")), ctx()
    )
    assert skipped(short).code == "no_split"
    ok = planned(
        plan_row(
            txn(splits=[(ME, "33.33"), (MARIA, "66.66")]), Changes(payer=Payer("own_share")), ctx()
        )
    )
    assert ok.paid_by is None and ok.payer_mode == PayerMode.own_share.value and ok.absorb_cent


def test_r19_fuel_rows_with_litres_keep_the_fuel_category():
    fuel = txn(category_id=FUEL, fuel_litres=Decimal("40.000"))
    away = plan_row(fuel, Changes(has_category=True, category_id=GROCERIES), ctx())
    assert skipped(away).code == "fuel_data"
    into = planned(plan_row(txn(), Changes(has_category=True, category_id=FUEL), ctx()))
    assert into.category_id == FUEL and into.changed


def test_rows_are_skipped_whole_never_half_changed():
    # The bucket move alone would apply; the payer change can't, so nothing does.
    t = txn(payment_method="cash")
    r = plan_row(
        t,
        Changes(has_bucket=True, bucket_id="bills", payer=Payer("single", MARIA)),
        ctx({"t1": ME}),
    )
    assert skipped(r).code == "cash_take"


def test_row_already_holding_every_target_is_unchanged():
    r = planned(
        plan_row(txn(), Changes(has_bucket=True, bucket_id="day", payment_method="card"), ctx())
    )
    assert r.changed is False
