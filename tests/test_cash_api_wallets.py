"""
The cash API's typed responses: ``GET /api/v1/cash/wallets`` (every member's
wallet for a month, the viewer first) and the wire shape of the existing
``/movements`` and ``/summary`` responses, pinned before they got Pydantic
response models so the models cannot change a key or a type.

Money is a JSON number on the wire (FastAPI's Decimal encoder gave a float
before the models; ``planning_models.Money`` keeps it a float).
"""

from datetime import date

import pytest

from app.models import Category
from tests.test_cash_stash import _bearer, _cash, _move
from tests.test_isolation import _add_member_user


@pytest.fixture()
def duo(db, authed):
    """The logged-in owner plus a second member (with login credentials)."""
    member, secret = _add_member_user(db, authed.household_id, "flatmate")
    authed.partner_id = member.id
    authed.partner_secret = secret
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


# ---------------------------------------------------------------------------
# Snapshot of today's shape (written and run against the code before the
# response models existed)
# ---------------------------------------------------------------------------

MOVEMENT_TYPES = {
    "id": {"string"},
    "user_id": {"string"},
    "kind": {"string"},
    "stash_owner_id": {"string", "null"},
    "amount": {"number"},
    "currency": {"string"},
    "category_id": {"string", "null"},
    "note": {"string", "null"},
    "movement_date": {"string"},
    "transaction_id": {"string", "null"},
    "created_at": {"string"},
    "deleted": {"boolean"},
}

WALLET_TYPES = {
    "carried": {"number"},
    "taken": {"number"},
    "put_back": {"number"},
    "still_have": {"number", "null"},
    "spent": {"number"},
    "logged": {"number"},
    "outs": {"number"},
    "labelled_out": {"number"},
    "not_yet_logged": {"number"},
    # Polish C6 (added keys; /wallets and /summary must keep matching).
    "logged_cross_month": {"number"},
    "over_logged": {"number"},
}


def _check_movement(item):
    assert set(item) == set(MOVEMENT_TYPES), item
    for k, v in item.items():
        assert _type(v) in MOVEMENT_TYPES[k], (k, v)


def _mixed(db, duo):
    """Every flavour of row the viewer (A) can receive."""
    a, b = duo.user_id, duo.partner_id
    cat = Category(household_id=duo.household_id, name="Snacks")
    db.add(cat)
    db.commit()
    _move(db, duo, "stash_in", 100, date(2026, 1, 1), note="Saved")
    _move(db, duo, "take", 20, date(2026, 1, 2), stash_owner=a)
    _move(db, duo, "take", 5, date(2026, 1, 2))  # bank
    _move(db, duo, "put_back", 3, date(2026, 1, 3))
    _move(db, duo, "still_have", 7, date(2026, 1, 20))
    _move(db, duo, "out", 1, date(2026, 1, 4), category_id=cat.id)  # legacy
    gone = _move(db, duo, "take", 30, date(2026, 1, 5), user=b, stash_owner=a)
    gone.deleted_at = gone.created_at
    db.commit()
    _cash(db, duo, 4, date(2026, 1, 6))


def test_movements_wire_shape_is_unchanged(client, db, duo):
    _mixed(db, duo)
    h = _bearer(duo, duo.user_id)
    raw = client.get("/api/v1/cash/movements?month=2026-01", headers=h)
    # Exact wire text: a JSON float, not a string ("83.00") nor an int.
    assert '"stash":83.0' in raw.text and '"amount":100.0' in raw.text
    body = raw.json()
    assert set(body) == {"items", "stash"}
    assert _type(body["stash"]) == "number" and body["stash"] == 83.0
    assert len(body["items"]) == 7
    for item in body["items"]:
        _check_movement(item)
    by_kind = {(i["kind"], i["user_id"]): i for i in body["items"]}
    assert by_kind[("stash_in", duo.user_id)]["amount"] == 100.0
    assert by_kind[("take", duo.partner_id)]["deleted"] is True
    assert len(by_kind[("still_have", duo.user_id)]["movement_date"]) == 10

    # The composer's useStash reads ?limit=1 -> .stash
    one = client.get("/api/v1/cash/movements?limit=1", headers=h).json()
    assert set(one) == {"items", "stash"} and one["stash"] == 83.0


