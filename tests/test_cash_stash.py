"""
Low-maintenance cash: a private stash and a wallet per member.

Model (app.services.cash): cash taken into a wallet counts as spent unless it
is logged or still there. Per member and month::

    spent          = carried + taken - put_back - still_have_end   (>= 0)
    not_yet_logged = spent - logged - outs                         (>= 0)
    carried(M)     = still_have_end(M-1)

    stash(owner) = stash_in - takes from it + put_back

Covers the user's own scenario end to end, the formula, the stash (balance,
overdraw, takes from a flatmate's stash with no debt), privacy (HTML + API,
other member and household owner), "I took this from my stash" (link, edit
sync, delete cascade), still_have, insights' "Cash (not yet logged)" line,
the expense wizard's payment default and the migration.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.models import (
    CashMovement,
    Category,
    PayerMode,
    Transaction,
    TransactionSplit,
    TransactionType,
)
from app.services import (
    InsightFilters,
    add_movement,
    build_insights,
    get_household_settlement,
    get_member_balances,
    list_movements,
    monthly_breakdown,
    not_yet_logged,
    stash_balance,
    wallet_summary,
    withdraw_and_spend,
)
from tests.test_isolation import _add_member_user, _web_login

D = Decimal
JAN, FEB = date(2026, 1, 1), date(2026, 2, 1)
JAN_END, FEB_END = date(2026, 1, 31), date(2026, 2, 28)
NOT_LOGGED = "Cash (not yet logged)"


@pytest.fixture()
def duo(db, authed):
    """The logged-in owner plus a second member (with login credentials)."""
    member, secret = _add_member_user(db, authed.household_id, "flatmate")
    authed.partner_id = member.id
    authed.partner_secret = secret
    return authed


def _move(db, ctx, kind, amount, day, *, user=None, stash_owner=None, category_id=None,
          note=None):
    return add_movement(db, ctx.household_id, user or ctx.user_id, kind, D(str(amount)), "EUR",
                        day, category_id, note, stash_owner_id=stash_owner)


def _cash(db, ctx, amount, day, *, payer="__me__", category_id=None, method="cash",
          mode="single", splits=()):
    t = Transaction(
        bucket_id=ctx.bucket_id, household_id=ctx.household_id, amount=D(str(amount)),
        currency="EUR", exchange_rate=1, type=TransactionType.expense, transaction_date=day,
        paid_by=ctx.user_id if payer == "__me__" else payer, payment_method=method,
        category_id=category_id, payer_mode=mode,
    )
    db.add(t)
    db.flush()
    for uid, amt in splits:
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=amt))
    db.commit()
    return t


def _category(db, ctx, name):
    c = Category(household_id=ctx.household_id, name=name)
    db.add(c)
    db.commit()
    return c


def _insights(db, ctx, start="2026-01-01", end="2026-01-31", **filters):
    return build_insights(db, ctx.household_id, InsightFilters(
        preset="custom", start_date=start, end_date=end, **filters))


def _bearer(ctx, user_id):
    """API headers without a TOTP round trip (the code may already be used)."""
    from app.api_auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user_id, ctx.household_id, 0)}"}


def _cats(data):
    return {c["name"]: c["amount"] for c in data["categories"]}


def _member(app, ctx):
    """The flatmate's own web session and its CSRF headers."""
    c = _web_login(app, "flatmate", ctx.partner_secret)
    return c, {"X-CSRF-Token": c.cookies.get("csrf_token")}


def _nyl(db, ctx, month=JAN, user=None):
    return not_yet_logged(db, ctx.household_id, user or ctx.user_id, month)


# ---------------------------------------------------------------------------
# The user's own scenario
# ---------------------------------------------------------------------------

def test_the_users_own_scenario(app, client, db, duo):
    """200 saved, 100 taken "to be safe", parking logged, 60 left; the
    flatmate borrows 50 from the stash without seeing it or owing anything."""
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    parking = _category(db, duo, "Parking")

    def add(data, c=client, headers=duo.headers):
        r = c.post("/cash/add", headers=headers, data=data)
        assert r.status_code in (200, 302), r.text
        return r

    # 200 saved in the stash.
    add({"kind": "stash_in", "amount": "200", "movement_date": "2026-01-01", "note": "savings"})
    assert stash_balance(db, hh, a) == D("200.00")
    # 100 taken into the wallet "to be safe", no expense.
    add({"kind": "take", "amount": "100", "movement_date": "2026-01-02", "source": a})
    assert stash_balance(db, hh, a) == D("100.00")
    summary = _insights(db, duo)["summary"]
    assert summary["total_spent"] == D("100.00") and summary["cash_not_logged"] == D("100.00")

    # Parking 5, paid in cash, logged as an expense.
    r = client.post("/transactions", headers=duo.headers, data={
        "bucket_id": duo.bucket_id, "transaction_date": "2026-01-10", "amount": "5",
        "type": "expense", "paid_by": a, "payment_method": "cash", "category_id": parking.id})
    assert r.status_code == 302, r.text
    data = _insights(db, duo)
    assert _cats(data) == {"Parking": D("5.00"), NOT_LOGGED: D("95.00")}
    assert data["summary"]["total_spent"] == D("100.00")         # no double count
    assert data["summary"]["cash_not_logged"] == D("95.00")
    assert {r["method"]: r["amount"] for r in data["by_method"]} == {"cash": D("100.00")}

    # 60 still in the wallet at the end of the month.
    add({"kind": "still_have", "amount": "60", "movement_date": "2026-01-31"})
    jan = wallet_summary(db, hh, a, JAN, JAN_END, viewer_id=a)
    assert (jan["taken"], jan["still_have"], jan["spent"], jan["logged"], jan["not_yet_logged"]) == (
        D("100.00"), D("60.00"), D("40.00"), D("5.00"), D("35.00"))
    assert wallet_summary(db, hh, a, FEB, FEB_END, viewer_id=a)["carried"] == D("60.00")
    assert _insights(db, duo)["summary"]["total_spent"] == D("40.00")

    # The flatmate takes 50 from A's stash into their own wallet.
    member, mh = _member(app, duo)
    add({"kind": "take", "amount": "50", "movement_date": "2026-01-20", "source": a},
        c=member, headers=mh)
    assert stash_balance(db, hh, a) == D("50.00")
    assert _nyl(db, duo, user=b) == D("50.00")
    assert _insights(db, duo)["summary"]["total_spent"] == D("90.00")
    # No debt: nothing reaches settle-up.
    assert get_household_settlement(db, hh) == []
    assert all(row["net"] == 0 for row in get_member_balances(db, hh))

    # The flatmate never sees A's stash: not on the page, not in the API.
    page = member.get("/cash?month=2026-01").text
    assert "savings" not in page and "€50.00" not in page.split("Your stash", 1)[1].split("This month")[0]
    for url in (f"/me?member={a}&preset=custom&start_date=2026-01-01&end_date=2026-01-31",):
        assert "savings" not in member.get(url).text
    bh = _bearer(duo, b)
    body = client.get("/api/v1/cash/movements", headers=bh).json()
    assert body["stash"] == 0.0                                  # their own (empty) stash
    assert [m["kind"] for m in body["items"]] == ["take"]        # only their own take
    assert body["items"][0]["stash_owner_id"] == a
    assert client.get(f"/api/v1/cash/movements?member_id={a}", headers=bh).json()["items"] == []
    assert client.get(f"/api/v1/cash/summary?month=2026-01&member_id={a}",
                      headers=bh).json()["stash"] == 0.0
    # The owner sees the take in their stash history.
    own = client.get("/cash?month=2026-01").text
    assert "Flatmate took €50.00 from your stash" in own

    # Taking more than A's stash holds is never refused: a refusal would let
    # the flatmate find the balance by trying amounts. A's stash goes negative
    # and only A is told.
    r = member.post("/cash/add", headers=mh, data={
        "kind": "take", "amount": "500", "movement_date": "2026-01-21", "source": a})
    assert r.status_code in (200, 302), r.text
    assert "Not enough" not in r.text and "450" not in r.text
    r = client.post("/api/v1/cash/movements", headers=bh, json={
        "kind": "take", "amount": "500", "stash_owner_id": a, "movement_date": "2026-01-22"})
    assert r.status_code in (200, 201), r.text
    assert "450" not in r.text and "950" not in r.text
    assert stash_balance(db, hh, a) == D("-950.00")
    own = client.get("/cash?month=2026-01").text
    assert "more than your stash held" in own
    assert "more than your stash held" not in member.get("/cash?month=2026-01").text

    # The flatmate deleting their take doesn't erase it from A's history.
    take_id = r.json()["id"]
    assert client.delete(f"/api/v1/cash/movements/{take_id}", headers=bh).status_code in (200, 204)
    assert stash_balance(db, hh, a) == D("-450.00")
    own = client.get("/cash?month=2026-01").text
    assert own.count("Flatmate took €500.00 from your stash") == 2
    assert "(deleted)" in own


