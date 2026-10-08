"""
Polish S3: idempotent cash saves (C5), serialised recounts, and the two
wallet terms the card left out (C6).

The first test pins the ``/cash/wallets`` wire shape as it was before C6
(written and run against the untouched code): C6 only adds keys.
"""

import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.clock import utcnow_naive
from app.models import CashMovement, Transaction
from app.services import cash as cash_svc
from app.services.cash import monthly_breakdown, stash_balance, wallet_summary
from tests.conftest import TEST_DATABASE_URL
from tests.test_cash_stash import _bearer, _cash, _move
from tests.test_isolation import _add_member_user

D = Decimal
JAN, FEB, MAR = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)
JAN_END, FEB_END = date(2026, 1, 31), date(2026, 2, 28)
WALLETS = "/api/v1/cash/wallets"
MOVEMENTS = "/api/v1/cash/movements"


@pytest.fixture()
def duo(db, authed):
    member, secret = _add_member_user(db, authed.household_id, "flatmate")
    authed.partner_id = member.id
    return authed


def _type(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int | float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


PRE_C6_WALLET = {
    "carried": {"number"},
    "taken": {"number"},
    "put_back": {"number", "null"},
    "still_have": {"number", "null"},
    "spent": {"number"},
    "logged": {"number"},
    "outs": {"number"},
    "not_yet_logged": {"number"},
}


def test_wallets_wire_shape_before_c6_is_kept(client, db, duo):
    a, b = duo.user_id, duo.partner_id
    _move(db, duo, "stash_in", 100, JAN)
    _move(db, duo, "take", 50, date(2026, 1, 2), stash_owner=a)
    _move(db, duo, "put_back", 20, date(2026, 1, 3))
    _move(db, duo, "still_have", 7, date(2026, 1, 20), user=b)
    raw = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(duo, a))
    body = raw.json()
    assert set(body) == {"month", "stash", "members"}
    assert '"taken":50.0' in raw.text
    for m in body["members"]:
        assert set(m) == {"member_id", "name", "is_me", "wallet"}
        assert set(PRE_C6_WALLET) <= set(m["wallet"])
        for k, allowed in PRE_C6_WALLET.items():
            assert _type(m["wallet"][k]) in allowed, (k, m["wallet"][k])
    me, them = body["members"]
    assert me["wallet"]["put_back"] == 20.0 and them["wallet"]["put_back"] is None


# ---------------------------------------------------------------------------
# C5: client_id
# ---------------------------------------------------------------------------


def _post(client, ctx, user_id=None, **body):
    return client.post(MOVEMENTS, headers=_bearer(ctx, user_id or ctx.user_id), json=body)


def test_a_replay_returns_the_original_and_creates_nothing(client, db, authed):
    cid = str(uuid.uuid4())
    first = _post(client, authed, kind="stash_in", amount="50", client_id=cid)
    assert first.status_code == 201, first.text
    again = _post(client, authed, kind="stash_in", amount="50", client_id=cid)
    assert again.status_code == 201
    assert again.json() == first.json()
    assert db.query(CashMovement).count() == 1
    assert stash_balance(db, authed.household_id, authed.user_id) == D("50.00")
    assert db.get(CashMovement, first.json()["id"]).client_id == cid


def test_a_different_id_is_a_new_movement(client, db, authed):
    a = _post(client, authed, kind="stash_in", amount="50", client_id=str(uuid.uuid4()))
    b = _post(client, authed, kind="stash_in", amount="50", client_id=str(uuid.uuid4()))
    c = _post(client, authed, kind="stash_in", amount="50")  # no id: never deduplicated
    d = _post(client, authed, kind="stash_in", amount="50")
    assert len({r.json()["id"] for r in (a, b, c, d)}) == 4
    assert stash_balance(db, authed.household_id, authed.user_id) == D("200.00")


