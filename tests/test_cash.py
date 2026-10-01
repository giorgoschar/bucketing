"""Cash ledger (Phase 4, Task 4.2)."""
from datetime import date
from decimal import Decimal

from app.api_auth import create_access_token
from app.clock import local_today, utcnow_naive
from app.models import CashMovement, Transaction, TransactionType
from app.services import (
    add_movement,
    cash_comparison,
    delete_movement,
    list_movements,
    member_balances,
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

def test_balances_per_member(db, make_household):
    hh = make_household()
    m = _add_member(db, hh.household_id, "cashb")
    db.commit()
    add_movement(db, hh.household_id, hh.user_id, "in", D("200"), "EUR", date(2026, 7, 1), None, "ATM")
    add_movement(db, hh.household_id, hh.user_id, "out", D("50.25"), "EUR", date(2026, 7, 2), None, None)
    add_movement(db, hh.household_id, m.id, "in", D("40"), "EUR", date(2026, 7, 3), None, None)
    bal = member_balances(db, hh.household_id)
    assert bal[hh.user_id] == D("149.75")
    assert bal[m.id] == D("40.00")


def test_verification_cash_expense_does_not_change_wallet(db, make_household):
    """Plan verification 4: in 200, 30 cash expense -> withdrawn 200, cash exp 30, unaccounted 170."""
    hh = make_household()
    add_movement(db, hh.household_id, hh.user_id, "in", D("200"), "EUR", date(2026, 7, 1), None, None)
    before = member_balances(db, hh.household_id)[hh.user_id]
    _cash_expense(db, hh, hh.user_id, D("30"))
    _cash_expense(db, hh, hh.user_id, D("99"), method="card")  # not cash: ignored
    assert member_balances(db, hh.household_id)[hh.user_id] == before == D("200.00")
    c = cash_comparison(db, hh.household_id, hh.user_id, *JULY)
    assert (c["withdrawn"], c["cash_expenses"], c["ledger_out"], c["unaccounted"]) == (
        D("200.00"), D("30.00"), D("0.00"), D("170.00"))


def test_comparison_math_ranges_and_deleted(db, make_household):
    hh = make_household()
    add_movement(db, hh.household_id, hh.user_id, "in", D("300"), "EUR", date(2026, 7, 5), None, None)
    add_movement(db, hh.household_id, hh.user_id, "in", D("999"), "EUR", date(2026, 6, 5), None, None)
    add_movement(db, hh.household_id, hh.user_id, "out", D("20"), "EUR", date(2026, 7, 6), None, None)
    _cash_expense(db, hh, hh.user_id, D("60"))
    gone = _cash_expense(db, hh, hh.user_id, D("500"))
    gone.deleted_at = utcnow_naive()  # soft-deleted: excluded
    other = _add_member(db, hh.household_id, "cashc")
    db.commit()
    _cash_expense(db, hh, other.id, D("77"))  # someone else's: excluded
    c = cash_comparison(db, hh.household_id, hh.user_id, *JULY)
    assert c["withdrawn"] == D("300.00")
    assert c["ledger_out"] == D("20.00")
    assert c["cash_expenses"] == D("60.00")
    assert c["unaccounted"] == D("220.00")


def test_cash_expenses_use_base_amount(db, make_household):
    hh = make_household()
    t = _cash_expense(db, hh, hh.user_id, D("100"))
    t.currency, t.exchange_rate = "USD", D("0.5")
    db.commit()
    assert cash_comparison(db, hh.household_id, hh.user_id, *JULY)["cash_expenses"] == D("50.00")


def test_soft_delete_hides(db, make_household):
    hh = make_household()
    mv = add_movement(db, hh.household_id, hh.user_id, "in", D("10"), "EUR", date(2026, 7, 1), None, None)
    assert len(list_movements(db, hh.household_id)) == 1
    delete_movement(db, mv)
    assert list_movements(db, hh.household_id) == []
    assert member_balances(db, hh.household_id).get(hh.user_id, D("0")) == D("0")
    assert db.get(CashMovement, mv.id).deleted_at is not None  # row kept


def test_list_filters(db, make_household):
    hh = make_household()
    m = _add_member(db, hh.household_id, "cashd")
    db.commit()
    add_movement(db, hh.household_id, hh.user_id, "in", D("1"), "EUR", date(2026, 7, 1), None, None)
    add_movement(db, hh.household_id, m.id, "in", D("2"), "EUR", date(2026, 8, 1), None, None)
    assert len(list_movements(db, hh.household_id, member_id=m.id)) == 1
    assert len(list_movements(db, hh.household_id, start=date(2026, 7, 1), end=date(2026, 7, 31))) == 1
    assert len(list_movements(db, hh.household_id, limit=1)) == 1


# -------------------------------------------------------------------- API

def test_api_add_list_summary_delete(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "in", "amount": "200", "movement_date": "2026-07-01", "note": "ATM"})
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    assert r.json()["user_id"] == hh.user_id and r.json()["currency"] == "EUR"
    _cash_expense(db, hh, hh.user_id, D("30"))
    r = client.get("/api/v1/cash/movements", headers=headers)
    assert [m["id"] for m in r.json()["items"]] == [mid]
    assert r.json()["balances"][hh.user_id] == 200.0
    r = client.get("/api/v1/cash/summary?month=2026-07", headers=headers)
    assert r.status_code == 200, r.text
    me = r.json()["comparison"]
    assert (me["withdrawn"], me["cash_expenses"], me["unaccounted"]) == (200.0, 30.0, 170.0)
    assert client.delete(f"/api/v1/cash/movements/{mid}", headers=headers).status_code == 204
    assert client.get("/api/v1/cash/movements", headers=headers).json()["items"] == []
    assert client.delete(f"/api/v1/cash/movements/{mid}", headers=headers).status_code == 404


