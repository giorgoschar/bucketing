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


# ---------------------------------------------------------------------------
# hx-boost re-execution hazards
# ---------------------------------------------------------------------------

def test_global_listeners_are_registered_once():
    """base.html re-executes on every boosted body swap.

    Listeners on document/window survive the swap, so an unguarded
    addEventListener accumulates one duplicate per navigation. That is what
    made the app get slower the more tabs you changed.
    """
    base = Path("templates/base.html").read_text()
    for guard in ("__csrfWired", "__csrfFieldsWired", "__offlineWired",
                  "__alpineReinitWired"):
        assert guard in base, f"missing one-time guard {guard}"


def test_notification_poller_keeps_a_single_timer():
    """setInterval lives on window, so a per-component timer leaks on each swap."""
    base = Path("templates/base.html").read_text()
    assert "window.__notifTimer" in base
    assert "clearInterval(window.__notifTimer)" in base


def test_no_duplicate_form_field_names_in_a_form():
    """FastAPI takes the LAST value for a repeated form field.

    Two inputs named end_date in the bucket form meant the hidden savings field
    silently wiped the trip end date, because x-show only sets display:none —
    the field still submits. Conditional fields must be :disabled when hidden.
    """
    import re

    html = Path("templates/buckets/detail.html").read_text()
    conditional = re.findall(r'<input[^>]*name="(end_date|start_date|goal_amount)"[^>]*>', html)
    assert conditional, "expected the conditional bucket fields"
    for match in re.finditer(r'<input[^>]*name="(end_date|start_date|goal_amount)"[^>]*>', html):
        tag = match.group(0)
        assert ":disabled=" in tag, (
            f'{match.group(1)} must be :disabled when hidden, or it still submits: {tag[:120]}'
        )


def test_dates_render_day_first():
    """Greek/EU convention is dd/mm/yyyy, not a month-abbreviation format."""
    from app.templates import dmy, dmy_short
    from datetime import date

    assert dmy(date(2026, 8, 15)) == "15/08/2026"
    assert dmy_short(date(2026, 8, 15)) == "15/08"
    assert dmy(None) == ""

    # No template should be back on the anglophone format.
    offenders = [
        str(p) for p in TEMPLATES.rglob("*.html")
        if "strftime('%d %b" in p.read_text() or 'strftime("%d %b' in p.read_text()
    ]
    assert not offenders, f"day-month strftime left in {offenders}"


# ---------------------------------------------------------------------------
# Tailwind build
# ---------------------------------------------------------------------------

def test_no_template_loads_the_tailwind_cdn():
    """cdn.tailwindcss.com ships a JIT compiler that generates CSS in the
    browser on every page load. It is explicitly not for production."""
    # Match the tag, not prose: base.html explains in a comment why the CDN was
    # removed, and that mention must not trip this.
    offenders = [
        str(p) for p in TEMPLATES.rglob("*.html")
        if 'src="https://cdn.tailwindcss.com"' in p.read_text()
    ]
    assert not offenders, f"Tailwind CDN still loaded in {offenders}"


def test_built_stylesheet_exists_and_is_substantial():
    css = Path("static/css/app.css")
    assert css.exists(), "run: npm run css"
    assert css.stat().st_size > 20_000, "stylesheet looks truncated — rebuild it"


def test_every_base_template_links_the_stylesheet():
    for base in ("templates/base.html", "templates/auth/base_auth.html"):
        assert '/static/css/app.css' in Path(base).read_text(), f"{base} has no stylesheet"


def test_tailwind_scans_the_static_js():
    """base.html and the component files build class strings at runtime (the
    offline pill picks its colour by state). Those never appear in markup, so
    without scanning the JS they get purged and the element renders unstyled."""
    config = Path("tailwind.config.js").read_text()
    assert "./static/*.js" in config
    assert "./templates/**/*.html" in config


@pytest.mark.parametrize("cls", [
    # built at runtime in JS, so only present if the JS is scanned
    "bg-amber-500", "bg-red-500", "bg-emerald-500",
    # arbitrary values, only present with JIT-style scanning
    r"text-\[11px\]", r"w-\[10rem\]",
    # dark mode and the custom palette
    r"dark\:bg-gray-900", "bg-primary-500",
    # migrated from the old inline <style>
    "x-cloak", "htmx-indicator",
])
def test_critical_classes_survived_purging(cls):
    assert cls in Path("static/css/app.css").read_text(), (
        f"{cls} was purged — check tailwind.config.js content globs, then npm run css"
    )


@pytest.mark.parametrize("shade", ["300", "400", "900"])
def test_primary_shades_used_in_templates_are_defined(shade):
    """Templates referenced primary-300/-400/-900, which the old inline config
    never defined — those classes silently produced nothing.

    Checks the built CSS rather than the config, since that is what actually
    reaches the browser."""
    css = Path("static/css/app.css").read_text()
    assert f"primary-{shade}" in css, (
        f"primary-{shade} is used in templates but absent from the built CSS"
    )


def test_inline_scripts_are_syntactically_balanced():
    """A stray brace in base.html kills the whole script block, and every
    Alpine component with it — silently, since no server test executes JS."""
    import re

    for tpl in ("templates/base.html", "templates/transactions/new.html"):
        html = Path(tpl).read_text()
        for i, m in enumerate(re.finditer(r"<script>(.*?)</script>", html, re.S)):
            body = m.group(1)
            line = html[:m.start()].count("\n") + 1
            assert body.count("{") == body.count("}"), (
                f"{tpl} script at line {line}: unbalanced braces"
            )
            assert body.count("(") == body.count(")"), (
                f"{tpl} script at line {line}: unbalanced parentheses"
            )
