# Pocket ID: passkey sign-in for the new app

The new app at `/app` signs in with passkeys (Face ID / Touch ID) through a self-hosted
[Pocket ID](https://pocket-id.org) v2, over OIDC. Pocket ID is used for this app only:
Coolify keeps its own login, so a broken Pocket ID can never lock you out of the tool
that fixes it. The old UI keeps password + 2FA exactly as before.

Production:

| | |
|---|---|
| App | `https://expenses.gch.gr` (new app at `https://expenses.gch.gr/app/`) |
| Pocket ID | `https://id.gch.gr` (Coolify, Let's Encrypt certificate) |
| OIDC client | `Tameio` |
| Callback URL | `https://expenses.gch.gr/app/auth/callback` |

## How sign-in and linking work

- **Users are never created by a passkey.** Every person needs an existing account in the
  app (password + 2FA) *and* a user in Pocket ID.
- **Linking is explicit, once per person, from a signed-in password+2FA session.** Old UI →
  Settings → *Passkey (new app)* → re-enter your password and a 2FA code → **Link passkey**.
  That posts to `/app/auth/link`, which sends you to Pocket ID with `prompt=login` (a fresh
  passkey ceremony). Pocket ID returns to `/app/auth/callback`, and the app stores your Pocket
  ID user id (the OIDC `sub`) on your account. The link attempt expires after 10 minutes.
- **Sign-in matches on `sub` only.** Email is never used to match or link accounts, so
  Pocket ID's email-verification settings don't matter here (`EMAILS_VERIFIED` is not needed).
  A passkey that isn't linked gets "This passkey isn't linked yet" and no session.
- **Unlink:** old UI → Settings → **Unlink passkey** (`POST /app/auth/unlink`). This also ends
  every session opened with the passkey (and revokes API refresh tokens); the browser you
  unlink from stays signed in. Personal ingest tokens (the Apple Pay Shortcut) are untouched.
- A passkey session counts as multi-factor. Password sessions still require 2FA.
- The old UI and the new app share one session cookie: signing in or out of either does the
  same for both.

## 1. Deploy Pocket ID in Coolify

1. Coolify → **New resource** → the *Pocket ID* service template. Set the image to
   `ghcr.io/pocket-id/pocket-id:v2`.
2. Give it its own domain: `https://id.gch.gr`. Coolify issues the Let's Encrypt certificate.
3. Persistent storage on `/app/data` (the SQLite database, keys and uploads live there).
4. Environment:

   | Variable | Value |
   |---|---|
   | `APP_URL` | `https://id.gch.gr` (passkeys are bound to this host) |
   | `ENCRYPTION_KEY` | `openssl rand -base64 32`. **Required by v2** (at least 16 bytes). Keep it: losing it loses the signing keys, and every client must be set up again. |
   | `TRUST_PROXY` | `true` (it sits behind Coolify's Traefik) |

5. Deploy, then check `https://id.gch.gr/.well-known/openid-configuration` returns JSON whose
   `issuer` is exactly `https://id.gch.gr`.

## 2. Admin and sign-up policy

1. Open `https://id.gch.gr/setup` and create the admin account, then register its passkey.
2. Settings → Application Configuration: keep **user sign-ups disabled** (the default). Users
   are created by the admin only. An open sign-up would not grant access to the app (nothing
   is linked without a password+2FA session), but there is no reason to allow it.

## 3. OIDC client "Tameio"

Pocket ID → OIDC Clients → **Add**:

- Name: `Tameio`.
- Callback URL: `https://expenses.gch.gr/app/auth/callback` (exact match; no trailing slash).
- Public client: **off** (the app is a confidential client with a secret).
- PKCE: **on**.
- Save, then copy the client ID and create/copy the client secret. Put them straight into
  Coolify (next step); don't paste them anywhere else.

## 4. Users and passkeys

For each household member, the admin creates a user in Pocket ID (Users → Add). Each person
then registers their passkey: either sign in once with a one-time login code (Users → ⋯ →
*Login Code*) and add a passkey under *My Account*, or let the admin hand them a setup link.

## 5. Configure the app

Coolify → the expenses app → Environment Variables (already set for production):

| Variable | Value |
|---|---|
| `OIDC_ISSUER` | `https://id.gch.gr` (no trailing path; must match the discovery `issuer`) |
| `OIDC_CLIENT_ID` | from step 3 |
| `OIDC_CLIENT_SECRET` | from step 3 |
| `NEW_APP_ENABLED` | `true` |

`APP_BASE_URL` must be `https://expenses.gch.gr`: the callback URL sent to Pocket ID is built
from it, so it has to match the callback registered in step 3. With `NEW_APP_ENABLED=true`
and any of the three OIDC values missing, the app refuses to start. Redeploy after changing
them. The old UI's CSP automatically allows the Pocket ID origin as a form target (the Link
passkey form redirects there).

## 6. Link once per person

Each person: sign in to `https://expenses.gch.gr/login` with password + 2FA → Settings →
*Passkey (new app)* → current password + a fresh 2FA code → **Link passkey** → Face ID at
Pocket ID → back on `/app/` with "Passkey linked". From then on, **Sign in with Face ID** on
`/app/` works.

## 7. iPhone check (after the deploy)

1. Safari → `https://expenses.gch.gr/app/` → Share → **Add to Home Screen**.
2. Open it from the home screen → **Sign in with Face ID**.
3. Expected: you land back **inside the installed app** with the tab bar.

If it lands in Safari instead, write down what happened here (iOS version, where it ended
up) and stop: the session cookie is shared with Safari, so the fix is a small "Continue in
app" screen at `/app/auth/done`. That fix gets its own task before Phase 2.

Result: *not yet checked on a device.*

## Recovery

- **Lost phone / no passkey:** the Pocket ID admin issues a one-time login code (Users → ⋯ →
  *Login Code*); the person signs in with it and registers a new passkey. The app link (the
  `sub`) stays the same, so nothing needs relinking.
- **Pocket ID down:** the old UI still works with password + 2FA.
- **Wrong account linked:** sign in to the old UI as that account → Settings → Unlink
  passkey, then link again from the right account.

## What the app does with your data offline

- Data the new app keeps on the device (cached responses and writes queued while offline)
  lives in IndexedDB (database `tameio`), **encrypted** with AES-GCM-256. The key is generated
  on the device as a non-extractable `CryptoKey`: page scripts can use it but never read it
  out, and a copy of the storage alone can't be decrypted. It does not protect an unlocked
  phone.
- **Sign out** wipes the whole database, key included. So does **switching account** (a
  different person signing in on the same device, in any tab).
- When a session merely **expires**, the encrypted data is **kept**, so changes made offline
  aren't lost: sign in again as the same person and they are sent.
- Queued writes only replay for the account that made them. Each one carries
  `X-Expected-Account: <user>:<household>`, and the server refuses it with **412** if the
  signed-in account differs.
- The service worker caches the app shell only; API data is never cached by it.

## Local development

```sh
# Compose interpolates the whole file, so the app's required vars need a (dummy) value.
APP_SECRET_KEY=x APP_BASE_URL=http://127.0.0.1:8000 \
  docker compose --profile pocketid up -d pocketid
```

1. Open <http://localhost:1411/setup> and create the admin with a passkey (WebAuthn works on
   `localhost` over plain http).
2. Add an OIDC client with callback `http://127.0.0.1:8000/app/auth/callback`, PKCE on.
3. Run the app on **127.0.0.1**, not `localhost`: cookies ignore the port, and Pocket ID's own
   cookies on `localhost` overwrite the app's session (you'd be signed out after the hop).
   ```sh
   (cd web && npm run build)
   NEW_APP_ENABLED=true DEBUG=true APP_SECRET_KEY=dev-only-0123456789 \
   DATABASE_URL=sqlite:////tmp/expenses-dev.db \
   OIDC_ISSUER=http://localhost:1411 OIDC_CLIENT_ID=… OIDC_CLIENT_SECRET=… \
     .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   `DEBUG=true` creates the tables in that SQLite file on startup (no Alembic run needed);
   the first visit to `/login` redirects to `/setup` to create the first user.
4. Sign in at <http://127.0.0.1:8000/login> with password + 2FA → Settings → Link passkey,
   then <http://127.0.0.1:8000/app/> → Sign in with Face ID.

Tear down with `docker compose --profile pocketid down -v` (drops the local Pocket ID data).

**Automated:** `.venv/bin/python scripts/e2e_passkey.py` does all of the above with a
Chromium virtual authenticator, in a throwaway compose project and SQLite database:
link from Settings, passkey sign-in at `/app/` (`/api/v1/auth/me` = 200), sign out
(IndexedDB `tameio` empty, `/me` = 401). It needs Docker, ports 1411 and 8000 free and
`.venv/bin/playwright install chromium`.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Passkey prompt never appears, or "operation is insecure" / not allowed | Passkeys need a **trusted HTTPS** origin (or `localhost`). An `http://…sslip.io` URL, a self-signed certificate or a plain-http IP will not work; give Pocket ID a real domain with a Let's Encrypt certificate. |
| Passkey created on one host doesn't work on another | Passkeys are bound to `APP_URL`'s host. Changing Pocket ID's domain means re-registering passkeys. |
| Pocket ID says the redirect/callback URL is invalid | The client's callback must be exactly `https://expenses.gch.gr/app/auth/callback`, and `APP_BASE_URL` must be `https://expenses.gch.gr`. |
| `/app/?auth_error=not_linked` | That Pocket ID user isn't linked to any account yet. Link from the old UI's Settings first. |
| `/app/?auth_error=subject_conflict` | That Pocket ID user is already linked to a different account. Unlink it there first. |
| `/app/?auth_error=link_requires_login` | The link was started without a valid password+2FA session, or took longer than 10 minutes. Sign in to the old UI and try again. |
| `/app/?auth_error=state` | The sign-in took too long (over 10 minutes) or was opened in a different browser. Try again. |
| `/app/?auth_error=provider` | The app couldn't reach Pocket ID. Check `OIDC_ISSUER` and that `https://id.gch.gr` is up. |
| App won't start: "NEW_APP_ENABLED needs OIDC_ISSUER…" | One of the three OIDC variables is empty. |
| Pocket ID won't start | `ENCRYPTION_KEY` missing or shorter than 16 bytes. |
| Wrong `issuer` / token rejected behind the proxy | Set `TRUST_PROXY=true` on Pocket ID and make `APP_URL` the public https URL. |
