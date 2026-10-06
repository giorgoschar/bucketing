"""payment_method + merchant on transactions (Phase 4, Task 4.1)."""
from app.core.clock import utcnow_naive
from app.models import PaymentMethod, Transaction
from app.services.bills import pay_occurrence
from tests.test_api import api  # noqa: F401  (fixture)


def _form(authed, **extra):
    return {"bucket_id": authed.bucket_id, "transaction_date": "2026-07-20",
            "amount": "12.50", "type": "expense", **extra}


def test_enum_members():
    assert {m.value for m in PaymentMethod} == {"card", "cash", "apple_pay", "transfer", "other"}


def test_html_post_stores_cash_and_merchant(client, db, authed):
    r = client.post("/transactions", data=_form(authed, payment_method="cash", merchant="Bakery"),
                    headers=authed.headers, follow_redirects=False)
    assert r.status_code in (200, 302)
    t = db.query(Transaction).one()
    assert t.payment_method == "cash"
    assert t.merchant == "Bakery"


def test_html_default_is_card(client, db, authed):
    client.post("/transactions", data=_form(authed), headers=authed.headers, follow_redirects=False)
    t = db.query(Transaction).one()
    assert t.payment_method == "card"
    assert t.merchant is None


def test_html_invalid_payment_method_rejected(client, db, authed):
    r = client.post("/transactions", data=_form(authed, payment_method="bitcoin"),
                    headers=authed.headers)
    assert r.status_code in (400, 422)
    assert db.query(Transaction).count() == 0


def test_api_create_and_dict(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "9.90",
        "payment_method": "apple_pay", "merchant": "Coffee Co"})
    assert r.status_code == 201, r.text
    assert r.json()["payment_method"] == "apple_pay"
    assert r.json()["merchant"] == "Coffee Co"
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "9.90"})
    assert r.json()["payment_method"] == "card"


def test_api_invalid_payment_method_is_422(client, db, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "9.90", "payment_method": "bitcoin"})
    assert r.status_code == 422
    assert db.query(Transaction).count() == 0


def test_api_update_payment_method(client, db, api):  # noqa: F811
    headers, hh = api
    tid = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "5"}).json()["id"]
    r = client.put(f"/api/v1/transactions/{tid}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "5", "payment_method": "cash", "merchant": "Kiosk"})
    assert r.status_code == 200, r.text
    assert r.json()["payment_method"] == "cash" and r.json()["merchant"] == "Kiosk"
    r = client.put(f"/api/v1/transactions/{tid}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "5", "payment_method": "nope"})
    assert r.status_code == 422


def test_edit_form_updates_payment_method(client, db, authed):
    client.post("/transactions", data=_form(authed), headers=authed.headers, follow_redirects=False)
    t = db.query(Transaction).one()
    r = client.post(f"/transactions/{t.id}/edit",
                    data=_form(authed, payment_method="transfer", merchant="Landlord"),
                    headers=authed.headers, follow_redirects=False)
    assert r.status_code == 302
    db.refresh(t)
    assert (t.payment_method, t.merchant) == ("transfer", "Landlord")
    r = client.post(f"/transactions/{t.id}/edit", data=_form(authed, payment_method="zzz"),
                    headers=authed.headers, follow_redirects=False)
    assert r.status_code in (400, 422)


def test_bill_payment_defaults_to_card_and_accepts_method(db, make_household, make_bill):
    hh = make_household()
    _, occ = make_bill(hh.household_id, hh.bucket_id, auto_pay=False)
    txn = pay_occurrence(db, occ, amount=10, paid_by=hh.user_id, paid_on=utcnow_naive())
    assert txn.payment_method == "card"
    _, occ2 = make_bill(hh.household_id, hh.bucket_id, auto_pay=False, name="Rent",
                        due=occ.due_date.replace(year=occ.due_date.year + 1))
    txn2 = pay_occurrence(db, occ2, amount=10, paid_by=hh.user_id, paid_on=utcnow_naive(),
                          payment_method="cash")
    assert txn2.payment_method == "cash"
