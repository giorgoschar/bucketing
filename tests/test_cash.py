"""Cash ledger: movements, the wallet summary, API and HTML basics.

The stash/wallet model itself is covered in tests/test_cash_stash.py.
"""
from datetime import date
from decimal import Decimal

from app.api_auth import create_access_token
from app.core.clock import local_today, utcnow_naive
from app.models import CashMovement, Transaction, TransactionType
from app.services import (
    add_movement,
    delete_movement,
    list_movements,
    stash_balance,
    wallet_summary,
)
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member

D = Decimal
JULY = (date(2026, 7, 1), date(2026, 7, 31))


def _cash_expense(db, hh, payer, amount, method="cash", day=date(2026, 7, 10)):
    t = Transaction(bucket_id=hh.bucket_id, household_id=hh.household_id, amount=amount,
                    currency="EUR", exchange_rate=1, type=TransactionType.expense,
                    paid_by=payer, payment_method=method, transaction_date=day)
    db.add(t)
    db.commit()
    return t


def _member_headers(db, hh, username="cashmember"):
    m = _add_member(db, hh.household_id, username)
    db.commit()
    return m, {"Authorization": f"Bearer {create_access_token(m.id, hh.household_id, m.session_version)}"}


# ---------------------------------------------------------------- service

def test_wallet_per_member(db, make_household):
    hh = make_household()
    m = _add_member(db, hh.household_id, "cashb")
    db.commit()
    add_movement(db, hh.household_id, hh.user_id, "take", D("200"), "EUR", date(2026, 7, 1), None, "ATM")
    add_movement(db, hh.household_id, hh.user_id, "put_back", D("50.25"), "EUR", date(2026, 7, 2))
    add_movement(db, hh.household_id, m.id, "take", D("40"), "EUR", date(2026, 7, 3))
    assert wallet_summary(db, hh.household_id, hh.user_id, *JULY)["not_yet_logged"] == D("149.75")
    assert wallet_summary(db, hh.household_id, m.id, *JULY)["not_yet_logged"] == D("40.00")
    assert stash_balance(db, hh.household_id, hh.user_id) == D("50.25")


def test_verification_cash_expense_reduces_not_yet_logged(db, make_household):
    """Take 200, 30 cash expense -> taken 200, logged 30, not yet logged 170;
    a card expense does not count."""
    hh = make_household()
    add_movement(db, hh.household_id, hh.user_id, "take", D("200"), "EUR", date(2026, 7, 1))
    _cash_expense(db, hh, hh.user_id, D("30"))
    _cash_expense(db, hh, hh.user_id, D("99"), method="card")  # not cash: ignored
    w = wallet_summary(db, hh.household_id, hh.user_id, *JULY, viewer_id=hh.user_id)
    assert (w["taken"], w["spent"], w["logged"], w["outs"], w["not_yet_logged"]) == (
        D("200.00"), D("200.00"), D("30.00"), D("0.00"), D("170.00"))


def test_summary_math_ranges_and_deleted(db, make_household):
    hh = make_household()
    add_movement(db, hh.household_id, hh.user_id, "take", D("300"), "EUR", date(2026, 7, 5))
    add_movement(db, hh.household_id, hh.user_id, "take", D("999"), "EUR", date(2026, 6, 5))
    add_movement(db, hh.household_id, hh.user_id, "out", D("20"), "EUR", date(2026, 7, 6))
    _cash_expense(db, hh, hh.user_id, D("60"))
    gone = _cash_expense(db, hh, hh.user_id, D("500"))
    gone.deleted_at = utcnow_naive()  # soft-deleted: excluded
    other = _add_member(db, hh.household_id, "cashc")
    db.commit()
    _cash_expense(db, hh, other.id, D("77"))  # someone else's: excluded
    w = wallet_summary(db, hh.household_id, hh.user_id, *JULY)
    assert w["taken"] == D("300.00")
    assert w["outs"] == D("20.00")
    assert w["logged"] == D("60.00")
    assert w["not_yet_logged"] == D("220.00")


