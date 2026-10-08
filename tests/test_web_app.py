import pytest

from app import web_app
from app.core.config import settings


@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Tameio</title>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "sw.js").write_text("self.x=1")
    monkeypatch.setattr(web_app, "DIST_DIR", tmp_path)
    monkeypatch.setattr(settings, "new_app_enabled", True)
    return tmp_path


def test_index_served_with_strict_csp(client, dist):
    r = client.get("/app/")
    assert r.status_code == 200 and "Tameio" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp
    assert "unsafe-inline" not in csp and "'unsafe-eval'" not in csp
    assert r.headers["cache-control"] == "no-cache"


def test_client_route_falls_back_to_index(client, dist):
    r = client.get("/app/activity/123")
    assert r.status_code == 200 and "Tameio" in r.text


def test_hashed_asset_is_immutable(client, dist):
    r = client.get("/app/assets/index-abc123.js")
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"]


def test_missing_asset_is_404_not_index(client, dist):
    assert client.get("/app/assets/nope.js").status_code == 404


def test_path_traversal_is_blocked(client, dist):
    assert client.get("/app/..%2f..%2fapp%2fmain.py").status_code == 404


def test_old_ui_keeps_its_csp(client):
    r = client.get("/login")
    assert "'unsafe-inline'" in r.headers["content-security-policy"]


def test_flag_off_is_404(client, dist, monkeypatch):
    monkeypatch.setattr(settings, "new_app_enabled", False)
    assert client.get("/app/").status_code == 404


@pytest.mark.parametrize("url", ["/app/a%00b", "/app/assets/%00"])
def test_null_byte_is_404_with_csp(client, dist, url):
    r = client.get(url)
    assert r.status_code == 404
    assert r.headers["content-security-policy"] == web_app.APP_CSP


def test_head_is_allowed(client, dist):
    r = client.head("/app/")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_auth_paths_are_not_shadowed(client, dist):
    assert client.get("/app/auth/nope").status_code == 404
    assert client.get("/app/auth/link", follow_redirects=False).status_code == 405


def test_sw_is_no_cache(client, dist):
    r = client.get("/app/sw.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_app_csp_allows_the_qr_decoder_worker():
    # qr-scanner 1.4 decodes in a Worker built from a blob: URL when the browser has no native
    # BarcodeDetector (iPhone Safari), so worker-src must allow blob: (2b scan).
    assert "worker-src 'self' blob:" in web_app.APP_CSP
    # Only the worker source widens: scripts stay same-origin.
    assert "script-src 'self' 'wasm-unsafe-eval';" in web_app.APP_CSP