def test_a_take_and_log_replay_makes_no_second_expense(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    cid = str(uuid.uuid4())
    body = dict(
        kind="take",
        amount="12.5",
        stash_owner_id=authed.user_id,
        spend_bucket_id=authed.bucket_id,
        movement_date="2026-01-02",
        client_id=cid,
    )
    first = _post(client, authed, **body)
    assert first.status_code == 201, first.text
    assert first.json()["transaction_id"]
    again = _post(client, authed, **body)
    assert again.status_code == 201 and again.json() == first.json()
    assert db.query(Transaction).count() == 1
    assert db.query(CashMovement).filter(CashMovement.kind == "take").count() == 1
    assert stash_balance(db, authed.household_id, authed.user_id) == D("87.50")


def test_a_take_and_log_replay_that_missed_the_movement_finds_the_expense(
    client, db, authed, monkeypatch
):
    """A replay racing the first save past the movement lookup still makes
    no second expense: the expense's own client_id answers it."""
    cid = str(uuid.uuid4())
    body = dict(kind="take", amount="5", spend_bucket_id=authed.bucket_id, client_id=cid)
    first = _post(client, authed, **body)
    assert first.status_code == 201, first.text
    monkeypatch.setattr(cash_svc, "find_movement_replay", lambda *a, **k: None)
    again = _post(client, authed, **body)
    assert again.status_code == 201, again.text
    assert again.json()["id"] == first.json()["id"]
    assert db.query(Transaction).count() == 1


def test_a_recount_replay_is_not_applied_twice(client, db, authed):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    cid = str(uuid.uuid4())
    first = _post(client, authed, kind="stash_count", amount="80", client_id=cid)
    assert first.status_code == 201, first.text
    _move(db, authed, "stash_in", 5, date(2026, 1, 3))  # then 85
    again = _post(client, authed, kind="stash_count", amount="80", client_id=cid)
    assert again.json() == first.json()
    assert stash_balance(db, authed.household_id, authed.user_id) == D("85.00")


def test_an_upper_case_id_is_the_same_id(client, db, authed):
    cid = str(uuid.uuid4())
    first = _post(client, authed, kind="stash_in", amount="5", client_id=cid.upper())
    again = _post(client, authed, kind="stash_in", amount="5", client_id=cid)
    assert first.json()["id"] == again.json()["id"]
    assert db.get(CashMovement, first.json()["id"]).client_id == cid


def test_a_cross_household_id_is_never_returned(client, db, authed, make_household):
    other = make_household(name="Other", username="outsider")
    cid = str(uuid.uuid4())
    theirs = _post(client, other, kind="stash_in", amount="500", client_id=cid)
    assert theirs.status_code == 201
    mine = _post(client, authed, kind="stash_in", amount="5", client_id=cid)
    assert mine.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"] and mine.json()["amount"] == 5.0
    assert stash_balance(db, authed.household_id, authed.user_id) == D("5.00")


def test_another_members_id_is_a_409_not_their_movement(client, db, duo):
    cid = str(uuid.uuid4())
    assert _post(client, duo, kind="stash_in", amount="70", client_id=cid).status_code == 201
    r = _post(client, duo, duo.partner_id, kind="stash_in", amount="1", client_id=cid)
    assert r.status_code == 409
    assert "70" not in r.text
    assert db.query(CashMovement).count() == 1


def test_an_old_id_counts_again_after_24_hours(client, db, authed):
    cid = str(uuid.uuid4())
    first = _post(client, authed, kind="stash_in", amount="50", client_id=cid)
    mv = db.get(CashMovement, first.json()["id"])
    mv.created_at = utcnow_naive() - timedelta(hours=25)
    db.commit()
    again = _post(client, authed, kind="stash_in", amount="50", client_id=cid)
    assert again.status_code == 201 and again.json()["id"] != first.json()["id"]


@pytest.mark.parametrize(
    "cid",
    [
        "nope",
        "123",
        "6f1c2a3e-8b1d-11ef-9c3a-0242ac120002",  # version 1
        "x" * 37,
        " 3b2e8c1a-4f5d-4e6a-9b7c-1d2e3f4a5b6c",
    ],
)
def test_a_bad_client_id_is_422(client, db, authed, cid):
    r = _post(client, authed, kind="stash_in", amount="50", client_id=cid)
    assert r.status_code == 422
    assert db.query(CashMovement).count() == 0


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="row locking needs Postgres")
def test_simultaneous_recounts_are_serialised(client, db, authed, monkeypatch):
    """Two recounts at once: without a lock both read the same balance and
    the stash ends at A + C - B. Serialised, it ends at the last count."""
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    real = cash_svc.stash_balance

    def slow_balance(*a, **k):
        value = real(*a, **k)
        time.sleep(0.4)  # hold the read open so the two overlap
        return value

    monkeypatch.setattr(cash_svc, "stash_balance", slow_balance)
    results = []

    def recount(amount):
        r = _post(client, authed, kind="stash_count", amount=amount)
        results.append((amount, r.status_code))

    threads = [threading.Thread(target=recount, args=(a,)) for a in ("70", "40")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(s for _a, s in results) == [201, 201]
    monkeypatch.setattr(cash_svc, "stash_balance", real)
    db.expire_all()
    assert db.query(CashMovement).filter(CashMovement.kind == "stash_count").count() == 2
    assert stash_balance(db, authed.household_id, authed.user_id) in (D("70.00"), D("40.00"))


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="row locking needs Postgres")
def test_simultaneous_replays_make_one_movement(client, db, authed, monkeypatch):
    _move(db, authed, "stash_in", 100, date(2026, 1, 1))
    real = cash_svc.stash_balance

    def slow_balance(*a, **k):
        value = real(*a, **k)
        time.sleep(0.4)
        return value

    monkeypatch.setattr(cash_svc, "stash_balance", slow_balance)
    cid = str(uuid.uuid4())
    codes = []

    def take():
        r = _post(
            client, authed, kind="take", amount="10", stash_owner_id=authed.user_id, client_id=cid
        )
        codes.append((r.status_code, r.json().get("id")))

    threads = [threading.Thread(target=take) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [c for c, _ in codes] == [201, 201] and codes[0][1] == codes[1][1]
    monkeypatch.setattr(cash_svc, "stash_balance", real)
    db.expire_all()
    assert stash_balance(db, authed.household_id, authed.user_id) == D("90.00")


# ---------------------------------------------------------------------------
# C6: the full wallet sum
# ---------------------------------------------------------------------------


def card_sum(w: dict, is_me: bool) -> Decimal:
    """What the wallet card adds up: Took (carried + taken - put back,
    floored at 0 for the viewer; others' taken is already net) - in hand -
    logged - outs - logged in a later month + logged more than taken."""
    took = D(str(w["carried"])) + D(str(w["taken"])) - D(str(w.get("put_back") or 0))
    if is_me:
        took = max(took, D(0))
    return (
        took
        - D(str(w["still_have"] or 0))
        - D(str(w["logged"]))
        - D(str(w["outs"]))
        - D(str(w["logged_cross_month"]))
        + D(str(w["over_logged"]))
    )


def _scenario_logged_next_month(db, ctx):
    _move(db, ctx, "take", 100, date(2026, 1, 2))
    _cash(db, ctx, 60, date(2026, 1, 10))
    _cash(db, ctx, 40, date(2026, 2, 5))


def _scenario_later_overspend(db, ctx):
    _move(db, ctx, "take", 100, date(2026, 1, 2))
    _cash(db, ctx, 30, date(2026, 1, 10))
    _cash(db, ctx, 50, date(2026, 2, 5))


def _scenario_stops_at_still_have(db, ctx):
    _move(db, ctx, "take", 100, date(2026, 1, 2))
    _move(db, ctx, "still_have", 0, date(2026, 1, 31))
    _cash(db, ctx, 40, date(2026, 2, 5))


def _scenario_logged_after_still_have(db, ctx):
    _move(db, ctx, "take", 100, date(2026, 1, 2))
    _move(db, ctx, "still_have", 30, date(2026, 2, 10))
    _cash(db, ctx, 50, date(2026, 2, 20))


def _scenario_carry(db, ctx):
    _move(db, ctx, "take", 100, date(2026, 1, 2))
    _cash(db, ctx, 30, date(2026, 1, 10))
    _move(db, ctx, "still_have", 40, date(2026, 1, 31))
    _cash(db, ctx, 10, date(2026, 2, 5))


def _scenario_mixed(db, ctx):
    _move(db, ctx, "stash_in", 300, date(2026, 1, 1))
    _move(db, ctx, "take", 120, date(2026, 1, 2), stash_owner=ctx.user_id)
    _move(db, ctx, "put_back", 10, date(2026, 1, 4))
    _move(db, ctx, "out", 5, date(2026, 1, 5))
    _cash(db, ctx, 75, date(2026, 1, 10))
    _move(db, ctx, "take", 20, date(2026, 2, 3))
    _cash(db, ctx, 60, date(2026, 2, 8))
    _cash(db, ctx, 30, date(2026, 3, 8))


def _scenario_put_back_carried_cash(db, ctx):
    _move(db, ctx, "take", 100, date(2026, 1, 2))
    _move(db, ctx, "still_have", 60, date(2026, 1, 31))
    _move(db, ctx, "put_back", 80, date(2026, 2, 3))  # more than came in: Took < 0


SCENARIOS = [
    _scenario_logged_next_month,
    _scenario_later_overspend,
    _scenario_stops_at_still_have,
    _scenario_logged_after_still_have,
    _scenario_carry,
    _scenario_mixed,
    _scenario_put_back_carried_cash,
]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda f: f.__name__[10:])
def test_the_card_sum_equals_not_yet_logged(client, db, duo, scenario):
    scenario(db, duo)
    for month in ("2026-01", "2026-02", "2026-03"):
        body = client.get(f"{WALLETS}?month={month}", headers=_bearer(duo, duo.user_id)).json()
        me = body["members"][0]
        w = me["wallet"]
        assert w["logged_cross_month"] >= 0 and w["over_logged"] >= 0
        assert card_sum(w, True) == D(str(w["not_yet_logged"])), (month, w)
    # Over a span of months the terms add up too.
    for first, last in ((JAN, FEB_END), (JAN, date(2026, 3, 31)), (FEB, date(2026, 3, 31))):
        w = wallet_summary(db, duo.household_id, duo.user_id, first, last, viewer_id=duo.user_id)
        w = {k: (float(v) if v is not None else None) for k, v in w.items()}
        assert card_sum(w, True) == D(str(w["not_yet_logged"])), (first, last, w)