def test_household_owner_role_grants_no_stash_access(app, client, db, duo):
    """The flatmate's stash, seen by the household owner: nothing."""
    hh, owner, b = duo.household_id, duo.user_id, duo.partner_id
    mv = _move(db, duo, "stash_in", 66.66, date(2026, 1, 2), user=b, note="memberstash")
    page = client.get("/cash?month=2026-01").text
    assert "memberstash" not in page and "66.66" not in page
    oh = _bearer(duo, owner)
    body = client.get("/api/v1/cash/movements", headers=oh).json()
    assert mv.id not in [m["id"] for m in body["items"]] and body["stash"] == 0.0
    assert client.get(f"/api/v1/cash/movements?member_id={b}", headers=oh).json()["items"] == []
    assert client.delete(f"/api/v1/cash/movements/{mv.id}", headers=oh).status_code == 404
    assert client.post(f"/cash/{mv.id}/delete", headers=duo.headers).status_code == 404
    db.refresh(mv)
    assert mv.deleted_at is None
    # The owner logs only their own cash: a user_id is not a thing any more.
    r = client.post("/api/v1/cash/movements", headers=oh, json={
        "kind": "stash_in", "amount": "5", "user_id": b})
    assert r.status_code == 201 and r.json()["user_id"] == owner
    assert stash_balance(db, hh, b) == D("66.66")


# ---------------------------------------------------------------------------
# The formula
# ---------------------------------------------------------------------------

def test_lazy_take_is_all_not_yet_logged(db, authed):
    _move(db, authed, "take", 50, date(2026, 1, 3))
    assert _nyl(db, authed) == D("50.00")


def test_stash_in_alone_is_not_spending(db, authed):
    _move(db, authed, "stash_in", 500, date(2026, 1, 3))
    assert _nyl(db, authed) == D("0.00")
    assert _insights(db, authed)["summary"]["total_spent"] == D("0.00")


def test_partial_logging_splits_category_and_not_logged(db, authed):
    food = _category(db, authed, "Coffee")
    _move(db, authed, "take", 50, date(2026, 1, 3))
    _cash(db, authed, 20, date(2026, 1, 4), category_id=food.id)
    data = _insights(db, authed)
    assert _cats(data) == {"Coffee": D("20.00"), NOT_LOGGED: D("30.00")}
    assert data["summary"]["total_spent"] == D("50.00")
    assert data["summary"]["cash_not_logged"] == D("30.00")


def test_put_back_is_not_spent(db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    _move(db, authed, "take", 80, date(2026, 1, 2), stash_owner=authed.user_id)
    _move(db, authed, "put_back", 30, date(2026, 1, 20))
    (jan,) = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, JAN)
    assert (jan["taken"], jan["put_back"], jan["spent"], jan["not_yet_logged"]) == (
        D("80.00"), D("30.00"), D("50.00"), D("50.00"))
    assert stash_balance(db, authed.household_id, authed.user_id) == D("50.00")


