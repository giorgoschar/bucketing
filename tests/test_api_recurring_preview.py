"""POST /api/v1/recurring/preview (2a spec §6): the next dates of a schedule rule. Writes nothing."""

from datetime import date, timedelta

from app.core.calendar_gr import last_business_day, orthodox_easter
from app.core.clock import local_today
from app.models import RecurringBill
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring/preview"
FUTURE = "2097-01-01"  # later than any run's today, so the expected dates are fixed


def _dates(r):
    assert r.status_code == 200, r.text
    return [date.fromisoformat(d) for d in r.json()["dates"]]


def test_salary_rule_moves_to_the_business_day_before(client, api):  # noqa: F811
    headers, _ = api
    body = {
        "rule_kind": "monthly_day",
        "rule_day": 26,
        "rule_adjust": "previous_business_day",
        "start_date": FUTURE,
    }
    r = client.post(URL, headers=headers, json=body)
    # 26 Jan 2097 is a Saturday: the salary comes on Friday the 25th.
    assert r.json() == {"dates": ["2097-01-25", "2097-02-26", "2097-03-26"]}


def test_last_business_day(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(
        URL,
        headers=headers,
        json={"rule_kind": "last_business_day", "start_date": FUTURE, "count": 6},
    )
    dates = _dates(r)
    assert [d.isoformat() for d in dates[:3]] == ["2097-01-31", "2097-02-28", "2097-03-29"]
    assert len(dates) == 6
    assert all(d == last_business_day(d.year, d.month) for d in dates)


def test_easter_offset_counts_from_orthodox_easter(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(
        URL,
        headers=headers,
        json={"rule_kind": "easter_offset", "rule_days": -2, "start_date": FUTURE},
    )
    dates = _dates(r)
    assert [d.isoformat() for d in dates] == ["2097-05-03", "2098-04-25", "2099-04-10"]
    assert all(d == orthodox_easter(d.year) - timedelta(days=2) for d in dates)


def test_count_and_end_date_limit_the_dates(client, api):  # noqa: F811
    headers, _ = api
    rule = {"rule_kind": "monthly_day", "rule_day": 5, "start_date": FUTURE}
    assert len(_dates(client.post(URL, headers=headers, json={**rule, "count": 12}))) == 12
    ended = _dates(
        client.post(URL, headers=headers, json={**rule, "count": 5, "end_date": "2097-02-28"})
    )
    assert [d.isoformat() for d in ended] == ["2097-01-05", "2097-02-05"]


def test_a_past_start_previews_from_today_and_keeps_its_anchor(client, api):  # noqa: F811
    headers, _ = api
    today = local_today()
    start = date(today.year - 2, today.month, 15)
    body = {"rule_kind": "monthly_interval", "interval_months": 3, "start_date": start.isoformat()}
    dates = _dates(client.post(URL, headers=headers, json=body))
    assert len(dates) == 3 and dates == sorted(dates)
    assert all(d >= today and d.day == 15 for d in dates)
    assert all(((d.year - start.year) * 12 + d.month - start.month) % 3 == 0 for d in dates)


def test_weekly_from_a_past_start_stays_on_its_weekday(client, api):  # noqa: F811
    headers, _ = api
    today = local_today()
    body = {
        "rule_kind": "weekly",
        "rule_weekday": 0,
        "rule_interval_weeks": 2,
        "start_date": (today - timedelta(days=100)).isoformat(),
    }
    dates = _dates(client.post(URL, headers=headers, json=body))
    assert len(dates) == 3 and all(d.weekday() == 0 and d >= today for d in dates)
    assert dates[1] - dates[0] == timedelta(weeks=2)


def test_an_invalid_rule_is_400_with_the_message(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(URL, headers=headers, json={"rule_kind": "monthly_day", "start_date": FUTURE})
    assert r.status_code == 400 and r.json()["detail"] == "The day must be 1 to 31."
    r = client.post(URL, headers=headers, json={"rule_kind": "fortnightly", "start_date": FUTURE})
    assert r.status_code == 400 and "Unknown schedule" in r.json()["detail"]
    r = client.post(
        URL,
        headers=headers,
        json={"rule_kind": "last_business_day", "start_date": FUTURE, "end_date": "2096-01-01"},
    )
    assert r.status_code == 400
    r = client.post(
        URL,
        headers=headers,
        json={"rule_kind": "last_business_day", "start_date": FUTURE, "count": 13},
    )
    assert r.status_code == 422


def test_needs_auth_and_writes_nothing(client, db, api):  # noqa: F811
    headers, _ = api
    body = {"rule_kind": "last_business_day", "start_date": FUTURE}
    assert client.post(URL, json=body).status_code == 401
    assert client.post(URL, headers=headers, json=body).status_code == 200
    assert db.query(RecurringBill).count() == 0