@pytest.mark.parametrize("scenario", SCENARIOS[:-1], ids=lambda f: f.__name__[10:])
def test_the_card_sum_holds_for_another_members_wallet(client, db, duo, scenario):
    scenario(db, duo)
    for month in ("2026-01", "2026-02", "2026-03"):
        body = client.get(f"{WALLETS}?month={month}", headers=_bearer(duo, duo.partner_id)).json()
        them = next(m for m in body["members"] if m["member_id"] == duo.user_id)
        w = them["wallet"]
        assert w["put_back"] is None
        assert card_sum(w, False) == D(str(w["not_yet_logged"])), (month, w)


def test_the_terms_name_what_happened(client, db, duo):
    """Take 100 in January, log 60 then and 40 in February: January's 40 was
    logged in a later month; February logged 40 more than it took."""
    _scenario_logged_next_month(db, duo)
    h = _bearer(duo, duo.user_id)
    jan = client.get(f"{WALLETS}?month=2026-01", headers=h).json()["members"][0]["wallet"]
    feb = client.get(f"{WALLETS}?month=2026-02", headers=h).json()["members"][0]["wallet"]
    assert (jan["logged_cross_month"], jan["over_logged"], jan["not_yet_logged"]) == (40, 0, 0)
    assert (feb["logged_cross_month"], feb["over_logged"], feb["not_yet_logged"]) == (0, 40, 0)
    rows = monthly_breakdown(db, duo.household_id, duo.user_id, JAN, FEB)
    assert [r["logged_cross_month"] for r in rows] == [D("40.00"), D("0.00")]


