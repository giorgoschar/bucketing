"""End-to-end passkey check: local Pocket ID + the app + a virtual WebAuthn authenticator.

    (cd web && npm run build) && .venv/bin/python scripts/e2e_passkey.py

Needs Docker, ports 1411 and 8000 free, and Playwright's chromium
(`.venv/bin/playwright install chromium`). Steps: fresh Pocket ID (compose project
`tameio-e2e`, profile `pocketid`) -> admin + passkey -> OIDC client "Tameio" -> the app on a
throwaway SQLite DB with one password+TOTP user -> legacy sign-in -> Settings -> Link
passkey -> sign out -> passkey sign-in at /app/ (/api/v1/auth/me = 200) -> sign out ->
IndexedDB `tameio` empty. Pocket ID's container and volume are removed at the end.
Screenshots and logs go to $E2E_OUT (default: a new temp directory, printed at the start).

The app runs on 127.0.0.1, not localhost: cookies ignore the port, and Pocket ID's own
`session` cookie on localhost would overwrite the app's.
"""

import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pyotp
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("E2E_OUT") or tempfile.mkdtemp(prefix="tameio-e2e-out-"))
OUT.mkdir(parents=True, exist_ok=True)
PROJECT = "tameio-e2e"
POCKET = "http://localhost:1411"
APP = os.environ.get("E2E_APP_ORIGIN", "http://127.0.0.1:8000")
_app = urlsplit(APP)
APP_HOST = _app.hostname or "127.0.0.1"
APP_PORT = str(_app.port or (443 if _app.scheme == "https" else 80))
PASSWORD = "correct horse battery staple 42"
COMPOSE_ENV = {**os.environ, "APP_SECRET_KEY": "x", "APP_BASE_URL": APP}


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


def wait_http(url: str, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"timed out waiting for {url}")


def compose(*args: str) -> None:
    done = subprocess.run(
        ["docker", "compose", "-p", PROJECT, "--profile", "pocketid", *args],
        cwd=ROOT,
        env=COMPOSE_ENV,
        capture_output=True,
        text=True,
    )
    if done.returncode:
        sys.stderr.write(done.stderr)
        raise RuntimeError(f"docker compose {' '.join(args)} failed ({done.returncode})")


def shot(page: Page, name: str) -> None:
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)


def seed(env: dict) -> str:
    """Create one household owner with password + TOTP; returns the TOTP secret."""
    code = """
import pyotp, sys
from app.core.database import SessionLocal
from app.main import app  # noqa: F401  (DEBUG=true creates the tables)
from app.auth import hash_password
from app.models import Household, HouseholdMember, MemberRole, User
from app.seed import seed_categories
db = SessionLocal()
secret = pyotp.random_base32()
hh = Household(name="E2E home")
db.add(hh); db.flush()
u = User(username="ada", email="ada@example.test", display_name="Ada Admin",
         password_hash=hash_password(sys.argv[1]), totp_enabled=True)
u.set_totp_secret(secret)
db.add(u); db.flush()
db.add(HouseholdMember(household_id=hh.id, user_id=u.id, role=MemberRole.owner))
seed_categories(db, hh.id)
db.commit()
print(secret)
"""
    out = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", code, PASSWORD],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.strip().splitlines()[-1]


def fresh_totp(totp: pyotp.TOTP, used: set[str]) -> str:
    """The app refuses a replayed TOTP step, so wait for a code not used yet."""
    while (code := totp.now()) in used:
        time.sleep(1)
    used.add(code)
    return code


def through_pocket_id(page: Page, label: str) -> None:
    """Click through Pocket ID's authorize page (passkey ceremony / consent) until back on the app."""
    for _ in range(20):
        page.wait_for_load_state("networkidle")
        if page.url.startswith(APP):
            return
        shot(page, f"{label}-pocketid")
        btn = page.get_by_role(
            "button", name=re.compile(r"^(Sign in|Authenticate|Authorize|Continue|Allow)", re.I)
        )
        if btn.count():
            btn.first.click()
        page.wait_for_timeout(1000)
    raise RuntimeError(f"{label}: stuck at {page.url}")


