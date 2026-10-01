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
import json
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
    "notifCenter": "static/app-components.js",
    "pushSettings": "static/app-components.js",
    "receiptScanner": "static/receipt-scanner.js",
    "stockAdd": "static/stock.js",
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
    # __alpineReinitWired is deliberately gone: every Alpine factory now loads
    # from <head>, so Alpine's own observer handles swapped nodes and the
    # htmx:afterSettle initTree() fallback (which double-initialised trees) was
    # removed along with it.
    for guard in ("__csrfWired", "__csrfFieldsWired", "__offlineWired"):
        assert guard in base, f"missing one-time guard {guard}"
    assert "__alpineReinitWired" not in base, (
        "the initTree fallback is back; it re-initialises trees Alpine already "
        "claimed and makes it throw during teardown"
    )


def test_notification_bells_each_own_their_timer():
    """Each bell keeps its own interval in this._timer and clears it in
    destroy(); a shared window.__notifTimer made the second bell cancel the
    first one's poller."""
    js = Path("static/app-components.js").read_text()
    assert "__notifTimer" not in js
    assert "this._timer = setInterval(" in js
    assert "clearInterval(this._timer)" in js


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
    from datetime import date

    from app.templates import dmy, dmy_short

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
        for m in re.finditer(r"<script>(.*?)</script>", html, re.S):
            body = m.group(1)
            line = html[:m.start()].count("\n") + 1
            assert body.count("{") == body.count("}"), (
                f"{tpl} script at line {line}: unbalanced braces"
            )
            assert body.count("(") == body.count(")"), (
                f"{tpl} script at line {line}: unbalanced parentheses"
            )


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def test_charts_need_no_javascript_library():
    """Charts sit inside #insights-body, which is replaced on every filter
    change. A JS charting library would need tearing down and re-instantiating
    on each swap — the lifecycle problem that repeatedly broke Alpine here."""
    for name in ("chart.js", "chartjs", "apexcharts", "echarts", "vega", "plotly"):
        for tpl in TEMPLATES.rglob("*.html"):
            assert name not in tpl.read_text().lower(), f"{name} referenced in {tpl}"


def test_chart_macros_exist():
    macros = Path("templates/macros/charts.html").read_text()
    for m in ("line_chart", "donut", "grouped_bars"):
        assert f"macro {m}(" in macros


def test_charts_do_not_distort_text():
    """preserveAspectRatio="none" stretches labels and turns point markers into
    ellipses when the SVG is wider than its viewBox."""
    macros = Path("templates/macros/charts.html").read_text()
    assert 'preserveAspectRatio="none"' not in macros


def test_axis_labels_are_anchored_inside_the_viewbox():
    """Centring the first and last labels on their points pushed them past the
    edge — "Feb" rendered as "eb" and "Jul" as "Ju"."""
    macros = Path("templates/macros/charts.html").read_text()
    assert "'start' if loop.first" in macros
    assert "'end' if loop.last" in macros


def _chart_markup() -> str:
    """The macro file with its Jinja comments stripped.

    The header comment explains why native <title> was dropped, and matching on
    the raw text made the guard below pass on its own documentation.
    """
    src = Path("templates/macros/charts.html").read_text()
    return re.sub(r"\{#.*?#\}", "", src, flags=re.S)


def test_every_chart_shape_carries_a_tooltip():
    """Native SVG <title> took about a second to appear and showed nothing at
    all on touch. Every interactive shape must instead expose data-tip, which
    the delegated listener in static/chart-tooltip.js reads."""
    macros = _chart_markup()
    assert "<title>" not in macros, "native <title> tooltips are back"
    # line points, both grouped-bar hit targets, donut segments
    assert macros.count("data-tip=") >= 3


def test_chart_shapes_are_reachable_without_a_mouse():
    """A tooltip that only responds to hover is unusable by keyboard, and the
    <title> it replaced was at least announced by screen readers."""
    macros = _chart_markup()
    tips = macros.count("data-tip=")
    assert macros.count("aria-label=") >= tips
    assert macros.count('tabindex="0"') >= tips