def test_later_overspend_only_counts_what_was_left(client, db, duo):
    _scenario_later_overspend(db, duo)
    h = _bearer(duo, duo.user_id)
    jan = client.get(f"{WALLETS}?month=2026-01", headers=h).json()["members"][0]["wallet"]
    feb = client.get(f"{WALLETS}?month=2026-02", headers=h).json()["members"][0]["wallet"]
    assert (jan["logged_cross_month"], jan["not_yet_logged"]) == (50, 20)
    assert (feb["over_logged"], feb["not_yet_logged"]) == (50, 0)


def test_no_cross_month_activity_means_zero_terms(client, db, duo):
    _move(db, duo, "take", 50, date(2026, 1, 2))
    _cash(db, duo, 20, date(2026, 1, 5))
    w = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(duo, duo.user_id)).json()
    w = w["members"][0]["wallet"]
    assert (w["logged_cross_month"], w["over_logged"], w["not_yet_logged"]) == (0.0, 0.0, 30.0)


def test_your_own_taken_is_never_negative(client, db, duo):
    _scenario_put_back_carried_cash(db, duo)
    h = _bearer(duo, duo.user_id)
    w = client.get(f"{WALLETS}?month=2026-02", headers=h).json()["members"][0]["wallet"]
    assert w["taken"] >= 0 and w["put_back"] == 80.0 and w["carried"] == 60.0
    # The card's Took (carried + taken - put back) is -20 here: shown as 0,
    # and the sum still comes out at not yet logged.
    assert card_sum(w, True) == D(str(w["not_yet_logged"])) == 0
    s = client.get("/api/v1/cash/summary?month=2026-02", headers=h).json()["wallet"]
    assert s["taken"] >= 0
    assert s["logged_cross_month"] == w["logged_cross_month"]
    assert s["over_logged"] == w["over_logged"]