def test_still_have_carries_into_next_month(db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _cash(db, authed, 30, date(2026, 1, 10))
    _move(db, authed, "still_have", 40, date(2026, 1, 31))
    _cash(db, authed, 10, date(2026, 2, 5))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["not_yet_logged"] == D("30.00") and jan["still_have"] == D("40.00")
    assert feb["carried"] == D("40.00") and feb["still_have"] is None
    assert feb["not_yet_logged"] == D("30.00")


def test_not_yet_logged_floors_at_zero(db, authed):
    _move(db, authed, "take", 20, date(2026, 1, 2))
    _cash(db, authed, 50, date(2026, 1, 3))
    assert _nyl(db, authed) == D("0.00")


def test_legacy_outs_still_count(db, authed):
    gift = _category(db, authed, "Gifts")
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _move(db, authed, "out", 15, date(2026, 1, 3), category_id=gift.id)
    _move(db, authed, "out", 25, date(2026, 1, 4))  # lent to a friend: not spending
    assert _nyl(db, authed) == D("60.00")
    data = _insights(db, authed)
    assert _cats(data) == {"Gifts": D("15.00"), NOT_LOGGED: D("60.00")}
    assert data["summary"]["total_spent"] == D("75.00")


def test_own_share_cash_expense_credits_each_member(db, duo):
    _move(db, duo, "take", 100, date(2026, 1, 2))
    _move(db, duo, "take", 100, date(2026, 1, 2), user=duo.partner_id)
    _cash(db, duo, 100, date(2026, 1, 3), payer=None, mode=PayerMode.own_share.value,
          splits=[(duo.user_id, D("70")), (duo.partner_id, D("30"))])
    assert _nyl(db, duo) == D("30.00")
    assert _nyl(db, duo, user=duo.partner_id) == D("70.00")


def test_wallet_figures_are_household_visible_but_put_backs_are_not(db, duo):
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    _move(db, duo, "stash_in", 100, date(2026, 1, 1))
    _move(db, duo, "take", 80, date(2026, 1, 2), stash_owner=a)
    _move(db, duo, "put_back", 30, date(2026, 1, 3))
    mine = wallet_summary(db, hh, a, JAN, JAN_END, viewer_id=a)
    seen = wallet_summary(db, hh, a, JAN, JAN_END, viewer_id=b)
    assert (mine["taken"], mine["put_back"], mine["not_yet_logged"]) == (
        D("80.00"), D("30.00"), D("50.00"))
    assert "put_back" not in seen
    assert (seen["taken"], seen["not_yet_logged"]) == (D("50.00"), D("50.00"))


# ---------------------------------------------------------------------------
# The stash
# ---------------------------------------------------------------------------

def test_stash_balance_counts_every_take_from_it(db, duo):
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    _move(db, duo, "stash_in", 200, date(2026, 1, 1))
    _move(db, duo, "take", 50, date(2026, 1, 2), stash_owner=a)
    _move(db, duo, "take", 30, date(2026, 1, 3), user=b, stash_owner=a)
    _move(db, duo, "take", 999, date(2026, 1, 3), user=b)              # from the bank
    _move(db, duo, "put_back", 10, date(2026, 1, 4))
    _move(db, duo, "put_back", 7, date(2026, 1, 4), user=b)            # b's own stash
    gone = _move(db, duo, "stash_in", 1000, date(2026, 1, 5))
    gone.deleted_at = gone.created_at
    db.commit()
    assert stash_balance(db, hh, a) == D("130.00")
    assert stash_balance(db, hh, b) == D("7.00")


def test_overdrawing_your_own_stash_is_refused(client, db, authed):
    _move(db, authed, "stash_in", 20, date(2026, 1, 1))
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "take", "amount": "25", "source": authed.user_id})
    assert r.status_code == 400 and "Not enough cash in your stash" in r.text
    r = client.post("/api/v1/cash/movements", headers=_bearer(authed, authed.user_id), json={
        "kind": "take", "amount": "25", "stash_owner_id": authed.user_id})
    assert r.status_code == 400
    assert db.query(CashMovement).filter_by(kind="take").count() == 0
    # The bank has no limit.
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "take", "amount": "25", "source": "bank"})
    assert r.status_code in (200, 302)
    assert db.query(CashMovement).filter_by(kind="take").one().stash_owner_id is None


def test_take_from_a_stash_outside_the_household(client, db, authed, make_household):
    other = make_household(name="Other", username="stashother")
    _move(db, other, "stash_in", 100, date(2026, 1, 1))
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "take", "amount": "5", "source": other.user_id})
    assert r.status_code == 400
    assert stash_balance(db, other.household_id, other.user_id) == D("100.00")


def test_deleting_takes_and_additions(app, client, db, duo):
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    added = _move(db, duo, "stash_in", 100, date(2026, 1, 1))
    theirs = _move(db, duo, "take", 60, date(2026, 1, 2), user=b, stash_owner=a)
    # The stash owner sees the flatmate's take but cannot delete it.
    assert client.post(f"/cash/{theirs.id}/delete", headers=duo.headers).status_code == 403
    assert client.delete(f"/api/v1/cash/movements/{theirs.id}",
                         headers=_bearer(duo, a)).status_code == 403
    # Deleting the addition would leave the stash at -60.
    r = client.post(f"/cash/{added.id}/delete", headers=duo.headers)
    assert r.status_code == 400 and "below zero" in r.text
    # The taker may undo their take; the stash gets it back.
    member, mh = _member(app, duo)
    assert member.post(f"/cash/{theirs.id}/delete", headers=mh).status_code in (200, 302)
    assert stash_balance(db, hh, a) == D("100.00")
    assert client.post(f"/cash/{added.id}/delete", headers=duo.headers).status_code in (200, 302)
    assert stash_balance(db, hh, a) == D("0.00")


def test_list_movements_is_personal(db, duo):
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    _move(db, duo, "stash_in", 100, date(2026, 1, 1))
    _move(db, duo, "take", 10, date(2026, 1, 2), user=b, stash_owner=a)
    _move(db, duo, "take", 20, date(2026, 1, 2), user=b)
    _move(db, duo, "stash_in", 5, date(2026, 1, 2), user=b)
    assert sorted(m.amount for m in list_movements(db, hh, a)) == [D("10"), D("100")]
    assert sorted(m.amount for m in list_movements(db, hh, b)) == [D("5"), D("10"), D("20")]


def test_cash_page_offers_every_stash_and_the_bank(client, db, duo):
    page = client.get("/cash").text
    assert "From: my stash" in page and "From: Flatmate's stash" in page
    assert 'value="bank"' in page
    assert "Your stash" in page and "Still have" in page


# ---------------------------------------------------------------------------
# "I took this from my stash"
# ---------------------------------------------------------------------------

def _user(db, ctx):
    from app.models import Bucket, User
    return db.get(User, ctx.user_id), db.get(Bucket, ctx.bucket_id)


def test_take_and_spend_links_and_nets_out(db, authed):
    hh, me = authed.household_id, authed.user_id
    food = _category(db, authed, "Groceries")
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    user, bucket = _user(db, authed)
    txn = withdraw_and_spend(db, user=user, household_id=hh, bucket=bucket, amount="40",
                             when=date(2026, 1, 5), category_id=food.id, notes="market")
    mv = db.query(CashMovement).filter_by(transaction_id=txn.id).one()
    assert (mv.kind, mv.amount, mv.stash_owner_id, mv.user_id) == ("take", D("40"), me, me)
    assert txn.payment_method == "cash"
    assert stash_balance(db, hh, me) == D("60.00")
    assert _nyl(db, authed) == D("0.00")
    assert _cats(_insights(db, authed)) == {"Groceries": D("40.00")}


def test_take_and_spend_from_the_bank(db, authed):
    user, bucket = _user(db, authed)
    txn = withdraw_and_spend(db, user=user, household_id=authed.household_id, bucket=bucket,
                             amount="12", source="bank", when=date(2026, 1, 5))
    mv = db.query(CashMovement).filter_by(transaction_id=txn.id).one()
    assert mv.stash_owner_id is None
    assert stash_balance(db, authed.household_id, authed.user_id) == D("0.00")


