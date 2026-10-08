"""Polish S6: save first, then ask. The ingest response says whether the
purchase still needs a category (with the names to choose from), and
``POST /ingest/apple-pay/{id}/classify`` lets the same token set the category
and bucket of a purchase it has just added."""

from datetime import timedelta

import pytest

from app.core.clock import utcnow_naive
from app.models import (
    Bucket,
    BucketStatus,
    BucketType,
    Category,
    CategoryRule,
    IngestAttempt,
    Transaction,
)
from tests.test_ingest import URL, _post, ingest  # noqa: F401  (fixture)
from tests.test_ingest_attempts import _member_with_token

PINNED = {
    "id",
    "amount",
    "currency",
    "category",
    "category_id",
    "bucket",
    "bucket_id",
    "transaction_date",
}


@pytest.fixture()
def home(db, ingest):  # noqa: F811
    """The ingest household with two more categories and two more buckets."""
    hh = ingest.hh.household_id
    ingest.cafe = Category(household_id=hh, name="Café & Bars")
    ingest.default = Category(household_id=hh, name="Zebra", is_default=True)
    ingest.trip = Bucket(household_id=hh, name="Trip", type=BucketType.trip)
    ingest.old = Bucket(household_id=hh, name="Old", status=BucketStatus.archived)
    db.add_all([ingest.cafe, ingest.default, ingest.trip, ingest.old])
    db.commit()
    return ingest


def _classify(client, who, txn_id, **body):
    return client.post(f"{URL}/{txn_id}/classify", json=body, headers=who.headers)


