"""Final-review frontend fixes: C8/C11 (stock → expense link), C9 (scan payment
method), C5+C6 (cash add form reset, member select, htmx error handler)."""

import html as htmllib
import json
import re
from decimal import Decimal as D
from urllib.parse import parse_qs, urlparse

from app.services import stock as stock_svc
from tests.test_household_settlement import _add_member


def _init_cfg(page):
    raw = re.search(r"data-init='([^']*)'", page, re.S).group(1)
    return json.loads(htmllib.unescape(raw))


def _expense_href(text):
    m = re.search(r'href="(/transactions/new\?[^"]+)"', text)
    return m.group(1).replace("&amp;", "&") if m else None


# ---------------------------------------------------------------------------
# C8 / C11
# ---------------------------------------------------------------------------


def test_mark_bought_without_prices_still_offers_expense_link(client, db, authed):
    item = stock_svc.add_product(
        db, authed.household_id, authed.user_id, name="Milk", quantity=D("0"), min_quantity=D("1")
    )
    db.commit()
    r = client.post(
        "/stock/shopping/bought",
        data={"item_id": [item.id], f"qty_{item.id}": "2"},
        headers=authed.headers,
    )
    assert r.status_code == 200
    href = _expense_href(r.text)
    assert href, "the mark-bought → expense flow must appear even with no prices"
    qs = parse_qs(urlparse(href).query)
    assert "amount" not in qs
    assert qs["currency"] == ["EUR"]


def test_new_expense_honours_currency_prefill(client, authed):
    cfg = _init_cfg(client.get("/transactions/new?currency=USD").text)
    assert cfg["currency"] == "USD"
    assert cfg["prefill"]["currency"] == "USD"
    cfg = _init_cfg(client.get("/transactions/new?currency=ZZZ").text)
    assert cfg["currency"] == "EUR"
    assert "currency" not in cfg["prefill"]


def test_shopping_mark_bought_form_does_not_push_url():
    tpl = open("templates/stock/shopping.html").read()
    form = re.search(r'<form method="POST" action="/stock/shopping/bought"[^>]*>', tpl, re.S).group(
        0
    )
    assert 'hx-push-url="false"' in form


# ---------------------------------------------------------------------------
# C9
# ---------------------------------------------------------------------------


def test_scan_form_offers_payment_method(client, authed):
    page = client.get("/transactions/scan").text
    form = page[page.index('action="/transactions"') :]
    form = form[: form.index("</form>")]
    for v in ("card", "cash"):
        assert f'data-payment-method="{v}"' in form
    assert 'name="payment_method"' in form
    assert "$el.dataset.paymentMethod" in form
    js = open("static/receipt-scanner.js").read()
    assert re.search(r"payment_method:\s*'card'", js)


def test_scan_form_cash_is_stored(client, db, authed):
    from app.models import Transaction

    r = client.post(
        "/transactions",
        data={
            "bucket_id": authed.bucket_id,
            "transaction_date": "2026-07-20",
            "amount": "8.40",
            "type": "expense",
            "exchange_rate": "1.0",
            "is_shared": "off",
            "payment_method": "cash",
        },
        headers=authed.headers,
        follow_redirects=False,
    )
    assert r.status_code in (200, 302)
    assert db.query(Transaction).one().payment_method == "cash"


# ---------------------------------------------------------------------------
# C5 + C6
# ---------------------------------------------------------------------------


def _add_form(page):
    """The "Take to wallet" form."""
    start = page.index('name="kind" value="take"')
    return page[page.rfind("<form", 0, start) : page.index("</form>", start)]


def test_cash_add_form_resets_after_successful_htmx_add(client, authed):
    form = _add_form(client.get("/cash").text)
    assert "hx-on::after-request" in form
    assert "event.detail.successful" in form and "reset()" in form


def test_cash_take_sources_list_every_members_stash(client, db, authed):
    """Any member may take from another's stash (never seeing its balance),
    so the source select lists them for owners and members alike."""
    other = _add_member(db, authed.household_id, "partner")
    db.commit()
    form = _add_form(client.get("/cash").text)
    assert f'value="{other.id}"' in form and f'value="{authed.user_id}"' in form
    assert 'value="bank"' in form


def test_cash_take_sources_for_a_non_owner(client, db, make_household, login):
    owner = make_household()
    member = _add_member(db, owner.household_id, "partner")
    db.commit()
    login(member.username, member.totp_secret)
    form = _add_form(client.get("/cash").text)
    assert f'value="{member.id}"' in form
    assert f'value="{owner.user_id}"' in form


def test_global_htmx_response_error_handler_shows_detail_safely():
    js = open("static/lib.js").read()
    assert "htmx:responseError" in js
    handler = js[js.index("__libHtmxErrorInstalled") :]
    assert "detail" in handler
    assert "textContent" in handler
    assert "innerHTML" not in handler
