"""Phase C S1 (spec §3.1, §3.3, §7 "Suggestion"; Review Focus 4)."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models import (
    Category,
    CategoryRule,
    CategoryRuleDismissal,
    Transaction,
    TransactionType,
)
from app.services.category_rules import normalise_pattern
from tests.test_api import api  # noqa: F401  (fixture)
from tests.test_isolation import _add_member_user  # noqa: F401

SUGGEST = "/api/v1/category-rules/suggestion"
DISMISS = "/api/v1/category-rules/suggestion/dismiss"
RULES = "/api/v1/settings/category-rules"
CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "rule_normalisation_cases.json").read_text("utf-8")
)


def _cat(db, hh, name="Groceries"):
    c = Category(household_id=hh.household_id, name=name)
    db.add(c)
    db.commit()
    return c.id


def _txn(db, hh, merchant, category_id, **kw):
    kw.setdefault("type", TransactionType.expense)
    kw.setdefault("bucket_id", hh.bucket_id)
    t = Transaction(
        household_id=hh.household_id,
        amount=Decimal("10"),
        paid_by=hh.user_id,
        transaction_date=date(2026, 10, 5),
        merchant=merchant,
        category_id=category_id,
        **kw,
    )
    db.add(t)
    db.commit()
    return t.id


def _ask(client, headers, txn_id):
    r = client.get(SUGGEST, params={"transaction_id": txn_id}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _two(db, hh, cat, merchants=("Lidl", "Lidl")):
    ids = [_txn(db, hh, m, cat) for m in merchants]
    return ids[-1]


# ------------------------------------------------------------ shared cases


@pytest.mark.parametrize("case", CASES, ids=lambda c: repr(c["input"]))
def test_normalisation_cases_agree_with_the_server(case):
    assert normalise_pattern(case["input"]) == case["pattern"]


@pytest.mark.parametrize(
    "spellings",
    [
        ("LIDL", "Lidl ", "  lidl"),
        ("Λιντλ", "ΛΙΝΤΛ", "λιντλ "),
        ("Σκλαβενίτης", "ΣΚΛΑΒΕΝΙΤΗΣ"),
        ("Καφέ  Μπάρ", "ΚΑΦΕ ΜΠΑΡ"),
    ],
)
def test_different_spellings_of_one_merchant_count_together(client, db, api, spellings):  # noqa: F811
    """Review Focus 4: the suggestion, the rule and the count agree."""
    headers, hh = api
    cat = _cat(db, hh)
    ids = [_txn(db, hh, s, cat) for s in spellings[:2]]
    got = _ask(client, headers, ids[-1])
    assert got is not None
    assert got["pattern"] == normalise_pattern(spellings[0])
    assert got["label"] == spellings[1].strip()
    # The rule Always creates folds to the very pattern offered.
    r = client.post(RULES, headers=headers, json={"pattern": got["pattern"], "category_id": cat})
    assert r.json()["pattern"] == got["pattern"]
    assert _ask(client, headers, ids[-1]) is None


# ------------------------------------------------------------- suggestion


def test_the_second_matching_entry_gives_a_suggestion(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh)
    first = _txn(db, hh, "Lidl", cat)
    assert _ask(client, headers, first) is None
    second = _txn(db, hh, "LIDL ", cat)
    assert _ask(client, headers, second) == {
        "pattern": "lidl",
        "label": "LIDL",
        "category_id": cat,
        "category_name": "Groceries",
    }


def test_a_different_category_or_merchant_does_not_count(client, db, api):  # noqa: F811
    headers, hh = api
    cat, other = _cat(db, hh), _cat(db, hh, "Coffee")
    _txn(db, hh, "Lidl", other)
    _txn(db, hh, "Lidl Express", cat)
    one = _txn(db, hh, "Lidl", cat)
    assert _ask(client, headers, one) is None


def test_deleted_entries_do_not_count(client, db, api):  # noqa: F811
    from app.core.clock import utcnow_naive

    headers, hh = api
    cat = _cat(db, hh)
    gone = _txn(db, hh, "Lidl", cat)
    db.query(Transaction).filter_by(id=gone).update({"deleted_at": utcnow_naive()})
    db.commit()
    assert _ask(client, headers, _txn(db, hh, "Lidl", cat)) is None
    assert client.get(SUGGEST, params={"transaction_id": gone}, headers=headers).status_code == 404


def test_income_and_merchantless_and_uncategorised_entries_give_null(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh)
    _txn(db, hh, "Lidl", cat)
    income = _txn(db, hh, "Lidl", cat, type=TransactionType.income, bucket_id=None)
    assert _ask(client, headers, income) is None
    for blank in (None, "", "   ", "x"):
        _txn(db, hh, blank, cat)
        assert _ask(client, headers, _txn(db, hh, blank, cat)) is None
    assert _ask(client, headers, _txn(db, hh, "Lidl", None)) is None


def test_a_rule_that_already_gives_the_category_gives_null(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh)
    last = _two(db, hh, cat)
    db.add(CategoryRule(household_id=hh.household_id, pattern="lidl", category_id=cat))
    db.commit()
    assert _ask(client, headers, last) is None


def test_a_rule_giving_another_category_still_gives_a_suggestion(client, db, api):  # noqa: F811
    headers, hh = api
    cat, other = _cat(db, hh), _cat(db, hh, "Coffee")
    last = _two(db, hh, cat)
    db.add(CategoryRule(household_id=hh.household_id, pattern="lidl", category_id=other))
    db.commit()
    assert _ask(client, headers, last)["category_id"] == cat


def test_two_dismissals_stop_it_and_creating_a_rule_clears_them(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh)
    last = _two(db, hh, cat)
    r = client.post(DISMISS, headers=headers, json={"pattern": "Lidl"})
    assert r.status_code == 200 and r.json() == {"pattern": "lidl", "times": 1}
    assert _ask(client, headers, last) is not None
    assert client.post(DISMISS, headers=headers, json={"pattern": " LIDL"}).json()["times"] == 2
    assert _ask(client, headers, last) is None
    # Teaching the rule (any path) forgets the dismissals.
    client.post(RULES, headers=headers, json={"pattern": "lidl", "category_id": cat})
    db.expire_all()
    assert db.query(CategoryRuleDismissal).count() == 0


def test_repointing_through_put_clears_the_dismissal(client, db, api):  # noqa: F811
    headers, hh = api
    cat = _cat(db, hh)
    rule = client.post(RULES, headers=headers, json={"pattern": "abc", "category_id": cat}).json()
    client.post(DISMISS, headers=headers, json={"pattern": "lidl"})
    r = client.put(
        f"{RULES}/{rule['id']}", headers=headers, json={"pattern": "Lidl", "category_id": cat}
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(CategoryRuleDismissal).count() == 0


def test_dismiss_rejects_an_unusable_pattern(client, api):  # noqa: F811
    headers, _ = api
    assert client.post(DISMISS, headers=headers, json={"pattern": "a"}).status_code == 400


def test_other_households_entry_is_404_and_dismissals_are_per_household(
    client,
    db,
    api,
    make_household,  # noqa: F811
):
    headers, hh = api
    cat = _cat(db, hh)
    mine = _two(db, hh, cat)
    other = make_household(username="neighbour")
    ocat = _cat(db, other)
    theirs = _two(db, other, ocat)
    assert (
        client.get(SUGGEST, params={"transaction_id": theirs}, headers=headers).status_code == 404
    )
    assert (
        client.get(SUGGEST, params={"transaction_id": "nope"}, headers=headers).status_code == 404
    )
    # Another household's entries never count towards mine.
    solo = _txn(db, hh, "Spar", cat)
    _txn(db, other, "Spar", ocat)
    _txn(db, other, "Spar", ocat)
    assert _ask(client, headers, solo) is None
    client.post(DISMISS, headers=headers, json={"pattern": "lidl"})
    client.post(DISMISS, headers=headers, json={"pattern": "lidl"})
    assert _ask(client, headers, mine) is None
    db.expire_all()
    assert db.query(CategoryRuleDismissal).filter_by(household_id=other.household_id).count() == 0


def test_requires_auth(client):
    assert client.get(SUGGEST, params={"transaction_id": "x"}).status_code == 401
    assert client.post(DISMISS, json={"pattern": "lidl"}).status_code == 401


def test_the_suggestion_route_is_in_the_openapi_with_a_model(client):
    spec = client.get("/openapi.json").json()["paths"]
    get = spec[SUGGEST]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "RuleSuggestionOut" in json.dumps(get)
    assert "RuleDismissOut" in json.dumps(spec[DISMISS]["post"])


def test_normalisation_fixture_is_the_same_file_as_the_web_copy():
    web = Path(__file__).parent.parent / "web/src/features/rules/rule_normalisation_cases.json"
    assert web.read_text("utf-8") == (Path(__file__).parent / "fixtures/rule_normalisation_cases.json").read_text("utf-8")
