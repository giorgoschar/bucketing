"""B3: editing a transaction runs the same validation as creating one."""

from decimal import Decimal

from app.core.clock import local_today
from app.models import Transaction, TransactionSplit, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member


def _txn(db, hh, *, paid_by="__me__", amount=100):
    t = Transaction(
        bucket_id=hh.bucket_id,
        household_id=hh.household_id,
        amount=amount,
        currency="EUR",
        exchange_rate=1,
        type=TransactionType.expense,
        transaction_date=local_today(),
        paid_by=hh.user_id if paid_by == "__me__" else paid_by,
    )
    db.add(t)
    db.commit()
    return t


# ---------------------------------------------------------------------------
# API PUT
# ---------------------------------------------------------------------------


def _put(client, headers, t, **body):
    payload = {"bucket_id": t.bucket_id, "amount": "100", **body}
    return client.put(f"/api/v1/transactions/{t.id}", headers=headers, json=payload)


def test_api_put_rejects_unknown_currency(client, db, api):  # noqa: F811
    headers, hh = api
    t = _txn(db, hh)
    assert _put(client, headers, t, currency="ZZZ").status_code == 422
    db.refresh(t)
    assert t.currency == "EUR"


def test_api_put_rejects_zero_or_negative_rate(client, db, api):  # noqa: F811
    headers, hh = api
    t = _txn(db, hh)
    assert _put(client, headers, t, exchange_rate=0).status_code == 422
    assert _put(client, headers, t, exchange_rate=-2).status_code == 422
    db.refresh(t)
    assert t.exchange_rate == 1


def test_api_put_rejects_splits_over_total(client, db, api):  # noqa: F811
    headers, hh = api
    t = _txn(db, hh)
    r = _put(client, headers, t, splits=[{"user_id": hh.user_id, "amount": "150"}])
    assert r.status_code == 422
    assert db.query(TransactionSplit).count() == 0


def test_api_put_split_expense_always_has_a_payer(client, db, api):  # noqa: F811
    headers, hh = api
    t = _txn(db, hh, paid_by=None)
    r = _put(client, headers, t, paid_by=None, splits=[{"user_id": hh.user_id, "amount": "50"}])
    assert r.status_code == 200, r.text
    assert r.json()["paid_by"] == hh.user_id


def test_api_put_blank_date_keeps_existing_date(client, db, api):  # noqa: F811
    from datetime import date

    headers, hh = api
    t = _txn(db, hh)
    t.transaction_date = date(2025, 3, 4)
    db.commit()
    assert _put(client, headers, t).status_code == 200
    db.refresh(t)
    assert t.transaction_date == date(2025, 3, 4)


# ---------------------------------------------------------------------------
# HTML edit
# ---------------------------------------------------------------------------


def _form(t, **extra):
    return {
        "bucket_id": t.bucket_id,
        "transaction_date": local_today().isoformat(),
        "amount": "100",
        "type": "expense",
        "currency": "EUR",
        **extra,
    }


def test_html_edit_rejects_splits_over_total(client, db, authed):
    t = _txn(db, authed)
    r = client.post(
        f"/transactions/{t.id}/edit",
        data=_form(t, **{f"split_{authed.user_id}": "150"}),
        headers=authed.headers,
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "exceed" in r.text
    assert db.query(TransactionSplit).count() == 0


def test_html_edit_rejects_zero_rate_and_bad_currency(client, db, authed):
    t = _txn(db, authed)
    for bad in ({"exchange_rate": "0"}, {"currency": "ZZZ"}):
        r = client.post(
            f"/transactions/{t.id}/edit",
            data=_form(t, **bad),
            headers=authed.headers,
            follow_redirects=False,
        )
        assert r.status_code == 400, bad


def test_html_edit_cannot_clear_payer_on_split_expense(client, db, authed):
    partner = _add_member(db, authed.household_id, "partner")
    db.commit()
    t = _txn(db, authed)
    r = client.post(
        f"/transactions/{t.id}/edit",
        data=_form(t, paid_by="", **{f"split_{partner.id}": "50"}),
        headers=authed.headers,
        follow_redirects=False,
    )
    assert r.status_code == 302
    db.refresh(t)
    assert t.paid_by == authed.user_id


def test_html_edit_amount_is_decimal(client, db, authed):
    t = _txn(db, authed)
    r = client.post(
        f"/transactions/{t.id}/edit",
        data=_form(t, amount="12,35", exchange_rate="1,1"),
        headers=authed.headers,
        follow_redirects=False,
    )
    assert r.status_code == 302
    db.refresh(t)
    assert Decimal(t.amount) == Decimal("12.35")
    assert Decimal(t.exchange_rate) == Decimal("1.1")
