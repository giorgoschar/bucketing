"""
Front-end wiring contracts.

base.html renders the content block before the scripts block, and hx-boost
inserts the whole body before HTMX evaluates any <script> inside it. An Alpine
factory defined in a page's trailing scripts block therefore does not exist
when Alpine initialises the nodes being inserted — it threw
"<factory> is not defined" and left the component dead until a hard refresh.

These are cheap guards against that regressing. Behaviour is verified in a real
browser separately; these keep the structural invariant honest.
"""
import re
from pathlib import Path

import pytest

TEMPLATES = Path("templates")
STATIC = Path("static")

# Factories that must be defined in <head>, not in a swapped body.
HEAD_LOADED = {
    "insightsFilters": "static/insights.js",
    "widgetToggle": "static/insights.js",
    "expenseWizard": "static/expense-wizard.js",
}


@pytest.mark.parametrize("factory,source", HEAD_LOADED.items())
def test_factory_lives_in_a_head_loaded_file(factory, source):
    assert f"function {factory}(" in Path(source).read_text(), (
        f"{factory} must be defined in {source}"
    )


@pytest.mark.parametrize("source", sorted(set(HEAD_LOADED.values())))
def test_head_loads_the_file_before_alpine(source):
    """Deferred scripts run in document order and Alpine initialises on start,
    so any factory it needs must already have been evaluated."""
    base = Path("templates/base.html").read_text()
    src = f'src="/{source}"'
    alpine = 'src="/static/vendor/alpine.min.js"'
    assert src in base, f"{src} is not loaded"
    # Match the tags, not prose mentioning the filename.
    assert base.index(src) < base.index(alpine), (
        f"/{source} must load before alpine.min.js"
    )


@pytest.mark.parametrize("factory", sorted(HEAD_LOADED))
def test_factory_is_not_also_defined_in_a_template(factory):
    """A duplicate definition in a swapped body reintroduces the race."""
    for tpl in TEMPLATES.rglob("*.html"):
        assert f"function {factory}(" not in tpl.read_text(), (
            f"{factory} is redefined in {tpl}"
        )


@pytest.mark.parametrize("source", sorted(set(HEAD_LOADED.values())))
def test_head_loaded_files_contain_no_jinja(source):
    """These are served as static assets — Jinja in them is never rendered."""
    text = Path(source).read_text()
    assert "{{" not in text and "{%" not in text, f"{source} contains Jinja"


def test_x_model_is_never_given_a_non_assignable_expression():
    """x-model compiles to an assignment.

    `x-model="form.is_shared ? 'on' : 'off'"` threw "Invalid left-hand side in
    assignment" and aborted Alpine's setup for the whole component. Use :value
    for a computed value.
    """
    offenders = []
    for tpl in TEMPLATES.rglob("*.html"):
        for match in re.finditer(r'x-model(?:\.[a-z]+)?="([^"]*)"', tpl.read_text()):
            expr = match.group(1)
            if "?" in expr or "(" in expr:
                offenders.append(f"{tpl}: {expr}")
    assert not offenders, "x-model needs an assignable target:\n" + "\n".join(offenders)
