"""2d §7.2: one category over the period, six months, its shops and rules."""

from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from app.core.clock import local_today
from app.models import Category, CategoryRule, Transaction, TransactionSplit, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

URL = "/api/v1/insights/categories"


def _cat(db, household_id, name="Groceries"):
    c = Category(household_id=household_id, name=name, icon="🛒", color="#10b981")
    db.add(c)
    db.commit()
    return c


def _spend(db, hh, amount, *, cat_id, merchant=None, when=None, splits=None, paid_by=None):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=Decimal(amount),
        currency="EUR",
        type=TransactionType.expense,
        paid_by=paid_by or hh.user_id,
        category_id=cat_id,
        merchant=merchant,
        transaction_date=when or local_today(),
    )
    db.add(t)
    db.flush()
    for uid, share in (splits or {}).items():
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=Decimal(share)))
    db.commit()
    return t


def test_detail_has_merchants_months_recent_and_rules(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh.household_id)
    today = local_today()
    for merchant, amount in (
        ("Sklavenitis", "40"),
        ("Sklavenitis", "20"),
        ("Lidl", "30"),
        (None, "5"),
        ("AB", "4"),
        ("My market", "3"),
        ("Kiosk", "2"),
    ):
        _spend(db, hh, amount, cat_id=cat.id, merchant=merchant, when=today)
    _spend(
        db,
        hh,
        "90",
        cat_id=cat.id,
        merchant="Lidl",
        when=today.replace(day=1) - relativedelta(months=1),
    )
    db.add(
        CategoryRule(
            household_id=hh.household_id, pattern="sklavenitis", category_id=cat.id, match_count=48
        )
    )
    db.commit()

    r = client.get(f"{URL}/{cat.id}", headers=headers, params={"preset": "this_month"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"] == {"id": cat.id, "name": "Groceries", "icon": "🛒", "color": "#10b981"}
    assert (body["total"], body["count"]) == (104.0, 7)
    assert [m["merchant"] for m in body["merchants"]] == [
        "Sklavenitis",
        "Lidl",
        "Other",
        "AB",
        "My market",
    ]
    assert body["merchants"][0] == {"merchant": "Sklavenitis", "count": 2, "total": 60.0}
    assert len(body["months"]) == 6
    assert (body["months"][-1]["month"], body["months"][-1]["total"]) == (today.month, 104.0)
    assert body["months"][-2]["total"] == 90.0
    # Five complete months: 90 and four zeros.
    assert body["avg_per_month"] == 18.0
    assert len(body["recent"]) == 7 and set(body["recent"][0]) == {
        "id",
        "date",
        "merchant",
        "notes",
        "amount",
        "paid_by",
    }
    assert body["rules"] == [
        {"id": body["rules"][0]["id"], "pattern": "sklavenitis", "match_count": 48}
    ]


def test_recent_is_the_latest_ten(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh.household_id)
    first = local_today().replace(day=1)
    for i in range(12):
        _spend(db, hh, "1", cat_id=cat.id, when=first, merchant=f"M{i}")
    body = client.get(f"{URL}/{cat.id}", headers=headers).json()
    assert len(body["recent"]) == 10


def test_uncategorised_works_and_has_no_rules(client, db, api):  # noqa: F811
    headers, hh = api
    _spend(db, hh, "12", cat_id=None, merchant="Kiosk")
    body = client.get(f"{URL}/uncategorised", headers=headers).json()
    assert body["category"] is None and body["total"] == 12.0 and body["rules"] == []


def test_lens_counts_the_members_share(client, db, api):  # noqa: F811
    headers, hh = api
    maria, _ = _add_member_user(db, hh.household_id, "maria")
    cat = _cat(db, hh.household_id)
    _spend(db, hh, "100", cat_id=cat.id, merchant="Lidl", splits={hh.user_id: "60", maria.id: "40"})
    body = client.get(f"{URL}/{cat.id}", headers=headers, params={"paid_by": maria.id}).json()
    assert body["total"] == 40.0 and body["merchants"][0]["total"] == 40.0
    assert body["recent"][0]["amount"] == 40.0


def test_foreign_or_unknown_category_and_member_are_404(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    theirs = _cat(db, other.household_id)
    assert client.get(f"{URL}/{theirs.id}", headers=headers).status_code == 404
    assert client.get(f"{URL}/nope", headers=headers).status_code == 404
    mine = _cat(db, hh.household_id, "Mine")
    r = client.get(f"{URL}/{mine.id}", headers=headers, params={"paid_by": other.user_id})
    assert r.status_code == 404


def test_months_end_at_the_period_end(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh.household_id)
    body = client.get(f"{URL}/{cat.id}", headers=headers, params={"preset": "last_month"}).json()
    last = local_today().replace(day=1) - timedelta(days=1)
    assert (body["months"][-1]["year"], body["months"][-1]["month"]) == (last.year, last.month)
    assert body["avg_per_month"] == 0.0 and body["total"] == 0.0