def test_take_and_spend_edit_sync_and_delete_cascade(client, db, authed):
    hh, me = authed.household_id, authed.user_id
    _move(db, authed, "stash_in", 60, date(2026, 1, 1))
    user, bucket = _user(db, authed)
    txn = withdraw_and_spend(db, user=user, household_id=hh, bucket=bucket, amount="40",
                             when=date(2026, 1, 5))
    mv = db.query(CashMovement).filter_by(transaction_id=txn.id).one()
    form = {"bucket_id": authed.bucket_id, "transaction_date": "2026-01-06", "amount": "55",
            "type": "expense", "paid_by": me, "payment_method": "cash"}
    r = client.post(f"/transactions/{txn.id}/edit", data=form, headers=authed.headers)
    assert r.status_code == 302, r.text
    db.refresh(mv)
    assert mv.amount == D("55") and mv.movement_date == date(2026, 1, 6) and mv.deleted_at is None
    assert stash_balance(db, hh, me) == D("5.00")
    # More than the stash holds: refused, nothing changes.
    r = client.post(f"/transactions/{txn.id}/edit", data={**form, "amount": "61"},
                    headers=authed.headers)
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Transaction, txn.id).amount == D("55")
    assert "Taken for this expense" in client.get(f"/transactions/{txn.id}/edit").text
    # Deleting the expense takes the take with it, and the stash gets it back.
    r = client.post(f"/transactions/{txn.id}/delete", headers=authed.headers)
    assert r.status_code in (200, 302)
    db.refresh(mv)
    assert mv.deleted_at is not None
    assert stash_balance(db, hh, me) == D("60.00")


def test_switching_away_from_cash_drops_the_take(client, db, authed):
    user, bucket = _user(db, authed)
    txn = withdraw_and_spend(db, user=user, household_id=authed.household_id, bucket=bucket,
                             amount="12", source="bank", when=date(2026, 1, 5))
    form = {"bucket_id": authed.bucket_id, "transaction_date": "2026-01-05", "amount": "12",
            "type": "expense", "paid_by": authed.user_id, "payment_method": "card"}
    assert client.post(f"/transactions/{txn.id}/edit", data=form,
                       headers=authed.headers).status_code == 302
    assert db.query(CashMovement).filter_by(transaction_id=txn.id).one().deleted_at is not None


def test_wizard_took_cash_checkbox(client, db, authed):
    _move(db, authed, "stash_in", 50, date(2026, 1, 1))
    form = {"bucket_id": authed.bucket_id, "transaction_date": "2026-01-05", "amount": "18",
            "type": "expense", "paid_by": authed.user_id, "payment_method": "cash",
            "took_cash": "on", "take_from": "stash"}
    r = client.post("/transactions", headers=authed.headers, data=form)
    assert r.status_code == 302, r.text
    txn = db.query(Transaction).one()
    mv = db.query(CashMovement).filter_by(kind="take").one()
    assert (mv.transaction_id, mv.stash_owner_id, mv.amount) == (txn.id, authed.user_id, D("18"))
    # From the bank.
    r = client.post("/transactions", headers=authed.headers, data={**form, "take_from": "bank"})
    assert r.status_code == 302, r.text
    assert db.query(CashMovement).filter_by(kind="take", stash_owner_id=None).count() == 1
    # More than the stash holds: nothing is saved.
    r = client.post("/transactions", headers=authed.headers, data={**form, "amount": "40"})
    assert r.status_code == 400
    assert db.query(Transaction).count() == 2
    page = client.get("/transactions/new").text
    assert "I took this from my stash" in page and "pocket" not in page.lower()


def test_wizard_card_ignores_took_cash(client, db, authed):
    r = client.post("/transactions", headers=authed.headers, data={
        "bucket_id": authed.bucket_id, "transaction_date": "2026-01-05", "amount": "18",
        "type": "expense", "paid_by": authed.user_id, "payment_method": "card",
        "took_cash": "on", "take_from": "stash"})
    assert r.status_code == 302, r.text
    assert db.query(CashMovement).count() == 0


def test_api_transaction_took_cash(client, db, authed):
    h = _bearer(authed, authed.user_id)
    r = client.post("/api/v1/transactions", headers=h, json={
        "bucket_id": authed.bucket_id, "amount": "25", "transaction_date": "2026-01-05",
        "payment_method": "cash", "took_cash": True, "take_from": "bank"})
    assert r.status_code == 201, r.text
    assert "cash_pocket" not in r.json()
    assert db.query(CashMovement).one().transaction_id == r.json()["id"]
    r = client.post("/api/v1/transactions", headers=h, json={
        "bucket_id": authed.bucket_id, "amount": "25", "payment_method": "card",
        "took_cash": True})
    assert r.status_code == 422
    r = client.post("/api/v1/transactions", headers=h, json={
        "bucket_id": authed.bucket_id, "amount": "25", "payment_method": "cash",
        "took_cash": True, "take_from": "sideways"})
    assert r.status_code == 422


def test_took_cash_is_the_payers_own(client, db, duo):
    h = _bearer(duo, duo.user_id)
    r = client.post("/api/v1/transactions", headers=h, json={
        "bucket_id": duo.bucket_id, "amount": "10", "transaction_date": "2026-01-05",
        "payment_method": "cash", "paid_by": duo.partner_id, "took_cash": True,
        "take_from": "bank"})
    assert r.status_code == 400, r.text
    assert db.query(Transaction).count() == 0 and db.query(CashMovement).count() == 0


def test_took_cash_needs_a_single_payer(client, db, duo):
    h = _bearer(duo, duo.user_id)
    r = client.post("/api/v1/transactions", headers=h, json={
        "bucket_id": duo.bucket_id, "amount": "1100", "transaction_date": "2026-01-05",
        "payment_method": "cash", "payer_mode": "own_share", "took_cash": True,
        "splits": [{"user_id": duo.user_id, "amount": "800"},
                   {"user_id": duo.partner_id, "amount": "300"}]})
    assert r.status_code == 422, r.text
    assert db.query(CashMovement).count() == 0

    # Nor can an existing one become own share.
    user, bucket = _user(db, duo)
    txn = withdraw_and_spend(db, user=user, household_id=duo.household_id, bucket=bucket,
                             amount="1100", source="bank", when=date(2026, 1, 5))
    r = client.put(f"/api/v1/transactions/{txn.id}", headers=h, json={
        "bucket_id": duo.bucket_id, "amount": "1100", "transaction_date": "2026-01-05",
        "payment_method": "cash", "payer_mode": "own_share",
        "splits": [{"user_id": duo.user_id, "amount": "800"},
                   {"user_id": duo.partner_id, "amount": "300"}]})
    assert r.status_code in (400, 422), r.text
    db.refresh(txn)
    assert txn.payer_mode == "single"
    # Bulk "each paid their own share" skips it too, even with matching splits.
    db.add_all([TransactionSplit(transaction_id=txn.id, user_id=duo.user_id, amount=D("800")),
                TransactionSplit(transaction_id=txn.id, user_id=duo.partner_id, amount=D("300"))])
    db.commit()
    r = client.post("/transactions/bulk-payer", headers=duo.headers, data={
        "ids": [txn.id], "payer": "__own_share__", "return_query": ""})
    assert r.headers["location"].endswith("updated=0&skipped=0&skipped_take=1")
    page = client.get(r.headers["location"]).text
    assert "1 skipped: cash was taken for it, so it stays paid by whoever took it" in page