def test_post_movement_wire_shape_is_unchanged(client, db, duo):
    h = _bearer(duo, duo.user_id)
    r = client.post(
        "/api/v1/cash/movements",
        headers=h,
        json={"kind": "stash_in", "amount": "50", "movement_date": "2026-01-01"},
    )
    assert r.status_code == 201
    _check_movement(r.json())
    assert r.json()["amount"] == 50.0
    # Take and spend: the linked take comes back.
    r = client.post(
        "/api/v1/cash/movements",
        headers=h,
        json={
            "kind": "take",
            "amount": "12.5",
            "stash_owner_id": duo.user_id,
            "spend_bucket_id": duo.bucket_id,
            "movement_date": "2026-01-02",
        },
    )
    assert r.status_code == 201, r.text
    _check_movement(r.json())
    assert r.json()["transaction_id"] and r.json()["amount"] == 12.5


def test_summary_wire_shape_is_unchanged(client, db, duo):
    _mixed(db, duo)
    h = _bearer(duo, duo.user_id)
    mine = client.get("/api/v1/cash/summary?month=2026-01", headers=h).json()
    assert set(mine) == {"month", "member_id", "stash", "wallet"}
    assert mine["month"] == "2026-01" and mine["member_id"] == duo.user_id
    assert _type(mine["stash"]) == "number"
    assert set(mine["wallet"]) == set(WALLET_TYPES)
    for k, v in mine["wallet"].items():
        assert _type(v) in WALLET_TYPES[k], (k, v)
    assert mine["wallet"]["still_have"] == 7.0

    # Another member's wallet: put_back is left out (not null), still_have null.
    theirs = client.get(
        f"/api/v1/cash/summary?month=2026-01&member_id={duo.partner_id}", headers=h
    ).json()
    assert set(theirs) == {"month", "member_id", "stash", "wallet"}
    assert set(theirs["wallet"]) == set(WALLET_TYPES) - {"put_back"}
    assert theirs["wallet"]["still_have"] is None
    for k, v in theirs["wallet"].items():
        assert _type(v) in WALLET_TYPES[k], (k, v)


# ---------------------------------------------------------------------------
# GET /cash/wallets
# ---------------------------------------------------------------------------

WALLETS = "/api/v1/cash/wallets"


@pytest.fixture()
def crowd(db, duo):
    """Four members: the owner (User1), Flatmate, and Zed and aaron added
    out of name order, so "by name" is not insertion order."""
    duo.zed_id = _add_member_user(db, duo.household_id, "zed")[0].id
    duo.aaron_id = _add_member_user(db, duo.household_id, "aaron")[0].id
    return duo


def test_wallets_lists_every_member_viewer_first_then_by_name(client, db, crowd):
    body = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(crowd, crowd.user_id)).json()
    assert set(body) == {"month", "stash", "members"}
    assert body["month"] == "2026-01"
    names = [m["name"] for m in body["members"]]
    assert names == ["User1", "Aaron", "Flatmate", "Zed"]
    assert [m["is_me"] for m in body["members"]] == [True, False, False, False]
    assert body["members"][0]["member_id"] == crowd.user_id
    # From the flatmate's side: they come first, the rest by name.
    body = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(crowd, crowd.partner_id)).json()
    assert [m["name"] for m in body["members"]] == ["Flatmate", "Aaron", "User1", "Zed"]