def test_tooltip_listener_is_delegated_and_registered_once():
    """Binding per chart element would have to be redone after every HTMX swap
    — the leak that made navigation slow down. One listener on document."""
    src = (STATIC / "chart-tooltip.js").read_text()
    assert "window.__chartTipWired" in src
    assert "document.addEventListener" in src
    # It is loaded from <head>, where document.body does not exist yet.
    assert "document.body.addEventListener" not in src


def test_head_loads_the_tooltip_listener():
    head = Path("templates/base.html").read_text().split("</head>")[0]
    assert "/static/chart-tooltip.js" in head


def test_tooltip_style_is_hand_written_not_purgeable_tailwind():
    """The element is created in JavaScript, so Tailwind's content scan would
    never see its classes."""
    css = Path("static/src/app.css").read_text()
    assert ".chart-tip" in css
    built = Path("static/css/app.css").read_text()
    assert ".chart-tip" in built, "rebuild the stylesheet: npm run css"


def test_service_worker_precaches_the_tooltip_listener():
    sw = (STATIC / "sw.js").read_text()
    assert "/static/chart-tooltip.js" in sw


# ---------------------------------------------------------------------------
# Task 1.4: no user data interpolated into JavaScript strings
# ---------------------------------------------------------------------------

_JS_ATTR = re.compile(
    r"""(?<![\w-])(?P<attr>x-[a-z:.-]+|@[a-z.:-]+|:[a-z-]+|on[a-z]+|hx-[a-z]+)"""
    r"""=(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)')""",
)
_INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
# Exact interpolations allowed inside JS attributes: server-generated UUIDs,
# enum values, loop counters and literal true/false. Anything else (a name, a
# URL, a currency...) must go through data-* attributes or `| tojson` in a
# <script> block. New interpolations fail by default; add here only after
# proving the value is not user-controlled.
_ALLOWED_ATTR_EXPRS = {
    "{{ bill.id }}", "{{ bucket.type.value }}", "{{ bucket.id }}",
    "{{ cat.id }}", "{{ u.id }}", "{{ member.id }}", "{{ p }}",
    "{{ value }}", "{{ key }}", "{{ amt }}", "{{ i }}",
    "{{ 'true' if bill.is_auto_pay else 'false' }}",
    "{{ 'true' if bill.splits else 'false' }}",
    "{{ 'true' if not bill.amount else 'false' }}",
    "{{ 'true' if txn.splits else 'false' }}",
}


def _js_attr_interpolations():
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text()
        for m in _JS_ATTR.finditer(text):
            if m.group("attr") in ("hx-get", "hx-post", "hx-target"):
                continue  # URLs, not JavaScript
            body = m.group("dq") if m.group("dq") is not None else m.group("sq")
            for expr in _EXPR.findall(body):
                if expr not in _ALLOWED_ATTR_EXPRS:
                    line = text.count("\n", 0, m.start()) + 1
                    yield f"{path}:{line}: attribute {expr}"
        for m in _INLINE_SCRIPT.finditer(text):
            for expr in _EXPR.findall(m.group(1)):
                if not re.search(r"\|\s*tojson\s*\}\}$", expr):
                    line = text.count("\n", 0, m.start(1)) + 1
                    yield f"{path}:~{line}: <script> {expr} (needs | tojson)"


def test_no_user_data_in_template_built_js_strings():
    offenders = list(_js_attr_interpolations())
    assert not offenders, "user data inside JS attribute:\n" + "\n".join(offenders)


def test_lib_js_has_delegated_confirm_and_is_loaded():
    lib = (STATIC / "lib.js").read_text()
    assert "data-confirm" in lib or "[data-confirm]" in lib
    assert "confirm(" in lib
    assert 'src="/static/lib.js"' in Path("templates/base.html").read_text()
    sw = (STATIC / "sw.js").read_text()
    assert "/static/lib.js" in sw


def test_no_inline_confirm_handlers_with_interpolation():
    for path in TEMPLATES.rglob("*.html"):
        for line in path.read_text().splitlines():
            assert not ("confirm(" in line and "{{" in line), f"{path}: {line.strip()}"


EVIL = "');alert(1);//"


