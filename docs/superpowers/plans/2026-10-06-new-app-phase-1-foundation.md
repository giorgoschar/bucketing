# New App Phase 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a signed-in, installable, offline-capable shell of the new React app at `/app`. It signs in with a Pocket ID passkey (Face ID), talks to the existing `/api/v1` through an httpOnly session cookie, and keeps cached data and queued writes encrypted in IndexedDB.

**Architecture:**
- FastAPI is the only origin and acts as the Backend-for-Frontend (BFF).
  - Pocket ID (a self-hosted OIDC provider) proves who you are.
  - FastAPI turns that into the app's **existing** signed session cookie, which is httpOnly, carries `session_version`, checks membership and uses CSRF double-submit.
  - JavaScript never sees a token.
- The SPA is built by Vite into `web/dist` and served by FastAPI at `/app/` under a strict CSP.
- The app shell has 5 tabs (Home · Activity · ＋ · Plan · Insights). Screens are placeholders until Phase 2.
- Offline storage:
  - Dexie (IndexedDB) stores records encrypted with AES-GCM under a non-extractable WebCrypto key that lives in IndexedDB.
  - Writes go to an encrypted queue that replays on app open, `online` and `visibilitychange`.
  - The existing `client_id` on transactions makes replays idempotent.

**Tech Stack:**
- Backend: Python 3.12, FastAPI 0.115, Authlib 1.8 (OIDC client), itsdangerous (existing), SQLAlchemy 2 + Alembic, pytest.
- Frontend: React 19, TypeScript 6, Vite 8, React Router 7, TanStack Query 5, Dexie 4.4, vite-plugin-pwa 2, openapi-typescript + openapi-fetch, Vitest + fake-indexeddb.

**Spec:** the decisions in this document's "Decisions" section, plus:
- the Vault design in `docs/redesign/mocks/` (tokens in `docs/redesign/mocks/tokens.css`);
- gaps to cover in later phases, in `docs/redesign/backlog.md`.

## Decisions (the spec for this phase)

1. **Identity provider.**
   - Pocket ID v2, self-hosted on Coolify, used for **this app only**. Coolify keeps its own login, so a broken Pocket ID can't lock you out of the tool that fixes it.
   - Passkey-only. Recovery is a login code issued by the Pocket ID admin.
2. **No custom crypto or auth protocol code.**
   - OIDC (authorization code + PKCE + state + nonce, ID-token verification against JWKS) is Authlib's job.
   - Session signing stays itsdangerous, as today.
3. **Account linking.**
   - New column `users.oidc_subject`, unique and nullable.
   - Sign-in matches on `sub` first.
   - The first sign-in links to a local user only when the ID token has `email_verified: true` **and** the email exactly matches one local user, case-insensitively.
   - Users are never created automatically. With no match, sign-in is refused and a message tells you to ask the household owner.
4. **Second factor.**
   - A passkey sign-in counts as multi-factor. Sessions created by OIDC carry `"amr": "oidc"` and skip the TOTP-enrolment requirement.
   - Password sessions still require TOTP, exactly as today. Nothing is relaxed globally.
5. **Same session for both UIs.** The old Jinja UI and the new app share the `session` cookie. Signing in to either signs in both. Logging out of either logs out both.
6. **API auth.**
   - `/api/v1` accepts **either** a Bearer access token (unchanged: mobile and Shortcut flows) **or** the session cookie.
   - On the cookie path, `POST/PUT/PATCH/DELETE` require `X-CSRF-Token` to match the `csrf_token` cookie.
   - The cookie path answers JSON 401, never a 302.
   - `pat_` tokens stay ingest-only.
7. **Routes live under the PWA scope.**
   - Sign-in start, callback and logout are `/app/auth/login`, `/app/auth/callback` and `/app/auth/logout`.
   - This way, in the installed iPhone app, only the hop to Pocket ID leaves the app's scope.
8. **Feature flag.** `NEW_APP_ENABLED` (default `false`). When it's false, `/app/*` returns 404 and nothing about the live app changes.
9. **Strict CSP on `/app/*` only:**
   ```
   default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self';
   img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self';
   manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self';
   frame-ancestors 'none'
   ```
   The old UI keeps its current policy until cutover.
10. **Offline encryption at rest.**
    - One AES-GCM-256 key per device, generated with `extractable: false` and stored as a `CryptoKey` object in IndexedDB.
    - Every cached record and queued write is encrypted with a fresh 12-byte IV.
    - Logout and a 401 on session bootstrap wipe the whole database, key included.
    - This protects data copied out of storage. It does not protect an unlocked phone; the user accepted that.
11. **Offline sync.**
    - iOS has no Background Sync, so the app replays the queue itself on app open, `online` and `visibilitychange` → visible.
    - Responses:
      - 2xx: done.
      - 409 (replay of a deleted transaction): drop it and tell the user.
      - 401: stop and keep the queue until sign-in.
      - Other 4xx: mark it failed and surface it.
      - 5xx or network error: exponential backoff, capped at 5 minutes.
12. **API types** are generated from FastAPI's OpenAPI schema. Hand-written request/response types for `/api/v1` are not allowed.

## Global Constraints

- Python changes must pass `ruff check` and `ruff format --check` on `app tests alembic scripts`, plus the **whole** pytest suite on SQLite and on Postgres 18 (`TEST_DATABASE_URL`).
- Production must not change while `NEW_APP_ENABLED` is unset. Every existing test passes unchanged.
- Never log or return token values, ID tokens or session cookie values.
- Cookies:
  - `session`: httpOnly, SameSite=Lax, Secure unless DEBUG (unchanged).
  - OIDC transaction cookie `oidc_tx`: httpOnly, SameSite=**Lax** (the callback is a cross-site top-level GET, so Strict would drop it), Secure unless DEBUG, max-age 600, path `/app/auth`.
- The frontend has no `localStorage` or `sessionStorage` for anything sensitive. Only the Dexie database holds data, and only encrypted.
- No inline `<script>` or `<style>` in `web/index.html`, and no `style=""` attributes in markup. React's `style` prop is fine: it uses the CSSOM and is allowed under `style-src 'self'`.
- Colours and type come from `web/src/styles/tokens.css` (Vault). Dark is the default, and light follows `prefers-color-scheme`.
- Tap targets are at least 44×44 pt. Fixed bars pad with `env(safe-area-inset-*)`.
- Env names: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `NEW_APP_ENABLED`.
- The redirect URI registered in Pocket ID is `${APP_BASE_URL}/app/auth/callback`.

## Review Focus