def _new(client, who, merchant="Corner Kiosk", **body):
    r = _post(client, who, merchant=merchant, **body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- the ingest response


def test_a_rule_match_needs_no_category(client, db, home):
    body = _new(client, home, merchant="Sklavenitis")
    assert PINNED <= set(body)
    assert body["needs_category"] is False and body["category"] == "Groceries"
    assert "categories" not in body and "category_names" not in body
    main = db.get(Bucket, home.hh.bucket_id)
    assert body["buckets"] == [
        {"id": main.id, "name": main.name},
        {"id": home.trip.id, "name": "Trip"},
    ]
    assert body["bucket_names"] == [main.name, "Trip"]


def test_no_match_lists_the_categories_and_buckets(client, db, home):
    body = _new(client, home)
    assert PINNED <= set(body)
    assert body["needs_category"] is True and body["category_id"] is None
    # The app picker's order: defaults first, then by name.
    assert body["categories"] == [
        {"id": home.default.id, "name": "Zebra"},
        {"id": home.cafe.id, "name": "Café & Bars"},
        {"id": home.category.id, "name": "Groceries"},
    ]
    assert body["category_names"] == ["Zebra", "Café & Bars", "Groceries"]
    assert [b["name"] for b in body["buckets"]] == ["Test Household Bucket", "Trip"]  # no archived


def test_the_chosen_bucket_comes_first(client, db, home):
    home.token.default_bucket_id = home.trip.id
    db.commit()
    body = _new(client, home)
    assert body["bucket"] == "Trip"
    assert body["bucket_names"] == ["Trip", "Test Household Bucket"]


def test_a_duplicate_reflects_the_existing_transaction(client, db, home):
    at = "2026-10-01T12:34:00+03:00"
    first = _new(client, home, occurred_at=at)
    again = _post(client, home, merchant="Corner Kiosk", occurred_at=at)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert again.json()["needs_category"] is True and again.json()["category_names"]
    db.get(Transaction, first["id"]).category_id = home.cafe.id
    db.commit()
    again = _post(client, home, merchant="Corner Kiosk", occurred_at=at).json()
    assert again["needs_category"] is False and "categories" not in again
    assert again["category"] == "Café & Bars"


# ---------------------------------------------------------------- classify


def test_classify_by_name(client, db, home):
    made = _new(client, home)
    r = _classify(client, home, made["id"], category="  café & BARS ", bucket="trip")
    assert r.status_code == 200, r.text
    body = r.json()
    assert PINNED <= set(body) and body["id"] == made["id"]
    assert (body["category"], body["category_id"]) == ("Café & Bars", home.cafe.id)
    assert (body["bucket"], body["bucket_id"]) == ("Trip", home.trip.id)
    assert body["needs_category"] is False and "categories" not in body
    assert body["bucket_names"][0] == "Trip"
    t = db.get(Transaction, made["id"])
    db.refresh(t)
    assert (t.category_id, t.bucket_id) == (home.cafe.id, home.trip.id)
    assert t.amount == made["amount"] and t.merchant == "Corner Kiosk"
    assert t.paid_by == home.hh.user_id and t.payment_method == "apple_pay"


def test_classify_by_id_and_one_field_at_a_time(client, db, home):
    made = _new(client, home, card="Visa")
    r = _classify(client, home, made["id"], category=home.cafe.id)
    assert r.status_code == 200, r.text
    assert r.json()["category_id"] == home.cafe.id
    assert r.json()["bucket_id"] == home.hh.bucket_id  # untouched
    r = _classify(client, home, made["id"], bucket=home.trip.id)
    assert r.status_code == 200, r.text
    assert (r.json()["category_id"], r.json()["bucket_id"]) == (home.cafe.id, home.trip.id)
    t = db.get(Transaction, made["id"])
    db.refresh(t)
    assert t.notes == "Apple Pay · Visa"


def test_only_a_bucket_still_needs_a_category(client, db, home):
    made = _new(client, home)
    r = _classify(client, home, made["id"], bucket="Trip")
    assert r.status_code == 200
    assert r.json()["needs_category"] is True and r.json()["category_names"]


def test_list_shaped_choices_are_accepted(client, db, home):
    made = _new(client, home)
    r = _classify(client, home, made["id"], category=["Groceries"], remember=True)
    assert r.status_code == 200 and r.json()["category"] == "Groceries"


@pytest.mark.parametrize(
    "body,detail",
    [
        ({"category": "Nope"}, "Unknown category 'Nope'"),
        ({"bucket": "Nope"}, "Unknown bucket 'Nope'"),
        ({"bucket": "Old"}, "Unknown bucket 'Old'"),  # archived
        ({"category": "Groceries", "bucket": "Nope"}, "Unknown bucket 'Nope'"),
        ({"category": "x\ny" + "z" * 100}, "Unknown category 'xy" + "z" * 38 + "'"),
    ],
)
def test_an_unknown_name_is_422_and_changes_nothing(client, db, home, body, detail):
    made = _new(client, home)
    r = _classify(client, home, made["id"], **body)
    assert r.status_code == 422, r.text
    assert r.json() == {"detail": detail}
    t = db.get(Transaction, made["id"])
    db.refresh(t)
    assert (t.category_id, t.bucket_id) == (None, home.hh.bucket_id)


@pytest.mark.parametrize("body", [{}, {"remember": True}, {"category": "", "bucket": "  "}])
def test_category_or_bucket_is_required(client, db, home, body):
    made = _new(client, home)
    r = _classify(client, home, made["id"], **body)
    assert r.status_code == 422


def test_a_body_that_is_not_an_object_is_422(client, db, home):
    made = _new(client, home)
    r = client.post(
        f"{URL}/{made['id']}/classify",
        content=b"[1]",
        headers={**home.headers, "Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_another_households_category_or_bucket_is_unknown(client, db, home, make_household):
    other = make_household(name="Other", username="outsider")
    theirs = Category(household_id=other.household_id, name="Secret")
    db.add(theirs)
    db.commit()
    made = _new(client, home)
    for body in ({"category": theirs.id}, {"category": "Secret"}, {"bucket": other.bucket_id}):
        r = _classify(client, home, made["id"], **body)
        assert r.status_code == 422 and "Unknown" in r.json()["detail"]


# ---------------------------------------------------------------- who may classify what

NOT_FOUND = {"detail": "Not found"}


def test_another_tokens_transaction_is_404(client, db, home):
    from app.services import issue_personal_token

    bob = _member_with_token(db, home.hh, "bob")
    _record, raw = issue_personal_token(
        db, user_id=home.hh.user_id, household_id=home.hh.household_id, name="iPad"
    )
    db.commit()
    made = _new(client, home)
    r = _classify(client, bob, made["id"], category="Groceries")  # another member's token
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    r = client.post(  # my own other token
        f"{URL}/{made['id']}/classify",
        json={"category": "Groceries"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    assert db.get(Transaction, made["id"]).category_id is None


def test_another_households_transaction_is_404(client, db, home, make_household):
    from types import SimpleNamespace

    from app.services import issue_personal_token

    other = make_household(name="Other", username="outsider")
    _record, raw = issue_personal_token(
        db, user_id=other.user_id, household_id=other.household_id, name="Theirs"
    )
    db.commit()
    stranger = SimpleNamespace(headers={"Authorization": f"Bearer {raw}"})
    made = _new(client, home)
    r = _classify(client, stranger, made["id"], category="Groceries")
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_a_transaction_the_token_did_not_ingest_is_404(client, db, home):
    from decimal import Decimal

    t = Transaction(
        household_id=home.hh.household_id,
        bucket_id=home.hh.bucket_id,
        amount=Decimal("5"),
        paid_by=home.hh.user_id,
        payment_method="apple_pay",
        merchant="Typed by hand",
    )
    db.add(t)
    db.commit()
    r = _classify(client, home, t.id, category="Groceries")
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    assert _classify(client, home, "no-such-id", category="Groceries").json() == NOT_FOUND


def test_older_than_15_minutes_is_404(client, db, home):
    made = _new(client, home)
    t = db.get(Transaction, made["id"])
    t.created_at = utcnow_naive() - timedelta(minutes=14)
    db.commit()
    assert _classify(client, home, made["id"], category="Groceries").status_code == 200
    t.created_at = utcnow_naive() - timedelta(minutes=16)
    db.commit()
    r = _classify(client, home, made["id"], category="Café & Bars")
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    db.refresh(t)
    assert t.category_id == home.category.id


def test_a_deleted_transaction_is_404(client, db, home):
    made = _new(client, home)
    db.get(Transaction, made["id"]).deleted_at = utcnow_naive()
    db.commit()
    r = _classify(client, home, made["id"], category="Groceries")
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_classify_needs_an_ingest_token(client, db, home):
    from app.api_auth import create_access_token

    made = _new(client, home)
    url = f"{URL}/{made['id']}/classify"
    assert client.post(url, json={"category": "Groceries"}).status_code == 401
    jwt = create_access_token(home.hh.user_id, home.hh.household_id, 0)
    r = client.post(url, json={"category": "Groceries"}, headers={"Authorization": f"Bearer {jwt}"})
    assert r.status_code == 401


# ---------------------------------------------------------------- remember


def _rules(db, home):
    return db.query(CategoryRule).filter_by(household_id=home.hh.household_id).all()


def test_remember_creates_the_rule_once_and_the_next_purchase_matches(client, db, home):
    made = _new(client, home)
    assert len(_rules(db, home)) == 1  # the fixture's Sklavenitis rule
    r = _classify(client, home, made["id"], category="Café & Bars", remember=True)
    assert r.status_code == 200, r.text
    rules = {r.pattern: r.category_id for r in _rules(db, home)}
    assert rules["corner kiosk"] == home.cafe.id and len(rules) == 2
    again = _classify(client, home, made["id"], category="Café & Bars", remember=True)
    assert again.status_code == 200 and len(_rules(db, home)) == 2

    nxt = _new(client, home, amount="3")
    assert nxt["needs_category"] is False and nxt["category"] == "Café & Bars"
    assert "categories" not in nxt


def test_without_remember_no_rule_is_made(client, db, home):
    made = _new(client, home)
    assert _classify(client, home, made["id"], category="Café & Bars").status_code == 200
    assert _classify(client, home, made["id"], bucket="Trip", remember=True).status_code == 200
    assert len(_rules(db, home)) == 1
    assert _new(client, home, amount="3")["needs_category"] is True


# ---------------------------------------------------------------- the edit path


def test_a_fixed_cost_stays_without_a_bucket(client, db, home, make_bill):
    """The edit goes through update_transaction: a Fixed cost (paid for a
    recurring item, no bucket) keeps its place. (Nothing else can be
    without a bucket at all: the table's own check constraint forbids it.)"""
    made = _new(client, home)
    bill, _occ = make_bill(home.hh.household_id, occurrence=False)
    t = db.get(Transaction, made["id"])
    t.recurring_bill_id, t.bucket_id = bill.id, None
    db.commit()
    r = _classify(client, home, made["id"], category="Groceries")
    assert r.status_code == 200, r.text
    assert (r.json()["bucket"], r.json()["bucket_id"]) == (None, None)
    db.refresh(t)
    assert (t.bucket_id, t.recurring_bill_id, t.category_id) == (None, bill.id, home.category.id)


def test_classify_keeps_splits(client, db, home):
    from decimal import Decimal

    from app.models import TransactionSplit

    bob = _member_with_token(db, home.hh, "bob")
    made = _new(client, home)
    db.add(TransactionSplit(transaction_id=made["id"], user_id=bob.user_id, amount=Decimal("5")))
    db.commit()
    assert _classify(client, home, made["id"], category="Groceries").status_code == 200
    [split] = db.query(TransactionSplit).filter_by(transaction_id=made["id"]).all()
    assert (split.user_id, split.amount) == (bob.user_id, Decimal("5"))


# ---------------------------------------------------------------- log and limits


def test_classify_attempts_are_logged(client, db, home, caplog):
    import logging

    made = _new(client, home)
    with caplog.at_level(logging.WARNING):
        assert _classify(client, home, made["id"], category="Nope\nINFO forged").status_code == 422
        assert _classify(client, home, "missing", category="Groceries").status_code == 404
    assert _classify(client, home, made["id"], category="Groceries").status_code == 200
    rows = (
        db.query(IngestAttempt)
        .order_by(IngestAttempt.created_at.desc(), IngestAttempt.id.desc())
        .all()
    )
    assert [(r.status_code, r.outcome) for r in rows] == [
        (200, "classified"),
        (404, "rejected"),
        (422, "rejected"),
        (201, "created"),
    ]
    done, missing, unknown, _made = rows
    assert done.transaction_id == made["id"] and done.merchant == "Corner Kiosk"
    assert unknown.reason == "Unknown category 'NopeINFO forged'" and missing.reason == "Not found"
    for row in rows:
        assert (row.household_id, row.user_id, row.token_id) == (
            home.hh.household_id,
            home.hh.user_id,
            home.token.id,
        )
    lines = [r.getMessage() for r in caplog.records if "rejected" in r.getMessage()]
    assert len(lines) == 2 and all("\n" not in ln for ln in lines)
    assert home.raw not in caplog.text


def test_classify_is_rate_limited_per_token(client, db, home):
    made = _new(client, home)
    for i in range(60):
        r = _classify(client, home, made["id"], category="Groceries")
        assert r.status_code == 200, (i, r.text)  # the 50-row cut keeps the marker
    assert _classify(client, home, made["id"], category="Groceries").status_code == 429
    mine = db.query(IngestAttempt).filter_by(user_id=home.hh.user_id).count()
    assert mine == 51  # the 50 newest and the purchase's own row


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/transactions",
        "/api/v1/settings/categories",
        "/api/v1/buckets",
        "/api/v1/ingest/attempts",
        "/api/v1/settings/category-rules",
    ],
)
def test_the_token_still_reads_nothing_else(client, db, home, path):
    assert client.get(path, headers=home.headers).status_code == 401


def test_the_guide_explains_asking_for_a_category(client, authed):
    page = client.get("/settings/automations", headers=authed.headers)
    assert page.status_code == 200
    for text in (
        "Ask for a category",
        "category_names",
        "/classify",
        "remember",
        "Choose from List",
    ):
        assert text in page.text, text
