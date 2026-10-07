"""2d §7.4: /api/v1/settings/category-rules. POST is an upsert by folded
pattern (201 new, 200 existing), so 2b can queue it."""

from datetime import date
from decimal import Decimal

from app.models import Category, CategoryRule, Transaction, TransactionType
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/settings/category-rules"
INVALID = "Enter at least 2 characters and pick a category from this household."


def _category(db, household_id, name="Groceries"):
    cat = Category(household_id=household_id, name=name)
    db.add(cat)
    db.commit()
    return cat.id


def test_post_creates_then_upserts_by_folded_pattern(client, db, api):  # noqa: F811
    headers, hh = api
    groceries = _category(db, hh.household_id)
    coffee = _category(db, hh.household_id, "Coffee")
    r = client.post(
        URL, headers=headers, json={"pattern": "  ΣΚΛΑΒΕΝΙΤΗΣ ", "category_id": groceries}
    )
    assert r.status_code == 201, r.text
    rule = r.json()
    assert (rule["pattern"], rule["category_id"], rule["match_count"]) == (
        "σκλαβενιτησ",
        groceries,
        0,
    )
    db.query(CategoryRule).filter_by(id=rule["id"]).update({"match_count": 48})
    db.commit()

    r = client.post(URL, headers=headers, json={"pattern": "Σκλαβενίτης", "category_id": coffee})
    assert r.status_code == 200, r.text
    assert (r.json()["id"], r.json()["category_id"], r.json()["match_count"]) == (
        rule["id"],
        coffee,
        48,
    )
    assert db.query(CategoryRule).count() == 1


def test_post_rejects_short_patterns_and_foreign_categories(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    mine = _category(db, hh.household_id)
    other = make_household(name="Other", username="other")
    theirs = _category(db, other.household_id)
    for body in (
        {"pattern": "a", "category_id": mine},
        {"pattern": "  á  ", "category_id": mine},
        {"pattern": "lidl", "category_id": theirs},
        {"pattern": "lidl", "category_id": "nope"},
    ):
        r = client.post(URL, headers=headers, json=body)
        assert r.status_code == 400, body
        assert r.json()["detail"] == INVALID
    assert db.query(CategoryRule).count() == 0


def test_list_is_most_used_first_with_every_field(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id)
    for pattern, count in (("lidl", 3), ("ab", 9)):
        db.add(
            CategoryRule(
                household_id=hh.household_id, pattern=pattern, category_id=cat, match_count=count
            )
        )
    db.commit()
    rows = client.get(URL, headers=headers).json()
    assert [r["pattern"] for r in rows] == ["ab", "lidl"]
    assert set(rows[0]) == {"id", "pattern", "category_id", "match_count", "created_at"}


def test_put_repoints_and_keeps_match_count(client, db, api):  # noqa: F811
    headers, hh = api
    a, b = _category(db, hh.household_id), _category(db, hh.household_id, "B")
    rule = client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": a}).json()
    db.query(CategoryRule).filter_by(id=rule["id"]).update({"match_count": 7})
    db.commit()
    r = client.put(
        f"{URL}/{rule['id']}", headers=headers, json={"pattern": "LIDL Express", "category_id": b}
    )
    assert r.status_code == 200, r.text
    assert (r.json()["pattern"], r.json()["category_id"], r.json()["match_count"]) == (
        "lidl express",
        b,
        7,
    )


def test_put_collision_is_409_and_bad_input_400(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id)
    first = client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": cat}).json()
    second = client.post(URL, headers=headers, json={"pattern": "ab", "category_id": cat}).json()
    r = client.put(
        f"{URL}/{second['id']}", headers=headers, json={"pattern": "Lidl", "category_id": cat}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Another rule already uses this pattern."
    # Saving a rule under its own pattern is not a collision.
    r = client.put(
        f"{URL}/{first['id']}", headers=headers, json={"pattern": "LIDL", "category_id": cat}
    )
    assert r.status_code == 200
    r = client.put(
        f"{URL}/{first['id']}", headers=headers, json={"pattern": "x", "category_id": cat}
    )
    assert r.status_code == 400


def test_other_households_rules_are_404(client, db, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    cat = _category(db, other.household_id)
    rule = CategoryRule(household_id=other.household_id, pattern="lidl", category_id=cat)
    db.add(rule)
    db.commit()
    mine = _category(db, hh.household_id)
    assert (
        client.put(
            f"{URL}/{rule.id}", headers=headers, json={"pattern": "lidl", "category_id": mine}
        ).status_code
        == 404
    )
    assert client.delete(f"{URL}/{rule.id}", headers=headers).status_code == 404
    assert rule.id not in {r["id"] for r in client.get(URL, headers=headers).json()}


def test_delete_is_204_then_404(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id)
    rule = client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": cat}).json()
    assert client.delete(f"{URL}/{rule['id']}", headers=headers).status_code == 204
    assert client.delete(f"{URL}/{rule['id']}", headers=headers).status_code == 404


def test_deleting_a_category_removes_its_rules(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id, "Snacks")
    client.post(URL, headers=headers, json={"pattern": "kiosk", "category_id": cat})
    r = client.delete(f"/api/v1/settings/categories/{cat}", headers=headers)
    assert r.status_code == 204
    assert db.query(CategoryRule).count() == 0


def test_categories_list_counts_expenses_and_rules(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _category(db, hh.household_id, "Snacks")
    for deleted in (False, False, True):
        t = Transaction(
            household_id=hh.household_id,
            bucket_id=hh.bucket_id,
            amount=Decimal("2"),
            currency="EUR",
            type=TransactionType.expense,
            paid_by=hh.user_id,
            category_id=cat,
            transaction_date=date(2026, 10, 1),
        )
        if deleted:
            from app.core.clock import utcnow_naive

            t.deleted_at = utcnow_naive()
        db.add(t)
    db.add(CategoryRule(household_id=hh.household_id, pattern="kiosk", category_id=cat))
    db.commit()
    row = next(
        c
        for c in client.get("/api/v1/settings/categories", headers=headers).json()
        if c["id"] == cat
    )
    assert (row["expense_count"], row["rule_count"]) == (2, 1)


def test_put_race_on_the_unique_pattern_is_409_not_500(client, db, api, monkeypatch):  # noqa: F811
    """Two PUTs both pass the pre-check; the unique constraint catches the second."""
    headers, hh = api
    cat = _category(db, hh.household_id)
    client.post(URL, headers=headers, json={"pattern": "lidl", "category_id": cat})
    second = client.post(URL, headers=headers, json={"pattern": "ab", "category_id": cat}).json()
    # The pre-check misses (the other request has not committed yet)...
    monkeypatch.setattr("app.api.category_rules._by_pattern", lambda *a, **k: None)
    r = client.put(
        f"{URL}/{second['id']}", headers=headers, json={"pattern": "lidl", "category_id": cat}
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Another rule already uses this pattern."
    # ...and the session is usable afterwards, with the rule unchanged.
    monkeypatch.undo()
    rules = {x["pattern"] for x in client.get(URL, headers=headers).json()}
    assert rules == {"lidl", "ab"}