def test_cash_expenses_use_base_amount(db, make_household):
    hh = make_household()
    t = _cash_expense(db, hh, hh.user_id, D("100"))
    t.currency, t.exchange_rate = "USD", D("0.5")
    db.commit()
    assert wallet_summary(db, hh.household_id, hh.user_id, *JULY)["logged"] == D("50.00")


def test_soft_delete_hides(db, make_household):
    hh = make_household()
    mv = add_movement(db, hh.household_id, hh.user_id, "stash_in", D("10"), "EUR", date(2026, 7, 1))
    assert len(list_movements(db, hh.household_id, hh.user_id)) == 1
    delete_movement(db, mv)
    assert list_movements(db, hh.household_id, hh.user_id) == []
    assert stash_balance(db, hh.household_id, hh.user_id) == D("0.00")
    assert db.get(CashMovement, mv.id).deleted_at is not None  # row kept


def test_list_filters(db, make_household):
    hh = make_household()
    add_movement(db, hh.household_id, hh.user_id, "take", D("1"), "EUR", date(2026, 7, 1))
    add_movement(db, hh.household_id, hh.user_id, "take", D("2"), "EUR", date(2026, 8, 1))
    hid, me = hh.household_id, hh.user_id
    assert len(list_movements(db, hid, me, start=date(2026, 7, 1), end=date(2026, 7, 31))) == 1
    assert len(list_movements(db, hid, me, limit=1)) == 1
    assert len(list_movements(db, hid, me, member_id=me)) == 2


def test_add_movement_rejects_unknown_kind(db, make_household):
    import pytest

    hh = make_household()
    with pytest.raises(ValueError):
        add_movement(db, hh.household_id, hh.user_id, "in", D("1"), "EUR", date(2026, 7, 1))


# -------------------------------------------------------------------- API

def test_api_add_list_summary_delete(client, db, api):  # noqa: F811
    headers, hh = api
    today = local_today()
    r = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "take", "amount": "200", "movement_date": today.isoformat(), "note": "ATM"})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert r.json()["user_id"] == hh.user_id and r.json()["currency"] == "EUR"
    assert r.json()["stash_owner_id"] is None and r.json()["transaction_id"] is None
    _cash_expense(db, hh, hh.user_id, D("30"), day=today)
    r = client.get("/api/v1/cash/movements", headers=headers)
    assert [m["id"] for m in r.json()["items"]] == [mid]
    assert r.json()["stash"] == 0.0
    r = client.get(f"/api/v1/cash/summary?month={today:%Y-%m}", headers=headers)
    assert r.status_code == 200, r.text
    me = r.json()["wallet"]
    assert (me["taken"], me["logged"], me["not_yet_logged"]) == (200.0, 30.0, 170.0)
    assert client.delete(f"/api/v1/cash/movements/{mid}", headers=headers).status_code == 204
    assert client.get("/api/v1/cash/movements", headers=headers).json()["items"] == []
    assert client.delete(f"/api/v1/cash/movements/{mid}", headers=headers).status_code == 404


def test_api_validation(client, db, api):  # noqa: F811
    headers, hh = api
    base = {"kind": "stash_in", "amount": "5", "movement_date": "2026-07-01"}
    for bad in ({"kind": "sideways"}, {"amount": "0"}, {"amount": "-3"}, {"amount": "abc"},
                {"currency": "USD"}, {"movement_date": "nope"}):
        r = client.post("/api/v1/cash/movements", headers=headers, json={**base, **bad})
        assert r.status_code in (400, 422), (bad, r.status_code)
    r = client.get("/api/v1/cash/summary?month=13-2026", headers=headers)
    assert r.status_code == 400
    assert db.query(CashMovement).count() == 0