def sign_count(cdp, auth) -> int:
    creds = cdp.send("WebAuthn.getCredentials", {"authenticatorId": auth["authenticatorId"]})
    return sum(c["signCount"] for c in creds["credentials"])


IDB_COUNTS = """() => new Promise((resolve, reject) => {
  const req = indexedDB.open('tameio')
  req.onerror = () => reject(req.error)
  req.onsuccess = () => {
    const idb = req.result
    const names = [...idb.objectStoreNames]
    if (!names.length) { idb.close(); return resolve({}) }
    const tx = idb.transaction(names, 'readonly')
    const out = {}
    names.forEach((n) => { const c = tx.objectStore(n).count(); c.onsuccess = () => { out[n] = c.result } })
    tx.oncomplete = () => { idb.close(); resolve(out) }
  }
})"""


def idb_counts(page: Page) -> dict:
    return page.evaluate(IDB_COUNTS)


def run(workdir: Path) -> None:
    # --- 1. Pocket ID, fresh volume -------------------------------------------------------
    log(f"screenshots and logs: {OUT}")
    log("starting Pocket ID (fresh volume)")
    compose("down", "-v")
    compose("up", "-d", "pocketid")
    wait_http(f"{POCKET}/.well-known/openid-configuration")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        console = (OUT / "console.log").open("w")
        page.on("console", lambda m: console.write(f"{m.type}: {m.text}\n"))
        cdp = ctx.new_cdp_session(page)
        cdp.send("WebAuthn.enable")
        auth = cdp.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }
            },
        )

        # --- 2. Pocket ID admin with a passkey ---------------------------------------------
        log("creating the Pocket ID admin and registering its passkey")
        page.goto(f"{POCKET}/setup")
        page.get_by_label("Username").fill("ada")
        page.get_by_label("Email").fill("ada@example.test")
        page.get_by_label("First name").fill("Ada")
        page.get_by_label("Last name").fill("Admin")
        page.get_by_role("button", name="Sign Up").click()
        page.wait_for_url(re.compile(r".*/signup/add-passkey"))
        page.get_by_role("button", name="Add Passkey").last.click()
        page.wait_for_url(lambda u: "add-passkey" not in u, timeout=15000)
        creds = cdp.send("WebAuthn.getCredentials", {"authenticatorId": auth["authenticatorId"]})
        assert len(creds["credentials"]) == 1, creds
        log(f"passkey registered; Pocket ID now at {page.url}")
        shot(page, "01-pocketid-admin")

        # --- 3. OIDC client via the admin API (same browser session) -----------------------
        log("creating the OIDC client 'Tameio'")
        r = page.request.post(
            f"{POCKET}/api/oidc/clients",
            data={
                "name": "Tameio",
                "callbackURLs": [f"{APP}/app/auth/callback"],
                "logoutCallbackURLs": [],
                "isPublic": False,
                "pkceEnabled": True,
            },
        )
        assert r.ok, (r.status, r.text())
        client_id = r.json()["id"]
        r = page.request.post(
            f"{POCKET}/api/oidc/clients/{client_id}/secrets", data={"expiresAt": None}
        )
        assert r.ok, (r.status, r.text())
        client_secret = r.json()["secret"]

        # --- 4. The app, throwaway SQLite, one password+TOTP user --------------------------
        db_path = workdir / "e2e.db"
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite:///{db_path}",
            "NEW_APP_ENABLED": "true",
            "DEBUG": "true",
            "APP_SECRET_KEY": "dev-only-0123456789",
            "OIDC_ISSUER": POCKET,
            "OIDC_CLIENT_ID": client_id,
            "OIDC_CLIENT_SECRET": client_secret,
            "ENABLE_SCHEDULER": "false",
            "POSOKANEI_ENABLED": "false",
        }
        env.pop("APP_BASE_URL", None)
        secret = seed(env)
        totp = pyotp.TOTP(secret)
        used: set[str] = set()
        log(f"starting the app on {APP}")
        server = subprocess.Popen(
            [
                str(ROOT / ".venv/bin/uvicorn"),
                "app.main:app",
                "--host",
                APP_HOST,
                "--port",
                APP_PORT,
            ],
            cwd=ROOT,
            env=env,
            stdout=(OUT / "uvicorn.log").open("w"),
            stderr=subprocess.STDOUT,
        )
        try:
            wait_http(f"{APP}/health")

            # --- 5. Legacy sign-in with password + TOTP ------------------------------------
            log("legacy sign-in: password + TOTP")
            page.goto(f"{APP}/login")
            page.locator("input[name=username]").fill("ada")
            page.locator("input[name=password]").fill(PASSWORD)
            page.locator("form button[type=submit]").first.click()
            page.wait_for_url(re.compile(r".*/login/verify"))
            page.locator("input[name=code]").fill(fresh_totp(totp, used))
            page.locator("form button[type=submit]").first.click()
            page.wait_for_url(re.compile(r".*/dashboard"))

            # --- 6. Settings -> Link passkey (re-enter password + a fresh TOTP) ------------
            log("Settings -> Link passkey (waits for a fresh TOTP step)")
            page.goto(f"{APP}/settings")
            form = page.locator("form[action='/app/auth/link']")
            form.locator("input[name=password]").fill(PASSWORD)
            form.locator("input[name=totp_code]").fill(fresh_totp(totp, used))
            shot(page, "02-settings-link")
            before = sign_count(cdp, auth)
            form.locator("button[type=submit]").click()
            page.wait_for_url(lambda u: u.startswith(POCKET) or "/app/" in u)
            through_pocket_id(page, "03-link")
            page.wait_for_load_state("networkidle")
            page.get_by_text("Passkey linked.").wait_for()
            shot(page, "04-linked")
            log(f"passkey assertions during link: {sign_count(cdp, auth) - before}")
            log(f"linked: landed on {page.url}")

            # --- 7. Sign out of the app, drop the Pocket ID session, sign in with the passkey
            log("signing out, then passkey sign-in at /app/")
            page.goto(f"{APP}/app/")
            page.get_by_role("button", name="Account").click()
            page.get_by_role("button", name="Sign out").click()
            page.get_by_role("link", name="Sign in with Face ID").wait_for()
            # Drop every cookie (Pocket ID's included: cookies ignore the port) so Pocket ID
            # runs a real passkey ceremony instead of a silent SSO hop.
            ctx.clear_cookies()
            page.goto(f"{APP}/app/")
            before = sign_count(cdp, auth)
            page.get_by_role("link", name="Sign in with Face ID").click()
            page.wait_for_url(lambda u: u.startswith(POCKET))
            through_pocket_id(page, "05-signin")
            page.wait_for_load_state("networkidle")
            me = page.request.get(f"{APP}/api/v1/auth/me")
            log(f"GET /api/v1/auth/me -> {me.status}")
            assert me.status == 200, me.text()
            log(f"passkey assertions during sign-in: {sign_count(cdp, auth) - before}")
            assert sign_count(cdp, auth) > before, "sign-in did not use the passkey"
            body = me.json()
            log(f"/me: { ({k: body.get(k) for k in ('username', 'display_name')}) }")
            page.get_by_role("button", name="Account").wait_for()
            page.wait_for_timeout(500)
            filled = idb_counts(page)
            log(f"IndexedDB tameio store counts while signed in: {filled}")
            assert filled.get("keys") and filled.get("cache"), filled
            shot(page, "06-shell-signed-in")

            # --- 8. Sign out -> IndexedDB 'tameio' is empty ----------------------------------
            log("sign out; checking IndexedDB 'tameio'")
            page.get_by_role("button", name="Account").click()
            page.get_by_role("button", name="Sign out").click()
            page.get_by_role("link", name="Sign in with Face ID").wait_for()
            page.wait_for_timeout(500)
            counts = idb_counts(page)
            log(f"IndexedDB tameio store counts after sign-out: {counts}")
            assert counts and all(v == 0 for v in counts.values()), counts
            me = page.request.get(f"{APP}/api/v1/auth/me")
            log(f"GET /api/v1/auth/me after sign-out -> {me.status}")
            assert me.status == 401
            shot(page, "07-signed-out")
            log("PASS")
        finally:
            server.terminate()
            server.wait(10)
            browser.close()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tameio-e2e-") as tmp:
        try:
            run(Path(tmp))
        finally:
            log("tearing down Pocket ID (container + volume)")
            compose("down", "-v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
