"""
Payer mode "each paid their own share" (``Transaction.payer_mode == own_share``).

Scenario: rent is 1100; the user pays 800 and the flatmate 300, each straight
to the landlord as the lease says. Nobody owes anybody, and insights must show
who paid what (800 / 300), not a single payer and not "Unassigned".
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.clock import local_today
from app.models import (
    PayerMode,
    PaymentMethod,
    RecurringBill,
    RecurringBillSplit,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.schemas import OWN_SHARE_CHOICE, TransactionCreate, payer_choice
from app.services.money import paid_for
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import _add_member


@pytest.fixture()
def duo(db, authed):
    partner = _add_member(db, authed.household_id, "flatmate")
    db.commit()
    authed.partner_id = partner.id
    return authed


def _rent(db, ctx, *, amount=1100, splits=None, payment_method="card"):
    """The 800/300 own-share rent expense."""
    splits = splits if splits is not None else [(ctx.user_id, 800), (ctx.partner_id, 300)]
    t = Transaction(
        bucket_id=ctx.bucket_id, household_id=ctx.household_id, amount=amount,
        currency="EUR", type=TransactionType.expense, transaction_date=local_today(),
        paid_by=None, payer_mode=PayerMode.own_share.value, payment_method=payment_method,
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


# ---------------------------------------------------------------------------
# paid_for
# ---------------------------------------------------------------------------

def _txn(amount, paid_by=None, mode="single", splits=()):
    return SimpleNamespace(
        amount=Decimal(amount), exchange_rate=Decimal("1"), paid_by=paid_by,
        payer_mode=mode,
        splits=[SimpleNamespace(user_id=u, amount=Decimal(a)) for u, a in splits],
    )


def test_paid_for_single_credits_the_payer_in_full():
    assert paid_for(_txn("100", "a", splits=[("b", "50")])) == {"a": Decimal("100")}


def test_paid_for_single_without_payer_credits_nobody():
    assert paid_for(_txn("100")) == {}


def test_paid_for_own_share_credits_each_split():
    t = _txn("1100", mode="own_share", splits=[("a", "800"), ("b", "300")])
    assert paid_for(t) == {"a": Decimal("800"), "b": Decimal("300")}


def test_paid_for_applies_the_exchange_rate():
    t = _txn("10", "a")
    t.exchange_rate = Decimal("2")
    assert paid_for(t) == {"a": Decimal("20")}


# ---------------------------------------------------------------------------
# Settlement, insights, person view, cash
# ---------------------------------------------------------------------------

def test_own_share_rent_nets_to_zero_in_settlement(db, duo):
    from app.services import get_bucket_settlement, get_member_balances
    from app.services.settlement import compute_bucket_net

    _rent(db, duo)
    net = compute_bucket_net(db, duo.bucket_id)
    assert all(abs(v) < Decimal("0.005") for v in net.values())
    assert get_bucket_settlement(db, duo.bucket_id) == []
    assert all(b["net"] == 0 for b in get_member_balances(db, duo.household_id))


def test_own_share_is_not_a_missing_payer_for_settle_up(db, duo):
    from app.models import Bucket
    from app.services.settlement import get_settlement_exclusions

    db.get(Bucket, duo.bucket_id).enable_settlement = True
    db.commit()
    _rent(db, duo)
    ex = get_settlement_exclusions(db, duo.household_id)
    assert ex["no_payer_count"] == 0
    assert ex["any"] is False


def test_insights_who_paid_shows_each_share(db, duo):
    from app.services import get_insights_summary

    _rent(db, duo)
    s = get_insights_summary(db, duo.household_id, None, None)
    assert s["total_spent"] == Decimal("1100")
    assert s["paid_by"][duo.user_id]["paid"] == Decimal("800")
    assert s["paid_by"][duo.partner_id]["paid"] == Decimal("300")
    assert s["paid_by"][duo.user_id]["share"] == Decimal("800")
    assert "unassigned" not in s["paid_by"]


def test_person_view_counts_own_share_as_paid_out(db, duo):
    from app.services.person import get_person_summary

    _rent(db, duo)
    me = get_person_summary(db, duo.household_id, duo.user_id)
    assert me["paid_out"] == Decimal("800")
    assert me["my_share"] == Decimal("800")
    assert me["balance"] == 0


def test_wallet_summary_counts_own_cash_share(db, duo):
    from app.services.cash import wallet_summary

    _rent(db, duo, payment_method=PaymentMethod.cash.value)
    mine = wallet_summary(db, duo.household_id, duo.user_id, None, None)
    theirs = wallet_summary(db, duo.household_id, duo.partner_id, None, None)
    assert mine["logged"] == Decimal("800")
    assert theirs["logged"] == Decimal("300")


def test_missing_payer_search_excludes_own_share(client, db, duo):
    rent = _rent(db, duo)
    orphan = Transaction(
        bucket_id=duo.bucket_id, household_id=duo.household_id, amount=20,
        currency="EUR", type=TransactionType.expense, transaction_date=local_today(),
        notes="orphan-row",
    )
    db.add(orphan)
    db.commit()
    page = client.get("/transactions/search?missing_payer=1").text
    assert "orphan-row" in page
    assert f"/transactions/{rent.id}/edit" not in page


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _create(**kw):
    base = {"bucket_id": "b", "amount": "1100", "payer_mode": "own_share"}
    return TransactionCreate(**{**base, **kw})


def test_payer_choice_maps_the_dropdown_value():
    assert payer_choice(OWN_SHARE_CHOICE) == (None, "own_share")
    assert payer_choice("u1") == ("u1", "single")
    assert payer_choice("") == (None, "single")


def test_own_share_requires_splits():
    with pytest.raises(ValidationError, match="own share"):
        _create()


def test_own_share_requires_splits_matching_the_total():
    with pytest.raises(ValidationError, match="add up"):
        _create(splits=[{"user_id": "a", "amount": "800"}, {"user_id": "b", "amount": "200"}])


def test_own_share_accepts_a_cent_of_rounding_and_drops_the_payer():
    data = _create(paid_by="a", splits=[{"user_id": "a", "amount": "800"},
                                        {"user_id": "b", "amount": "299.99"}])
    assert data.paid_by is None
    assert data.payer_mode == "own_share"


def test_own_share_is_only_for_expenses():
    with pytest.raises(ValidationError, match="expense"):
        _create(type="income", splits=[{"user_id": "a", "amount": "1100"}])


def test_unknown_payer_mode_is_rejected():
    with pytest.raises(ValidationError, match="payer mode"):
        _create(payer_mode="both")


def test_html_create_own_share(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "1100", "paid_by": OWN_SHARE_CHOICE, "is_shared": "on",
        f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300",
    })
    assert r.status_code == 302, r.text
    t = db.query(Transaction).one()
    assert t.payer_mode == "own_share"
    assert t.paid_by is None
    assert sorted(float(s.amount) for s in t.splits) == [300.0, 800.0]


def test_html_create_own_share_parses_splits_even_if_not_marked_shared(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "1100", "paid_by": OWN_SHARE_CHOICE, "is_shared": "off",
        f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300",
    })
    assert r.status_code == 302, r.text
    assert db.query(Transaction).one().payer_mode == "own_share"


def test_html_create_own_share_rejects_mismatched_splits(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "1100", "paid_by": OWN_SHARE_CHOICE, "is_shared": "on",
        f"split_{duo.user_id}": "800",
    })
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_html_shared_single_still_defaults_payer_to_submitter(client, db, duo):
    r = client.post("/transactions", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "100", "paid_by": "", "is_shared": "on",
    })
    assert r.status_code == 302
    t = db.query(Transaction).one()
    assert t.payer_mode == "single"
    assert t.paid_by == duo.user_id


def test_html_edit_switches_to_own_share_and_back(client, db, duo):
    t = _rent(db, duo)
    form = {
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "1100", "type": "expense",
        f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300",
    }
    r = client.post(f"/transactions/{t.id}/edit", headers=duo.headers,
                    data={**form, "paid_by": duo.partner_id})
    assert r.status_code == 302
    db.expire_all()
    t = db.get(Transaction, t.id)
    assert (t.payer_mode, t.paid_by) == ("single", duo.partner_id)

    r = client.post(f"/transactions/{t.id}/edit", headers=duo.headers,
                    data={**form, "paid_by": OWN_SHARE_CHOICE})
    assert r.status_code == 302
    db.expire_all()
    t = db.get(Transaction, t.id)
    assert (t.payer_mode, t.paid_by) == ("own_share", None)


def test_html_edit_own_share_without_splits_is_rejected(client, db, duo):
    t = _rent(db, duo)
    r = client.post(f"/transactions/{t.id}/edit", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "1100", "type": "expense", "paid_by": OWN_SHARE_CHOICE,
    })
    assert r.status_code == 400
    db.expire_all()
    assert len(db.get(Transaction, t.id).splits) == 2


def test_edit_page_offers_own_share_and_preselects_it(client, db, duo):
    t = _rent(db, duo)
    page = client.get(f"/transactions/{t.id}/edit").text
    assert "Each paid their own share" in page
    assert f'value="{OWN_SHARE_CHOICE}" selected' in page


def test_rows_say_each_paid_own_share(client, db, duo):
    _rent(db, duo)
    assert "Each paid own share" in client.get(f"/buckets/{duo.bucket_id}").text
    assert "Each paid own share" in client.get("/transactions/search?q=&type=expense").text


def test_wizard_offers_own_share(client, duo):
    assert "Each paid their own share" in client.get("/transactions/new").text


def test_duplicate_keeps_own_share_and_its_splits(client, db, duo):
    t = _rent(db, duo)
    r = client.post(f"/transactions/{t.id}/duplicate", headers=duo.headers)
    assert r.status_code == 302
    copy = db.query(Transaction).filter(Transaction.id != t.id).one()
    assert copy.payer_mode == "own_share"
    assert sorted(float(s.amount) for s in copy.splits) == [300.0, 800.0]


# ---------------------------------------------------------------------------
# API parity
# ---------------------------------------------------------------------------

def test_api_create_own_share(client, db, api):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "flatmate")
    db.commit()
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "1100", "payer_mode": "own_share",
        "splits": [{"user_id": hh.user_id, "amount": "800"},
                   {"user_id": partner.id, "amount": "300"}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["payer_mode"] == "own_share"
    assert body["paid_by"] is None


def test_api_create_own_share_without_splits_is_422(client, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "1100", "payer_mode": "own_share",
    })
    assert r.status_code == 422


def test_api_single_create_reports_payer_mode(client, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/transactions", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "10",
    })
    assert r.status_code == 201
    assert r.json()["payer_mode"] == "single"
    assert r.json()["paid_by"] == hh.user_id


def test_api_update_without_payer_mode_keeps_own_share(client, db, api):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "flatmate")
    db.commit()
    hh.partner_id = partner.id
    t = _rent(db, hh)
    r = client.put(f"/api/v1/transactions/{t.id}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "1100", "notes": "rent",
        "splits": [{"user_id": hh.user_id, "amount": "800"},
                   {"user_id": partner.id, "amount": "300"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["payer_mode"] == "own_share"
    assert r.json()["paid_by"] is None


def test_api_update_own_share_with_bad_splits_is_rejected(client, db, api):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "flatmate")
    db.commit()
    hh.partner_id = partner.id
    t = _rent(db, hh)
    r = client.put(f"/api/v1/transactions/{t.id}", headers=headers, json={
        "bucket_id": hh.bucket_id, "amount": "1200",
        "splits": [{"user_id": hh.user_id, "amount": "800"},
                   {"user_id": partner.id, "amount": "300"}],
    })
    assert r.status_code in (400, 422)


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------

def _own_share_bill(db, make_bill, ctx, *, splits=True, auto_pay=False):
    bill, occ = make_bill(ctx.household_id, ctx.bucket_id, amount=1100,
                          auto_pay=auto_pay, name="Rent")
    bill.payer_mode = PayerMode.own_share.value
    if splits:
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=ctx.user_id, amount=800))
        db.add(RecurringBillSplit(bill_id=bill.id, user_id=ctx.partner_id, amount=300))
    db.commit()
    return bill, occ


def test_html_pay_own_share_bill(client, db, duo, make_bill):
    bill, occ = _own_share_bill(db, make_bill, duo)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                    data={"paid_by": ""}, headers=duo.headers)
    assert r.status_code in (200, 302), r.text
    db.expire_all()
    t = db.query(Transaction).one()
    assert (t.payer_mode, t.paid_by) == ("own_share", None)
    assert {s.user_id: float(s.amount) for s in t.splits} == {duo.user_id: 800.0,
                                                               duo.partner_id: 300.0}
    assert db.get(type(occ), occ.id).paid_by is None


def test_html_pay_own_share_bill_scales_a_variable_amount(client, db, duo, make_bill):
    bill, occ = _own_share_bill(db, make_bill, duo)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                    data={"paid_by": "", "amount": "1210"}, headers=duo.headers)
    assert r.status_code in (200, 302), r.text
    t = db.query(Transaction).one()
    assert sum(Decimal(str(s.amount)) for s in t.splits) == Decimal("1210")


def test_html_pay_with_explicit_member_overrides_own_share(client, db, duo, make_bill):
    bill, occ = _own_share_bill(db, make_bill, duo)
    client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay",
                data={"paid_by": duo.partner_id}, headers=duo.headers)
    t = db.query(Transaction).one()
    assert (t.payer_mode, t.paid_by) == ("single", duo.partner_id)


def test_html_pay_can_choose_own_share_explicitly(client, db, duo, make_bill):
    bill, occ = make_bill(duo.household_id, duo.bucket_id, amount=1100, auto_pay=False)
    r = client.post(f"/bills/{bill.id}/occurrences/{occ.id}/pay", headers=duo.headers, data={
        "paid_by": OWN_SHARE_CHOICE,
        f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300",
    })
    assert r.status_code in (200, 302), r.text
    t = db.query(Transaction).one()
    assert (t.payer_mode, t.paid_by) == ("own_share", None)


def test_api_pay_own_share_bill(client, db, api, make_bill):  # noqa: F811
    headers, hh = api
    hh.partner_id = _add_member(db, hh.household_id, "flatmate").id
    db.commit()
    _, occ = _own_share_bill(db, make_bill, hh)
    r = client.post(f"/api/v1/bills/occurrences/{occ.id}/pay", headers=headers, json={})
    assert r.status_code == 200, r.text
    t = db.query(Transaction).one()
    assert (t.payer_mode, t.paid_by) == ("own_share", None)


def test_autopay_own_share_bill(db, duo, make_bill, monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    _own_share_bill(db, make_bill, duo, auto_pay=True)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    scheduler.auto_mark_paid_job()
    db.expire_all()
    t = db.query(Transaction).one()
    assert (t.payer_mode, t.paid_by) == ("own_share", None)
    assert sorted(float(s.amount) for s in t.splits) == [300.0, 800.0]


def test_autopay_own_share_bill_without_splits_falls_back_to_single(
        db, duo, make_bill, monkeypatch, SessionLocal):
    import app.core.database as database
    import app.scheduler as scheduler

    _own_share_bill(db, make_bill, duo, splits=False, auto_pay=True)
    monkeypatch.setattr(database, "SessionLocal", SessionLocal, raising=False)
    scheduler.auto_mark_paid_job()
    db.expire_all()
    t = db.query(Transaction).one()
    assert t.payer_mode == "single"
    assert t.paid_by == duo.user_id  # owner fallback


def test_html_create_own_share_bill(client, db, duo):
    r = client.post("/bills", headers=duo.headers, data={
        "name": "Rent", "amount": "1100", "start_date": local_today().isoformat(),
        "paid_by_default": OWN_SHARE_CHOICE,
        f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "300",
    })
    assert r.status_code == 302, r.text
    bill = db.query(RecurringBill).one()
    assert (bill.payer_mode, bill.paid_by_default) == ("own_share", None)


def test_html_own_share_bill_needs_splits(client, db, duo):
    r = client.post("/bills", headers=duo.headers, data={
        "name": "Rent", "amount": "1100", "start_date": local_today().isoformat(),
        "paid_by_default": OWN_SHARE_CHOICE,
    })
    assert r.status_code == 400
    assert db.query(RecurringBill).count() == 0


def test_bill_forms_offer_own_share(client, db, duo, make_bill):
    bill, _ = _own_share_bill(db, make_bill, duo)
    assert "Each paid their own share" in client.get("/bills").text
    page = client.get(f"/bills/{bill.id}/edit").text
    assert f'value="{OWN_SHARE_CHOICE}" selected' in page


def test_api_bill_payer_mode_round_trip(client, db, api):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "flatmate")
    db.commit()
    r = client.post("/api/v1/bills", headers=headers, json={
        "name": "Rent", "amount": "1100", "start_date": local_today().isoformat(),
        "payer_mode": "own_share",
        "splits": [{"user_id": hh.user_id, "amount": "800"},
                   {"user_id": partner.id, "amount": "300"}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["payer_mode"] == "own_share"
    assert r.json()["paid_by_default"] is None


def test_api_bill_rejects_unknown_payer_mode(client, api):  # noqa: F811
    headers, hh = api
    r = client.post("/api/v1/bills", headers=headers, json={
        "name": "Rent", "amount": "1100", "start_date": local_today().isoformat(),
        "payer_mode": "both",
    })
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# A cent of rounding is absorbed, never left to nobody
# ---------------------------------------------------------------------------

def test_own_share_cent_of_rounding_goes_to_the_largest_share():
    data = _create(splits=[{"user_id": "a", "amount": "800"},
                           {"user_id": "b", "amount": "299.99"}])
    assert {s.user_id: s.amount for s in data.splits} == {
        "a": Decimal("800.01"), "b": Decimal("299.99"),
    }


def test_own_share_saved_a_cent_short_shows_no_unassigned(client, db, duo):
    from app.services import get_insights_summary

    r = client.post("/transactions", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": local_today().isoformat(),
        "amount": "1100", "paid_by": OWN_SHARE_CHOICE, "is_shared": "on",
        f"split_{duo.user_id}": "800", f"split_{duo.partner_id}": "299.99",
    })
    assert r.status_code == 302, r.text
    t = db.query(Transaction).one()
    assert sum(Decimal(str(s.amount)) for s in t.splits) == Decimal("1100")
    who = get_insights_summary(db, duo.household_id, None, None)["paid_by"]
    assert "unassigned" not in who
    assert who[duo.user_id]["paid"] == Decimal("800.01")


def test_api_own_share_update_absorbs_the_cent(client, db, api):  # noqa: F811
    headers, hh = api
    partner = _add_member(db, hh.household_id, "flatmate")
    db.commit()
    body = {
        "bucket_id": hh.bucket_id, "amount": "100", "payer_mode": "own_share",
        "transaction_date": local_today().isoformat(),
        "splits": [{"user_id": hh.user_id, "amount": "50"},
                   {"user_id": partner.id, "amount": "50"}],
    }
    r = client.post("/api/v1/transactions", headers=headers, json=body)
    assert r.status_code == 201, r.text
    body["splits"] = [{"user_id": hh.user_id, "amount": "33.33"},
                      {"user_id": partner.id, "amount": "66.66"}]
    r = client.put(f"/api/v1/transactions/{r.json()['id']}", headers=headers, json=body)
    assert r.status_code == 200, r.text
    db.expire_all()
    t = db.query(Transaction).one()
    assert {s.user_id: Decimal(str(s.amount)) for s in t.splits} == {
        hh.user_id: Decimal("33.33"), partner.id: Decimal("66.67"),
    }
