"""
The stash recount (``stash_count``): the owner says what is physically in
their stash and the server stores the signed correction ``counted − balance``
(spec 2026-10-08-cash-design §3.1).

A recount changes the stash only: never a wallet, never Insights, and nobody
but the owner ever receives it.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models import CashMovement
from app.services import record_stash_count, stash_balance
from tests.test_cash_stash import _bearer, _insights, _move
from tests.test_isolation import _add_member_user

D = Decimal
URL = "/api/v1/cash/movements"


@pytest.fixture()
def duo(db, authed):
    """The logged-in owner plus a second member (with login credentials)."""
    member, secret = _add_member_user(db, authed.household_id, "flatmate")
    authed.partner_id = member.id
    authed.partner_secret = secret
    return authed


def _count(client, ctx, counted, *, user=None, **extra):
    return client.post(
        URL,
        headers=_bearer(ctx, user or ctx.user_id),
        json={"kind": "stash_count", "amount": counted, "movement_date": "2026-01-15", **extra},
    )


def _balance(db, ctx, user=None):
    return stash_balance(db, ctx.household_id, user or ctx.user_id)


def test_count_below_the_balance_stores_a_negative_correction(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    r = _count(client, authed, "80")
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "stash_count" and r.json()["amount"] == -20.0
    row = db.query(CashMovement).filter_by(kind="stash_count").one()
    assert row.amount == D("-20") and row.user_id == authed.user_id
    assert row.stash_owner_id is None and row.category_id is None
    assert _balance(db, authed) == D("80.00")


def test_count_above_the_balance_stores_a_positive_correction(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    assert _count(client, authed, "130").json()["amount"] == 30.0
    assert _balance(db, authed) == D("130.00")


def test_count_that_matches_stores_a_zero_row(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    r = _count(client, authed, "100.00")
    assert r.status_code == 201 and r.json()["amount"] == 0.0
    assert db.query(CashMovement).filter_by(kind="stash_count").count() == 1
    assert _balance(db, authed) == D("100.00")


def test_count_of_zero_is_accepted(client, db, authed):
    _move(db, authed, "stash_in", 40, date(2026, 1, 1))
    r = _count(client, authed, "0")
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == -40.0
    assert _balance(db, authed) == D("0.00")


def test_count_fixes_a_stash_others_overdrew(client, db, duo):
    _move(db, duo, "stash_in", 10, date(2026, 1, 1))
    _move(db, duo, "take", 30, date(2026, 1, 2), user=duo.partner_id, stash_owner=duo.user_id)
    assert _balance(db, duo) == D("-20.00")
    assert _count(client, duo, "0").json()["amount"] == 20.0
    assert _balance(db, duo) == D("0.00")


def test_negative_count_is_rejected(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    r = _count(client, authed, "-5")
    assert r.status_code == 422
    assert "Count can't be negative" in r.text
    assert db.query(CashMovement).filter_by(kind="stash_count").count() == 0


@pytest.mark.parametrize("field", ["stash_owner_id", "spend_bucket_id", "category_id"])
def test_count_rejects_take_only_fields(client, db, authed, field):
    value = authed.bucket_id if field == "spend_bucket_id" else authed.user_id
    r = _count(client, authed, "10", **{field: value})
    assert r.status_code == 422, (field, r.text)
    assert db.query(CashMovement).count() == 0


def test_count_then_own_take_subtracts(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    _count(client, authed, "80")
    r = client.post(
        URL,
        headers=_bearer(authed, authed.user_id),
        json={"kind": "take", "amount": "30", "stash_owner_id": authed.user_id},
    )
    assert r.status_code == 201, r.text
    assert _balance(db, authed) == D("50.00")


def test_backdated_take_after_a_count_then_deleting_the_count(client, db, authed):
    """Review focus 1: the stash is all-time, so a take dated before the
    count still comes off it; deleting the count follows §3.1."""
    h = _bearer(authed, authed.user_id)
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    count = _count(client, authed, "130").json()  # +30, dated 15 Jan
    r = client.post(
        URL,
        headers=h,
        json={
            "kind": "take",
            "amount": "40",
            "stash_owner_id": authed.user_id,
            "movement_date": "2026-01-10",
        },
    )
    assert r.status_code == 201, r.text
    assert _balance(db, authed) == D("90.00")  # count 130 - later take 40
    # Freeing the +30 leaves 60 >= 0: allowed.
    assert client.delete(f"{URL}/{count['id']}", headers=h).status_code == 204
    assert _balance(db, authed) == D("60.00")


def test_deleting_a_positive_correction_that_would_go_below_zero(client, db, authed):
    h = _bearer(authed, authed.user_id)
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    up = _count(client, authed, "130").json()
    _move(db, authed, "take", 110, date(2026, 1, 20), stash_owner=authed.user_id)
    assert _balance(db, authed) == D("20.00")
    r = client.delete(f"{URL}/{up['id']}", headers=h)
    assert r.status_code == 400 and "below zero" in r.text
    assert _balance(db, authed) == D("20.00")


def test_deleting_a_negative_correction_is_always_allowed(client, db, duo):
    h = _bearer(duo, duo.user_id)
    _move(db, duo, "stash_in", 100, date(2026, 1, 1))
    down = _count(client, duo, "80").json()
    # A flatmate then overdraws it: the stash is below zero.
    _move(db, duo, "take", 130, date(2026, 1, 20), user=duo.partner_id, stash_owner=duo.user_id)
    assert _balance(db, duo) == D("-50.00")
    assert client.delete(f"{URL}/{down['id']}", headers=h).status_code == 204
    assert _balance(db, duo) == D("-30.00")


def test_deleting_a_zero_correction_is_allowed_on_a_negative_stash(client, db, duo):
    h = _bearer(duo, duo.user_id)
    _move(db, duo, "stash_in", 20, date(2026, 1, 1))
    matched = _count(client, duo, "20").json()
    assert matched["amount"] == 0.0
    _move(db, duo, "take", 30, date(2026, 1, 20), user=duo.partner_id, stash_owner=duo.user_id)
    assert _balance(db, duo) == D("-10.00")
    # It frees nothing, so the stash cannot go any lower.
    assert client.delete(f"{URL}/{matched['id']}", headers=h).status_code == 204
    assert _balance(db, duo) == D("-10.00")


def test_member_never_receives_anothers_count(client, db, duo):
    a, b = duo.user_id, duo.partner_id
    _move(db, duo, "stash_in", 100, date(2026, 1, 1))
    _move(db, duo, "stash_in", 50, date(2026, 1, 1), user=b)
    _move(db, duo, "take", 10, date(2026, 1, 2), user=b, stash_owner=a)
    hb = _bearer(duo, b)
    before = client.get("/api/v1/cash/summary?month=2026-01", headers=hb).json()
    count = _count(client, duo, "60").json()
    for q in ("", "?month=2026-01", f"?member_id={a}"):
        items = client.get(f"{URL}{q}", headers=hb).json()["items"]
        assert all(i["kind"] != "stash_count" for i in items), q
        assert count["id"] not in {i["id"] for i in items}
    after = client.get("/api/v1/cash/summary?month=2026-01", headers=hb).json()
    assert after["stash"] == before["stash"] == 50.0
    # A's view of A's wallet from B's side does not move either.
    them = client.get(f"/api/v1/cash/summary?month=2026-01&member_id={a}", headers=hb).json()
    assert them["stash"] == 50.0
    # B cannot delete it, nor learn it exists.
    assert client.delete(f"{URL}/{count['id']}", headers=hb).status_code == 404
    # And A's own count is the other way round: B's count never reaches A.
    b_count = _count(client, duo, "45", user=b).json()
    ha = _bearer(duo, a)
    items = client.get(URL, headers=ha).json()["items"]
    assert b_count["id"] not in {i["id"] for i in items}
    assert {i["id"] for i in items if i["kind"] == "stash_count"} == {count["id"]}


def test_count_changes_neither_wallet_nor_insights(client, db, duo):
    a = duo.user_id
    h = _bearer(duo, a)
    _move(db, duo, "stash_in", 200, date(2026, 1, 1))
    _move(db, duo, "take", 50, date(2026, 1, 2), stash_owner=a)
    _move(db, duo, "take", 30, date(2026, 1, 3), user=duo.partner_id)
    _move(db, duo, "still_have", 10, date(2026, 1, 25))

    def snapshot():
        mine = client.get("/api/v1/cash/summary?month=2026-01", headers=h).json()
        feb = client.get("/api/v1/cash/summary?month=2026-02", headers=h).json()
        ins = _insights(db, duo)
        return (
            mine["wallet"],
            feb["wallet"],
            ins["summary"]["cash_not_logged"],
            ins["kpis"]["total"],
        )

    before = snapshot()
    stash_before = _balance(db, duo)
    assert _count(client, duo, "300").status_code == 201
    assert _count(client, duo, "0").status_code == 201
    assert snapshot() == before
    assert before[2] == D("70.00")
    assert stash_before == D("150.00") and _balance(db, duo) == D("0.00")


def test_legacy_cash_page_renders_a_recount(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    _count(client, authed, "80")
    page = client.get("/cash?month=2026-01").text
    assert "Recounted your stash (−€20.00)" in page
    _count(client, authed, "95")
    page = client.get("/cash?month=2026-01").text
    assert "Recounted your stash (+€15.00)" in page
    # Nothing new in the forms.
    assert 'value="stash_count"' not in page


def test_legacy_form_cannot_log_a_count(client, db, authed):
    r = client.post(
        "/cash/add", headers=authed.headers, data={"kind": "stash_count", "amount": "5"}
    )
    assert r.status_code == 400
    assert db.query(CashMovement).count() == 0


def test_record_stash_count_service(db, authed):
    _move(db, authed, "stash_in", 25, date(2026, 1, 1))
    mv = record_stash_count(
        db,
        household_id=authed.household_id,
        actor_id=authed.user_id,
        counted=D("10"),
        when=date(2026, 1, 5),
        note="  under the mattress ",
    )
    assert mv.kind == "stash_count" and mv.amount == D("-15.00")
    assert mv.note == "under the mattress" and mv.currency == "EUR"
    assert _balance(db, authed) == D("10.00")