1. **Password user with TOTP not enrolled hits `/api/v1` with a cookie.** Must get 403 "TOTP enrollment required", the same as Bearer. Only `amr: oidc` sessions skip it. Pinned in Task 3.
2. **Callback opened twice, or with a stale or forged `state`.** Second use or a mismatch → redirect to `/app/?auth_error=state`. No session is set, and nothing raises a 500. Pinned in Task 4.
3. **Pocket ID user whose email matches nobody, or matches but `email_verified` is false.** Refused with `auth_error=no_account`. No user is created or linked. Pinned in Task 2.
4. **Cookie-authenticated POST from another site** (no `X-CSRF-Token`, or one that doesn't match). 403 JSON, and the session survives because this isn't a navigation. Pinned in Task 3.
5. **Queue replay while signed out, or after the session was revoked.** Replay stops at the first 401, keeps every item, and the app shows the sign-in screen. Nothing is dropped. Pinned in Task 10.

---

## File Structure

Backend (new):
- `app/core/oidc.py`: Authlib OAuth registry; `oidc_client()`.
- `app/services/identity.py`: `resolve_oidc_user(db, claims) -> User` and `IdentityError`.
- `app/web_app.py`: router for `/app/auth/*`, the SPA static mount and fallback, and the `/app` CSP.
- `alembic/versions/f0a1b2c3d4e5_user_oidc_subject.py`
- `scripts/export_openapi.py`
- `tests/test_oidc_identity.py`, `tests/test_oidc_routes.py`, `tests/test_api_cookie_auth.py`, `tests/test_web_app.py`

Backend (modify):
- `app/core/config.py`: OIDC settings and `new_app_enabled`.
- `app/models.py`: `User.oidc_subject`.
- `app/auth.py`:
  - `set_session(..., amr="pwd")`;
  - `require_auth` honours `amr`;
  - extract `csrf_matches(request)`.
- `app/api_auth.py`: `require_api_auth` accepts the cookie.
- `app/main.py`: include the `web_app` router before other mounts; per-path CSP.
- `requirements.txt`: `Authlib==1.8.0`.
- `Dockerfile`, `.dockerignore`: node build stage for `web/`.
- `.env.example`, `docs/DEPLOY-COOLIFY.md`: Pocket ID setup.

Frontend (new, under `web/src/`):
- `api/schema.d.ts` (generated), `api/client.ts`: openapi-fetch with credentials, CSRF header and a 401 event.
- `session/SessionProvider.tsx`, `session/SignIn.tsx`
- `offline/crypto.ts`, `offline/db.ts`, `offline/queue.ts`, `offline/persister.ts`
- `shell/AppShell.tsx`, `shell/TabBar.tsx`, `shell/TopBar.tsx`, `shell/shell.css`
- `screens/{Home,Activity,Plan,Insights,Compose}.tsx` (placeholders)
- `router.tsx`
- `test/setup.ts`; tests next to sources as `*.test.ts(x)`

Frontend (modify): `main.tsx`, `App.tsx` (removed; replaced by `router.tsx`), `vite.config.ts`, `package.json`, `index.html`.

---

### Task 1: Settings, OIDC client and the `oidc_subject` column

**Files:**
- Modify: `requirements.txt`, `app/core/config.py`, `app/models.py` (class `User`), `.env.example`
- Create: `app/core/oidc.py`, `alembic/versions/f0a1b2c3d4e5_user_oidc_subject.py`
- Test: `tests/test_migrations.py` (existing; the single-head and upgrade checks cover the new revision)

**Interfaces:**
- Produces:
  - `settings.oidc_issuer: str | None`, `settings.oidc_client_id: str | None`, `settings.oidc_client_secret: str | None`, `settings.new_app_enabled: bool`, `settings.oidc_enabled -> bool` (property: all three OIDC values set).
  - `app.core.oidc.oidc_client() -> authlib StarletteOAuth2App`, registered as `"pocketid"`.
  - `User.oidc_subject: str | None` (unique).

- [ ] **Step 1: Add the dependency**

`requirements.txt`, after `PyJWT[crypto]==2.10.1`:
```
Authlib==1.8.0
```
Run: `.venv/bin/pip install Authlib==1.8.0`

- [ ] **Step 2: Settings**

In `app/core/config.py`, inside `class Settings`, next to `app_base_url`:
```python
    # New app (/app). Off until cutover; when off, /app/* is a 404.
    new_app_enabled: bool = False
    # Pocket ID (OIDC). All three are needed for passkey sign-in.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)
```
Also, in the production validation block (where `APP_BASE_URL` is required), add:
```python
            if self.new_app_enabled and not self.oidc_enabled:
                raise RuntimeError(
                    "NEW_APP_ENABLED needs OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET."
                )
```

- [ ] **Step 3: OIDC client module**

Create `app/core/oidc.py`:
```python
"""Pocket ID (OIDC) client. Authlib does the protocol: discovery, PKCE, state,
nonce and ID-token verification against the provider's JWKS."""

from functools import lru_cache

from authlib.integrations.starlette_client import OAuth

from app.core.config import settings


@lru_cache(maxsize=1)
def _registry() -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="pocketid",
        server_metadata_url=f"{settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    return oauth


def oidc_client():
    return _registry().pocketid
```

- [ ] **Step 4: Model column**

In `app/models.py`, class `User`, after `email_verified`:
```python
    # Pocket ID subject ("sub"); set the first time this user signs in with a passkey.
    oidc_subject = Column(String(255), unique=True, nullable=True)
```

- [ ] **Step 5: Migration**

Run `.venv/bin/alembic heads` and expect `e9f0a1b2c3d4 (head)`. Create `alembic/versions/f0a1b2c3d4e5_user_oidc_subject.py`:
```python
"""users.oidc_subject for Pocket ID sign-in

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
"""

import sqlalchemy as sa

from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("oidc_subject", sa.String(255), nullable=True))
        batch.create_unique_constraint("uq_users_oidc_subject", ["oidc_subject"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_oidc_subject", type_="unique")
        batch.drop_column("oidc_subject")
```

- [ ] **Step 6: Env example**

Append to `.env.example`:
```
# New app at /app (off until cutover) and Pocket ID passkey sign-in.
NEW_APP_ENABLED=false
OIDC_ISSUER=
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
```

- [ ] **Step 7: Run migration tests**

Run: `.venv/bin/python -m pytest tests/test_migrations.py -q`
Expected: PASS (single head, upgrade/downgrade round trip).

- [ ] **Step 8: Commit**
```bash
git add requirements.txt app/core/config.py app/core/oidc.py app/models.py alembic/versions/f0a1b2c3d4e5_user_oidc_subject.py .env.example
git commit -m "feat(auth): Pocket ID settings, Authlib client and users.oidc_subject"
```

---

### Task 2: Account linking (`resolve_oidc_user`)

**Files:**
- Create: `app/services/identity.py`
- Test: `tests/test_oidc_identity.py`

**Interfaces:**
- Consumes: `User.oidc_subject` (Task 1).
- Produces: `resolve_oidc_user(db: Session, claims: dict) -> User`, which raises `IdentityError(code: str)` with `code` in `{"no_account", "ambiguous", "subject_conflict"}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_oidc_identity.py`:
```python
import pytest

from app.models import User
from app.services.identity import IdentityError, resolve_oidc_user


def _user(db, username, email, sub=None):
    u = User(username=username, email=email, display_name=username, password_hash="x",
             oidc_subject=sub)
    db.add(u)
    db.commit()
    return u


def test_known_subject_wins(db):
    u = _user(db, "g", "g@x.t", sub="sub-1")
    assert resolve_oidc_user(db, {"sub": "sub-1", "email": "other@x.t"}).id == u.id


def test_first_sign_in_links_by_verified_email(db):
    u = _user(db, "g", "G@X.t")
    got = resolve_oidc_user(db, {"sub": "sub-2", "email": "g@x.T", "email_verified": True})
    assert got.id == u.id
    db.refresh(u)
    assert u.oidc_subject == "sub-2"


def test_unverified_email_is_refused(db):
    _user(db, "g", "g@x.t")
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "s", "email": "g@x.t", "email_verified": False})
    assert e.value.code == "no_account"


def test_unknown_email_is_refused_and_creates_nothing(db):
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "s", "email": "nobody@x.t", "email_verified": True})
    assert e.value.code == "no_account"
    assert db.query(User).count() == 0


def test_email_already_linked_to_another_subject_is_refused(db):
    _user(db, "g", "g@x.t", sub="sub-old")
    with pytest.raises(IdentityError) as e:
        resolve_oidc_user(db, {"sub": "sub-new", "email": "g@x.t", "email_verified": True})
    assert e.value.code == "subject_conflict"


def test_missing_sub_is_refused(db):
    with pytest.raises(IdentityError):
        resolve_oidc_user(db, {"email": "g@x.t", "email_verified": True})
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_oidc_identity.py -q`
Expected: FAIL, `ModuleNotFoundError: app.services.identity`.

- [ ] **Step 3: Implement**

`app/services/identity.py`:
```python
"""Map a verified Pocket ID identity to a local user. Never creates users."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import User


class IdentityError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def resolve_oidc_user(db: Session, claims: dict) -> User:
    sub = claims.get("sub")
    if not sub:
        raise IdentityError("no_account")

    user = db.query(User).filter(User.oidc_subject == sub).one_or_none()
    if user:
        return user

    email = (claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") is not True:
        raise IdentityError("no_account")

    matches = db.query(User).filter(func.lower(User.email) == email).all()
    if not matches:
        raise IdentityError("no_account")
    if len(matches) > 1:
        raise IdentityError("ambiguous")
    user = matches[0]
    if user.oidc_subject and user.oidc_subject != sub:
        raise IdentityError("subject_conflict")

    user.oidc_subject = sub
    db.commit()
    return user
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_oidc_identity.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**
```bash
git add app/services/identity.py tests/test_oidc_identity.py
git commit -m "feat(auth): link Pocket ID identities to local users by sub, then verified email"
```

---

### Task 3: Session `amr` marker and cookie auth on `/api/v1`

**Files:**
- Modify: `app/auth.py` (`set_session`, `require_auth`, `require_household_member`, new `csrf_matches`), `app/api_auth.py` (`require_api_auth`)
- Test: `tests/test_api_cookie_auth.py`

**Interfaces:**
- Consumes: the existing `set_session`, `decode_cookie`, `COOKIE_NAME`, `CSRF_COOKIE_NAME` and `verify_csrf_token`.
- Produces:
  - `set_session(response, user_id, household_id, session_version, amr: str = "pwd")`. The payload gains `"amr"`.
  - `csrf_matches(request: Request, user_id: str) -> bool`, which checks the header against the cookie (header only, no form parsing).
  - `require_api_auth` returns `(user, household_id)` for a valid Bearer token **or** a valid session cookie.

- [ ] **Step 1: Write the failing tests**

`tests/test_api_cookie_auth.py`. It uses the existing `client` and `db` fixtures from `tests/conftest.py`; read `conftest.py` first for helpers that create a user and household and adapt the names if they differ.
```python
import pytest
from starlette.responses import Response

from app.auth import COOKIE_NAME, CSRF_COOKIE_NAME, set_session
from app.models import Household, HouseholdMember, User


def _member(db, totp=True):
    u = User(username="g", email="g@x.t", display_name="G", password_hash="x",
             totp_enabled=totp)
    h = Household(name="Home")
    db.add_all([u, h]); db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=u.id, role="owner")); db.commit()
    return u, h