def test_member_permissions(client, db, api):  # noqa: F811
    headers, hh = api  # owner
    member, mh = _member_headers(db, hh)
    owner_mv = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "take", "amount": "10", "movement_date": "2026-07-01"}).json()["id"]
    # A member cannot see or delete the owner's movement...
    assert client.delete(f"/api/v1/cash/movements/{owner_mv}", headers=mh).status_code == 404
    # ...nor the other way round: each member manages only their own.
    r = client.post("/api/v1/cash/movements", headers=mh, json={
        "kind": "take", "amount": "5", "movement_date": "2026-07-01"})
    assert r.status_code == 201 and r.json()["user_id"] == member.id
    own = r.json()["id"]
    assert client.delete(f"/api/v1/cash/movements/{own}", headers=headers).status_code == 404
    assert client.delete(f"/api/v1/cash/movements/{own}", headers=mh).status_code == 204
    # The wallet figures are household-visible.
    r = client.get(f"/api/v1/cash/summary?month=2026-07&member_id={hh.user_id}", headers=mh)
    assert r.json()["wallet"]["taken"] == 10.0 and r.json()["stash"] == 0.0


def test_other_household_isolated(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="cashother")
    mv = add_movement(db, other.household_id, other.user_id, "stash_in", D("9"), "EUR",
                      date(2026, 7, 1))
    assert client.delete(f"/api/v1/cash/movements/{mv.id}", headers=headers).status_code == 404
    r = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "take", "amount": "5", "movement_date": "2026-07-01",
        "stash_owner_id": other.user_id})
    assert r.status_code == 400
    r = client.get(f"/api/v1/cash/movements?member_id={other.user_id}", headers=headers)
    assert r.status_code in (400, 404)


# ------------------------------------------------------------------- HTML

def test_html_page_add_delete(client, db, authed):
    r = client.get("/cash")
    assert r.status_code == 200
    r = client.post("/cash/add", data={"kind": "take", "amount": "75.50", "source": "bank",
                                       "movement_date": "2026-07-01", "note": "walletfill"},
                    headers=authed.headers, follow_redirects=False)
    assert r.status_code in (200, 302)
    mv = db.query(CashMovement).one()
    assert mv.amount == D("75.50") and mv.user_id == authed.user_id and mv.currency == "EUR"
    page = client.get("/cash?month=2026-07")
    assert "75.50" in page.text and "walletfill" in page.text
    r = client.post(f"/cash/{mv.id}/delete", headers=authed.headers, follow_redirects=False)
    assert r.status_code in (200, 302)
    db.refresh(mv)
    assert mv.deleted_at is not None
    assert "walletfill" not in client.get("/cash?month=2026-07").text


def test_html_invalid_rejected(client, db, authed):
    r = client.post("/cash/add", data={"kind": "oops", "amount": "5", "movement_date": "2026-07-01"},
                    headers=authed.headers)
    assert r.status_code == 400
    r = client.post("/cash/add", data={"kind": "take", "amount": "-5", "movement_date": "2026-07-01"},
                    headers=authed.headers)
    assert r.status_code == 400
    r = client.post("/cash/add", data={"kind": "take", "amount": "5", "movement_date": "nope"},
                    headers=authed.headers)
    assert r.status_code == 400
    r = client.post("/cash/add", data={"kind": "take", "amount": "5", "note": "x" * 501},
                    headers=authed.headers)
    assert r.status_code == 400
    assert client.get("/cash?month=2026-13").status_code == 400
    assert db.query(CashMovement).count() == 0


def test_html_htmx_returns_list_partial(client, db, authed):
    h = {**authed.headers, "HX-Request": "true"}
    r = client.post("/cash/add", data={"kind": "stash_in", "amount": "12", "movement_date": "2026-07-01",
                                       "note": "partialnote", "month": "2026-07"}, headers=h)
    assert r.status_code == 200 and "partialnote" in r.text and "<html" not in r.text
    r = client.get("/cash?month=2026-07", headers={"HX-Request": "true", "HX-Target": "cash-list"})
    assert r.status_code == 200 and "<html" not in r.text


def test_me_page_links_and_shows_wallet(client, authed, db):
    add_movement(db, authed.household_id, authed.user_id, "take", D("200"), "EUR", local_today())
    r = client.get("/me")
    assert r.status_code == 200
    assert "/cash" in r.text and "not yet logged" in r.text.lower()