def test_cash_page_take_and_spend(client, db, authed):
    food = _category(db, authed, "Market")
    _move(db, authed, "stash_in", 50, date(2026, 1, 1))
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "take", "amount": "33", "movement_date": "2026-01-07",
        "source": authed.user_id, "spend_bucket_id": authed.bucket_id,
        "category_id": food.id, "note": "veg"})
    assert r.status_code in (200, 302), r.text
    txn = db.query(Transaction).one()
    assert (txn.payment_method, txn.amount, txn.category_id, txn.notes) == (
        "cash", D("33"), food.id, "veg")
    mv = db.query(CashMovement).filter_by(kind="take").one()
    assert mv.transaction_id == txn.id and mv.stash_owner_id == authed.user_id
    assert _nyl(db, authed) == D("0.00")


def test_take_and_spend_needs_your_own_stash_or_the_bank(client, db, duo):
    _move(db, duo, "stash_in", 50, date(2026, 1, 1), user=duo.partner_id)
    r = client.post("/cash/add", headers=duo.headers, data={
        "kind": "take", "amount": "5", "source": duo.partner_id,
        "spend_bucket_id": duo.bucket_id})
    assert r.status_code == 400
    r = client.post("/api/v1/cash/movements", headers=_bearer(duo, duo.user_id), json={
        "kind": "take", "amount": "5", "stash_owner_id": duo.partner_id,
        "spend_bucket_id": duo.bucket_id})
    assert r.status_code == 400
    assert db.query(Transaction).count() == 0


def test_api_movement_take_and_spend(client, db, authed):
    h = _bearer(authed, authed.user_id)
    r = client.post("/api/v1/cash/movements", headers=h, json={
        "kind": "take", "amount": "21", "movement_date": "2026-01-07",
        "spend_bucket_id": authed.bucket_id, "note": "lunch"})
    assert r.status_code == 201, r.text
    txn = db.query(Transaction).one()
    assert r.json()["transaction_id"] == txn.id and txn.notes == "lunch"
    assert r.json()["stash_owner_id"] is None


def test_payerless_cash_expense_is_the_submitters(client, db, authed):
    """The form allows a blank payer; cash still has to come out of a wallet."""
    _move(db, authed, "take", 50, date(2026, 1, 2))
    form = {"bucket_id": authed.bucket_id, "transaction_date": "2026-01-03", "amount": "20",
            "type": "expense", "paid_by": "", "payment_method": "cash", "notes": "coffee"}
    assert client.post("/transactions", headers=authed.headers, data=form).status_code == 302
    assert db.query(Transaction).filter_by(notes="coffee").one().paid_by == authed.user_id
    assert _nyl(db, authed) == D("30.00")
    assert _insights(db, authed)["summary"]["total_spent"] == D("50.00")
    # A card expense may still be left without a payer.
    form.update(payment_method="card", notes="card")
    assert client.post("/transactions", headers=authed.headers, data=form).status_code == 302
    assert db.query(Transaction).filter_by(notes="card").one().paid_by is None


# ---------------------------------------------------------------------------
# The wizard starts on the method you used last
# ---------------------------------------------------------------------------

def _init(page):
    import html
    import json
    import re

    raw = re.search(r"data-init='(.*?)'>", page, re.S).group(1)
    return json.loads(html.unescape(raw))


def test_wizard_defaults_to_your_last_payment_method(client, db, duo):
    assert _init(client.get("/transactions/new").text)["paymentMethod"] == "card"
    _cash(db, duo, 5, date(2026, 1, 3), method="cash")
    _cash(db, duo, 5, date(2026, 1, 1), payer=duo.partner_id, method="transfer")
    assert _init(client.get("/transactions/new").text)["paymentMethod"] == "cash"


# ---------------------------------------------------------------------------
# Still have
# ---------------------------------------------------------------------------

def test_still_have_html_and_api(client, db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 2))
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "still_have", "amount": "42.50", "movement_date": "2026-01-31"})
    assert r.status_code in (200, 302), r.text
    mv = db.query(CashMovement).filter_by(kind="still_have").one()
    assert mv.amount == D("42.50") and mv.category_id is None
    page = client.get("/cash?month=2026-01")
    assert "Still have: €42.50" in page.text
    assert _nyl(db, authed) == D("57.50")

    h = _bearer(authed, authed.user_id)
    r = client.post("/api/v1/cash/movements", headers=h, json={
        "kind": "still_have", "amount": "50", "movement_date": "2026-01-31"})
    assert r.status_code == 201 and r.json()["kind"] == "still_have"
    r = client.get("/api/v1/cash/summary?month=2026-01", headers=h)
    assert r.json()["wallet"]["still_have"] == 50.0


def test_still_have_zero_records_an_empty_wallet(client, db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 1))
    _move(db, authed, "still_have", 100, date(2026, 1, 10))
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "still_have", "amount": "0", "movement_date": "2026-01-31"})
    assert r.status_code in (200, 302), r.text
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["still_have"] == D("0.00") and jan["not_yet_logged"] == D("100.00")
    assert feb["carried"] == D("0.00")

    h = _bearer(authed, authed.user_id)
    r = client.post("/api/v1/cash/movements", headers=h, json={
        "kind": "still_have", "amount": "0", "movement_date": "2026-01-31"})
    assert r.status_code == 201, r.text
    # Only a still_have may be zero.
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "take", "amount": "0", "movement_date": "2026-01-31"})
    assert r.status_code == 400
    r = client.post("/api/v1/cash/movements", headers=h, json={"kind": "stash_in", "amount": "0"})
    assert r.status_code == 422
    assert 'min="0"' in client.get("/cash").text


def test_legacy_kinds_cannot_be_logged(client, db, authed):
    for kind in ("in", "out", "count", "sideways"):
        r = client.post("/cash/add", headers=authed.headers, data={"kind": kind, "amount": "5"})
        assert r.status_code == 400, kind
        r = client.post("/api/v1/cash/movements", headers=_bearer(authed, authed.user_id),
                        json={"kind": kind, "amount": "5"})
        assert r.status_code == 422, kind
    assert db.query(CashMovement).count() == 0


