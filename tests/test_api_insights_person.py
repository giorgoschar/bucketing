"""2d §7.1: "Paid out vs my share" for a member lens, without settle-up's net."""

from decimal import Decimal

from app.core.clock import local_today
from app.models import Transaction, TransactionSplit, TransactionType
from app.services.insights import resolve_insight_period
from app.services.person import get_person_summary
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user

URL = "/api/v1/insights/person"


def _expense(db, hh, amount, *, paid_by, splits=None, notes=None):
    t = Transaction(
        household_id=hh.household_id,
        bucket_id=hh.bucket_id,
        amount=Decimal(amount),
        currency="EUR",
        type=TransactionType.expense,
        paid_by=paid_by,
        notes=notes,
        transaction_date=local_today(),
    )
    db.add(t)
    db.flush()
    for uid, share in (splits or {}).items():
        db.add(TransactionSplit(transaction_id=t.id, user_id=uid, amount=Decimal(share)))
    db.commit()
    return t


def test_figures_equal_the_person_summary_without_net(client, db, api):  # noqa: F811
    headers, hh = api
    maria, _ = _add_member_user(db, hh.household_id, "maria")
    _expense(
        db,
        hh,
        "100",
        paid_by=hh.user_id,
        splits={hh.user_id: "50", maria.id: "50"},
        notes="Groceries",
    )
    _expense(db, hh, "40", paid_by=maria.id, splits={hh.user_id: "20", maria.id: "20"})
    r = client.get(URL, headers=headers, params={"user_id": hh.user_id, "preset": "this_month"})
    assert r.status_code == 200, r.text
    body = r.json()
    period = resolve_insight_period("this_month")
    expected = get_person_summary(db, hh.household_id, hh.user_id, period["start"], period["end"])
    for key in ("paid_out", "my_share", "balance", "household_total", "share_pct"):
        assert Decimal(str(body[key])) == expected[key], key
    assert (body["shared_count"], body["transaction_count"]) == (2, 2)
    assert body["balance"] == 30.0  # paid 100, share 70
    assert body["largest"]["amount"] == 50.0 and body["largest"]["notes"] == "Groceries"
    assert "net" not in body and "by_bucket" not in body


def test_a_non_member_is_404(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    stranger = make_household(name="Other", username="other")
    for uid in (stranger.user_id, "nobody"):
        r = client.get(URL, headers=headers, params={"user_id": uid})
        assert r.status_code == 404
        assert r.json()["detail"] == "Member not found"


def test_empty_period_has_no_largest(client, api):  # noqa: F811
    headers, hh = api
    body = client.get(URL, headers=headers, params={"user_id": hh.user_id}).json()
    assert body["largest"] is None and body["paid_out"] == 0 and body["share_pct"] is None