def _login(client, u, h, amr):
    r = Response()
    set_session(r, u.id, h.id, u.session_version, amr=amr)
    for raw in r.headers.getlist("set-cookie"):
        name, _, rest = raw.partition("=")
        client.cookies.set(name, rest.split(";")[0])
    return client.cookies.get(CSRF_COOKIE_NAME)


def test_cookie_get_works(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200 and r.json()["household_id"] == h.id


def test_no_credentials_is_json_401_not_redirect(client):
    r = client.get("/api/v1/auth/me", follow_redirects=False)
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/json")


def test_cookie_post_without_csrf_is_403_and_session_survives(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    r = client.post("/api/v1/notifications/read-all")
    assert r.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_cookie_post_with_csrf_header_passes_csrf(client, db):
    u, h = _member(db)
    csrf = _login(client, u, h, "pwd")
    r = client.post("/api/v1/notifications/read-all", headers={"X-CSRF-Token": csrf})
    assert r.status_code != 403


def test_password_session_without_totp_is_403(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "pwd")
    assert client.get("/api/v1/auth/me").status_code == 403


def test_oidc_session_without_totp_is_allowed(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "oidc")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_stale_session_version_is_401(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    u.session_version += 1; db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_removed_member_cookie_is_401(client, db):
    u, h = _member(db)
    _login(client, u, h, "pwd")
    db.query(HouseholdMember).delete(); db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_web_ui_oidc_session_without_totp_is_not_sent_to_enroll(client, db):
    u, h = _member(db, totp=False)
    _login(client, u, h, "oidc")
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 200
```
Before running, check that `POST /api/v1/notifications/read-all` exists: `grep -n "@router.post" app/api/notifications.py`. If it doesn't, use any cookie-safe POST from that file and keep the same assertions.

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_api_cookie_auth.py -q`
Expected: FAIL. `set_session()` got an unexpected keyword `amr`, and cookie requests get 401.

- [ ] **Step 3: `set_session` gains `amr`**

In `app/auth.py`:
```python
def set_session(response, user_id: str, household_id: str, session_version: int, amr: str = "pwd"):
    """Set a full authenticated session cookie. amr: "pwd" (password+TOTP) or "oidc" (passkey)."""
    value = _serializer.dumps(
        {
            "user_id": user_id,
            "hh_id": household_id,
            "sv": session_version,
            "state": "authenticated",
            "amr": amr,
        }
    )
```
Leave the rest of the function as is. Existing callers keep the default `"pwd"`. Check with `git grep -n "set_session("`: household switch must **preserve** the current `amr`. In `app/routes/auth.py`, wherever `set_session` re-issues the cookie for a household switch, pass `amr=session.get("amr", "pwd")`.

- [ ] **Step 4: TOTP check honours `amr` in the web dependencies**

In `require_auth` and `require_household_member`, change:
```python
    if not user.totp_enabled:
```
to:
```python
    if not user.totp_enabled and session.get("amr") != "oidc":
```

- [ ] **Step 5: Extract a header-only CSRF check**

In `app/auth.py`, below `verify_csrf_token`:
```python
def csrf_matches(request: Request, user_id: str) -> bool:
    """Double-submit check for JSON API calls: header must equal the cookie and be valid."""
    header = request.headers.get("X-CSRF-Token", "")
    cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    return bool(header) and hmac.compare_digest(header, cookie) and verify_csrf_token(header, user_id)
```
Add `import hmac` at the top if it isn't already there.

- [ ] **Step 6: `require_api_auth` accepts the cookie**

In `app/api_auth.py`, add the `request: Request` parameter and a cookie branch **before** the `if not credentials:` check:
```python
def require_api_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    if not credentials:
        return _cookie_auth(request, db)
    ...  # existing Bearer path unchanged
```
and add:
```python
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _cookie_auth(request: Request, db: Session):
    """Session-cookie auth for the new app at /app (same origin, no tokens in JS)."""
    from app.auth import COOKIE_NAME, csrf_matches, decode_cookie

    unauth = HTTPException(status_code=401, detail="Not authenticated")
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    if not session or session.get("state") != "authenticated":
        raise unauth
    user = db.get(User, session.get("user_id"))
    if not user or session.get("sv", -1) != user.session_version:
        raise unauth
    hh_id = session.get("hh_id")
    if not _is_member(db, hh_id, user.id):
        raise unauth
    if request.method in _UNSAFE and not csrf_matches(request, user.id):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    if not user.totp_enabled and session.get("amr") != "oidc":
        raise HTTPException(status_code=403, detail="TOTP enrollment required")
    return user, hh_id
```
`Request` comes from `fastapi`. The 401 for a missing Bearer moves into `_cookie_auth`; the response body stays `{"detail": "Not authenticated"}`.

- [ ] **Step 7: Run the new and existing auth tests**

Run: `.venv/bin/python -m pytest tests/test_api_cookie_auth.py tests/test_api.py tests/test_auth.py tests/test_isolation.py tests/test_personal_tokens.py tests/test_final_fix_security.py -q`
Expected: all pass. If an existing test asserted the `WWW-Authenticate` header on a credential-less 401, keep that header in `unauth`.

- [ ] **Step 8: Commit**
```bash
git add app/auth.py app/api_auth.py app/routes/auth.py tests/test_api_cookie_auth.py
git commit -m "feat(api): /api/v1 accepts the session cookie with CSRF header; passkey sessions skip TOTP enrolment"
```

---

### Task 4: `/app/auth/*` routes (login, callback, logout)

**Files:**
- Create: `app/web_app.py`
- Modify: `app/main.py` (include the router and add `SessionMiddleware` for the OIDC transaction cookie)
- Test: `tests/test_oidc_routes.py`

**Interfaces:**
- Consumes:
  - `oidc_client()` (Task 1);
  - `resolve_oidc_user`, `IdentityError` (Task 2);
  - `set_session(..., amr="oidc")` (Task 3);
  - the existing `clear_session` (logout clears only this browser; do **not** call `invalidate_user_sessions`).
- Produces:
  - `GET /app/auth/login` → 302 to Pocket ID;
  - `GET /app/auth/callback` → 302 to `/app/` or `/app/?auth_error=<code>`;
  - `POST /app/auth/logout` → 204, cookies cleared;
  - `router` in `app/web_app.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_oidc_routes.py`:
```python
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.models import Household, HouseholdMember, User


@pytest.fixture(autouse=True)
def _oidc_on(monkeypatch):
    monkeypatch.setattr(settings, "new_app_enabled", True)
    monkeypatch.setattr(settings, "oidc_issuer", "https://id.example.test")
    monkeypatch.setattr(settings, "oidc_client_id", "cid")
    monkeypatch.setattr(settings, "oidc_client_secret", "secret")


def _member(db, email="g@x.t"):
    u = User(username="g", email=email, display_name="G", password_hash="x")
    h = Household(name="Home"); db.add_all([u, h]); db.flush()
    db.add(HouseholdMember(household_id=h.id, user_id=u.id, role="owner")); db.commit()
    return u, h


def _fake_client(userinfo=None, exc=None):
    c = AsyncMock()
    if exc:
        c.authorize_access_token.side_effect = exc
    else:
        c.authorize_access_token.return_value = {"userinfo": userinfo}
    return c


def test_callback_signs_in_and_redirects_home(client, db):
    u, h = _member(db)
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app/"
    assert client.get("/api/v1/auth/me").json()["id"] == u.id


def test_callback_unknown_user_gets_error_and_no_session(client, db):
    fake = _fake_client({"sub": "s1", "email": "nobody@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=no_account"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_callback_bad_state_is_handled(client, db):
    from authlib.integrations.base_client.errors import MismatchingStateError

    fake = _fake_client(exc=MismatchingStateError())
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=forged", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/app/?auth_error=state"


def test_callback_provider_error_param(client):
    r = client.get("/app/auth/callback?error=access_denied", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=denied"


def test_user_without_household_is_refused(client, db):
    u = User(username="g", email="g@x.t", display_name="G", password_hash="x")
    db.add(u); db.commit()
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    assert r.headers["location"] == "/app/?auth_error=no_household"


def test_login_redirects_to_provider(client):
    fake = AsyncMock()
    from starlette.responses import RedirectResponse
    fake.authorize_redirect.return_value = RedirectResponse("https://id.example.test/authorize?x=1")
    with patch("app.web_app.oidc_client", return_value=fake):
        r = client.get("/app/auth/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://id.example.test/")
    redirect_uri = fake.authorize_redirect.call_args.args[1]
    assert str(redirect_uri).endswith("/app/auth/callback")


def test_logout_clears_session(client, db):
    u, h = _member(db)
    fake = _fake_client({"sub": "s1", "email": "g@x.t", "email_verified": True})
    with patch("app.web_app.oidc_client", return_value=fake):
        client.get("/app/auth/callback?code=c&state=s", follow_redirects=False)
    csrf = client.cookies.get("csrf_token")
    r = client.post("/app/auth/logout", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_flag_off_hides_everything(client, monkeypatch):
    monkeypatch.setattr(settings, "new_app_enabled", False)
    assert client.get("/app/auth/login", follow_redirects=False).status_code == 404
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_oidc_routes.py -q`
Expected: FAIL with 404s, because the routes don't exist yet.

- [ ] **Step 3: Implement the router**

`app/web_app.py`:
```python
"""The new app at /app: passkey sign-in via Pocket ID, and (Task 5) the SPA itself."""

import logging

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import clear_session, csrf_matches, decode_cookie, COOKIE_NAME, set_session
from app.core.config import settings
from app.core.database import get_db
from app.core.oidc import oidc_client
from app.core.ratelimit import limiter
from app.models import HouseholdMember
from app.services.identity import IdentityError, resolve_oidc_user

logger = logging.getLogger(__name__)
security_logger = logging.getLogger("security")

router = APIRouter(prefix="/app/auth", include_in_schema=False)


def _enabled() -> None:
    if not (settings.new_app_enabled and settings.oidc_enabled):
        raise HTTPException(status_code=404)


def _fail(code: str) -> RedirectResponse:
    return RedirectResponse(f"/app/?auth_error={code}", status_code=302)


def _callback_url(request: Request) -> str:
    base = (settings.app_base_url or str(request.base_url)).rstrip("/")
    return f"{base}/app/auth/callback"


@router.get("/login", dependencies=[Depends(_enabled)])
@limiter.limit("20/minute")
async def login(request: Request):
    return await oidc_client().authorize_redirect(request, _callback_url(request))


@router.get("/callback", dependencies=[Depends(_enabled)])
@limiter.limit("20/minute")
async def callback(request: Request, db: Session = Depends(get_db)):
    if request.query_params.get("error"):
        return _fail("denied")
    try:
        token = await oidc_client().authorize_access_token(request)
    except OAuthError as exc:
        security_logger.warning("OIDC callback rejected: %s", type(exc).__name__)
        return _fail("state")
    claims = token.get("userinfo") or {}
    try:
        user = resolve_oidc_user(db, claims)
    except IdentityError as exc:
        security_logger.warning("OIDC sign-in refused: %s", exc.code)
        return _fail(exc.code)
    member = (
        db.query(HouseholdMember)
        .filter_by(user_id=user.id)
        .order_by(HouseholdMember.joined_at.asc())
        .first()
    )
    if not member:
        return _fail("no_household")
    response = RedirectResponse("/app/", status_code=302)
    set_session(response, user.id, member.household_id, user.session_version, amr="oidc")
    return response


@router.post("/logout", dependencies=[Depends(_enabled)], status_code=204)
async def logout(request: Request):
    raw = request.cookies.get(COOKIE_NAME)
    session = decode_cookie(raw) if raw else None
    if session and not csrf_matches(request, session.get("user_id", "")):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    response = Response(status_code=204)
    clear_session(response)
    return response
```
Check that `HouseholdMember` has `joined_at`: `grep -n "class HouseholdMember" -A12 app/models.py`. If the column has another name (`created_at`), use that.

- [ ] **Step 4: Wire into `app/main.py`**

After `app.add_exception_handler(RateLimitExceeded, ...)`:
```python
from starlette.middleware.sessions import SessionMiddleware

# Authlib keeps the OIDC state, nonce and PKCE verifier here between /app/auth/login
# and the callback. Lax, because the callback is a cross-site top-level redirect.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_secret_key,
    session_cookie="oidc_tx",
    max_age=600,
    path="/app/auth",
    same_site="lax",
    https_only=not settings.debug,
)
```
In the Routers section, include it **first**:
```python
from app import web_app

app.include_router(web_app.router)
```
`SessionMiddleware` needs `itsdangerous`, which is already a dependency.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_oidc_routes.py tests/test_auth.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**
```bash
git add app/web_app.py app/main.py tests/test_oidc_routes.py
git commit -m "feat(auth): passkey sign-in at /app/auth via Pocket ID (Authlib), behind NEW_APP_ENABLED"
```

---

### Task 5: Serve the SPA at `/app` with a strict CSP; Docker builds it

**Files:**
- Modify: `app/web_app.py` (SPA routes), `app/main.py` (CSP chosen per path), `Dockerfile`, `.dockerignore`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Consumes: `settings.new_app_enabled`.
- Produces:
  - `GET /app/` and any `/app/<client-route>` → `web/dist/index.html` with `Cache-Control: no-cache`;
  - `GET /app/assets/*` → hashed file with `Cache-Control: public, max-age=31536000, immutable`;
  - `GET /app/sw.js` and `/app/manifest.webmanifest` → `no-cache`;
  - `APP_CSP` string constant in `app/web_app.py`.

- [ ] **Step 1: Write the failing tests**

`tests/test_web_app.py`:
```python
import pytest

from app.core.config import settings
from app import web_app


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
```

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/test_web_app.py -q`
Expected: FAIL, because `web_app.DIST_DIR` doesn't exist and `/app/` is a 404.

- [ ] **Step 3: SPA routes in `app/web_app.py`**

Append:
```python
from pathlib import Path

from fastapi.responses import FileResponse

DIST_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"

APP_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; "
    "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self'; "
    "manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)

spa = APIRouter(include_in_schema=False)


def _spa_enabled() -> None:
    if not settings.new_app_enabled:
        raise HTTPException(status_code=404)


def _file(rel: str) -> Path | None:
    root = DIST_DIR.resolve()
    target = (root / rel).resolve()
    if root not in target.parents and target != root:
        return None
    return target if target.is_file() else None


@spa.get("/app", dependencies=[Depends(_spa_enabled)])
def app_root():
    return RedirectResponse("/app/", status_code=308)


@spa.get("/app/{path:path}", dependencies=[Depends(_spa_enabled)])
def app_files(path: str):
    if path.startswith("auth/"):
        raise HTTPException(status_code=404)
    found = _file(path) if path else None
    if found:
        immutable = path.startswith("assets/")
        return FileResponse(
            found,
            headers={
                "Cache-Control": "public, max-age=31536000, immutable"
                if immutable
                else "no-cache"
            },
        )
    if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:
        raise HTTPException(status_code=404)
    index = _file("index.html")
    if not index:
        raise HTTPException(status_code=404)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
```
In `app/main.py`, include `web_app.spa` **after** `web_app.router` and before all others:
```python
app.include_router(web_app.router)
app.include_router(web_app.spa)
```

- [ ] **Step 4: Per-path CSP in `app/main.py`**

In the security-headers middleware, replace the single `Content-Security-Policy` assignment with:
```python
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        from app.web_app import APP_CSP

        response.headers["Content-Security-Policy"] = APP_CSP
    else:
        response.headers["Content-Security-Policy"] = (
            # existing policy string, unchanged
        )
```
Keep the existing string byte for byte in the `else` branch.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_web_app.py tests/test_final_fix_security.py tests/test_security_hardening_16.py -q`
Expected: all pass.

- [ ] **Step 6: Docker builds the SPA**

`.dockerignore`: replace the `web/` line with:
```
web/node_modules/
web/dist/
```
`Dockerfile`: add this stage at the very top:
```dockerfile
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build
```
After `COPY . .` in the Python stage, add:
```dockerfile
COPY --from=web /web/dist ./web/dist
```
Run: `docker build -t expenses-phase1 .` and expect success. Then run `docker run --rm expenses-phase1 ls web/dist` and expect `index.html` and `assets`.

- [ ] **Step 7: Commit**
```bash
git add app/web_app.py app/main.py Dockerfile .dockerignore tests/test_web_app.py
git commit -m "feat(web): serve the new app at /app with a strict CSP; Docker builds web/dist"
```

---

### Task 6: OpenAPI → TypeScript client

**Files:**
- Create: `scripts/export_openapi.py`, `web/src/api/client.ts`, `web/src/api/client.test.ts`, `web/src/test/setup.ts`
- Generated: `web/src/api/openapi.json`, `web/src/api/schema.d.ts`
- Modify: `web/package.json`, `web/vite.config.ts` (Vitest config), `.github/workflows/ci.yml`

**Interfaces:**
- Produces:
  - `api` (an openapi-fetch client typed by `paths`);
  - `readCsrf(): string`;
  - `onUnauthorized(cb: () => void): () => void`;
  - `npm run gen:api`, `npm test`.

- [ ] **Step 1: Export script**

`scripts/export_openapi.py`:
```python
"""Write the FastAPI OpenAPI schema for the web client's generated types.

Usage: python scripts/export_openapi.py web/src/api/openapi.json
"""

import json
import os
import sys

os.environ.setdefault("APP_SECRET_KEY", "openapi-export-only")
os.environ.setdefault("DEBUG", "true")

from app.main import app  # noqa: E402

out = sys.argv[1]
schema = app.openapi()
schema["paths"] = {k: v for k, v in schema["paths"].items() if k.startswith("/api/v1/")}
with open(out, "w") as f:
    json.dump(schema, f, indent=2, sort_keys=True)
    f.write("\n")
```

- [ ] **Step 2: Packages and scripts**

Run in `web/`:
```bash
npm i react-router@7 @tanstack/react-query@5 dexie@4.4 openapi-fetch
npm i -D openapi-typescript vitest@3 jsdom fake-indexeddb @testing-library/react @testing-library/jest-dom vite-plugin-pwa@2
```
Then add to the `package.json` scripts:
```json
"gen:api": "cd .. && .venv/bin/python scripts/export_openapi.py web/src/api/openapi.json && cd web && openapi-typescript src/api/openapi.json -o src/api/schema.d.ts",
"test": "vitest run",
"typecheck": "tsc -b"
```
Run `npm run gen:api` and expect `src/api/schema.d.ts` to contain `"/api/v1/auth/me"`.

- [ ] **Step 3: Vitest config**

In `web/vite.config.ts`, add to the config object:
```ts
  test: { environment: 'jsdom', setupFiles: ['src/test/setup.ts'] },
```
(Add `/// <reference types="vitest/config" />` at the top.) Then create `web/src/test/setup.ts`:
```ts
import 'fake-indexeddb/auto'
import '@testing-library/jest-dom/vitest'
```

- [ ] **Step 4: Write the failing client test**

`web/src/api/client.test.ts`:
```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, onUnauthorized } from './client'

afterEach(() => { vi.restoreAllMocks(); document.cookie = 'csrf_token=; max-age=0' })

describe('api client', () => {
  it('sends the CSRF cookie as a header on writes, same-origin credentials', async () => {
    document.cookie = 'csrf_token=abc.def'
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    await api.POST('/api/v1/notifications/read-all' as never, {} as never)
    const req = f.mock.calls[0][0] as Request
    expect(req.headers.get('X-CSRF-Token')).toBe('abc.def')
    expect(req.credentials).toBe('same-origin')
  })

  it('does not send the CSRF header on GET', async () => {
    document.cookie = 'csrf_token=abc.def'
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    await api.GET('/api/v1/auth/me')
    expect((f.mock.calls[0][0] as Request).headers.get('X-CSRF-Token')).toBeNull()
  })

  it('emits unauthorized on 401', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
    const cb = vi.fn()
    const off = onUnauthorized(cb)
    await api.GET('/api/v1/auth/me')
    off()
    expect(cb).toHaveBeenCalledOnce()
  })
})
```
Run `npm test` and expect FAIL (module not found).

- [ ] **Step 5: Implement `web/src/api/client.ts`**
```ts
import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const listeners = new Set<() => void>()

export function readCsrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

export function onUnauthorized(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

const session: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method)) request.headers.set('X-CSRF-Token', readCsrf())
    return request
  },
  onResponse({ response }) {
    if (response.status === 401) listeners.forEach((cb) => cb())
    return response
  },
}

export const api = createClient<paths>({ baseUrl: '', credentials: 'same-origin' })
api.use(session)
```
Run `npm test` and expect 3 passed. Then `npm run typecheck` should pass.

- [ ] **Step 6: CI keeps the generated types honest**

Add a job to `.github/workflows/ci.yml`:
```yaml
  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip, cache-dependency-path: requirements*.txt }
      - run: python -m venv .venv && .venv/bin/pip install -r requirements.txt
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm, cache-dependency-path: web/package-lock.json }
      - run: npm ci
        working-directory: web
      - run: npm run gen:api && git diff --exit-code src/api/
        working-directory: web
      - run: npm run lint && npm run typecheck && npm test && npm run build
        working-directory: web
```

- [ ] **Step 7: Commit**
```bash
git add scripts/export_openapi.py web/package.json web/package-lock.json web/vite.config.ts web/src/api web/src/test .github/workflows/ci.yml
git commit -m "feat(web): generated API types and a cookie+CSRF client; web CI job"
```

---

### Task 7: Encrypted local store

**Files:**
- Create: `web/src/offline/crypto.ts`, `web/src/offline/db.ts`, `web/src/offline/crypto.test.ts`, `web/src/offline/db.test.ts`

**Interfaces:**
- Produces:
  - `getKey(): Promise<CryptoKey>`, which creates the key once and stores it non-extractable;
  - `seal(value: unknown): Promise<{ iv: Uint8Array; data: ArrayBuffer }>`;
  - `open<T>(rec: { iv: Uint8Array; data: ArrayBuffer }): Promise<T>`;
  - `db` (a Dexie instance with tables `keys`, `cache` and `queue`);
  - `cacheGet<T>(key: string): Promise<T | undefined>`;
  - `cachePut(key: string, value: unknown): Promise<void>`;
  - `wipe(): Promise<void>`.

- [ ] **Step 1: Write the failing tests**

`web/src/offline/crypto.test.ts`:
```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { getKey, open, seal } from './crypto'
import { wipe } from './db'

beforeEach(() => wipe())

describe('crypto', () => {
  it('round-trips a value', async () => {
    const rec = await seal({ amount: '64.20', note: 'Sklavenitis' })
    expect(await open(rec)).toEqual({ amount: '64.20', note: 'Sklavenitis' })
  })

  it('uses a fresh IV each time', async () => {
    const a = await seal('x'), b = await seal('x')
    expect(Array.from(a.iv)).not.toEqual(Array.from(b.iv))
  })

  it('stores ciphertext, not plaintext', async () => {
    const rec = await seal('Sklavenitis')
    expect(new TextDecoder().decode(rec.data)).not.toContain('Sklavenitis')
  })

  it('key is not extractable and is reused', async () => {
    const k1 = await getKey(), k2 = await getKey()
    expect(k1.extractable).toBe(false)
    expect(k1).toBe(k2)
  })

  it('wipe makes old records unreadable', async () => {
    const rec = await seal('secret')
    await wipe()
    await expect(open(rec)).rejects.toThrow()
  })
})
```
`web/src/offline/db.test.ts`:
```ts
import { beforeEach, expect, it } from 'vitest'
import { cacheGet, cachePut, db, wipe } from './db'

beforeEach(() => wipe())

it('cache round-trips through encryption', async () => {
  await cachePut('dashboard', { total: 893.79 })
  expect(await cacheGet('dashboard')).toEqual({ total: 893.79 })
  const raw = await db.cache.get('dashboard')
  expect(raw && 'data' in raw && !('total' in raw)).toBe(true)
})

it('wipe empties every table', async () => {
  await cachePut('a', 1)
  await wipe()
  expect(await db.cache.count()).toBe(0)
  expect(await db.keys.count()).toBe(0)
})
```
Run `npm test` and expect FAIL.

- [ ] **Step 2: Implement `web/src/offline/db.ts`**
```ts
import Dexie, { type Table } from 'dexie'

export interface Sealed { iv: Uint8Array; data: ArrayBuffer }
export interface KeyRow { id: 'device'; key: CryptoKey }
export interface CacheRow extends Sealed { key: string; updatedAt: number }
export interface QueueRow extends Sealed {
  id?: number
  createdAt: number
  attempts: number
  nextAttemptAt: number
  status: 'pending' | 'failed'
  error?: string
}

class LocalDB extends Dexie {
  keys!: Table<KeyRow, string>
  cache!: Table<CacheRow, string>
  queue!: Table<QueueRow, number>
  constructor() {
    super('tameio')
    this.version(1).stores({ keys: 'id', cache: 'key', queue: '++id, status, nextAttemptAt' })
  }
}

export const db = new LocalDB()

export async function wipe(): Promise<void> {
  const { forgetKey } = await import('./crypto')
  forgetKey()
  await db.transaction('rw', db.keys, db.cache, db.queue, async () => {
    await Promise.all([db.keys.clear(), db.cache.clear(), db.queue.clear()])
  })
}

export async function cachePut(key: string, value: unknown): Promise<void> {
  const { seal } = await import('./crypto')
  await db.cache.put({ key, ...(await seal(value)), updatedAt: Date.now() })
}

export async function cacheGet<T>(key: string): Promise<T | undefined> {
  const row = await db.cache.get(key)
  if (!row) return undefined
  const { open } = await import('./crypto')
  return open<T>(row)
}
```

- [ ] **Step 3: Implement `web/src/offline/crypto.ts`**
```ts
import { db, type Sealed } from './db'

let cached: Promise<CryptoKey> | null = null

export function forgetKey(): void { cached = null }

export function getKey(): Promise<CryptoKey> {
  cached ??= (async () => {
    const row = await db.keys.get('device')
    if (row) return row.key
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
      'encrypt',
      'decrypt',
    ])
    await db.keys.put({ id: 'device', key })
    return key
  })()
  return cached
}

export async function seal(value: unknown): Promise<Sealed> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const plain = new TextEncoder().encode(JSON.stringify(value))
  const data = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await getKey(), plain)
  return { iv, data }
}

export async function open<T>(rec: Sealed): Promise<T> {
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: rec.iv }, await getKey(), rec.data)
  return JSON.parse(new TextDecoder().decode(plain)) as T
}
```
Run `npm test` and expect all crypto and db tests to pass. If fake-indexeddb can't structured-clone a `CryptoKey` under jsdom, switch the Vitest environment for `src/offline/**` to `node` with `// @vitest-environment node` at the top of both test files. Node 22 has `crypto.subtle` and fake-indexeddb clones `CryptoKey` there.

- [ ] **Step 4: Commit**
```bash
git add web/src/offline
git commit -m "feat(web): encrypted IndexedDB store (non-extractable AES-GCM key, wipe on logout)"
```

---

### Task 8: Session bootstrap, sign-in screen and app shell

**Files:**
- Create:
  - `web/src/session/SessionProvider.tsx`, `web/src/session/SignIn.tsx`, `web/src/session/SessionProvider.test.tsx`;
  - `web/src/shell/AppShell.tsx`, `web/src/shell/TabBar.tsx`, `web/src/shell/TopBar.tsx`, `web/src/shell/shell.css`;
  - `web/src/screens/Home.tsx`, `Activity.tsx`, `Plan.tsx`, `Insights.tsx`, `Compose.tsx`;
  - `web/src/router.tsx`.
- Modify: `web/src/main.tsx`; delete `web/src/App.tsx` and `web/src/assets/` if unused.

**Interfaces:**
- Consumes: `api` and `onUnauthorized` (Task 6); `wipe` (Task 7).
- Produces:
  - `useSession(): { status: 'loading' | 'signedOut' | 'signedIn'; me?: Me; signOut(): Promise<void> }`, where `Me` is the generated `/api/v1/auth/me` response type;
  - routes `/app/`, `/app/activity`, `/app/plan`, `/app/insights`, `/app/new`.

- [ ] **Step 1: Write the failing session test**

`web/src/session/SessionProvider.test.tsx`:
```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SessionProvider, useSession } from './SessionProvider'
import { cachePut, cacheGet } from '../offline/db'

function Probe() {
  const s = useSession()
  return <p>{s.status}{s.me ? `:${s.me.username}` : ''}</p>
}

afterEach(() => vi.restoreAllMocks())

it('signed in when /me returns 200', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ id: '1', username: 'g', household_id: 'h' }), { status: 200 }),
  )
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
})

it('401 signs out and wipes local data', async () => {
  await cachePut('x', 1)
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  expect(await cacheGet('x')).toBeUndefined()
})

it('offline with a cached profile stays signed in', async () => {
  await cachePut('me', { id: '1', username: 'g', household_id: 'h' })
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
})
```
Run `npm test` and expect FAIL.

- [ ] **Step 2: Implement `SessionProvider.tsx`**
```tsx
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, onUnauthorized, readCsrf } from '../api/client'
import type { paths } from '../api/schema'
import { cacheGet, cachePut, wipe } from '../offline/db'

type Me = paths['/api/v1/auth/me']['get']['responses']['200']['content']['application/json']
type Status = 'loading' | 'signedOut' | 'signedIn'
interface Session { status: Status; me?: Me; signOut(): Promise<void> }

const Ctx = createContext<Session>({ status: 'loading', signOut: async () => {} })
export const useSession = () => useContext(Ctx)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me>()

  const signedOut = useCallback(async () => {
    await wipe()
    setMe(undefined)
    setStatus('signedOut')
  }, [])

  useEffect(() => onUnauthorized(() => void signedOut()), [signedOut])

  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const { data, response } = await api.GET('/api/v1/auth/me')
        if (!live) return
        if (response.ok && data) {
          await cachePut('me', data)
          setMe(data); setStatus('signedIn')
        } else if (response.status === 401) {
          await signedOut()
        } else {
          setStatus('signedOut')
        }
      } catch {
        const cached = await cacheGet<Me>('me')
        if (!live) return
        if (cached) { setMe(cached); setStatus('signedIn') } else setStatus('signedOut')
      }
    })()
    return () => { live = false }
  }, [signedOut])

  const signOut = useCallback(async () => {
    await fetch('/app/auth/logout', {
      method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': readCsrf() },
    }).catch(() => {})
    await signedOut()
  }, [signedOut])

  return <Ctx.Provider value={{ status, me, signOut }}>{children}</Ctx.Provider>
}
```
Run `npm test` and expect 3 passed.

- [ ] **Step 3: Sign-in screen `SignIn.tsx`**

The error messages map to the backend `auth_error` codes from Task 4:
```tsx
const MESSAGES: Record<string, string> = {
  no_account: 'This passkey isn’t linked to anyone in a household yet. Ask the household owner to add your email.',
  no_household: 'You’re signed in but not in a household yet. Ask for an invite.',
  denied: 'Sign-in was cancelled.',
  state: 'That sign-in link expired. Try again.',
  ambiguous: 'More than one account uses this email. Ask the owner to fix it.',
  subject_conflict: 'This account is already linked to a different passkey.',
}

export function SignIn() {
  const code = new URLSearchParams(location.search).get('auth_error')
  return (
    <main className="signin">
      <div className="signin__mark" aria-hidden="true">T</div>
      <h1 className="signin__title">Tameio</h1>
      <p className="signin__lede">Household money, private by default.</p>
      {code && <p role="alert" className="signin__error">{MESSAGES[code] ?? 'Sign-in failed. Try again.'}</p>}
      <a className="btn btn--primary btn--block" href="/app/auth/login">Sign in with Face ID</a>
    </main>
  )
}
```
`/app/auth/login` is a top-level navigation, so it stays inside the PWA scope until the hop to Pocket ID.

- [ ] **Step 4: Shell, tab bar and routes**

`web/src/router.tsx`:
```tsx
import { createBrowserRouter } from 'react-router'
import { AppShell } from './shell/AppShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { Compose } from './screens/Compose'
import { Plan } from './screens/Plan'
import { Insights } from './screens/Insights'

export const router = createBrowserRouter(
  [{
    path: '/', element: <AppShell />, children: [
      { index: true, element: <Home /> },
      { path: 'activity', element: <Activity /> },
      { path: 'new', element: <Compose /> },
      { path: 'plan', element: <Plan /> },
      { path: 'insights', element: <Insights /> },
    ],
  }],
  { basename: '/app' },
)
```
`TabBar.tsx` has 5 `NavLink`s:
- Home, Activity, Plan and Insights each have an icon and a label.
- The centre ＋ is a 56 pt accent circle linking to `new`, with `aria-label="Add"`.
- The bar is fixed at the bottom with `padding-bottom: env(safe-area-inset-bottom)`, and `aria-current` is set by NavLink.

`TopBar.tsx` shows the screen title in Sora 600 and, on the right, an avatar button (initials from `me.display_name`) that opens a sheet with "Sign out" → `signOut()`. Each placeholder screen renders its title and one line, e.g. "Activity — coming in Phase 2". `AppShell.tsx`:
```tsx
import { Navigate, Outlet } from 'react-router'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { TabBar } from './TabBar'

export function AppShell() {
  const { status } = useSession()
  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn />
  return (
    <div className="shell">
      <main className="shell__main"><Outlet /></main>
      <TabBar />
    </div>
  )
}
```
`shell.css` uses only tokens from `styles/tokens.css`, and every tap target is at least 44 pt. `main.tsx` renders `<QueryClientProvider client={queryClient}><SessionProvider><RouterProvider router={router} /></SessionProvider></QueryClientProvider>`, with `queryClient` from `new QueryClient({ defaultOptions: { queries: { networkMode: 'offlineFirst', staleTime: 30_000 } } })`. Remove the `Navigate` import if it ends up unused.

- [ ] **Step 5: Verify in a browser**

Run the backend with `NEW_APP_ENABLED=true DEBUG=true .venv/bin/uvicorn app.main:app --port 8000` and `npm run dev` in `web/`. Open `http://localhost:5173/app/`; signed out, it should show the sign-in screen. Sign in to the **old** UI at `http://localhost:5173/login` (Vite proxies it; add `'/login'`, `'/static'`, `'/app/auth'` and `'/dashboard'` to the proxy in `vite.config.ts`), then reload `/app/`. Expect the shell with 5 tabs, and the tab routes switch without a reload. Screenshot at 390×844 in dark and light.

- [ ] **Step 6: Commit**
```bash
git add web/src web/vite.config.ts
git commit -m "feat(web): session bootstrap, passkey sign-in screen and the 5-tab Vault shell"
```

---

### Task 9: Installable PWA

**Files:**
- Modify: `web/vite.config.ts`, `web/index.html`
- Create: `web/public/icons/icon-192.png`, `icon-512.png`, `maskable-512.png`, `apple-touch-icon.png` (from the Vault "T" mark in `docs/redesign/mocks/`)

**Interfaces:**
- Produces: `/app/manifest.webmanifest` and `/app/sw.js` (precaches the shell).

- [ ] **Step 1: Configure vite-plugin-pwa**

In `web/vite.config.ts`:
```ts
import { VitePWA } from 'vite-plugin-pwa'
// plugins: [react(), VitePWA({...})]
VitePWA({
  registerType: 'autoUpdate',
  scope: '/app/',
  base: '/app/',
  manifest: {
    name: 'Tameio', short_name: 'Tameio', id: '/app/', start_url: '/app/', scope: '/app/',
    display: 'standalone', background_color: '#090B10', theme_color: '#090B10',
    icons: [
      { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png' },
      { src: 'icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  },
  workbox: {
    navigateFallback: '/app/index.html',
    navigateFallbackDenylist: [/^\/app\/auth\//, /^\/api\//],
    globPatterns: ['**/*.{js,css,html,woff2,svg,png}'],
    runtimeCaching: [],
  },
})
```
`runtimeCaching` stays empty: API data is cached by our encrypted store, never by the service worker in plaintext.

- [ ] **Step 2: iOS meta in `web/index.html`**

```html
<link rel="apple-touch-icon" href="/app/icons/apple-touch-icon.png" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
```

- [ ] **Step 3: Verify**

Run `npm run build` and expect `dist/sw.js` and `dist/manifest.webmanifest`. Then confirm that `grep -c "<script>" dist/index.html` and `grep -c "<style" dist/index.html` both print `0`, so the strict CSP holds. With the backend serving `dist`, open `/app/` in Chrome, check DevTools → Application → Manifest shows no errors, and check the Console shows no CSP violations.

- [ ] **Step 4: Commit**
```bash
git add web/vite.config.ts web/index.html web/public/icons
git commit -m "feat(web): installable PWA scoped to /app; shell precached, API data never cached by the SW"
```

---

### Task 10: Offline write queue

**Files:**
- Create: `web/src/offline/queue.ts`, `web/src/offline/queue.test.ts`, `web/src/offline/useQueue.ts`
- Modify: `web/src/main.tsx` (start the replay triggers)

**Interfaces:**
- Consumes: `seal` and `open` (Task 7); `readCsrf` (Task 6).
- Produces:
  - `enqueue(req: { method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; path: string; body?: unknown }): Promise<number>`;
  - `replay(): Promise<{ sent: number; failed: number; stoppedOnAuth: boolean }>`;
  - `startReplayTriggers(): () => void`;
  - `useQueue(): { pending: number; failed: number }`.

- [ ] **Step 1: Write the failing tests**

`web/src/offline/queue.test.ts`:
```ts
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db, wipe } from './db'
import { enqueue, replay } from './queue'

beforeEach(() => wipe())
afterEach(() => vi.restoreAllMocks())

const ok = () => new Response('{}', { status: 201 })

it('replays in order and removes sent items', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'b' } })
  expect(await replay()).toMatchObject({ sent: 2, failed: 0 })
  expect(await db.queue.count()).toBe(0)
  const bodies = f.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string).client_id)
  expect(bodies).toEqual(['a', 'b'])
})

it('stores the body encrypted', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { note: 'Sklavenitis' } })
  const row = (await db.queue.toArray())[0]
  expect(new TextDecoder().decode(row.data)).not.toContain('Sklavenitis')
})

it('stops on 401 and keeps everything', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  await enqueue({ method: 'POST', path: '/x', body: {} })
  await enqueue({ method: 'POST', path: '/y', body: {} })
  expect(await replay()).toMatchObject({ sent: 0, stoppedOnAuth: true })
  expect(await db.queue.count()).toBe(2)
})

it('network error backs off and keeps the item pending', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
  await enqueue({ method: 'POST', path: '/x', body: {} })
  await replay()
  const row = (await db.queue.toArray())[0]
  expect(row.status).toBe('pending')
  expect(row.attempts).toBe(1)
  expect(row.nextAttemptAt).toBeGreaterThan(Date.now())
})

it('4xx marks failed with the server message; 409 is dropped', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'bad split' }), { status: 422 }))
    .mockResolvedValueOnce(new Response('{}', { status: 409 }))
  await enqueue({ method: 'POST', path: '/x', body: {} })
  await enqueue({ method: 'POST', path: '/y', body: {} })
  await replay()
  const rows = await db.queue.toArray()
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ status: 'failed', error: 'bad split' })
})

it('sends the CSRF header', async () => {
  document.cookie = 'csrf_token=tok'
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await enqueue({ method: 'POST', path: '/x', body: {} })
  await replay()
  expect(new Headers((f.mock.calls[0][1] as RequestInit).headers).get('X-CSRF-Token')).toBe('tok')
})
```
Run `npm test` and expect FAIL.

- [ ] **Step 2: Implement `web/src/offline/queue.ts`**
```ts
import { readCsrf } from '../api/client'
import { open, seal } from './crypto'
import { db } from './db'

type Method = 'POST' | 'PUT' | 'PATCH' | 'DELETE'
interface Req { method: Method; path: string; body?: unknown }

const MAX_BACKOFF_MS = 5 * 60_000
let running: Promise<{ sent: number; failed: number; stoppedOnAuth: boolean }> | null = null

export async function enqueue(req: Req): Promise<number> {
  const now = Date.now()
  return db.queue.add({
    ...(await seal(req)), createdAt: now, attempts: 0, nextAttemptAt: now, status: 'pending',
  })
}

export function replay() {
  running ??= drain().finally(() => { running = null })
  return running
}

async function drain() {
  let sent = 0, failed = 0
  const rows = await db.queue.where('status').equals('pending').sortBy('id')
  for (const row of rows) {
    if (row.nextAttemptAt > Date.now()) continue
    const req = await open<Req>(row)
    let res: Response
    try {
      res = await fetch(req.path, {
        method: req.method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': readCsrf() },
        body: req.body === undefined ? undefined : JSON.stringify(req.body),
      })
    } catch {
      const attempts = row.attempts + 1
      await db.queue.update(row.id!, {
        attempts, nextAttemptAt: Date.now() + Math.min(MAX_BACKOFF_MS, 2 ** attempts * 1000),
      })
      break // offline: stop, keep order
    }
    if (res.status === 401) return { sent, failed, stoppedOnAuth: true }
    if (res.ok || res.status === 409) {
      await db.queue.delete(row.id!); sent++; continue
    }
    if (res.status >= 500) {
      const attempts = row.attempts + 1
      await db.queue.update(row.id!, {
        attempts, nextAttemptAt: Date.now() + Math.min(MAX_BACKOFF_MS, 2 ** attempts * 1000),
      })
      break
    }
    const detail = await res.json().then((j) => (typeof j?.detail === 'string' ? j.detail : ''), () => '')
    await db.queue.update(row.id!, { status: 'failed', error: detail || `HTTP ${res.status}` })
    failed++
  }
  return { sent, failed, stoppedOnAuth: false }
}

export function startReplayTriggers(): () => void {
  const run = () => void replay()
  const vis = () => { if (document.visibilityState === 'visible') run() }
  window.addEventListener('online', run)
  document.addEventListener('visibilitychange', vis)
  run()
  return () => {
    window.removeEventListener('online', run)
    document.removeEventListener('visibilitychange', vis)
  }
}
```
A 409 replay of a deleted transaction is reported in Phase 2's toast. For now it's counted as sent and removed, matching Decision 11. Run `npm test` and expect all queue tests to pass.

- [ ] **Step 3: `useQueue` and the triggers**

`useQueue.ts` uses `useLiveQuery` from `dexie-react-hooks` (`npm i dexie-react-hooks`) to count `pending` and `failed`. In `main.tsx`, after render, call `startReplayTriggers()`, but only once the session status is `signedIn`: call it from `AppShell` in a `useEffect` when `status === 'signedIn'`, and return its cleanup.

- [ ] **Step 4: Commit**
```bash
git add web/src/offline web/src/main.tsx web/src/shell/AppShell.tsx web/package.json web/package-lock.json
git commit -m "feat(web): encrypted offline write queue with replay on open, online and visibility"
```

---

### Task 11: Pocket ID locally, the iPhone vertical slice, and deploy docs

**Files:**
- Create: `docs/POCKET-ID.md`
- Modify: `docs/DEPLOY-COOLIFY.md` (env table, plus a "New app" section), `docker-compose.yml` (optional `pocketid` service under a `pocketid` profile for local dev)

- [ ] **Step 1: Local Pocket ID**

Add to `docker-compose.yml`:
```yaml
  pocketid:
    profiles: ["pocketid"]
    image: ghcr.io/pocket-id/pocket-id:v2
    ports: ["1411:1411"]
    environment:
      APP_URL: http://localhost:1411
      TRUST_PROXY: "false"
    volumes: ["pocketid_data:/app/data"]
```
and `pocketid_data:` under `volumes:`. Before committing, check the image's required env vars in the Pocket ID v2 docs (context7 or <https://pocket-id.org/docs>). v2 may require an `ENCRYPTION_KEY`; add it if the docs say so. Then:
1. Run `docker compose --profile pocketid up -d pocketid`.
2. Open <http://localhost:1411/setup> and create the admin with a passkey.
3. Add an OIDC client with callback `http://localhost:8000/app/auth/callback`.
4. Create a user with the same email as your local app user.

- [ ] **Step 2: End-to-end on desktop**

Run `OIDC_ISSUER=http://localhost:1411 OIDC_CLIENT_ID=… OIDC_CLIENT_SECRET=… NEW_APP_ENABLED=true DEBUG=true .venv/bin/uvicorn app.main:app --port 8000` with `web/dist` built. Open `http://localhost:8000/app/` → Sign in with Face ID → passkey → back on `/app/` with the shell. Expect `/api/v1/auth/me` to return 200 in the Network tab. Then sign out → sign-in screen; IndexedDB `tameio` is empty.

- [ ] **Step 3: Docs**

`docs/POCKET-ID.md` covers:
1. **Deploy Pocket ID in Coolify:** use the template, set the image to `ghcr.io/pocket-id/pocket-id:v2`, give it its own domain (e.g. `id.<domain>`) and persistent storage on `/app/data`.
2. **Create the admin** with a passkey. Turn off self sign-up.
3. **Add an OIDC client "Tameio":**
   - callback `https://<app domain>/app/auth/callback`;
   - PKCE on;
   - copy the client id and secret.
4. **Create both household users** with the **same emails** as in the app, so the first sign-in links them. Enable "emails verified" for admin-created users so the `email_verified` claim is true.
5. **In the expenses app** (Coolify → Environment Variables), set `OIDC_ISSUER=https://id.<domain>`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` and `NEW_APP_ENABLED=true`, then redeploy.
6. **Recovery:** the Pocket ID admin issues a one-time login code (Users → … → Login code).

Add the four env vars to the table in `docs/DEPLOY-COOLIFY.md`.

- [ ] **Step 4: iPhone slice (user, on the real device)**

After deploying with the flag on:
1. Safari → `https://<app domain>/app/` → Share → Add to Home Screen.
2. Open from the home screen → Sign in with Face ID.
3. Expect to land back **inside the installed app** with the tab bar.

If it lands in Safari instead, record that in `docs/POCKET-ID.md` and stop: the session cookie is shared with Safari, so the fix is a "Continue in app" screen at `/app/auth/done`. That fix needs its own small task before Phase 2.

- [ ] **Step 5: Commit**
```bash
git add docs/POCKET-ID.md docs/DEPLOY-COOLIFY.md docker-compose.yml
git commit -m "docs: Pocket ID setup, env vars and the iPhone sign-in check"
```

---

## Out of scope for Phase 1 (later phases)

- **Phase 2:** Home, Activity and the composer (offline-first create through `enqueue`). Also bulk changes and default payment method on bills, from `docs/redesign/backlog.md`.
- **Phase 3:** Plan (Bills, Budgets, Cash, Pantry).
- **Phase 4:** Insights, Settings, desktop layouts.
- **Phase 5:**
  - receipt scan;
  - web push via the session cookie;
  - an "Install" prompt;
  - linking Pocket ID from the old Settings for users whose email doesn't match.
- **Phase 6:**
  - cutover: `/` redirects to `/app/`;
  - export and drop settlements;
  - delete Jinja, HTMX and Alpine;
  - one CSP for everything;
  - security review.