# ---------------------------------------------------------------------------
# Insights: "Cash (not yet logged)", household-visible
# ---------------------------------------------------------------------------

@pytest.fixture()
def cash_mix(db, duo):
    _move(db, duo, "stash_in", 500, date(2026, 1, 1))                      # never spending
    _move(db, duo, "take", 50, date(2026, 1, 2), stash_owner=duo.user_id)    # owner
    _move(db, duo, "take", 30, date(2026, 1, 2), user=duo.partner_id)        # member, bank
    return duo


def test_insights_household_counts_everyones_not_logged(db, cash_mix):
    data = _insights(db, cash_mix)
    assert data["summary"]["cash_not_logged"] == D("80.00")
    assert _cats(data)[NOT_LOGGED] == D("80.00")


def test_insights_person_filter(db, cash_mix):
    me, them = cash_mix.user_id, cash_mix.partner_id
    assert _insights(db, cash_mix, paid_by=me)["summary"]["cash_not_logged"] == D("50.00")
    assert _insights(db, cash_mix, paid_by=them)["summary"]["cash_not_logged"] == D("30.00")


def test_insights_widgets_that_include_not_logged(db, cash_mix):
    data = _insights(db, cash_mix)
    assert data["kpis"]["total"] == D("80.00")
    assert {r["method"]: r["amount"] for r in data["by_method"]} == {"cash": D("80.00")}
    assert data["cash_share"] == D("100.0")
    assert data["bucket_breakdown"] == []      # no bucket
    assert data["net"] == D("-80.00")
    # A bucket filter leaves it out entirely.
    filtered = _insights(db, cash_mix, bucket_ids=cash_mix.bucket_id)
    assert filtered["summary"]["cash_not_logged"] == D("0.00")
    assert filtered["summary"]["total_spent"] == D("0.00")


def test_insights_trend_includes_not_logged(db, authed):
    from app.clock import local_today

    _move(db, authed, "take", 45, local_today())
    data = build_insights(db, authed.household_id, InsightFilters())
    assert data["trend"][-1]["total"] == D("45.00")
    assert data["summary"]["cash_not_logged"] == D("45.00")


def test_insights_html_and_api_for_another_member(app, client, db, cash_mix):
    member, _ = _member(app, cash_mix)
    r = member.get(f"/insights?preset=custom&start_date=2026-01-01&end_date=2026-01-31"
                   f"&paid_by={cash_mix.user_id}")
    assert r.status_code == 200
    assert NOT_LOGGED in r.text and "500.00" not in r.text
    h = _bearer(cash_mix, cash_mix.partner_id)
    r = client.get(f"/api/v1/insights?preset=custom&start_date=2026-01-01&end_date=2026-01-31"
                   f"&paid_by={cash_mix.user_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["cash_not_logged"] == 50.0 and "cash_untracked" not in r.json()


def test_me_and_dashboard_show_not_logged(client, db, authed):
    from app.clock import local_today

    _move(db, authed, "stash_in", 777, local_today(), note="hidden-savings")
    _move(db, authed, "take", 45, local_today())
    me = client.get("/me").text
    assert NOT_LOGGED in me.split("share by category", 1)[1]
    assert "Not yet logged" in me and "777" not in me
    dash = client.get("/dashboard").text
    assert "45.00 cash not yet logged" in dash and "777" not in dash


def test_forecast_includes_not_logged_cash(db, duo):
    from app.clock import local_today

    today = local_today()
    for back in (1, 2, 3):
        y, m = today.year, today.month - back
        while m <= 0:
            m, y = m + 12, y - 1
        _move(db, duo, "take", 300, date(y, m, 10))
        _move(db, duo, "stash_in", 999, date(y, m, 10))    # never spending
    _move(db, duo, "take", 50, today)
    for paid_by in ("", duo.partner_id):
        forecast = build_insights(db, duo.household_id, InsightFilters(paid_by=paid_by))["forecast"]
        assert forecast["baseline"] == D("300.00"), paid_by
        assert forecast["spend_so_far"] == D("50.00"), paid_by


# ---------------------------------------------------------------------------
# Regressions carried over: carry, later logging, partial windows
# ---------------------------------------------------------------------------

def test_mid_month_still_have_carries_what_is_left(db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 1))
    _move(db, authed, "still_have", 100, date(2026, 1, 5))
    _cash(db, authed, 30, date(2026, 1, 10))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["not_yet_logged"] == D("0.00") and jan["still_have"] == D("70.00")
    assert feb["carried"] == D("70.00") and feb["not_yet_logged"] == D("70.00")
    # Only 100 was ever taken: 30 logged + 70 not yet logged, nothing twice.
    assert _insights(db, authed, end="2026-02-28")["summary"]["total_spent"] == D("100.00")


def test_put_back_after_a_mid_month_still_have_is_not_carried(db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 1))
    _move(db, authed, "still_have", 100, date(2026, 1, 5))
    _move(db, authed, "put_back", 20, date(2026, 1, 6))
    _move(db, authed, "take", 10, date(2026, 1, 7))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["still_have"] == D("90.00") and jan["not_yet_logged"] == D("0.00")
    assert feb["carried"] == D("90.00")


def test_cash_logged_next_month_is_not_counted_twice(db, authed):
    """Take 100 in January, log 60 then and 40 in February: 100 spent."""
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _cash(db, authed, 60, date(2026, 1, 10))
    _cash(db, authed, 40, date(2026, 2, 5))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["not_yet_logged"] == D("0.00") and feb["not_yet_logged"] == D("0.00")
    summary = _insights(db, authed, end="2026-02-28")["summary"]
    assert summary["total_spent"] == D("100.00") and summary["cash_not_logged"] == D("0.00")