def test_hostile_names_render_inert(client, db, authed):
    from app.models import Category, HouseholdMember, User

    hh_id = db.query(HouseholdMember).first().household_id
    db.add(Category(household_id=hh_id, name=EVIL, color="#112233", icon="x"))
    db.add(Category(household_id=hh_id, name="<script>boom</script>",
                    color="#112233", icon="x"))
    for u in db.query(User).all():
        u.display_name = EVIL
    db.commit()

    for url in ("/transactions/new", "/settings", "/bills"):
        r = client.get(url)
        assert r.status_code == 200, url
        html = r.text
        assert "<script>boom" not in html, url
        # The raw payload may only appear HTML-escaped, never inside a JS
        # string (the quote would be a literal ' instead of &#39;).
        assert EVIL not in html, f"{url} leaks an unescaped payload"


def test_csp_hardening_directives(client):
    csp = client.get("/login").headers["content-security-policy"]
    for d in ("object-src 'none'", "base-uri 'self'", "form-action 'self'"):
        assert d in csp


@pytest.mark.parametrize("bad", ["red", "#12345", "#1234567", "#gggggg",
                                 "url(javascript:x)", "#fff;x:y", ""])
def test_parse_color_rejects(bad):
    from fastapi import HTTPException

    from app.validators import parse_color
    with pytest.raises(HTTPException) as e:
        parse_color(bad)
    assert e.value.status_code == 400


def test_parse_color_normalises():
    from app.validators import parse_color
    assert parse_color(" #AbCdEf ") == "#abcdef"