def test_api_validation(client, db, api):  # noqa: F811
    headers, hh = api
    base = {"kind": "in", "amount": "5", "movement_date": "2026-07-01"}
    for bad in ({"kind": "sideways"}, {"amount": "0"}, {"amount": "-3"}, {"amount": "abc"},
                {"currency": "USD"}, {"movement_date": "nope"}):
        r = client.post("/api/v1/cash/movements", headers=headers, json={**base, **bad})
        assert r.status_code in (400, 422), (bad, r.status_code)
    r = client.post("/api/v1/cash/movements", headers=headers, json={**base, "category_id": "missing"})
    assert r.status_code == 404
    assert db.query(CashMovement).count() == 0


def test_member_permissions(client, db, api):  # noqa: F811
    headers, hh = api  # owner
    member, mh = _member_headers(db, hh)
    owner_mv = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "in", "amount": "10", "movement_date": "2026-07-01"}).json()["id"]
    # member cannot delete the owner's movement, nor log for the owner
    assert client.delete(f"/api/v1/cash/movements/{owner_mv}", headers=mh).status_code == 403
    r = client.post("/api/v1/cash/movements", headers=mh, json={
        "kind": "in", "amount": "5", "movement_date": "2026-07-01", "user_id": hh.user_id})
    assert r.status_code == 403
    # member's own: fine
    r = client.post("/api/v1/cash/movements", headers=mh, json={
        "kind": "in", "amount": "5", "movement_date": "2026-07-01"})
    assert r.status_code == 201 and r.json()["user_id"] == member.id
    own = r.json()["id"]
    assert client.delete(f"/api/v1/cash/movements/{own}", headers=mh).status_code == 204
    # owner may log for and delete for the member
    r = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "out", "amount": "3", "movement_date": "2026-07-01", "user_id": member.id})
    assert r.status_code == 201 and r.json()["user_id"] == member.id
    assert client.delete(f"/api/v1/cash/movements/{r.json()['id']}", headers=headers).status_code == 204


def test_other_household_isolated(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="cashother")
    mv = add_movement(db, other.household_id, other.user_id, "in", D("9"), "EUR", date(2026, 7, 1), None, None)
    assert client.delete(f"/api/v1/cash/movements/{mv.id}", headers=headers).status_code == 404
    r = client.post("/api/v1/cash/movements", headers=headers, json={
        "kind": "in", "amount": "5", "movement_date": "2026-07-01", "user_id": other.user_id})
    assert r.status_code in (400, 403)


# ------------------------------------------------------------------- HTML

def test_html_page_add_delete(client, db, authed):
    r = client.get("/cash")
    assert r.status_code == 200
    r = client.post("/cash/add", data={"kind": "in", "amount": "75.50", "movement_date": "2026-07-01",
                                       "note": "walletfill"}, headers=authed.headers, follow_redirects=False)
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
    r = client.post("/cash/add", data={"kind": "in", "amount": "-5", "movement_date": "2026-07-01"},
                    headers=authed.headers)
    assert r.status_code == 400
    assert db.query(CashMovement).count() == 0


def test_html_htmx_returns_list_partial(client, db, authed):
    h = {**authed.headers, "HX-Request": "true"}
    r = client.post("/cash/add", data={"kind": "in", "amount": "12", "movement_date": "2026-07-01",
                                       "note": "partialnote", "month": "2026-07"}, headers=h)
    assert r.status_code == 200 and "partialnote" in r.text and "<html" not in r.text


def test_me_page_links_and_shows_comparison(client, authed, db):
    add_movement(db, authed.household_id, authed.user_id, "in", D("200"), "EUR", local_today(), None, None)
    r = client.get("/me")
    assert r.status_code == 200
    assert "/cash" in r.text and "unaccounted" in r.text.lower()
