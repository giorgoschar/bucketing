"""Phase C S2 (spec §4.1, §7 "Search"; Review Focus 5, server side)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.core.clock import utcnow_naive
from app.models import Category, RecurringBill, Transaction, TransactionType
from app.services import stock as stock_svc
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/search"


def _get(client, headers, q):
    return client.get(URL, params={"q": q}, headers=headers)


def _txn(db, hh, day=date(2026, 10, 5), **kw):
    kw.setdefault("amount", Decimal("29.90"))
    kw.setdefault("type", TransactionType.expense)
    kw.setdefault("bucket_id", hh.bucket_id)
    t = Transaction(household_id=hh.household_id, paid_by=hh.user_id, transaction_date=day, **kw)
    db.add(t)
    db.commit()
    return t


def _bill(db, hh, name, **kw):
    b = RecurringBill(household_id=hh.household_id, name=name, start_date=date(2026, 1, 1), **kw)
    db.add(b)
    db.commit()
    return b


def _count(db, fn):
    statements = []

    def count(conn, cursor, statement, *a):
        statements.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        fn()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    return len(statements)


# ------------------------------------------------------------------ groups


def test_entries_match_like_activity_and_carry_the_documented_shape(client, db, api):  # noqa: F811
    headers, hh = api
    cat = Category(household_id=hh.household_id, name="Groceries")
    db.add(cat)
    db.commit()
    t = _txn(db, hh, merchant="Lidl", category_id=cat.id, currency="EUR")
    inc = _txn(db, hh, type=TransactionType.income, bucket_id=None, merchant="Lidl refund")
    r = _get(client, headers, "lidl")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"entries", "entries_more", "items", "pantry"}
    by_id = {e["id"]: e for e in body["entries"]}
    assert by_id[t.id] == {
        "id": t.id,
        "date": "2026-10-05",
        "label": "Lidl",
        "category": "Groceries",
        "amount": -29.9,
        "currency": "EUR",
    }
    assert by_id[inc.id]["amount"] == 29.9 and by_id[inc.id]["category"] is None
    # The same fields Activity's q matches: notes, category name, the amount.
    _txn(db, hh, notes="weekly shop at the market")
    assert len(_get(client, headers, "market").json()["entries"]) == 1
    assert len(_get(client, headers, "grocer").json()["entries"]) == 1
    assert len(_get(client, headers, "29.90").json()["entries"]) == 3


def test_entries_newest_first_at_most_five_and_more(client, db, api):  # noqa: F811
    headers, hh = api
    for n in range(7):
        _txn(db, hh, date(2026, 10, 1) + timedelta(days=n), merchant=f"Shop {n}")
    body = _get(client, headers, "shop").json()
    assert [e["label"] for e in body["entries"]] == [f"Shop {n}" for n in (6, 5, 4, 3, 2)]
    assert body["entries_more"] is True
    for n in (0, 1):  # exactly five left: no "more"
        db.query(Transaction).filter_by(merchant=f"Shop {n}").delete()
    db.commit()
    body = _get(client, headers, "shop").json()
    assert len(body["entries"]) == 5 and body["entries_more"] is False


def test_soft_deleted_entries_never_match(client, db, api):  # noqa: F811
    headers, hh = api
    t = _txn(db, hh, merchant="Lidl")
    t.deleted_at = utcnow_naive()
    db.commit()
    assert _get(client, headers, "lidl").json()["entries"] == []


def test_items_match_by_name_active_first_at_most_five(client, db, api):  # noqa: F811
    headers, hh = api
    _bill(db, hh, "Nova internet", direction="out", is_active=False)
    for n in range(5):
        _bill(db, hh, f"Nova line {n}", direction="in" if n == 0 else "out")
    _bill(db, hh, "Rent")
    body = _get(client, headers, "NOVA").json()
    names = [i["name"] for i in body["items"]]
    assert names == [f"Nova line {n}" for n in range(5)]  # the paused one is the sixth
    assert body["items"][0] == {
        "id": body["items"][0]["id"],
        "name": "Nova line 0",
        "direction": "in",
        "is_active": True,
    }
    db.query(RecurringBill).filter(RecurringBill.name == "Nova line 4").delete()
    db.commit()
    items = _get(client, headers, "nova").json()["items"]
    assert items[-1] == {**items[-1], "name": "Nova internet", "is_active": False}


def test_pantry_matches_name_brand_and_exact_barcode_and_skips_archived(
    client,
    db,
    api,  # noqa: F811
):
    headers, hh = api
    spag = stock_svc.add_product(
        db,
        hh.household_id,
        hh.user_id,
        name="Spaghetti n5",
        brand="Barilla",
        barcode="8076800195057",
        quantity=Decimal("3"),
    )
    gone = stock_svc.add_product(db, hh.household_id, hh.user_id, name="Barilla penne")
    gone.product.archived_at = utcnow_naive()
    db.commit()
    by_name = _get(client, headers, "spagh").json()["pantry"]
    assert by_name == [{"id": spag.id, "name": "Spaghetti n5", "brand": "Barilla", "quantity": 3}]
    assert [p["id"] for p in _get(client, headers, "BARILLA").json()["pantry"]] == [spag.id]
    assert [p["id"] for p in _get(client, headers, "8076800195057").json()["pantry"]] == [spag.id]
    # A barcode is matched whole, never as a fragment.
    assert _get(client, headers, "80768001950").json()["pantry"] == []


def test_pantry_at_most_five(client, db, api):  # noqa: F811
    headers, hh = api
    for n in range(7):
        stock_svc.add_product(db, hh.household_id, hh.user_id, name=f"Rice {n}")
    db.commit()
    assert len(_get(client, headers, "rice").json()["pantry"]) == 5


# -------------------------------------------------------------- hostile q


@pytest.mark.parametrize("wild", ["%%", "__", "a%", "_x", "\\\\", "100%"])
def test_like_wildcards_are_literal_in_every_group(client, db, api, wild):  # noqa: F811
    headers, hh = api
    _txn(db, hh, merchant="Plain shop")
    _bill(db, hh, "Plain bill")
    stock_svc.add_product(db, hh.household_id, hh.user_id, name="Plain rice")
    db.commit()
    body = _get(client, headers, wild).json()
    assert body["entries"] == [] and body["items"] == [] and body["pantry"] == []
    # ...and a literal one is found.
    _txn(db, hh, merchant=f"Sale {wild} off")
    _bill(db, hh, f"Plan {wild}")
    stock_svc.add_product(db, hh.household_id, hh.user_id, name=f"Tin {wild}")
    db.commit()
    body = _get(client, headers, wild).json()
    assert len(body["entries"]) == 1 and len(body["items"]) == 1 and len(body["pantry"]) == 1


def test_greek_text_matches_case_insensitively(client, db, api):  # noqa: F811
    headers, hh = api
    _bill(db, hh, "Νερό ΕΥΔΑΠ")
    _txn(db, hh, merchant="Σκλαβενίτης")
    assert len(_get(client, headers, "Σκλαβ").json()["entries"]) == 1
    assert [i["name"] for i in _get(client, headers, "ΕΥΔΑΠ").json()["items"]] == ["Νερό ΕΥΔΑΠ"]
    if db.get_bind().dialect.name != "postgresql":
        return  # SQLite's LOWER/ILIKE folds ASCII only; production is PostgreSQL
    assert len(_get(client, headers, "σκλαβ").json()["entries"]) == 1
    assert [i["name"] for i in _get(client, headers, "νερό").json()["items"]] == ["Νερό ΕΥΔΑΠ"]


def test_length_limits(client, api):  # noqa: F811
    headers, _ = api
    for bad in ("", " ", "a", "  a  ", "x" * 101, " " + "x" * 101):
        assert _get(client, headers, bad).status_code == 400, repr(bad)
    assert client.get(URL, headers=headers).status_code == 400
    assert _get(client, headers, "ab").status_code == 200
    assert _get(client, headers, "  " + "x" * 100 + " ").status_code == 200
    assert _get(client, headers, "x" * 100).status_code == 200


def test_requires_auth(client):
    assert client.get(URL, params={"q": "lidl"}).status_code == 401


# ------------------------------------------------------ isolation, limits


def test_other_households_rows_never_appear(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(username="neighbour")
    _txn(db, other, merchant="Lidl")
    _bill(db, other, "Lidl card")
    stock_svc.add_product(
        db, other.household_id, other.user_id, name="Lidl pasta", barcode="5201234567890"
    )
    db.commit()
    for q in ("lidl", "5201234567890"):
        body = _get(client, headers, q).json()
        assert body == {"entries": [], "entries_more": False, "items": [], "pantry": []}


def test_the_rate_limit_is_60_a_minute_per_user(client, api, make_household):  # noqa: F811
    headers, _ = api
    for _ in range(60):
        assert _get(client, headers, "lidl").status_code == 200
    r = _get(client, headers, "lidl")
    assert r.status_code == 429 and "searches" in r.json()["detail"].lower()

    import pyotp

    from tests.test_api import PASSWORD

    other = make_household(username="neighbour")
    pending = client.post(
        "/api/v1/auth/login", json={"username": other.username, "password": PASSWORD}
    ).json()["pending_token"]
    token = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": pending, "code": pyotp.TOTP(other.secret).now()},
    ).json()["access_token"]
    assert _get(client, {"Authorization": f"Bearer {token}"}, "lidl").status_code == 200


def test_unauthenticated_requests_do_not_spend_the_limit(client, api):  # noqa: F811
    headers, _ = api
    for _ in range(70):
        assert client.get(URL, params={"q": "lidl"}).status_code == 401
    assert _get(client, headers, "lidl").status_code == 200


def test_query_count_is_bounded(client, db, api):  # noqa: F811
    """At most 4 queries beyond authentication, however many rows match."""
    headers, hh = api
    auth_only = _count(db, lambda: _get(client, headers, "x"))  # 400 before any search
    empty = _count(db, lambda: _get(client, headers, "shop"))
    for n in range(8):
        _txn(db, hh, merchant=f"Shop {n}")
        _bill(db, hh, f"Shop bill {n}")
        stock_svc.add_product(db, hh.household_id, hh.user_id, name=f"Shop item {n}")
    db.commit()
    full = _count(db, lambda: _get(client, headers, "shop"))
    assert full == empty
    assert full - auth_only <= 4
