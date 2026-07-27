"""
User-defined categorisation rules.

Categorisation previously relied on a hardcoded keyword list plus fuzzy name
matching, neither of which could learn from a correction.
"""
import pytest

from app.category_rules import (
    apply_rules, learn_rule, list_rules, normalise_pattern, resolve_category,
)
from app.models import Category, CategoryRule


@pytest.fixture()
def cats(db, authed):
    groceries = Category(household_id=authed.household_id, name="Groceries", icon="🛒")
    fuel = Category(household_id=authed.household_id, name="Fuel", icon="⛽")
    db.add_all([groceries, fuel])
    db.commit()
    authed.groceries_id = groceries.id
    authed.fuel_id = fuel.id
    return authed


# ---------------------------------------------------------------------------
# Pattern handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("LIDL", "lidl"),
    ("  Lidl  Hellas ", "lidl hellas"),
    # Greek: final sigma and accents fold away so OCR variants still match
    ("ΣΚΛΑΒΕΝΙΤΗΣ", "σκλαβενιτησ"),
    ("Σκλαβενίτης", "σκλαβενιτησ"),
    ("ΚΑΦΈ", "καφε"),
    ("", None),
    ("x", None),        # too short to be meaningful
    (None, None),
])
def test_pattern_normalisation(raw, expected):
    assert normalise_pattern(raw) == expected


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_rule_matches_case_insensitively(db, cats):
    learn_rule(db, cats.household_id, "LIDL", cats.groceries_id)
    db.commit()
    assert apply_rules(db, cats.household_id, "Lidl Hellas 123") == cats.groceries_id


def test_no_match_returns_none(db, cats):
    learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    db.commit()
    assert apply_rules(db, cats.household_id, "Shell station") is None


def test_longer_pattern_wins(db, cats):
    """A household can special-case without deleting the general rule."""
    learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    learn_rule(db, cats.household_id, "lidl fuel", cats.fuel_id)
    db.commit()

    assert apply_rules(db, cats.household_id, "LIDL FUEL station") == cats.fuel_id
    assert apply_rules(db, cats.household_id, "LIDL market") == cats.groceries_id


def test_match_count_increments(db, cats):
    learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    db.commit()

    apply_rules(db, cats.household_id, "lidl")
    apply_rules(db, cats.household_id, "lidl")
    db.commit()

    assert db.query(CategoryRule).one().match_count == 2


def test_matches_across_several_texts(db, cats):
    learn_rule(db, cats.household_id, "shell", cats.fuel_id)
    db.commit()
    assert apply_rules(db, cats.household_id, None, "receipt from SHELL") == cats.fuel_id


def test_rules_are_household_scoped(db, cats, make_household):
    other = make_household(name="Other", username="ruleother")
    learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    db.commit()
    assert apply_rules(db, other.household_id, "lidl") is None


# ---------------------------------------------------------------------------
# Learning
# ---------------------------------------------------------------------------

def test_learning_creates_a_rule(db, cats):
    rule = learn_rule(db, cats.household_id, "Sklavenitis", cats.groceries_id)
    db.commit()
    assert rule is not None
    assert rule.pattern == "sklavenitis"


def test_relearning_repoints_instead_of_duplicating(db, cats):
    """Correcting a merchant's category must fix the rule, not add a second."""
    learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    db.commit()
    learn_rule(db, cats.household_id, "LIDL", cats.fuel_id)
    db.commit()

    rules = db.query(CategoryRule).all()
    assert len(rules) == 1
    assert rules[0].category_id == cats.fuel_id


def test_unusable_pattern_is_ignored(db, cats):
    assert learn_rule(db, cats.household_id, "", cats.groceries_id) is None
    assert learn_rule(db, cats.household_id, "x", cats.groceries_id) is None
    assert db.query(CategoryRule).count() == 0


def test_cannot_point_at_another_households_category(db, cats, make_household):
    """A rule must never reference a category outside its household."""
    other = make_household(name="Other", username="rulevictim")
    foreign = Category(household_id=other.household_id, name="Foreign")
    db.add(foreign)
    db.commit()

    assert learn_rule(db, cats.household_id, "lidl", foreign.id) is None
    assert db.query(CategoryRule).count() == 0


def test_list_is_ordered_by_use(db, cats):
    learn_rule(db, cats.household_id, "aaa shop", cats.groceries_id)
    learn_rule(db, cats.household_id, "shell", cats.fuel_id)
    db.commit()
    for _ in range(3):
        apply_rules(db, cats.household_id, "shell")
    db.commit()

    assert list_rules(db, cats.household_id)[0].pattern == "shell"