def test_wallets_hides_put_back_from_others(client, db, duo):
    a, b = duo.user_id, duo.partner_id
    _move(db, duo, "stash_in", 100, date(2026, 1, 1))
    _move(db, duo, "take", 50, date(2026, 1, 2), stash_owner=a)
    _move(db, duo, "put_back", 20, date(2026, 1, 3))
    _move(db, duo, "take", 40, date(2026, 1, 2), user=b)
    _move(db, duo, "put_back", 15, date(2026, 1, 3), user=b)
    body = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(duo, a)).json()
    me, them = body["members"]
    assert me["wallet"]["put_back"] == 20.0 and me["wallet"]["taken"] == 50.0
    assert them["wallet"]["put_back"] is None  # present, null
    assert them["wallet"]["taken"] == 25.0  # net of the put back
    assert body["stash"] == 70.0
    for m in body["members"]:
        assert {
            "carried",
            "taken",
            "put_back",
            "still_have",
            "spent",
            "logged",
            "outs",
            "not_yet_logged",
        } <= set(m["wallet"])
        assert set(m) == {"member_id", "name", "is_me", "wallet"}


@pytest.mark.parametrize("month", ["2026-13", "nope", "2026"])
def test_wallets_bad_month_is_400(client, db, authed, month):
    r = client.get(f"{WALLETS}?month={month}", headers=_bearer(authed, authed.user_id))
    assert r.status_code == 400


def test_wallets_default_is_the_current_month(client, db, authed):
    from app.core.clock import local_today

    body = client.get(WALLETS, headers=_bearer(authed, authed.user_id)).json()
    assert body["month"] == local_today().strftime("%Y-%m")


def test_wallets_needs_auth(client):
    assert client.get(WALLETS).status_code == 401


def test_wallets_household_isolation(client, db, duo, make_household):
    other = make_household(name="Other", username="outsider")
    _move(db, other, "stash_in", 500, date(2026, 1, 1))
    _move(db, other, "take", 70, date(2026, 1, 2), stash_owner=other.user_id)
    body = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(duo, duo.user_id)).json()
    ids = {m["member_id"] for m in body["members"]}
    assert ids == {duo.user_id, duo.partner_id}
    assert "Outsider" not in {m["name"] for m in body["members"]}
    assert body["stash"] == 0.0
    theirs = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(other, other.user_id)).json()
    assert [m["member_id"] for m in theirs["members"]] == [other.user_id]
    assert theirs["stash"] == 430.0


def test_wallets_totals_match_summary(client, db, crowd):
    a, b = crowd.user_id, crowd.partner_id
    _move(db, crowd, "stash_in", 300, date(2026, 1, 1))
    _move(db, crowd, "take", 120, date(2026, 1, 2), stash_owner=a)
    _move(db, crowd, "put_back", 10, date(2026, 1, 4))
    _move(db, crowd, "still_have", 15, date(2026, 1, 28))
    _move(db, crowd, "take", 60, date(2026, 1, 3), user=b, stash_owner=a)
    _move(db, crowd, "put_back", 5, date(2026, 1, 9), user=b)
    _move(db, crowd, "take", 20, date(2025, 12, 20), user=b)
    _move(db, crowd, "still_have", 20, date(2025, 12, 31), user=b)
    _cash(db, crowd, 75, date(2026, 1, 10))
    _cash(db, crowd, 30, date(2026, 1, 11), payer=b)
    for viewer in (a, b):
        h = _bearer(crowd, viewer)
        body = client.get(f"{WALLETS}?month=2026-01", headers=h).json()
        assert len(body["members"]) == 4
        for m in body["members"]:
            s = client.get(
                f"/api/v1/cash/summary?month=2026-01&member_id={m['member_id']}", headers=h
            ).json()
            assert body["stash"] == s["stash"]
            for k, v in m["wallet"].items():
                assert v == s["wallet"].get(k), (viewer, m["name"], k)
    mine = client.get(f"{WALLETS}?month=2026-01", headers=_bearer(crowd, a)).json()["members"][0]
    assert mine["wallet"]["not_yet_logged"] == 20.0  # 120 - 10 - 15 - 75
