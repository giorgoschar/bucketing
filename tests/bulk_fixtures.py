"""Shared seed for the bulk tests (2c spec §9): one household with two
members, monthly, event, archived and no-income buckets, a Fuel category,
an out item (Cosmote, in Bills) and an in item (Salary).

Import both names in a test module: ``from tests.bulk_fixtures import env``
and ``from tests.test_api import api``, each with ``# noqa: F401``.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.clock import local_today
from app.models import (
    FUEL_SYSTEM_KEY,
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    HouseholdMember,
    ItemDirection,
    MemberRole,
    RecurringBill,
    Transaction,
    TransactionType,
    User,
)

URL = "/api/v1/transactions/bulk"


@pytest.fixture()
def env(client, api, db):
    headers, hh = api
    hid, today = hh.household_id, local_today()

    maria = User(
        username="maria",
        display_name="Maria",
        email="maria@example.com",
        password_hash="x",
        session_version=0,
    )
    db.add(maria)
    db.flush()
    db.add(HouseholdMember(household_id=hid, user_id=maria.id, role=MemberRole.member))

    day = db.get(Bucket, hh.bucket_id)
    day.name, day.budget = "Day to day", Decimal("1000")
    bills = Bucket(household_id=hid, name="Bills", budget=Decimal("300"))
    box = Bucket(household_id=hid, name="Cash box", show_income=False)
    old = Bucket(household_id=hid, name="Old", status=BucketStatus.archived)
    trip = Bucket(
        household_id=hid,
        name="Crete",
        type=BucketType.trip,
        budget=Decimal("900"),
        start_date=today - timedelta(days=10),
        end_date=today + timedelta(days=10),
    )
    groceries = Category(household_id=hid, name="Groceries")
    utilities = Category(household_id=hid, name="Utilities")
    fuel = Category(household_id=hid, name="Fuel", system_key=FUEL_SYSTEM_KEY)
    db.add_all([bills, box, old, trip, groceries, utilities, fuel])
    db.flush()
    cosmote = RecurringBill(
        household_id=hid,
        bucket_id=bills.id,
        name="Cosmote",
        amount=Decimal("38.90"),
        currency="EUR",
        start_date=today - timedelta(days=90),
        is_active=True,
    )
    salary = RecurringBill(
        household_id=hid,
        name="Salary",
        direction=ItemDirection.in_.value,
        amount=Decimal("1500"),
        currency="EUR",
        start_date=today - timedelta(days=90),
        is_active=True,
    )
    db.add_all([cosmote, salary])
    db.commit()

    def add(amount="10.00", *, days_ago=0, **kw) -> str:
        fields = dict(
            household_id=hid,
            amount=Decimal(amount),
            currency="EUR",
            exchange_rate=Decimal("1"),
            type=TransactionType.expense,
            bucket_id=day.id,
            paid_by=hh.user_id,
            payer_mode="single",
            payment_method="card",
            transaction_date=today - timedelta(days=days_ago),
        )
        fields.update(kw)
        t = Transaction(**fields)
        db.add(t)
        db.commit()
        return t.id

    def bulk(select, changes, *, dry_run=False, **extra):
        body = {"select": select, "changes": changes, "dry_run": dry_run, **extra}
        return client.post(URL, headers=headers, json=body)

    def row(txn_id) -> Transaction:
        db.expire_all()
        return db.get(Transaction, txn_id)

    return SimpleNamespace(
        client=client,
        headers=headers,
        hh=hh,
        hid=hid,
        today=today,
        me=hh.user_id,
        maria=maria.id,
        day=day.id,
        bills=bills.id,
        box=box.id,
        old=old.id,
        trip=trip.id,
        groceries=groceries.id,
        utilities=utilities.id,
        fuel=fuel.id,
        cosmote=cosmote.id,
        salary=salary.id,
        add=add,
        bulk=bulk,
        row=row,
    )
