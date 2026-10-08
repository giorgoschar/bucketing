"""B1 x B2: Keep both hides pairs from the feed's duplicates and counts;
a transaction's history shows its bulk changes (2c spec §5.2, §9 item 11)."""

from tests.bulk_fixtures import URL, env  # noqa: F401
from tests.test_api import api  # noqa: F401

TXNS = "/api/v1/transactions"


def test_dismissed_pair_is_hidden_but_partly_dismissed_group_shows(env):  # noqa: F811
    a, b = env.add("7.50"), env.add("7.50")
    x, y, z = env.add("4.20"), env.add("4.20"), env.add("4.20")
    get = lambda path: env.client.get(f"{TXNS}/{path}", headers=env.headers).json()  # noqa: E731
    assert get("counts")["duplicate_groups"] == 2
    env.client.post(f"{TXNS}/duplicates/dismiss", headers=env.headers, json={"ids": [a, b]})
    env.client.post(f"{TXNS}/duplicates/dismiss", headers=env.headers, json={"ids": [x, y]})
    groups = get("duplicates")["groups"]
    assert [sorted(t["id"] for t in g["transactions"]) for g in groups] == [sorted([x, y, z])]
    assert get("counts")["duplicate_groups"] == 1


def test_counts_duplicates_and_bulk_are_not_read_as_ids(env):  # noqa: F811
    for path in ("counts", "duplicates", "bulk"):
        r = env.client.get(f"{TXNS}/{path}", headers=env.headers)
        assert r.status_code == 200, (path, r.text)


def test_history_shows_bulk_change_with_undo_then_undone(env):  # noqa: F811
    a = env.add()
    batch = env.bulk({"ids": [a]}, {"bucket_id": env.bills}).json()["batch_id"]
    events = env.client.get(f"{TXNS}/{a}/history", headers=env.headers).json()["events"]
    change = next(e for e in events if e["kind"] == "bulk_change")
    assert change["batch_id"] == batch and change["can_undo"] is True
    assert change["text"] == "Bucket: Day to day → Bills"
    env.client.post(f"{URL}/{batch}/undo", headers=env.headers)
    events = env.client.get(f"{TXNS}/{a}/history", headers=env.headers).json()["events"]
    assert events[0]["kind"] == "bulk_undone"
    assert next(e for e in events if e["kind"] == "bulk_change")["can_undo"] is False


def test_feed_month_without_year_is_400(env):  # noqa: F811
    r = env.client.get(f"{TXNS}?month=5", headers=env.headers)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Pick a year for the month."
    assert env.client.get(f"{TXNS}?year=2026&month=5", headers=env.headers).status_code == 200
