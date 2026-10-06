"""B4: settle-up forms/API post a fingerprint of the transfers they displayed;
a repeat (double) submit no longer matches and records nothing."""

import re

from app.models import Settlement
from app.services import get_bucket_settlement, get_household_settlement
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_household_settlement import two_buckets  # noqa: F401  (fixture)
from tests.test_settlement import shared  # noqa: F401  (fixture)


def _expected(html):
    m = re.search(r'name="expected" value="([^"]+)"', html)
    assert m, "settle form must post the displayed transfers' fingerprint"
    return m.group(1)


def test_bucket_settle_row_double_submit_records_once(client, db, shared):  # noqa: F811
    page = client.get(f"/buckets/{shared.bucket_id}").text
    form = {
        "from_user_id": shared.partner_id,
        "to_user_id": shared.user_id,
        "amount": "50.00",
        "expected": _expected(page),
    }
    r1 = client.post(
        f"/buckets/{shared.bucket_id}/settle",
        data=form,
        headers=shared.headers,
        follow_redirects=False,
    )
    r2 = client.post(
        f"/buckets/{shared.bucket_id}/settle",
        data=form,
        headers=shared.headers,
        follow_redirects=False,
    )
    assert r1.status_code == 302
    assert r2.status_code in (302, 303, 409)
    assert db.query(Settlement).count() == 1
    assert get_bucket_settlement(db, shared.bucket_id) == []  # not reversed
    if r2.status_code in (302, 303):
        assert "settle=stale" in r2.headers["location"]
        assert "changed" in client.get(r2.headers["location"]).text.lower()


def test_household_settle_all_double_submit_records_once(client, db, two_buckets):  # noqa: F811
    page = client.get("/settlement").text
    form = {"expected": _expected(page)}
    client.post("/settlement/settle", data=form, headers=two_buckets.headers)
    n = db.query(Settlement).count()
    assert n >= 1
    r2 = client.post(
        "/settlement/settle", data=form, headers=two_buckets.headers, follow_redirects=False
    )
    assert db.query(Settlement).count() == n
    assert get_household_settlement(db, two_buckets.household_id) == []
    assert r2.status_code in (302, 303, 409)


def test_household_settle_row_double_submit_records_once(client, db, two_buckets):  # noqa: F811
    row = get_household_settlement(db, two_buckets.household_id)[0]
    page = client.get("/settlement").text
    form = {
        "from_user_id": row["from_id"],
        "to_user_id": row["to_id"],
        "amount": str(row["amount"]),
        "expected": _expected(page),
    }
    client.post("/settlement/settle", data=form, headers=two_buckets.headers)
    client.post("/settlement/settle", data=form, headers=two_buckets.headers)
    assert db.query(Settlement).count() == 1
    assert get_household_settlement(db, two_buckets.household_id) == []


def test_api_settle_with_stale_fingerprint_is_409(client, db, api, make_household):  # noqa: F811
    from decimal import Decimal

    from app.models import Bucket
    from tests.test_household_settlement import _add_member, _shared_expense

    headers, hh = api
    partner = _add_member(db, hh.household_id, "partner")
    db.get(Bucket, hh.bucket_id).enable_settlement = True
    _shared_expense(
        db, hh.bucket_id, hh.household_id, hh.user_id, [hh.user_id, partner.id], Decimal("100")
    )
    db.commit()

    fp = client.get("/api/v1/settlement", headers=headers).json()["fingerprint"]
    body = {"from_user_id": partner.id, "to_user_id": hh.user_id, "amount": 50, "expected": fp}
    r1 = client.post("/api/v1/settlement/settle", headers=headers, json=body)
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/v1/settlement/settle", headers=headers, json=body)
    assert r2.status_code == 409
    assert db.query(Settlement).count() == 1

    fp = client.get(f"/api/v1/buckets/{hh.bucket_id}/settlement", headers=headers).json()[
        "fingerprint"
    ]
    r3 = client.post(
        f"/api/v1/buckets/{hh.bucket_id}/settle", headers=headers, json={"expected": "stale" + fp}
    )
    assert r3.status_code == 409