# ---------------------------------------------------------------------------
# Resolution chain
# ---------------------------------------------------------------------------

def test_rule_beats_the_builtin_guess(db, cats):
    """The household's own correction outranks the hardcoded keyword list."""
    learn_rule(db, cats.household_id, "lidl", cats.fuel_id)   # deliberately "wrong"
    db.commit()

    resolved = resolve_category(
        db, cats.household_id, merchant="LIDL HELLAS",
        hint="groceries", raw_text="LIDL HELLAS",
    )
    assert resolved == cats.fuel_id


def test_falls_back_to_builtin_when_no_rule(db, cats):
    resolved = resolve_category(
        db, cats.household_id, merchant="Some Shop", hint="groceries",
    )
    assert resolved == cats.groceries_id


def test_returns_none_when_nothing_matches(db, cats):
    assert resolve_category(
        db, cats.household_id, merchant="Unknown", hint=None
    ) is None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def test_scan_parse_applies_a_rule(client, db, cats):
    learn_rule(db, cats.household_id, "sklavenitis", cats.fuel_id)
    db.commit()

    r = client.post("/transactions/scan/parse",
                    json={"text": "SKLAVENITIS SUPERMARKET\nΣΥΝΟΛΟ 42,50"},
                    headers=cats.headers)
    assert r.status_code == 200
    assert r.json()["category_id"] == cats.fuel_id


def test_settings_page_lists_rules(client, db, cats):
    learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    db.commit()

    r = client.get("/settings")
    assert r.status_code == 200
    assert "lidl" in r.text
    assert "Auto-categorisation" in r.text


def test_can_add_a_rule(client, db, cats):
    r = client.post("/settings/category-rules", data={
        "pattern": "Jumbo", "category_id": cats.groceries_id,
    }, headers=cats.headers)
    assert r.status_code == 302
    assert db.query(CategoryRule).one().pattern == "jumbo"


def test_adding_a_too_short_rule_is_rejected(client, db, cats):
    r = client.post("/settings/category-rules", data={
        "pattern": "x", "category_id": cats.groceries_id,
    }, headers=cats.headers)
    assert r.status_code == 400
    assert db.query(CategoryRule).count() == 0


def test_can_delete_a_rule(client, db, cats):
    rule = learn_rule(db, cats.household_id, "lidl", cats.groceries_id)
    db.commit()
    rule_id = rule.id

    r = client.post(f"/settings/category-rules/{rule_id}/delete", headers=cats.headers)
    assert r.status_code == 302
    assert db.query(CategoryRule).count() == 0


def test_cannot_delete_another_households_rule(client, db, cats, make_household):
    other = make_household(name="Other", username="ruledelvictim")
    foreign_cat = Category(household_id=other.household_id, name="Foreign")
    db.add(foreign_cat)
    db.commit()
    rule = learn_rule(db, other.household_id, "secret", foreign_cat.id)
    db.commit()

    r = client.post(f"/settings/category-rules/{rule.id}/delete", headers=cats.headers)
    assert r.status_code == 404
    assert db.query(CategoryRule).count() == 1


def test_saving_a_scan_learns_the_rule(client, db, cats):
    """The whole point: correct it once and it sticks."""
    r = client.post("/transactions", data={
        "bucket_id": cats.bucket_id, "transaction_date": "2026-07-20",
        "amount": "42.50", "type": "expense",
        "category_id": cats.groceries_id,
        "merchant": "Sklavenitis Athens", "remember_rule": "on",
    }, headers=cats.headers)
    assert r.status_code == 302

    rule = db.query(CategoryRule).one()
    assert rule.pattern == "sklavenitis athens"
    assert rule.category_id == cats.groceries_id


def test_saving_without_the_toggle_learns_nothing(client, db, cats):
    r = client.post("/transactions", data={
        "bucket_id": cats.bucket_id, "transaction_date": "2026-07-20",
        "amount": "42.50", "type": "expense",
        "category_id": cats.groceries_id, "merchant": "Sklavenitis",
    }, headers=cats.headers)
    assert r.status_code == 302
    assert db.query(CategoryRule).count() == 0


def test_greek_final_sigma_and_accents_match(db, cats):
    """OCR variants of the same Greek merchant must hit the same rule."""
    learn_rule(db, cats.household_id, "ΣΚΛΑΒΕΝΙΤΗΣ", cats.groceries_id)
    db.commit()

    for variant in ("Σκλαβενίτης", "ΣΚΛΑΒΕΝΙΤΗΣ ΑΕ", "σκλαβενιτησ"):
        assert apply_rules(db, cats.household_id, variant) == cats.groceries_id, variant