def test_later_overspend_only_uses_up_what_was_left(db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _cash(db, authed, 30, date(2026, 1, 10))
    _cash(db, authed, 50, date(2026, 2, 5))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["not_yet_logged"] == D("20.00") and feb["not_yet_logged"] == D("0.00")
    assert _insights(db, authed, end="2026-02-28")["summary"]["total_spent"] == D("100.00")


def test_later_overspend_stops_at_a_still_have(db, authed):
    """A still_have says what was really left; later logging cannot undo it."""
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _move(db, authed, "still_have", 0, date(2026, 1, 31))
    _cash(db, authed, 40, date(2026, 2, 5))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["not_yet_logged"] == D("100.00") and feb["not_yet_logged"] == D("0.00")


def test_partial_window_counts_not_logged_cash_from_its_takes(db, authed):
    _move(db, authed, "take", 50, date(2026, 1, 3))
    _move(db, authed, "take", 30, date(2026, 1, 20))

    def nyl(start, end):
        return _insights(db, authed, start=start, end=end)["summary"]["cash_not_logged"]

    assert nyl("2026-01-01", "2026-01-31") == D("80.00")
    assert nyl("2026-01-01", "2026-01-10") == D("50.00")
    assert nyl("2026-01-11", "2026-01-31") == D("30.00")
    assert nyl("2025-12-28", "2026-01-02") == D("0.00")


def test_partial_windows_add_up_to_the_month(db, authed):
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _cash(db, authed, 60, date(2026, 1, 20))
    first = _insights(db, authed, start="2026-01-01", end="2026-01-10")["summary"]
    rest = _insights(db, authed, start="2026-01-11", end="2026-01-31")["summary"]
    assert first["total_spent"] == D("40.00") and first["cash_not_logged"] == D("40.00")
    assert rest["total_spent"] == D("60.00") and rest["cash_not_logged"] == D("0.00")


def test_carried_cash_counts_from_the_first_of_the_month(db, authed):
    _move(db, authed, "still_have", 40, date(2025, 12, 31))
    assert _insights(db, authed, start="2026-01-01", end="2026-01-04")[
        "summary"]["cash_not_logged"] == D("40.00")
    assert _insights(db, authed, start="2026-01-05", end="2026-01-31")[
        "summary"]["cash_not_logged"] == D("0.00")


def test_kpi_previous_window_does_not_take_a_whole_month_of_cash(db, authed):
    """On 6 October, 1-6 Oct is compared with 25-30 Sep, not with all of September."""
    _move(db, authed, "take", 300, date(2026, 9, 3))
    _move(db, authed, "take", 50, date(2026, 10, 2))
    data = build_insights(db, authed.household_id, InsightFilters(
        preset="this_month", today=date(2026, 10, 6)))
    assert data["kpis"]["total"] == D("50.00")
    assert data["kpis"]["previous_total"] == D("0.00")


# ---------------------------------------------------------------------------
# The migration
# ---------------------------------------------------------------------------

def _seeded_db(tmp_path, name, revision):
    """A database migrated to ``revision`` with one household and user."""
    import uuid

    from sqlalchemy import create_engine, text

    from tests.test_migrations import _alembic, _db_url

    url = _db_url(tmp_path, name)
    assert _alembic(["upgrade", revision], url).returncode == 0
    engine = create_engine(url)
    ids = {k: str(uuid.uuid4()) for k in ("hh", "user")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO households (id, name, default_currency) "
                          "VALUES (:i, 'H', 'EUR')"), {"i": ids["hh"]})
        conn.execute(text(
            "INSERT INTO users (id, username, display_name, password_hash, session_version, "
            "totp_enabled, email_verified) VALUES (:i, 'u', 'U', 'x', 0, false, false)"
        ), {"i": ids["user"]})

    def movement(kind, deleted=False, **extra):
        cols = {"id": str(uuid.uuid4()), "household_id": ids["hh"], "user_id": ids["user"],
                "kind": kind, "amount": 30, "currency": "EUR", "movement_date": "2026-01-05",
                "deleted_at": "2026-01-06 00:00:00" if deleted else None, **extra}
        with engine.begin() as conn:
            conn.execute(text(
                f"INSERT INTO cash_movements ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})"), cols)
        return cols["id"]

    return url, engine, movement, ids


def _kinds(engine):
    from sqlalchemy import text

    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, kind FROM cash_movements")).all())


def test_migration_converts_legacy_rows_and_reverses(tmp_path):
    from sqlalchemy import inspect

    from tests.test_migrations import _alembic

    url, engine, movement, _ids = _seeded_db(tmp_path, "stash-up.db", "b6c7d8e9f0a1")
    withdrawn, spent = movement("in"), movement("out")
    assert _alembic(["upgrade", "head"], url).returncode == 0
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("cash_movements")}
    assert {"stash_owner_id", "transaction_id"} <= cols and "pocket" not in cols
    assert "cash_pocket" not in {c["name"] for c in insp.get_columns("transactions")}
    assert {"ix_cash_movements_transaction_id", "ix_cash_movements_stash_owner_id"} <= {
        i["name"] for i in insp.get_indexes("cash_movements")}
    assert _kinds(engine) == {withdrawn: "take", spent: "out"}
    # A bank take is a legacy withdrawal again after a downgrade.
    down = _alembic(["downgrade", "b6c7d8e9f0a1"], url)
    assert down.returncode == 0, down.stderr
    assert _kinds(engine) == {withdrawn: "in", spent: "out"}
    assert "stash_owner_id" not in {c["name"] for c in inspect(engine).get_columns("cash_movements")}
    assert _alembic(["upgrade", "head"], url).returncode == 0
    engine.dispose()


@pytest.mark.parametrize("kind,own_stash", [
    ("stash_in", False), ("put_back", False), ("still_have", False), ("take", True),
])
def test_downgrade_refuses_while_stash_rows_exist(tmp_path, kind, own_stash):
    from sqlalchemy import inspect

    from tests.test_migrations import _alembic

    url, engine, movement, ids = _seeded_db(tmp_path, f"down-{kind}.db", "head")
    movement(kind, **({"stash_owner_id": ids["user"]} if own_stash else {}))
    down = _alembic(["downgrade", "b6c7d8e9f0a1"], url)
    assert down.returncode != 0
    assert "Cannot downgrade" in down.stderr
    assert "stash_owner_id" in {c["name"] for c in inspect(engine).get_columns("cash_movements")}
    engine.dispose()


def test_downgrade_ignores_deleted_stash_rows(tmp_path):
    from tests.test_migrations import _alembic

    url, engine, movement, _ids = _seeded_db(tmp_path, "down-deleted.db", "head")
    gone = movement("still_have", deleted=True)
    movement("stash_in", deleted=True)
    movement("take")
    down = _alembic(["downgrade", "b6c7d8e9f0a1"], url)
    assert down.returncode == 0, down.stderr
    assert _kinds(engine)[gone] == "count"      # fits the old VARCHAR(8)
    engine.dispose()


# ---------------------------------------------------------------------------
# A linked take stays its taker's: payer, amount, privacy
# ---------------------------------------------------------------------------

def _linked_expense(db, ctx, amount="40", stash=100):
    _move(db, ctx, "stash_in", stash, date(2026, 1, 1))
    user, bucket = _user(db, ctx)
    return withdraw_and_spend(db, user=user, household_id=ctx.household_id, bucket=bucket,
                              amount=amount, when=date(2026, 1, 5))


def _put(ctx, txn, **fields):
    return {"bucket_id": ctx.bucket_id, "amount": "40", "transaction_date": "2026-01-05",
            "payment_method": "cash", **fields}


