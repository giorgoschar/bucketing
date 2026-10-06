"""B1: dashboard / bucket page / API "who paid" use the same payer semantics as Insights.

Scenario (plan Review Focus 3): A pays 100, only B has a split of 50.
Who paid must show A=100, B=0 (share 50) and the bars must sum to the total.
"""

from decimal import Decimal

import pyotp
import pytest

from app.core.clock import local_today
from app.models import HouseholdMember
from app.services import get_all_time_summary, get_bucket_month_summary, get_month_summary
from tests.conftest import PASSWORD
from tests.test_household_settlement import _add_member
from tests.test_insights import _paid


@pytest.fixture()
def duo(db, authed):
    partner = _add_member(db, authed.household_id, "partner")
    db.commit()
    authed.partner_id = partner.id
    return authed


def _assert_payer_semantics(paid_by, a, b, total):
    assert paid_by[a]["amount"] == Decimal("100")
    assert paid_by[a]["paid"] == Decimal("100")
    assert paid_by[b]["amount"] == Decimal("0")
    assert paid_by[b]["share"] == Decimal("50")
    assert sum(d["amount"] for d in paid_by.values()) == total


def test_dashboard_month_who_paid_credits_payer(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(b, 50)])
    today = local_today()
    s = get_month_summary(db, duo.household_id, today.year, today.month)
    _assert_payer_semantics(s["paid_by"], a, b, s["total_spent"])


def test_dashboard_all_time_who_paid_credits_payer(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(b, 50)])
    s = get_all_time_summary(db, duo.household_id)
    _assert_payer_semantics(s["paid_by"], a, b, s["total_spent"])


def test_bucket_month_who_paid_credits_payer_and_unassigned(db, duo):
    a, b = duo.user_id, duo.partner_id
    _paid(db, duo, 100, [(b, 50)])
    _paid(db, duo, 20, payer=None)
    today = local_today()
    s = get_bucket_month_summary(db, duo.bucket_id, today.year, today.month)
    assert s["paid_by"][a]["amount"] == Decimal("100")
    assert s["paid_by"]["unassigned"]["amount"] == Decimal("20")
    assert sum(d["amount"] for d in s["paid_by"].values()) == s["total_spent"] == Decimal("120")


def test_bucket_page_renders_payer(client, db, duo):
    _paid(db, duo, 100, [(duo.partner_id, 50)])
    page = client.get(f"/buckets/{duo.bucket_id}").text
    assert "Who paid" in page
    assert "width: 100.0%" in page  # A's bar is the whole total


def test_dashboard_who_paid_keeps_former_member_payer(db, duo):
    b = duo.partner_id
    _paid(db, duo, 30, payer=b)
    db.query(HouseholdMember).filter_by(household_id=duo.household_id, user_id=b).delete()
    db.commit()
    today = local_today()
    s = get_month_summary(db, duo.household_id, today.year, today.month)
    assert s["paid_by"][b]["amount"] == Decimal("30")
    assert s["paid_by"][b]["name"].startswith("Former member")


def test_api_dashboard_who_paid_credits_payer(db, client, make_household):
    hh = make_household()
    partner = _add_member(db, hh.household_id, "partner")
    db.commit()
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(hh.secret).now()},
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    _paid(db, hh, 100, [(partner.id, 50)])
    body = client.get("/api/v1/dashboard", headers=headers).json()
    assert body["paid_by"][hh.user_id]["amount"] == 100
    assert body["paid_by"][partner.id]["amount"] == 0