def test_html_settings_reject_bad_colors(client, db, authed):
    from app.models import Category, User
    r = client.post("/settings/categories", data={
        "name": "X", "color": 'red;" onload="x', "icon": "a"}, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(Category).filter_by(name="X").count() == 0
    r = client.post("/settings/profile", data={
        "display_name": "N", "avatar_color": "nope"}, headers=authed.headers)
    assert r.status_code == 400
    assert db.query(User).filter_by(avatar_color="nope").count() == 0


def test_api_settings_reject_bad_colors(client, make_household):
    import pyotp

    from tests.conftest import PASSWORD
    hh = make_household()
    r = client.post("/api/v1/auth/login",
                    json={"username": hh.username, "password": PASSWORD})
    p = r.json()["pending_token"]
    r = client.post("/api/v1/auth/totp/verify",
                    json={"pending_token": p, "code": pyotp.TOTP(hh.secret).now()})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post("/api/v1/settings/categories", headers=h,
                       json={"name": "X", "color": "<b>"}).status_code == 400
    assert client.put("/api/v1/settings/profile", headers=h,
                      json={"display_name": "N", "avatar_color": "bad"}).status_code == 400
    ok = client.post("/api/v1/settings/categories", headers=h,
                     json={"name": "X", "color": "#ABCDEF"})
    assert ok.status_code == 201 and ok.json()["color"] == "#abcdef"


def test_scan_page_renders_currency_as_json(client, db, authed):
    """receiptScanner() lives in static/receipt-scanner.js, so per-page config
    reaches it through a data-init attribute, JSON-encoded by `| tojson`."""
    import html as htmllib

    from app.models import Household, HouseholdMember
    hh = db.get(Household, db.query(HouseholdMember).first().household_id)
    r = client.get("/transactions/scan")
    assert r.status_code == 200
    m = re.search(r"x-data=\"receiptScanner\(\)\"[^>]*data-init='([^']*)'", r.text, re.S)
    assert m, "scan page lost its data-init config"
    cfg = json.loads(htmllib.unescape(m.group(1)))
    assert cfg["currency"] == hh.default_currency
    assert "currency: '" not in r.text


def test_api_household_rejects_script_currency(client, make_household):
    import pyotp

    from tests.conftest import PASSWORD
    hh = make_household()
    r = client.post("/api/v1/auth/login",
                    json={"username": hh.username, "password": PASSWORD})
    r = client.post("/api/v1/auth/totp/verify", json={
        "pending_token": r.json()["pending_token"],
        "code": pyotp.TOTP(hh.secret).now()})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    bad = client.put("/api/v1/settings/household", headers=h,
                     json={"name": "H", "default_currency": "');alert(1);//"})
    assert bad.status_code == 400
    ok = client.put("/api/v1/settings/household", headers=h,
                    json={"name": "H", "default_currency": "EUR"})
    assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Task 2.6: CSRF on every mutating fetch, no CDN, single lib.js
# ---------------------------------------------------------------------------

def _first_party_sources():
    """Templates and our own static JS; vendored libraries are not ours."""
    for path in sorted(TEMPLATES.rglob("*.html")):
        yield path
    for path in sorted(STATIC.glob("*.js")):
        yield path


def _fetch_calls(text):
    """Yield (offset, call_text) for every `fetch(` call, balancing parens."""
    for m in re.finditer(r"(?<![\w.$])fetch\(", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        yield m.start(), text[m.start():i]


def test_every_mutating_fetch_carries_a_csrf_token():
    """A POST/PUT/PATCH/DELETE fetch must go through app.fetchJSON (which adds
    X-CSRF-Token) or set the header itself. The scan page's two POSTs did
    neither and were rejected with 403."""
    offenders, seen = [], 0
    for path in _first_party_sources():
        if path.name == "lib.js":
            continue  # defines app.fetchJSON
        text = path.read_text()
        for offset, call in _fetch_calls(text):
            if re.search(r"method:\s*['\"](POST|PUT|PATCH|DELETE)['\"]", call):
                seen += 1
                if "X-CSRF-Token" not in call:
                    line = text.count("\n", 0, offset) + 1
                    offenders.append(f"{path}:{line}")
    assert seen, "expected to find mutating fetch calls; is the regex stale?"
    assert not offenders, "fetch without CSRF token (use app.fetchJSON):\n" + "\n".join(offenders)


def test_no_template_loads_a_remote_script():
    for path in TEMPLATES.rglob("*.html"):
        assert not re.search(r"<script[^>]*\bsrc=[\"']https?://", path.read_text()), (
            f"{path} loads a remote script"
        )


def test_no_first_party_code_references_a_cdn():
    for path in _first_party_sources():
        if path.name == "sw.js":
            continue  # the service worker may cache whatever origins it sees
        text = path.read_text()
        for host in ("cdn.jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com"):
            if path.suffix == ".html":
                # comments may explain history; markup and script may not
                text = re.sub(r"<!--.*?-->|\{#.*?#\}", "", text, flags=re.S)
            assert host not in text, f"{path} references {host}"


def _strip_js(src):
    """Blank out strings and comments so only structure is left."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"`":
            q, i = c, i + 1
            while i < n and src[i] != q:
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append('""')
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _top_level_lexicals(script):
    code = _strip_js(script)
    depth, found = 0, []
    for m in re.finditer(r"[{}()\[\]]|\b(?:const|let)\s+[\w${]", code):
        tok = m.group(0)
        if tok in "{([":
            depth += 1
        elif tok in "})]":
            depth -= 1
        elif depth == 0:
            found.append(tok.split()[0])
    return found


def test_no_top_level_const_or_let_in_inline_scripts():
    """The body re-executes on every hx-boost swap. A top-level const/let in an
    inline script throws "Identifier has already been declared" the second time
    and takes the rest of the block with it."""
    offenders = []
    for path in TEMPLATES.rglob("*.html"):
        for m in _INLINE_SCRIPT.finditer(path.read_text()):
            if _top_level_lexicals(m.group(1)):
                line = path.read_text().count("\n", 0, m.start(1)) + 1
                offenders.append(f"{path}:~{line}")
    assert not offenders, "top-level const/let:\n" + "\n".join(offenders)


def test_top_level_lexical_detector_works():
    assert _top_level_lexicals("const a = 1;")
    assert _top_level_lexicals("function f(){ const a = 1; }") == []
    assert _top_level_lexicals("var s = 'let x'; // const y") == []


def test_lib_js_exposes_app_helpers():
    lib = (STATIC / "lib.js").read_text()
    assert "window.app" in lib
    assert "csrfToken" in lib and "fetchJSON" in lib
    assert "X-CSRF-Token" in lib


def test_there_is_one_csrf_token_reader():
    """_csrfToken (base.html) and _csrf (offline.js) were duplicates of the
    reader that now lives in lib.js."""
    for path in _first_party_sources():
        text = path.read_text()
        assert "_csrfToken" not in text, f"{path} still uses _csrfToken"
        if path.name != "sw.js":
            assert not re.search(r"\b_csrf\(", text), f"{path} still uses _csrf()"


def test_lib_js_loads_before_other_scripts_that_use_it():
    head = Path("templates/base.html").read_text().split("</head>")[0]
    lib = head.index('src="/static/lib.js"')
    for src in ("receipt-scanner.js", "app-components.js", "offline.js"):
        assert lib < head.index(f'src="/static/{src}"'), src


def test_push_is_not_auto_subscribed_on_every_page_load():
    base = Path("templates/base.html").read_text()
    assert "/push/subscribe" not in base
    assert "pushManager.subscribe" not in base
    assert "pushManager.subscribe" in (STATIC / "app-components.js").read_text()


def test_scanner_libraries_are_vendored():
    for rel in (
        "qr-scanner/qr-scanner.legacy.min.js",
        "tesseract/tesseract.min.js",
        "tesseract/worker.min.js",
        "tesseract/core/tesseract-core-simd-lstm.wasm.js",
        "tesseract/core/tesseract-core-lstm.wasm.js",
        "tesseract/lang/eng.traineddata.gz",
        "tesseract/lang/ell.traineddata.gz",
        "pdfjs/pdf.min.mjs",
        "pdfjs/pdf.worker.min.mjs",
    ):
        assert (STATIC / "vendor" / rel).is_file(), f"run: npm run vendor:copy ({rel})"


def test_receipt_scanner_uses_vendored_paths_and_fetch_helper():
    js = (STATIC / "receipt-scanner.js").read_text()
    for needle in ("'/static/vendor/tesseract'", "TESS_BASE + '/worker.min.js'",
                   "TESS_BASE + '/core'", "TESS_BASE + '/lang'",
                   "'/static/vendor/pdfjs'", "PDFJS_BASE + '/pdf.worker.min.mjs'"):
        assert needle in js, needle
    assert js.count("app.fetchJSON(") >= 2
    assert "{{" not in js and "{%" not in js


def test_scanner_vendor_scripts_load_from_self_on_the_scan_page():
    html = Path("templates/transactions/scan.html").read_text()
    assert "/static/vendor/qr-scanner/qr-scanner.legacy.min.js" in html
    assert "/static/vendor/tesseract/tesseract.min.js" in html


def test_csp_does_not_allow_a_cdn(client):
    csp = client.get("/login").headers["content-security-policy"]
    assert "jsdelivr" not in csp and "unpkg" not in csp
    assert "worker-src blob: 'self'" in csp


def test_offline_form_hook_lives_in_the_wizard():
    assert "offlineExpenses" in (STATIC / "expense-wizard.js").read_text()
    assert "<script" not in Path("templates/transactions/new.html").read_text()


def test_service_worker_precaches_new_static_files():
    sw = (STATIC / "sw.js").read_text()
    assert "/static/receipt-scanner.js" in sw
    assert "expenses-v7'" not in sw


def test_offline_save_failure_is_reported_not_swallowed():
    """The submit is cancelled before the IndexedDB save; if the save throws the
    expense is neither sent nor queued, so the user must be told."""
    js = (STATIC / "expense-wizard.js").read_text()
    save = js.index("await window.offlineExpenses.saveOfflineTransaction")
    assert js[:save].rstrip().endswith("try {")
    catch = js.index("catch (err)", save)
    assert "NOT saved" in js[catch:catch + 800] and "return;" in js[catch:catch + 800]
    # success state only after the try/catch
    assert js.index("this.step = 5; // hide", catch) > catch


def test_scanner_base_paths_are_not_globals():
    js = (STATIC / "receipt-scanner.js").read_text()
    assert not re.search(r"^(var|let|const)\s", js, re.M)


def test_stock_is_in_both_navs_and_mobile_nav_stays_at_seven():
    """The bottom bar only fits seven items; Stock replaced Settle there
    (settle up stays in the sidebar and on the My money page)."""
    base = Path("templates/base.html").read_text()
    side = base[base.index("{% set nav = ["):base.index("] %}", base.index("{% set nav = ["))]
    mobile = base[base.index("{% set mobile_nav = ["):base.index("] %}", base.index("{% set mobile_nav = ["))]
    assert "('/stock'" in side and "('/settlement'" in side
    assert "('/stock'" in mobile
    assert mobile.count("('/") <= 7
    assert 'href="/settlement"' in Path("templates/person.html").read_text()