def test_payer_of_an_expense_cash_was_taken_for_stays_the_taker(app, client, db, duo):
    """The take is the payer's own: moving the expense to another payer would
    credit them for cash that came out of the taker's wallet and stash."""
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    txn = _linked_expense(db, duo)
    for h in (_bearer(duo, a), _bearer(duo, b)):
        r = client.put(f"/api/v1/transactions/{txn.id}", headers=h, json=_put(duo, txn, paid_by=b))
        assert r.status_code == 400, r.text
    form = {"bucket_id": duo.bucket_id, "transaction_date": "2026-01-05", "amount": "40",
            "type": "expense", "paid_by": b, "payment_method": "cash"}
    assert client.post(f"/transactions/{txn.id}/edit", data=form,
                       headers=duo.headers).status_code == 400
    # Bulk "who paid" skips it.
    r = client.post("/transactions/bulk-payer", headers=duo.headers, data={
        "ids": [txn.id], "payer": b, "return_query": ""})
    assert r.headers["location"].endswith("updated=0&skipped=0&skipped_take=1")
    db.expire_all()
    assert db.get(Transaction, txn.id).paid_by == a
    assert stash_balance(db, hh, a) == D("60.00")
    # No longer cash: the take goes, and so does the rule.
    r = client.put(f"/api/v1/transactions/{txn.id}", headers=_bearer(duo, a),
                   json=_put(duo, txn, paid_by=b, payment_method="card"))
    assert r.status_code == 200, r.text
    assert stash_balance(db, hh, a) == D("100.00")


def test_only_the_taker_changes_what_an_expense_took_from_their_stash(client, db, duo):
    """Another member editing the amount would move the owner's stash and,
    by accept/refuse, reveal its balance: refused the same way either way."""
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    txn = _linked_expense(db, duo, amount="10", stash=200)
    h = _bearer(duo, b)
    answers = set()
    for amount in ("190", "201", "5"):
        r = client.put(f"/api/v1/transactions/{txn.id}", headers=h,
                       json=_put(duo, txn, amount=amount, paid_by=a))
        answers.add((r.status_code, r.json()["detail"]))
    assert len(answers) == 1 and answers.pop()[0] == 403
    assert stash_balance(db, hh, a) == D("190.00")
    # Anything else about the expense is still theirs to fix.
    r = client.put(f"/api/v1/transactions/{txn.id}", headers=h,
                   json=_put(duo, txn, amount="10", paid_by=a, notes="kiosk"))
    assert r.status_code == 200, r.text
    # The taker may.
    r = client.put(f"/api/v1/transactions/{txn.id}", headers=_bearer(duo, a),
                   json=_put(duo, txn, amount="30", paid_by=a))
    assert r.status_code == 200, r.text
    assert stash_balance(db, hh, a) == D("170.00")


def test_cash_logged_after_a_still_have_does_not_reach_past_it(db, authed):
    """Logged after the still_have beyond what it held came from somewhere
    unrecorded: it must not use up the not-yet-logged cash before it."""
    _move(db, authed, "take", 100, date(2026, 1, 2))
    _move(db, authed, "still_have", 30, date(2026, 2, 10))
    _cash(db, authed, 50, date(2026, 2, 20))
    jan, feb = monthly_breakdown(db, authed.household_id, authed.user_id, JAN, FEB)
    assert jan["not_yet_logged"] == D("70.00") and feb["not_yet_logged"] == D("0.00")
    assert feb["still_have"] == D("0.00")


def test_cash_logged_after_a_still_have_in_the_same_month(db, authed):
    _move(db, authed, "take", 100, date(2026, 2, 1))
    _move(db, authed, "still_have", 30, date(2026, 2, 10))
    _cash(db, authed, 50, date(2026, 2, 20))
    assert _nyl(db, authed, month=FEB) == D("70.00")


def test_others_never_see_a_negative_taken(client, db, duo):
    """A put back of carried-in cash would show as negative takes, i.e. the
    put-back amount; others see 0 instead."""
    hh, a, b = duo.household_id, duo.user_id, duo.partner_id
    _move(db, duo, "take", 100, date(2026, 1, 2))
    _move(db, duo, "still_have", 60, date(2026, 1, 31))
    _move(db, duo, "put_back", 30, date(2026, 2, 3))
    assert wallet_summary(db, hh, a, FEB, FEB_END, viewer_id=b)["taken"] == D("0.00")
    assert wallet_summary(db, hh, a, FEB, FEB_END, viewer_id=a)["put_back"] == D("30.00")
    r = client.get("/api/v1/cash/summary", headers=_bearer(duo, b),
                   params={"month": "2026-02", "member_id": a})
    assert r.status_code == 200 and D(str(r.json()["wallet"]["taken"])) == D("0")


def test_wizard_default_ignores_bill_payments(client, db, duo):
    """A bill paid in the background (auto-pay) is not the user's choice."""
    from app.clock import utcnow_naive
    from app.models import BillOccurrence, RecurringBill
    from app.services.bills import generate_occurrences, pay_occurrence

    _cash(db, duo, 5, date(2026, 1, 3), method="cash")
    bill = RecurringBill(household_id=duo.household_id, bucket_id=duo.bucket_id, name="Gym",
                         amount=30, currency="EUR", start_date=date(2026, 1, 1),
                         interval_months=1, total_occurrences=1, paid_by_default=duo.user_id)
    db.add(bill)
    db.flush()
    generate_occurrences(db, bill)
    occ = db.query(BillOccurrence).filter_by(bill_id=bill.id).one()
    pay_occurrence(db, occ, amount=30, paid_by=duo.user_id, paid_on=utcnow_naive())
    db.commit()
    assert db.query(Transaction).filter_by(payment_method="card").count() == 1
    assert _init(client.get("/transactions/new").text)["paymentMethod"] == "cash"


def test_cash_page_spend_needs_a_bucket(client, db, authed):
    from app.models import Bucket, BucketStatus

    _move(db, authed, "stash_in", 50, date(2026, 1, 1))
    db.get(Bucket, authed.bucket_id).status = BucketStatus.archived
    db.commit()
    assert "Spent it straight away" not in client.get("/cash").text
    r = client.post("/cash/add", headers=authed.headers, data={
        "kind": "take", "amount": "20", "source": authed.user_id, "spend": "on"})
    assert r.status_code == 400 and "bucket" in r.text.lower()
    assert db.query(CashMovement).filter_by(kind="take").count() == 0


def test_private_cash_page_is_never_cached(client, db, authed):
    """The stash card is the viewer's alone: the service worker must not keep
    it for whoever opens the app offline next."""
    from pathlib import Path

    assert "no-store" in client.get("/cash").headers["cache-control"]
    r = client.post("/cash/add", headers={**authed.headers, "HX-Request": "true"},
                    data={"kind": "stash_in", "amount": "5"})
    assert r.status_code == 200 and "no-store" in r.headers["cache-control"]
    sw = Path("static/sw.js").read_text()
    assert "no-store" in sw
