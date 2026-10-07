"""The /app/ CSP lets the Passkey form follow /app/auth/link's redirect to the IdP.

Browsers check form-action on every redirect hop, so the validated issuer origin is
appended exactly as the legacy CSP does. Everything else stays identical."""

import pytest

from app import web_app
from app.core.config import settings


@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>Tameio</title>")
    monkeypatch.setattr(web_app, "DIST_DIR", tmp_path)
    monkeypatch.setattr(settings, "new_app_enabled", True)
    return tmp_path


def _oidc(monkeypatch, issuer="https://id.example.test"):
    monkeypatch.setattr(settings, "oidc_issuer", issuer)
    monkeypatch.setattr(settings, "oidc_client_id", "cid")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")


def _directives(csp: str) -> dict[str, str]:
    return {d.split(" ", 1)[0]: d for d in (p.strip() for p in csp.split(";")) if d}


def test_app_csp_allows_the_issuer_as_a_form_action(client, dist, monkeypatch):
    _oidc(monkeypatch, "https://id.example.test:8443/realm")
    csp = client.get("/app/").headers["content-security-policy"]
    assert "form-action 'self' https://id.example.test:8443;" in csp
    # Only form-action changes: every other directive is APP_CSP's.
    got, base = _directives(csp), _directives(web_app.APP_CSP)
    assert got.pop("form-action") != base.pop("form-action")
    assert got == base
    assert got["script-src"] == "script-src 'self' 'wasm-unsafe-eval'"


def test_app_csp_without_oidc_is_self_only(client, dist, monkeypatch):
    monkeypatch.setattr(settings, "oidc_issuer", "")
    csp = client.get("/app/").headers["content-security-policy"]
    assert "form-action 'self';" in csp
    assert csp == web_app.APP_CSP


def test_app_csp_ignores_an_unsafe_issuer(client, dist, monkeypatch):
    _oidc(monkeypatch, "https://a.com; script-src *")
    csp = client.get("/app/").headers["content-security-policy"]
    assert "form-action 'self';" in csp and "script-src *" not in csp


def test_app_csp_on_a_client_route_and_a_404(client, dist, monkeypatch):
    _oidc(monkeypatch)
    for url in ("/app/settings/profile", "/app/assets/nope.js"):
        csp = client.get(url).headers["content-security-policy"]
        assert "form-action 'self' https://id.example.test;" in csp
