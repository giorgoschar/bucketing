# Phase 2b: the ＋ Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One keypad-first composer at `/new` and `/edit/:id` that creates and edits expenses and income (including foreign currency, split, own share, fuel, cash from wallet, QR scan and photo receipt), works offline through the queue with `client_id` idempotency, and saves a €3 coffee in two taps.

**Architecture:** Pure logic (`amount.ts`, `state.ts`, `defaults.ts`, `model.ts`, `splits.ts`) is written and unit-tested first and has no React. Hooks in `features/composer/hooks/` are the only code that touches `api`, the encrypted cache or 2a's `useAction`/`useCachedQuery`, and they reach 2a only through one adapter file, `features/composer/bridge.tsx`. Screens (`Composer.tsx`, `ComposerForm.tsx`, sheets, `scan/`) use hooks and the kit only. Two additive backend endpoints (B1 QR lookup, B2 duplicate check) expose existing HTML-only logic to the API through shared functions.

**Tech Stack:** React 19, Vite 8, TypeScript 6, Vitest 4 + Testing Library (jsdom, `fake-indexeddb`), TanStack Query 5, Dexie (encrypted store in `web/src/offline`), openapi-fetch, react-router 7, `qr-scanner` (new, lazy chunk). Backend: FastAPI + SQLAlchemy, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-phase-2b-composer-design.md` (the authority). Also read `docs/superpowers/specs/2026-10-07-phase-2a-plan-home-design.md` §3 (data layer and kit) and `docs/superpowers/specs/2026-10-07-phase-2d-insights-settings-design.md` §7.4 (category-rules API). Visual source: `docs/redesign/mocks/composer.html` with `tokens.css` and `components.css`.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied from the spec.

- **Amount entry:** at most 7 integer digits, at most 2 decimals, one decimal point, no leading zeros ("007" shows "7"), `.` first gives "0.". Kept as a string; the API receives a decimal string such as `"4.10"`. Floats are never used for money: integer cents (`number`) for amounts and shares, `BigInt` for any multiplication by a rate or division by a fuel price.
- **Rate:** units of household currency per 1 unit of the chosen currency, up to 6 decimals, greater than 0 and at most 1,000,000. `"1"` when the currency is the household's.
- **Fuel price per litre:** decimal, up to 3 decimals, greater than 0. Litres = amount ÷ price, half-up to 3 decimals, display only (the server computes its own).
- **Limits:** notes at most 500 characters; merchant at most 100; no date later than today.
- **Date:** always sent as `YYYY-MM-DD` from the device's local calendar day (`getFullYear/getMonth/getDate`, never `toISOString()`).
- **`client_id`:** `crypto.randomUUID()` generated when a new composer mounts; sent on create only; the same value for every attempt of one entry (double tap, lost response, queue replay).
- **Payment methods:** `card`, `cash`, `apple_pay`, `transfer`, `other` (labels Card · Cash · Apple Pay · Transfer · Other). Income sends `transfer` unless `lastIncome` says otherwise, and has no method pill.
- **Currencies:** EUR, USD, GBP, CHF, JPY, AUD, CAD, SEK, NOK, DKK.
- **Receipts:** up to 10 MB; `.jpg .jpeg .png .gif .webp .pdf .heic .heif`; picker `accept="image/*,application/pdf"`; upload needs a connection. Photo shrink: longest side 2000 px, JPEG quality 0.85.
- **Timings:** duplicate check timeout 2 seconds; Undo toast 5 seconds; new-row highlight 2 seconds (none under reduced motion).
- **Settlement:** `exclude_from_settlement` is never offered; create sends `false`, edit sends the stored value back.
- **Layering:** screens never call `api` directly. Only files under `features/composer/hooks/`, `features/composer/scan/useQrLookup.ts` and `features/composer/bridge.tsx` import `api`, `data/*` or `offline/*`; other composer files reach 2a through `bridge.tsx`.
- **Look:** Vault tokens from `web/src/styles/tokens.css`; inputs at 16 px or larger; tap targets at least 44 pt; keypad keys at least 48 px high; Sora for the amount, JetBrains Mono for share boxes, tabular numerals; width 360–430 px, wider screens get the centred 480 px column. The caret does not blink and nothing slides under `prefers-reduced-motion`.
- **Copy (verbatim):** "Where? (optional)", "Choose a budget", "Save €4.10" / "Save income €700.00" / "Save changes", "Discard this entry?", "Delete this entry?", "Date can't be in the future", "Enter the rate", "Fix the split", "Your wallet has €X", "Saved €64.20 to Day to day", "Saved on this phone. It will sync when you're back online.", "Saved on this phone. The receipt wasn't attached: add it when you're back online.", "Saved. The receipt didn't upload.", "Add the receipt later when you're online (Edit)", "Max 10 MB", "Unsupported file type", "Read from myDATA QR", "from receipt", "Couldn't find the total", "Receipt attached. Type the details.", "That is not a receipt QR", "No QR? Use Photo to attach the receipt", "Camera not available", "Scanning needs a connection. Type it instead", "Connect once to load this entry.", "This entry no longer exists", "Waiting to sync", "Turn off for one-offs", "Asks for price per litre", "Each paid own share", "Who paid what", "Not tracked" · "My wallet" · "Bank/ATM".
- **Backend:** two additive endpoints, no migration; the `down_revision` rule (`c9d0e1f2a3b4`) does not come into play. Regenerate web types with `cd web && npm run gen:api` after any backend API change.
- **UI tasks** say so in their first step: load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.
- **Speed mode:** each task runs only its own tests (`cd web && npm test -- <file>`, or `.venv/bin/python -m pytest <files> -o addopts="" -p no:cacheprovider`). The integration task (C7-1) runs everything.
- **Worktrees:** each stream works in its own git worktree and branch and is merged in order, as in 2a. Parallel streams never edit the same file (the "Files" block of each task is the contract).

### The 2a contract this plan consumes

2a's plan (`docs/superpowers/plans/2026-10-07-phase-2a-plan-home.md`, section "Stream A exports") fixes these names; 2b uses them as written. Composer files reach them through `web/src/features/composer/bridge.tsx` (Task C1-1), which re-exports them and adds 2b's few helpers.

| 2a module | What 2b uses |
|---|---|
| `data/action.ts` (A6) | `useAction<V = void, T = unknown>(spec: ActionSpec<V, T>): { run(vars: V): Promise<ActionResult<T>>; busy }`; `ActionSpec { method; path: string \| (v) => string; body?: unknown \| (v) => unknown; optimistic?(qc, v); invalidates: readonly QueryKey[]; pendingId?; toastRejections? }`; `ActionResult<T> = { status: 'done'; data: T } \| { status: 'queued' } \| { status: 'rejected'; code: number; detail: string }`. Offline or a network error queues; 5xx/408/429 queue; other 4xx roll back, toast the detail (unless `toastRejections: false`; never for 401) and resolve `rejected`. This already is spec §3.1's "`run()` resolves done or queued", so 2b changes nothing in `action.ts`. |
| `data/cachedQuery.ts` (A5) | `useCachedQuery<T>(key, fetcher: (signal) => Promise<T>, opts?)` → `CachedQuery<T> { data; dataUpdatedAt; fromCache; isLoading; isError; offline; stale; noData; refetch }`. The device-cache key is household-scoped (`cacheKeyFor`), so query keys carry no household id. |
| `data/keys.ts` (A5) | `keys.transactions.{all, recent(), one(id)}`, `keys.plan.all`, `keys.home.all`, `keys.matches()`, `keys.insights.all`, `keys.household()`, `keys.buckets()`, `keys.categories()`, `keys.categoryRules()`, `keys.cashStash()`. 2a already defines every key spec §3.1 lists, so 2b adds no `keys.ts` entries (only two keys under `transactions.all`, in the bridge). |
| `data/http.ts`, `data/online.ts` (A4) | `unwrap`, `ApiError { status; detail }`, `detailOf`; `useOnline()`, `isOnline()`. |
| `data/reads.ts`, `data/types.ts` (A8, A1) | `useHousehold()`, `useBuckets()`, `useCategories()`, `toTransactionPage()`, `memberName()`; types `Member`, `Household`, `Bucket`, `Category`, `TransactionRow`, `TransactionPage`. C1-1 adds the fields the composer needs (`Bucket.start_date/end_date/show_income`, `Category.system_key`). |
| `ui/*` (A2, A3) | `Sheet({ open, onClose, title, footer?, … })` (a `role="dialog"` named by `title`), `Segmented<T>({ label, options, value, onChange, disabled? })` (a radiogroup), `Badge({ tone?: 'neutral'\|'pos'\|'neg'\|'warn'\|'acc', icon? })`, `toast(message, { action?: { label, onClick }, durationMs?, tone? })` with a module-level store and `<Toaster />`, icons (`CheckIcon`, `ChevronDownIcon`, `ClockIcon`, `XIcon`, …), `ui.css` (`.chip`, `.toggle`, `.btn`). |
| `data/queueBridge.ts` (A7) | `installQueueBridge(qc)`; AppShell installs it and renders `<Toaster />`. |
| `test/fakeApi.ts`, `test/render.tsx`, `test/fixtures.ts` (A4) | `fakeApi(routes)` → `FakeApi { calls; callsTo; on; down; up }` (route keys `"METHOD /path/template"`, handlers return the body or a `Response`; unknown routes 404); `testQueryClient()`, `setOnline(bool)`, `resetTestEnv()`, `renderWithProviders()`, fixture factories. C1-1 makes `fakeApi` keep a `FormData` body (the receipt upload). |

**`router.tsx`:** the brief for this plan said 2a does not change `router.tsx`. 2a's plan does: its task D5 adds the child route `plan/items`. The only 2b task that edits `router.tsx` is **C2-10**, which therefore merges after 2a's D5 and keeps that route.


## Review Focus

The five inputs the spec implies but its test list does not pin, most likely to bite first. Each has a test in the task named.

1. **A double tap on Save, or Enter pressed twice, sends exactly one POST** with one `client_id`, never two rows. Test in C2-8 ("a double tap on Save sends one POST").
2. **An entry made shortly after local midnight** (Athens is UTC+3 in summer) gets the device's calendar day, not the UTC one. Test in C2-1 (`todayLocal` under `TZ=Europe/Athens`).
3. **Editing an entry whose budget was archived since** still shows the stored budget's name and sends its id back unchanged; the picker lists active budgets only. Test in C2-9.
4. **Method Cash with "My wallet" or "Bank/ATM" and another member as payer** is blocked on the phone with "Cash taken must be paid by you", instead of a server 400 after an offline replay. Test in C2-4 (`validate`).
5. **The largest amount at the largest rate** (9,999,999.99 at 1,000,000) converts exactly for the "≈ €x" line and the wallet check, with no float drift. Test in C2-1 (`convertCents`).

---

## Streams, tasks and dependencies

| Stream | Tasks | Can start |
|---|---|---|
| **C3** backend | C3-1 B1 `POST /api/v1/transactions/scan/qr` · C3-2 B2 `GET /api/v1/transactions/check-duplicate` + `gen:api` | now |
| **C1** kit and contract | C1-1 bridge, action result, keys, fake API · C1-2 `Keypad`, `AmountDisplay` · C1-3 `Pill`, `ToggleRow` | after 2a stream A merges |
| **C2** core composer | C2-1 `amount.ts`, `dates.ts`, `currencies.ts` · C2-2 `types.ts`, `state.ts` · C2-3 `defaults.ts` · C2-4 `model.ts` · C2-5 data and save hooks · C2-6 duplicate check and receipt upload hooks · C2-7 pickers · C2-8 composer screen (new, income, cash) · C2-9 edit, copy, delete · C2-10 routes and full-screen shell | C2-1 now; C2-2..C2-4 after C1-1 (2a's types); the rest after C1 (and C3 for C2-6); C2-10 after 2a's D5 |
| **C4** More and split | C4-1 `splits.ts` · C4-2 `SplitSheet` · C4-3 More sheet fuel, FX, split and own share | C4-1 after C2-2; C4-3 after C2 merges |
| **C5** offline surfaces | C5-1 `listQueuedBodies` · C5-2 `usePendingTransactions` · C5-3 Home Recent integration | C5-1 now; C5-3 after 2a stream E |
| **C6** scan | C6-1 `qr.ts`, `image.ts`, dependency, CSP · C6-2 `ScanScreen`, `useQrLookup` · C6-3 scan wiring, review banner, Remember rule | C6-1 now; C6-3 after C4-3 |
| **C7** integration | C7-1 full checks, manual Chrome pass at 390×844 | last |

**Dependency graph:** `C3-1→C3-2`; `2a-A→C1-1→{C1-2,C1-3}`; `{C2-1,C1-1}→C2-2→{C2-3,C2-4,C4-1}`; `{C1-1,C2-3,C2-4}→C2-5`; `{C1-1,C3-2}→C2-6`; `{C1-3,C2-2}→C2-7`; `{C1-2,C2-5,C2-6,C2-7}→C2-8→C2-9`; `{C2-9,2a-D5}→C2-10`; `{C4-1,C1-1,C1-3}→C4-2`; `{C2-10,C4-2}→C4-3`; `C5-1`; `{C5-1,C2-5}→C5-2`; `{C5-2,2a-E}→C5-3`; `C6-1`; `{C6-1,C1-1,C3-2}→C6-2`; `{C6-2,C4-3}→C6-3`; `all→C7-1`.

**Why the spec's §10 split was adjusted** (all additive, recorded in the final report):
- Duplicate check and receipt upload move from C5 to C2 (C2-6), because both render inside the composer's save flow; C5 keeps only files no other stream touches (`offline/queuedBodies.ts`, `usePendingTransactions`, Home).
- Cash from wallet moves from C4 to C2 (C2-8): it changes the payer pill, the method pill and the modes row, all owned by `ComposerForm.tsx`.
- `ComposerForm.tsx` is edited after C2 only by C4-3 (own-share opens the split sheet) and then C6-3 (scan overlay, review banner, Scan chip). C6-3 waits for C4-3, so no two parallel tasks edit it.
- Spec §3 lists one `hooks.ts`; this plan uses one file per hook under `features/composer/hooks/` so streams stay on disjoint files.
- `listQueuedBodies` goes in a new file `offline/queuedBodies.ts` instead of editing Phase 1's `queue.ts`.
- No `data/keys.ts` additions: 2a's keys already hold `transactions.recent/one`, `buckets`, `categories`, `household`, `categoryRules`, `cashStash` and `matches`. 2b's two extra keys (`editKey`, `merchantsKey`) sit under `transactions.all` in the bridge.
- 2a's shared reads (`useHousehold`, `useBuckets`, `useCategories`) are reused; C1-1 adds the bucket and category fields the composer needs to them instead of a second read of the same endpoints.

## File map

```
app/routes/scan.py                      C3-1  modify: extract lookup_qr_receipt(); HTML route calls it
app/api/transactions.py                 C3-1, C3-2  modify: POST /scan/qr, GET /check-duplicate (+ response models)
app/services/duplicates.py              C3-2  modify: duplicate_check() shared by both routes
app/services/__init__.py                C3-2  modify: export duplicate_check
app/routes/transactions_search.py       C3-2  modify: HTML check-duplicate calls duplicate_check
tests/test_api_composer.py              C3-1, C3-2  create
web/src/api/openapi.json, schema.d.ts   C3-2  regenerate
app/web_app.py, tests/test_web_app.py   C6-1  modify: APP_CSP worker-src adds blob: (only if qr-scanner needs it)

web/src/data/types.ts, data/reads.ts     C1-1  modify (2a files, additive): Bucket/Category fields
web/src/test/fakeApi.ts, test/fixtures.ts C1-1  modify (2a files, additive): FormData bodies, fixture fields
web/src/data/reads.composer.test.ts, web/src/test/fakeApi.formdata.test.ts   C1-1  create
web/src/features/composer/bridge.tsx (+ bridge.test.tsx), testHelpers.ts     C1-1  create
web/src/ui/Keypad.tsx, AmountDisplay.tsx, composer-kit.css, Keypad.test.tsx, AmountDisplay.test.tsx   C1-2
web/src/ui/Pill.tsx, ToggleRow.tsx, Pill.test.tsx, ToggleRow.test.tsx                                  C1-3 (+ composer-kit.css rules appended)

web/src/features/composer/
  amount.ts, dates.ts, currencies.ts (+ .test.ts)          C2-1
  types.ts, state.ts (+ state.test.ts)                     C2-2
  defaults.ts (+ defaults.test.ts)                         C2-3
  model.ts (+ model.test.ts)                               C2-4
  hooks/useComposerData.ts, hooks/useDefaults.ts, hooks/pendingStore.ts,
  hooks/useSaveTransaction.ts, hooks/undo.ts (+ hooks/useSaveTransaction.test.tsx)   C2-5
  hooks/useDuplicateCheck.ts, hooks/useReceiptUpload.ts, receipt.ts (+ tests)        C2-6
  pickers/BucketSheet.tsx, CategorySheet.tsx, PayerSheet.tsx, MethodSheet.tsx,
  CurrencySheet.tsx, DateSheet.tsx, labels.ts, pickers.css (+ pickers.test.tsx)       C2-7
  Composer.tsx, ComposerForm.tsx, CashControls.tsx, DuplicateCard.tsx, ConfirmSheet.tsx,
  MoreSheet.tsx, useClose.ts, composer.css, testing.tsx (+ Composer.test.tsx)         C2-8
  EditTopMenu.tsx (+ Composer.edit.test.tsx), Composer.tsx/ComposerForm.tsx edits    C2-9
web/src/router.tsx, web/src/screens/Compose.tsx, web/src/shell/FullScreenShell.tsx (+ test),
  web/src/main.tsx and web/src/shell/AppShell.tsx only if the toast host must move  C2-10

  splits.ts (+ splits.test.ts)                             C4-1
  SplitSheet.tsx, split.css (+ SplitSheet.test.tsx)        C4-2
  MoreSheet.tsx, ComposerForm.tsx (own share, split sheet, fuel prefill) (+ More.test.tsx)   C4-3

web/src/offline/queuedBodies.ts (+ test)                   C5-1
web/src/features/composer/hooks/usePendingTransactions.ts (+ test)                   C5-2
web/src/features/home/mergePending.ts (+ test), features/home/RecentActivity.tsx,
  features/home/Home.tsx, features/home/home.css (2a files)                          C5-3

web/package.json, package-lock.json, scan/qr.ts, scan/image.ts (+ tests)             C6-1
scan/ScanScreen.tsx, scan/useQrLookup.ts, scan/scan.css (+ ScanScreen.test.tsx)      C6-2
scan/ReviewBanner.tsx, ComposerForm.tsx (scan overlay, banner, Scan chip) (+ Scan.test.tsx, ScanRemember.test.tsx)   C6-3
```

---

## Stream C3: backend (starts now)

### Task C3-1: B1, `POST /api/v1/transactions/scan/qr`

**Stream:** C3 · **Depends on:** nothing · **Parallel with:** everything

**Files:**
- Modify: `app/routes/scan.py` (the `scan_qr` route, lines ~321–388)
- Modify: `app/api/transactions.py` (imports; new models after `_txn_dict`; new route placed **before** `@router.get("/{txn_id}")`)
- Create: `tests/test_api_composer.py`

**Interfaces:**
- Produces: `app.routes.scan.lookup_qr_receipt(db: Session, household_id: str, url: object) -> dict` (keys `amount, currency, date, merchant, category_hint, category_id`); API route `POST /api/v1/transactions/scan/qr`, body `QrScanIn {url: str}`, response `QrReceiptOut {amount: float | None, currency: str, date: str | None, merchant: str | None, category_hint: str | None, category_id: str | None}`. C6-2 consumes it through the generated type `components['schemas']['QrReceiptOut']`.
- Why the shared function stays in `app/routes/scan.py`: `tests/test_scan_qr_mydata.py` patches `scan._fetch_public_page`, `scan._resolve` and `app.routes.scan.httpx.AsyncClient` on that module. Keeping the helpers and the shared function there leaves every existing patch target valid. `app/api/transactions.py` imports it (no import cycle: `app.routes.scan` imports `app.routes.transactions`, which never imports `app.api`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_composer.py`:

```python
"""Phase 2b composer APIs: POST /api/v1/transactions/scan/qr (B1) and
GET /api/v1/transactions/check-duplicate (B2)."""

from datetime import timedelta
from unittest.mock import patch

import httpx
import pyotp
import pytest

from app.core.clock import local_today
from tests.conftest import PASSWORD
from tests.test_api import api  # noqa: F401  (fixture)

AADE_URL = "https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc"
AADE_HTML = """<table>
<tr><td>Επωνυμία</td><td>Test Taverna</td></tr>
<tr><td>Συνολική αξία</td><td>12,50</td></tr>
<tr><td>Ημερομηνία, ώρα</td><td>2026-03-04 12:30</td></tr>
</table>"""


class _FakeAsyncClient:
    def __init__(self, response=None, exc=None):
        self._response, self._exc = response, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        if self._exc:
            raise self._exc
        return self._response


def _patch_httpx(response=None, exc=None):
    return patch("app.routes.scan.httpx.AsyncClient", lambda **kw: _FakeAsyncClient(response, exc))


def _bearer(client, hh):
    """Bearer headers for a second household's owner (own TOTP secret, so no code reuse)."""
    r = client.post("/api/v1/auth/login", json={"username": hh.username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/auth/totp/verify",
        json={"pending_token": r.json()["pending_token"], "code": pyotp.TOTP(hh.secret).now()},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------- B1 /scan/qr


def test_api_scan_qr_reads_the_receipt_with_a_bearer_token(client, api):  # noqa: F811
    headers, _ = api
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        r = client.post("/api/v1/transactions/scan/qr", headers=headers, json={"url": AADE_URL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == 12.5 and body["currency"] == "EUR"
    assert body["date"] == "2026-03-04" and body["merchant"] == "Test Taverna"
    assert set(body) == {"amount", "currency", "date", "merchant", "category_hint", "category_id"}


def test_api_scan_qr_gives_the_same_payload_as_the_html_route(client, authed):
    # Same household and session for both: require_api_auth falls back to the cookie.
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        api_r = client.post(
            "/api/v1/transactions/scan/qr", headers=authed.headers, json={"url": AADE_URL}
        )
    with _patch_httpx(httpx.Response(200, text=AADE_HTML)):
        web_r = client.post("/transactions/scan/qr", headers=authed.headers, json={"url": AADE_URL})
    assert api_r.status_code == web_r.status_code == 200
    assert api_r.json() == web_r.json()


def test_api_scan_qr_needs_auth(client):
    r = client.post("/api/v1/transactions/scan/qr", json={"url": AADE_URL})
    assert r.status_code == 401


@pytest.mark.parametrize(
    "url",
    [
        "http://www1.aade.gr/tameiakes/myweb/q1.php?x=1",
        "https://10.0.0.1/tameiakes/myweb/q1.php",
        "https://www1.aade.gr:8080/tameiakes/myweb/q1.php",
        "x" * 501,
    ],
)
def test_api_scan_qr_refuses_disallowed_urls_without_fetching(client, api, url):  # noqa: F811
    headers, _ = api
    with patch("app.routes.scan.httpx.AsyncClient") as ac:
        r = client.post("/api/v1/transactions/scan/qr", headers=headers, json={"url": url})
    assert r.status_code == 400
    ac.assert_not_called()


def test_api_scan_qr_upstream_failure_is_a_502_with_the_message(client, api):  # noqa: F811
    headers, _ = api
    with _patch_httpx(exc=httpx.ConnectError("down")):
        r = client.post("/api/v1/transactions/scan/qr", headers=headers, json={"url": AADE_URL})
    assert r.status_code == 502
    assert r.json()["detail"] == "Could not reach AADE portal"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_composer.py -o addopts="" -p no:cacheprovider -q`
Expected: FAIL; the API calls return 404/405 (route not found) for every B1 test except `test_api_scan_qr_needs_auth` (which may also get 404 rather than 401).

- [ ] **Step 3: Extract the shared function in `app/routes/scan.py`**

Replace the whole `scan_qr` route (from `@router.post("/scan/qr", response_class=JSONResponse)` to the end of the file) with:

```python
async def lookup_qr_receipt(db: Session, household_id: str, url: object) -> dict:
    """
    Read a receipt from the URL in its QR code: the AADE cash-register lookup,
    AADE's myDATA page, or an e-invoicing provider's page that links to the
    myDATA page. Only AADE pages are parsed; provider pages are fetched through
    an SSRF-hardened client just to find the AADE link.

    Shared by the web route and ``POST /api/v1/transactions/scan/qr``; raises
    HTTPException 400/502/504 with the user-facing message.
    """
    if not isinstance(url, str) or len(url) > 500:
        raise HTTPException(status_code=400, detail="Invalid URL")

    try:
        parsed_url = urlparse(url.strip())
        port = parsed_url.port
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid URL") from None

    host = (parsed_url.hostname or "").lower()
    if (
        parsed_url.scheme != "https"
        or not host
        or parsed_url.username is not None
        or port not in (None, 443)
        or _is_ip_literal(host)
    ):
        raise HTTPException(status_code=400, detail="URL not allowed")
    url = parsed_url.geturl()

    if host == _AADE_HOST and parsed_url.path.startswith(_AADE_PATH_PREFIX):
        receipt = _parse_aade_html(await _fetch_aade(url, "AADE portal"))
    else:
        if not (host == settings.mydata_qr_host and parsed_url.path == settings.mydata_qr_path):
            page = await _fetch_public_page(url)
            link = _MYDATA_LINK_RE.search(html_lib.unescape(page))
            if not link:
                raise HTTPException(
                    status_code=400,
                    detail="This receipt page has no AADE link. Upload a photo instead.",
                )
            url = link.group(0)
        receipt = _parse_mydata_qr_html(await _fetch_aade(url, "AADE myDATA"))
        if receipt["amount"] is None:
            raise HTTPException(status_code=502, detail="Could not read the receipt from AADE")

    category_id = resolve_category(
        db,
        household_id,
        merchant=receipt["merchant"],
        hint=receipt["category_hint"],
    )
    db.commit()

    return {
        "amount": receipt["amount"],
        "currency": receipt["currency"],
        "date": receipt["date"],
        "merchant": receipt["merchant"],
        "category_hint": receipt["category_hint"],
        "category_id": category_id,
    }


@router.post("/scan/qr", response_class=JSONResponse)
async def scan_qr(
    request: Request,
    db: Session = Depends(get_db),
    auth=Depends(require_auth),
):
    """Web route for the QR lookup; see ``lookup_qr_receipt``."""
    user, hh_id = auth
    body = await request.json()
    return await lookup_qr_receipt(db, hh_id, body.get("url", ""))
```

- [ ] **Step 4: Add the API route in `app/api/transactions.py`**

Add to the imports:

```python
from pydantic import BaseModel

from app.routes.scan import lookup_qr_receipt
```

Add after `_txn_dict` (in the "Schemas" section):

```python
class QrScanIn(BaseModel):
    url: str = ""


class QrReceiptOut(BaseModel):
    amount: float | None
    currency: str
    date: str | None
    merchant: str | None
    category_hint: str | None
    category_id: str | None
```

Add this route immediately **after** `list_transactions` and **before** `create_transaction` (any position above `@router.get("/{txn_id}")` works; keep all fixed paths above the `{txn_id}` routes):

```python
@router.post("/scan/qr", response_model=QrReceiptOut)
async def scan_qr(
    body: QrScanIn,
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Read a receipt from the URL in its QR code (AADE lookup). Same rules,
    messages and result as the web route ``POST /transactions/scan/qr``."""
    user, hh_id = auth
    return await lookup_qr_receipt(db, hh_id, body.url)
```

- [ ] **Step 5: Run the new and the existing scan tests**

Run: `.venv/bin/python -m pytest tests/test_api_composer.py tests/test_scan_qr_mydata.py tests/test_route_coverage.py -k "scan or qr" -o addopts="" -p no:cacheprovider -q`
Expected: PASS (the existing HTML-route tests are unchanged and still pass).

- [ ] **Step 6: Lint and format**

Run: `.venv/bin/ruff check app/routes/scan.py app/api/transactions.py tests/test_api_composer.py && .venv/bin/ruff format app/routes/scan.py app/api/transactions.py tests/test_api_composer.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add app/routes/scan.py app/api/transactions.py tests/test_api_composer.py
git commit -m "feat(api): POST /api/v1/transactions/scan/qr through a shared AADE lookup"
```

### Task C3-2: B2, `GET /api/v1/transactions/check-duplicate`, then regenerate web types

**Stream:** C3 · **Depends on:** C3-1 (same file `app/api/transactions.py`)

**Files:**
- Modify: `app/services/duplicates.py` (add `duplicate_check`)
- Modify: `app/services/__init__.py` (export it next to `find_duplicate_candidates`, line ~40)
- Modify: `app/routes/transactions_search.py:458-500` (HTML `check_duplicate` calls the shared function)
- Modify: `app/api/transactions.py` (models and route, above `/{txn_id}`)
- Modify: `tests/test_api_composer.py` (append B2 tests)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/schema.d.ts`

**Interfaces:**
- Produces: `app.services.duplicate_check(db, household_id, *, amount: str, transaction_date: str, bucket_id: str = "", exclude_id: str = "") -> list[dict]`; API `GET /api/v1/transactions/check-duplicate?amount=&transaction_date=&bucket_id=&exclude_id=` → `DuplicateCheckOut {duplicates: DuplicateOut[]}` with `DuplicateOut {id, amount: float, currency, date, notes, merchant, bucket, paid_by, same_bucket: bool}` (at most 5). C2-6 consumes `components['schemas']['DuplicateCheckOut']`.
- Behaviour change on the HTML route (spec §6 B2 "Blank or invalid input returns an empty list"): a malformed amount such as `abc` now gives `{"duplicates": []}` instead of a 400, and each row gains `merchant`.

- [ ] **Step 1: Append the failing tests to `tests/test_api_composer.py`**

```python
# ---------------------------------------------------------------- B2 /check-duplicate


def _expense(client, headers, hh, amount="42.50", when=None, merchant="Taverna"):
    r = client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "amount": amount,
            "bucket_id": hh.bucket_id,
            "merchant": merchant,
            "transaction_date": (when or local_today()).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _check(client, headers, **params):
    return client.get("/api/v1/transactions/check-duplicate", headers=headers, params=params)


def test_check_duplicate_finds_a_same_amount_expense_within_three_days(client, api):  # noqa: F811
    headers, hh = api
    txn = _expense(client, headers, hh, when=local_today() - timedelta(days=3))
    r = _check(
        client,
        headers,
        amount="42.50",
        transaction_date=local_today().isoformat(),
        bucket_id=hh.bucket_id,
    )
    assert r.status_code == 200, r.text  # not a 404 from GET /{txn_id}
    [d] = r.json()["duplicates"]
    assert d["id"] == txn["id"] and d["amount"] == 42.5 and d["merchant"] == "Taverna"
    assert d["same_bucket"] is True and d["date"] == (local_today() - timedelta(days=3)).isoformat()
    assert set(d) == {
        "id", "amount", "currency", "date", "notes", "merchant", "bucket", "paid_by", "same_bucket",
    }


def test_check_duplicate_ignores_four_days_away_and_the_excluded_id(client, api):  # noqa: F811
    headers, hh = api
    _expense(client, headers, hh, when=local_today() - timedelta(days=4))
    near = _expense(client, headers, hh)
    today = local_today().isoformat()
    assert [d["id"] for d in _check(client, headers, amount="42.50", transaction_date=today).json()["duplicates"]] == [near["id"]]
    assert _check(client, headers, amount="42.50", transaction_date=today, exclude_id=near["id"]).json() == {"duplicates": []}


@pytest.mark.parametrize(
    "params",
    [
        {"amount": "", "transaction_date": ""},
        {"amount": "abc", "transaction_date": "2026-10-07"},
        {"amount": "10", "transaction_date": "nonsense"},
        {},
    ],
)
def test_check_duplicate_blank_or_invalid_input_is_an_empty_list(client, api, params):  # noqa: F811
    headers, _ = api
    r = _check(client, headers, **params)
    assert r.status_code == 200 and r.json() == {"duplicates": []}


def test_check_duplicate_is_household_scoped(client, api, make_household):  # noqa: F811
    headers, hh = api
    other = make_household(name="Other", username="other")
    _expense(client, _bearer(client, other), other)
    r = _check(client, headers, amount="42.50", transaction_date=local_today().isoformat())
    assert r.json() == {"duplicates": []}


def test_check_duplicate_needs_auth(client):
    r = client.get("/api/v1/transactions/check-duplicate", params={"amount": "1", "transaction_date": "2026-10-07"})
    assert r.status_code == 401


def test_html_check_duplicate_also_returns_empty_for_a_malformed_amount(client, authed):
    r = client.get("/transactions/check-duplicate?amount=abc&transaction_date=2026-10-07")
    assert r.status_code == 200 and r.json() == {"duplicates": []}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_api_composer.py -k check_duplicate -o addopts="" -p no:cacheprovider -q`
Expected: FAIL; the API calls return 404 ("Transaction not found", matched by `/{txn_id}`), and the HTML `abc` case returns 400.

- [ ] **Step 3: Add `duplicate_check` to `app/services/duplicates.py`**

Add the imports `from fastapi import HTTPException` and `from app.validators import parse_amount` at the top, then append:

```python
def duplicate_check(
    db: Session,
    household_id: str,
    *,
    amount: str,
    transaction_date: str,
    bucket_id: str = "",
    exclude_id: str = "",
) -> list[dict]:
    """The advisory "looks like one you already logged" check behind the
    add-expense form and the composer. Blank or malformed input gives no
    matches rather than an error: this check must never block a save."""
    try:
        value = parse_amount(amount, field="Amount", allow_blank=True)
        when = date.fromisoformat((transaction_date or "").strip())
    except (HTTPException, ValueError):
        return []
    if value is None:
        return []

    matches = find_duplicate_candidates(
        db,
        household_id,
        amount=value,
        transaction_date=when,
        bucket_id=bucket_id or None,
        exclude_id=exclude_id or None,
    )
    return [
        {
            "id": t.id,
            "amount": float(t.amount),
            "currency": t.currency,
            "date": t.transaction_date.isoformat(),
            "notes": t.notes,
            "merchant": t.merchant,
            "bucket": t.bucket.name if t.bucket else None,
            "paid_by": t.paid_by_user.display_name if t.paid_by_user else None,
            "same_bucket": bool(bucket_id) and t.bucket_id == bucket_id,
        }
        for t in matches
    ]
```

If `from app.validators import parse_amount` creates an import cycle (check with `.venv/bin/python -c "import app.main"`), import it inside the function body instead.

In `app/services/__init__.py`, add `duplicate_check` to the import from `.duplicates` and to `__all__` if the module defines one.

- [ ] **Step 4: Make the HTML route use it**

In `app/routes/transactions_search.py`, replace the body of `check_duplicate` (after the docstring) with:

```python
    user, hh_id = auth
    return {
        "duplicates": duplicate_check(
            db,
            hh_id,
            amount=amount,
            transaction_date=transaction_date,
            bucket_id=bucket_id,
            exclude_id=exclude_id,
        )
    }
```

Add `duplicate_check` to that file's `from app.services import (...)`, and remove imports that ruff now reports unused (`find_duplicate_candidates`, possibly `parse_amount`, `date`).

- [ ] **Step 5: Add the API route in `app/api/transactions.py`**

Add `from app.services import duplicate_check` to the imports, these models next to `QrReceiptOut`:

```python
class DuplicateOut(BaseModel):
    id: str
    amount: float
    currency: str
    date: str
    notes: str | None
    merchant: str | None
    bucket: str | None
    paid_by: str | None
    same_bucket: bool


class DuplicateCheckOut(BaseModel):
    duplicates: list[DuplicateOut]
```

and this route directly below the `scan_qr` route from C3-1 (still above `@router.get("/{txn_id}")`):

```python
@router.get("/check-duplicate", response_model=DuplicateCheckOut)
def check_duplicate(
    amount: str = Query(default=""),
    transaction_date: str = Query(default=""),
    bucket_id: str = Query(default=""),
    exclude_id: str = Query(default=""),
    auth=Depends(require_api_auth),
    db: Session = Depends(get_db),
):
    """Expenses that look like the one being entered (same amount ±0.01,
    within 3 days), at most 5. Advisory only: never blocks a save."""
    user, hh_id = auth
    return {
        "duplicates": duplicate_check(
            db,
            hh_id,
            amount=amount,
            transaction_date=transaction_date,
            bucket_id=bucket_id,
            exclude_id=exclude_id,
        )
    }
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_api_composer.py tests/test_duplicates.py tests/test_income_no_bucket.py tests/test_transactions.py tests/test_api.py -k "duplicate or client_id or scan" -o addopts="" -p no:cacheprovider -q`
Expected: PASS. `tests/test_api.py::test_api_client_id_is_idempotent` (201 then 200, same id) is the spec §9 regression pin for `client_id`; it already exists and must stay green.

- [ ] **Step 7: Lint, format, regenerate the web types**

Run: `.venv/bin/ruff check app tests/test_api_composer.py && .venv/bin/ruff format app/services/duplicates.py app/routes/transactions_search.py app/api/transactions.py tests/test_api_composer.py`
Run: `cd web && npm run gen:api && grep -n "check-duplicate\|scan/qr\|QrReceiptOut\|DuplicateCheckOut" src/api/schema.d.ts | head`
Expected: both paths and both schemas appear in `schema.d.ts`.

- [ ] **Step 8: Commit**

```bash
git add app/services/duplicates.py app/services/__init__.py app/routes/transactions_search.py app/api/transactions.py tests/test_api_composer.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(api): GET /api/v1/transactions/check-duplicate through a shared duplicate_check; regenerate web types"
```

---

## Stream C1: kit additions and the 2a contract (after 2a stream A merges)

### Task C1-1: Composer fields in 2a's shared reads, multipart in the fake API, the bridge

**Stream:** C1 · **Depends on:** 2a stream A merged (A1–A8)

**Files:**
- Modify: `web/src/data/types.ts` (2a A1; additive: `Bucket` and `Category` fields)
- Modify: `web/src/data/reads.ts` (2a A8; additive: `toBuckets`, `toCategories` carry the new fields)
- Modify: `web/src/test/fixtures.ts` (2a A4; `bucket()` and `category()` defaults for the new fields)
- Modify: `web/src/test/fakeApi.ts` (2a A4; keep a `FormData` request body as the `FormData`)
- Create: `web/src/features/composer/bridge.tsx`, `web/src/features/composer/testHelpers.ts`
- Test: `web/src/data/reads.composer.test.ts`, `web/src/test/fakeApi.formdata.test.ts`, `web/src/features/composer/bridge.test.tsx`

**Interfaces:**
- Consumes: the 2a contract table in Global Constraints.
- Produces:
  - `Bucket` gains `start_date: string | null; end_date: string | null; show_income: boolean`; `Category` gains `system_key: string | null` (the composer lists event ranges, income budgets and the Fuel category).
  - `bridge.tsx` re-exports `useAction`, `ActionResult`, `ActionSpec`, `useCachedQuery`, `CachedQuery`, `unwrap`, `ApiError`, `keys`, `useOnline`, `useHousehold`, `useBuckets`, `useCategories`, `toTransactionPage`, the types `Bucket`, `Category`, `Household`, `Member`, `TransactionPage`, `TransactionRow`, `Sheet`, `Segmented`, `Badge`, `toast`, `Toaster`, `CheckIcon`, `ChevronDownIcon`, `ClockIcon`, `XIcon`; and adds `interface ToastInput { text: string; action?: { label: string; onPress: () => void }; durationMs?: number }`, `useComposerToast(): (t: ToastInput) => void`, `ToastHost({ children? })`, `afterTxnWrite: readonly QueryKey[]`, `editKey(id)`, `merchantsKey`.
  - `testHelpers.ts`: `loose(routes: Record<string, unknown>): Routes` (plain values become handlers; concrete paths such as `"GET /api/v1/transactions/t9"` are matched literally), `writes(api: FakeApi): FakeCall[]` (non-GET calls, `/auth/me` excluded), `goOffline(): void` (`setOnline(false)` and every fetch rejects).

- [ ] **Step 1: Write the failing tests**

`web/src/data/reads.composer.test.ts`:

```ts
import { expect, it } from 'vitest'
import { toBuckets, toCategories } from './reads'

it('buckets keep the date range and the income flag the composer needs', () => {
  const [crete] = toBuckets([
    { id: 'b1', name: 'Crete', kind: 'event', status: 'active', budget: null, start_date: '2026-08-12', end_date: '2026-08-19', show_income: true },
  ])
  expect(crete).toMatchObject({ start_date: '2026-08-12', end_date: '2026-08-19', show_income: true })
  expect(toBuckets([{ id: 'b2', name: 'Day to day' }])[0]).toMatchObject({ start_date: null, end_date: null, show_income: false })
})

it('categories keep system_key (the Fuel category asks for litres)', () => {
  expect(toCategories([{ id: 'c1', name: 'Fuel', system_key: 'fuel' }, { id: 'c2', name: 'Coffee' }]).map((c) => c.system_key)).toEqual(['fuel', null])
})
```

`web/src/test/fakeApi.formdata.test.ts`:

```ts
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from './fakeApi'
import { resetTestEnv } from './render'

afterEach(resetTestEnv)

it('keeps a multipart body as the FormData itself', async () => {
  const api = fakeApi({ 'POST /api/v1/transactions/{txn_id}/receipt': () => ({ receipt_path: 'x.jpg' }) })
  const form = new FormData()
  form.append('file', new File(['img'], 'r.jpg', { type: 'image/jpeg' }))
  const res = await fetch('/api/v1/transactions/t1/receipt', { method: 'POST', body: form })
  expect(res.ok).toBe(true)
  expect((api.calls[0].body as FormData).get('file')).toBeInstanceOf(File)
})
```

`web/src/features/composer/bridge.test.tsx`:

```tsx
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { afterTxnWrite, editKey, keys, merchantsKey, ToastHost, useComposerToast } from './bridge'

afterEach(resetTestEnv)

it("useComposerToast shows the text and its action through 2a's toast", () => {
  const onPress = vi.fn()
  render(<ToastHost />)
  const { result } = renderHook(() => useComposerToast())
  act(() => result.current({ text: 'Saved €3.00 to Day to day', action: { label: 'Undo', onPress } }))
  expect(screen.getByText('Saved €3.00 to Day to day')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  expect(onPress).toHaveBeenCalled()
})

it('a transaction write makes transactions, matches, plan, home, buckets and insights stale; 2b keys sit under transactions', () => {
  expect(afterTxnWrite).toEqual([keys.transactions.all, keys.matches(), keys.plan.all, keys.home.all, keys.buckets(), keys.insights.all])
  expect(editKey('t9').slice(0, keys.transactions.all.length)).toEqual([...keys.transactions.all])
  expect(merchantsKey.slice(0, keys.transactions.all.length)).toEqual([...keys.transactions.all])
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npm test -- src/data/reads.composer.test.ts src/test/fakeApi.formdata.test.ts src/features/composer/bridge.test.tsx`
Expected: FAIL: `start_date` is undefined, `JSON.parse` throws on the multipart body (or the body is not a `FormData`), and `./bridge` does not resolve.

- [ ] **Step 3: Extend 2a's types, reads and fixtures (additive)**

In `web/src/data/types.ts`:

```ts
export interface Bucket {
  id: string
  name: string
  kind: string
  status: string
  budget: number | null
  /** Event buckets: shown as "12–19 Aug" in the composer's budget picker. */
  start_date: string | null
  end_date: string | null
  /** Income may be filed under this budget (composer income picker). */
  show_income: boolean
}
export interface Category { id: string; name: string; icon: string | null; color: string | null; system_key: string | null }
```

In `web/src/data/reads.ts`, `toBuckets` returns `{ ..., budget: numOrNull(d.budget), start_date: strOrNull(d.start_date), end_date: strOrNull(d.end_date), show_income: d.show_income === true }` and `toCategories` returns `{ ..., color: strOrNull(d.color), system_key: strOrNull(d.system_key) }`.

In `web/src/test/fixtures.ts`, `bucket()` defaults gain `start_date: null, end_date: null, show_income: false` and `category()` gains `system_key: null`.

- [ ] **Step 4: Keep multipart bodies in `web/src/test/fakeApi.ts`**

Inside the `mockImplementation`, replace the first three lines (`const req = …`, `const url = …`, `const text = …`) and the `body:` line of `call` with:

```ts
    // A FormData body (receipt upload) stays a FormData: jsdom's FormData cannot go through a Node Request.
    const raw = input instanceof Request ? undefined : init?.body
    const multipart = raw instanceof FormData
    const req = input instanceof Request
      ? input
      : new Request(new URL(String(input), globalThis.location.origin), multipart ? { ...init, body: undefined } : init)
    const url = new URL(req.url)
    const text = multipart || req.method === 'GET' || req.method === 'HEAD' ? '' : await req.clone().text()
```

```ts
      body: multipart ? raw : text ? (JSON.parse(text) as unknown) : undefined,
```

- [ ] **Step 5: Write `bridge.tsx` and `testHelpers.ts`**

`web/src/features/composer/bridge.tsx`:

```tsx
/**
 * The composer's import point for 2a's data layer and kit (2a plan, "Stream A exports"), plus the few
 * helpers 2b adds. Composer files import 2a through here.
 */
import type { QueryKey } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { keys } from '../../data/keys'
import { toast, Toaster } from '../../ui/Toast'

export { type ActionResult, type ActionSpec, useAction } from '../../data/action'
export { type CachedQuery, useCachedQuery } from '../../data/cachedQuery'
export { ApiError, unwrap } from '../../data/http'
export { keys } from '../../data/keys'
export { useOnline } from '../../data/online'
export { toTransactionPage, useBuckets, useCategories, useHousehold } from '../../data/reads'
export type { Bucket, Category, Household, Member, TransactionPage, TransactionRow } from '../../data/types'
export { Badge } from '../../ui/Badge'
export { CheckIcon, ChevronDownIcon, ClockIcon, XIcon } from '../../ui/icons'
export { Segmented } from '../../ui/Segmented'
export { Sheet } from '../../ui/Sheet'
export { toast, Toaster }

export interface ToastInput { text: string; action?: { label: string; onPress: () => void }; durationMs?: number }

const showToast = (t: ToastInput) =>
  toast(t.text, { action: t.action && { label: t.action.label, onClick: t.action.onPress }, durationMs: t.durationMs })

/** 2b's toast shape over 2a's module-level toast(); safe to call after the composer has unmounted. */
export function useComposerToast(): (t: ToastInput) => void {
  return showToast
}

/** A tree plus the toast region (tests, and the full-screen shell). */
export function ToastHost({ children }: { children?: ReactNode }) {
  return (
    <>
      {children}
      <Toaster />
    </>
  )
}

/** Every key a transaction create, edit or delete makes stale (2b spec §5.3). */
export const afterTxnWrite: readonly QueryKey[] = [
  keys.transactions.all, keys.matches(), keys.plan.all, keys.home.all, keys.buckets(), keys.insights.all,
]

/**
 * The full transaction for edit and copy (`null` = the server said 404). Its own key, not
 * `keys.transactions.one(id)`, because that one holds 2c's shape and throws on 404; still under
 * `transactions.all`, so every transaction write refreshes it.
 */
export const editKey = (id: string) => [...keys.transactions.all, 'edit', id] as const

/** Up to 200 recent transactions, for merchant suggestions only. */
export const merchantsKey = [...keys.transactions.all, 'merchants'] as const
```

`web/src/features/composer/testHelpers.ts`:

```ts
import { vi } from 'vitest'
import type { FakeApi, FakeCall, Routes } from '../../test/fakeApi'
import { setOnline } from '../../test/render'

/**
 * Composer tests describe routes as plain values or handlers. Plain values become handlers; concrete
 * paths ("GET /api/v1/transactions/t9") match literally; paths not yet in the schema (2d's rules) are fine.
 */
export function loose(routes: Record<string, unknown>): Routes {
  return Object.fromEntries(Object.entries(routes).map(([k, v]) => [k, typeof v === 'function' ? v : () => v])) as Routes
}

/** The writes a test made, in order. */
export const writes = (api: FakeApi): FakeCall[] =>
  api.calls.filter((c) => c.method !== 'GET' && c.path !== '/api/v1/auth/me')

/** No connection: navigator.onLine false and every request fails at the network level. */
export function goOffline(): void {
  setOnline(false)
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
}
```

- [ ] **Step 6: Run the tests, 2a's suites that use the touched files, and the type check**

Run: `cd web && npm test -- src/data/reads.composer.test.ts src/test/fakeApi.formdata.test.ts src/features/composer/bridge.test.tsx src/data/reads.test.tsx src/test/fakeApi.test.ts && npm run typecheck`
Expected: PASS. If typecheck flags a 2a test that builds a `Bucket` or `Category` literal by hand, add the new fields there with the fixture defaults.

- [ ] **Step 7: Commit**

```bash
git add web/src/data/types.ts web/src/data/reads.ts web/src/test/fixtures.ts web/src/test/fakeApi.ts web/src/data/reads.composer.test.ts web/src/test/fakeApi.formdata.test.ts web/src/features/composer/bridge.tsx web/src/features/composer/bridge.test.tsx web/src/features/composer/testHelpers.ts
git commit -m "feat(web): composer fields in shared reads, multipart in the fake API, composer bridge"
```

### Task C1-2: `Keypad` and `AmountDisplay`

**Stream:** C1 · **Depends on:** C1-1 (merged 2a kit CSS present)

**Files:**
- Create: `web/src/ui/Keypad.tsx`, `web/src/ui/AmountDisplay.tsx`, `web/src/ui/composer-icons.tsx`, `web/src/ui/composer-kit.css`
- Test: `web/src/ui/Keypad.test.tsx`, `web/src/ui/AmountDisplay.test.tsx`

**Interfaces:**
- Produces: `type KeypadKey = '0'|'1'|'2'|'3'|'4'|'5'|'6'|'7'|'8'|'9'|'.'|'back'|'clear'`; `Keypad({ onKey(k: KeypadKey): void; hidden?: boolean })`; `AmountDisplay({ text, symbol, currency, spoken, tone?: 'default'|'income', converted?: string|null, onCurrency?: () => void, tag?: string|null })`; `BackspaceIcon` from `ui/composer-icons.tsx`. No data access in `ui/`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Open `docs/redesign/mocks/composer.html` screen 1 and `components.css` (`.keypad`, `.amt-entry`, `.big`, `.caret`, `.cur`).

- [ ] **Step 2: Write the failing tests**

`web/src/ui/Keypad.test.tsx`:

```tsx
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Keypad } from './Keypad'

afterEach(() => { cleanup(); vi.useRealTimers() })

it('has 12 named keys and reports taps', () => {
  const onKey = vi.fn()
  render(<Keypad onKey={onKey} />)
  expect(screen.getAllByRole('button')).toHaveLength(12)
  fireEvent.click(screen.getByRole('button', { name: '3' }))
  fireEvent.click(screen.getByRole('button', { name: 'Decimal point' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete last digit' }))
  expect(onKey.mock.calls.map((c) => c[0])).toEqual(['3', '.', 'back'])
})

it('a long press on backspace clears once and does not also delete', () => {
  vi.useFakeTimers()
  const onKey = vi.fn()
  render(<Keypad onKey={onKey} />)
  const back = screen.getByRole('button', { name: 'Delete last digit' })
  fireEvent.pointerDown(back)
  act(() => { vi.advanceTimersByTime(500) })
  fireEvent.pointerUp(back)
  fireEvent.click(back)
  expect(onKey.mock.calls.map((c) => c[0])).toEqual(['clear'])
})

it('hidden removes it from the accessibility tree', () => {
  render(<Keypad onKey={() => {}} hidden />)
  expect(screen.queryByRole('button', { name: '3' })).not.toBeInTheDocument()
})
```

`web/src/ui/AmountDisplay.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AmountDisplay } from './AmountDisplay'

afterEach(cleanup)

it('announces the spoken amount and opens the currency sheet', () => {
  const onCurrency = vi.fn()
  render(<AmountDisplay text="4.10" symbol="€" currency="EUR" spoken="Amount 4.10 euro" onCurrency={onCurrency} />)
  expect(screen.getByRole('status')).toHaveTextContent('Amount 4.10 euro')
  fireEvent.click(screen.getByRole('button', { name: 'Currency: EUR. Change' }))
  expect(onCurrency).toHaveBeenCalled()
})

it('shrinks above 9 characters, shows the converted line and the tag', () => {
  const { container } = render(
    <AmountDisplay text="1,234,567.8" symbol="£" currency="GBP" spoken="x" converted="≈ €23.06" tag="from receipt" />,
  )
  expect(container.querySelector('.amount__big--small')).not.toBeNull()
  expect(screen.getByText('≈ €23.06')).toBeInTheDocument()
  expect(screen.getByText('from receipt')).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('income tone', () => {
  const { container } = render(<AmountDisplay text="700" symbol="€" currency="EUR" spoken="x" tone="income" />)
  expect(container.querySelector('.amount--income')).not.toBeNull()
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd web && npm test -- src/ui/Keypad.test.tsx src/ui/AmountDisplay.test.tsx`
Expected: FAIL with "Failed to resolve import ./Keypad".

- [ ] **Step 4: Implement**

`web/src/ui/composer-icons.tsx`: one inline SVG component, `BackspaceIcon` (lucide `delete`: 24×24 viewBox, `stroke="currentColor"`, `strokeWidth={2}`, `fill="none"`, `aria-hidden="true"`), drawn the same way as 2a's `ui/icons.tsx`, which has no backspace. Chevron and check come from 2a's `ui/icons.tsx`.

`web/src/ui/Keypad.tsx`:

```tsx
import { useRef } from 'react'
import { BackspaceIcon } from './composer-icons'
import './composer-kit.css'

export type KeypadKey = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back' | 'clear'

const LAYOUT: KeypadKey[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'back']
const NAMES: Partial<Record<KeypadKey, string>> = { '.': 'Decimal point', back: 'Delete last digit' }
const LONG_PRESS_MS = 500

/** The composer keypad: 12 keys in 48 px rows; a long press on backspace clears the amount. */
export function Keypad({ onKey, hidden = false }: { onKey: (k: KeypadKey) => void; hidden?: boolean }) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const cleared = useRef(false)
  const down = () => {
    cleared.current = false
    timer.current = setTimeout(() => {
      cleared.current = true
      onKey('clear')
    }, LONG_PRESS_MS)
  }
  const up = () => clearTimeout(timer.current)
  return (
    <div className="keypad keypad--tight" role="group" aria-label="Amount keypad" hidden={hidden}>
      {LAYOUT.map((k) => (
        <button
          key={k}
          type="button"
          className="keypad__key"
          aria-label={NAMES[k] ?? k}
          onPointerDown={k === 'back' ? down : undefined}
          onPointerUp={k === 'back' ? up : undefined}
          onPointerLeave={k === 'back' ? up : undefined}
          onClick={() => {
            if (k === 'back' && cleared.current) {
              cleared.current = false
              return
            }
            onKey(k)
          }}
        >
          {k === 'back' ? <BackspaceIcon /> : k}
        </button>
      ))}
    </div>
  )
}
```

`web/src/ui/AmountDisplay.tsx`:

```tsx
import { ChevronDownIcon } from './icons'
import './composer-kit.css'

export interface AmountDisplayProps {
  /** The typed amount formatted for display, e.g. "1,234.5"; "0" when empty. */
  text: string
  symbol: string
  currency: string
  /** Read by screen readers, e.g. "Amount 4.10 euro". */
  spoken: string
  tone?: 'default' | 'income'
  /** "≈ €23.06" when the currency is not the household's. */
  converted?: string | null
  /** Absent: the currency is shown but not changeable. */
  onCurrency?: () => void
  /** "from receipt" after a QR scan, until the amount is edited. */
  tag?: string | null
}

export function AmountDisplay(p: AmountDisplayProps) {
  return (
    <div className={p.tone === 'income' ? 'amount amount--income' : 'amount'}>
      <div role="status" className="ck-visually-hidden">{p.spoken}</div>
      <div className={p.text.length > 9 ? 'amount__big amount__big--small' : 'amount__big'} aria-hidden="true">
        <span className="amount__symbol">{p.symbol}</span>
        {p.text}
        <span className="amount__caret" />
      </div>
      {p.onCurrency ? (
        <button type="button" className="amount__cur" onClick={p.onCurrency} aria-label={`Currency: ${p.currency}. Change`}>
          {p.currency}
          <ChevronDownIcon />
        </button>
      ) : (
        <span className="amount__cur">{p.currency}</span>
      )}
      {p.converted && <p className="amount__converted">{p.converted}</p>}
      {p.tag && <span className="amount__tag">{p.tag}</span>}
    </div>
  )
}
```

`web/src/ui/composer-kit.css` (tokens only; mock values):
- `.ck-visually-hidden`: the standard 1 px clip pattern.
- `.keypad--tight`: `display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px;` `.keypad[hidden] { display: none }`; `.keypad__key`: `min-height: 48px; border: 0; border-radius: var(--r-md); background: transparent; color: var(--ink); font: var(--display-weight) 24px/1 var(--font-display); font-variant-numeric: tabular-nums; touch-action: manipulation; -webkit-tap-highlight-color: transparent; user-select: none; -webkit-user-select: none;` `:active` background `var(--surface-2)`; svg 24 px.
- `.amount`: centred column, `gap: 6px`. `.amount__big`: `font-family: var(--font-display); font-weight: var(--display-weight); font-size: 62px; line-height: 1; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; color: var(--ink)`; `.amount__big--small`: `font-size: 44px`. `.amount__symbol`: `color: var(--muted); margin-right: 2px`.
- `.amount__caret`: `display: inline-block; width: 3px; height: .8em; margin-left: 4px; vertical-align: -0.05em; border-radius: 2px; background: var(--accent); animation: ck-blink 1s steps(1) infinite`; `.amount--income .amount__caret { background: var(--pos) }`; `@keyframes ck-blink { 50% { opacity: 0 } }`; `@media (prefers-reduced-motion: reduce) { .amount__caret { animation: none } }`.
- `.amount__cur`: chip, `min-height: 32px; padding: 0 12px; border-radius: var(--r-pill); background: var(--surface-2); color: var(--ink-2); font: 600 13px var(--font-body)`; as a button it gets a 44 px hit area via `::after { inset: -6px }`.
- `.amount__converted`: `margin: 0; color: var(--muted); font: 500 14px var(--font-num); font-variant-numeric: tabular-nums`.
- `.amount__tag`: small `var(--accent-soft)`/`var(--accent)` tag, 12 px.

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/ui/Keypad.test.tsx src/ui/AmountDisplay.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/ui/Keypad.tsx web/src/ui/AmountDisplay.tsx web/src/ui/composer-icons.tsx web/src/ui/composer-kit.css web/src/ui/Keypad.test.tsx web/src/ui/AmountDisplay.test.tsx
git commit -m "feat(ui): Keypad and AmountDisplay"
```

### Task C1-3: `Pill` and `ToggleRow`

**Stream:** C1 · **Depends on:** C1-2 (`composer-kit.css`)

**Files:**
- Create: `web/src/ui/Pill.tsx`, `web/src/ui/ToggleRow.tsx`
- Modify: `web/src/ui/composer-kit.css` (append)
- Test: `web/src/ui/Pill.test.tsx`, `web/src/ui/ToggleRow.test.tsx`

**Interfaces:**
- Produces: `Pill({ label: string; value: string; empty?: boolean; icon?: ReactNode; tag?: string | null; readOnly?: boolean; onPress?: () => void })` with accessible name `"<label>: <value>. Change"`, `"<label>: <value>, <tag>. Change"` when tagged, `"<label>: <value>"` when read-only; `ToggleRow({ label: string; hint?: string; checked: boolean; onChange(v: boolean): void; disabled?: boolean })`, a `role="switch"` button named by `label`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.**

- [ ] **Step 2: Write the failing tests**

`web/src/ui/Pill.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Pill } from './Pill'

afterEach(cleanup)

it('names itself "Label: value. Change" and reports a press', () => {
  const onPress = vi.fn()
  render(<Pill label="Budget" value="Day to day" onPress={onPress} />)
  fireEvent.click(screen.getByRole('button', { name: 'Budget: Day to day. Change' }))
  expect(onPress).toHaveBeenCalled()
})

it('empty is dashed, a tag is part of the name, read-only is not a button', () => {
  const { container, rerender } = render(<Pill label="Budget" value="Choose a budget" empty onPress={() => {}} />)
  expect(container.querySelector('.pill--empty')).not.toBeNull()
  rerender(<Pill label="Category" value="Coffee" tag="rule: coffee island" onPress={() => {}} />)
  expect(screen.getByRole('button', { name: 'Category: Coffee, rule: coffee island. Change' })).toBeInTheDocument()
  rerender(<Pill label="Payer" value="You" readOnly />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.getByText('You')).toBeInTheDocument()
})
```

`web/src/ui/ToggleRow.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ToggleRow } from './ToggleRow'

afterEach(cleanup)

it('is a switch named by its label and flips', () => {
  const onChange = vi.fn()
  render(<ToggleRow label="Count in forecast" hint="Turn off for one-offs" checked onChange={onChange} />)
  const sw = screen.getByRole('switch', { name: 'Count in forecast' })
  expect(sw).toHaveAttribute('aria-checked', 'true')
  expect(screen.getByText('Turn off for one-offs')).toBeInTheDocument()
  fireEvent.click(sw)
  expect(onChange).toHaveBeenCalledWith(false)
})

it('disabled does not flip', () => {
  const onChange = vi.fn()
  render(<ToggleRow label="Split" checked={false} onChange={onChange} disabled />)
  fireEvent.click(screen.getByRole('switch', { name: 'Split' }))
  expect(onChange).not.toHaveBeenCalled()
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd web && npm test -- src/ui/Pill.test.tsx src/ui/ToggleRow.test.tsx`
Expected: FAIL with "Failed to resolve import ./Pill".

- [ ] **Step 4: Implement**

`web/src/ui/Pill.tsx`:

```tsx
import type { ReactNode } from 'react'
import { ChevronDownIcon } from './icons'
import './composer-kit.css'

export interface PillProps {
  label: string
  value: string
  /** Nothing chosen yet: dashed outline (e.g. "Choose a budget"). */
  empty?: boolean
  icon?: ReactNode
  /** "rule: coffee island", "from receipt". */
  tag?: string | null
  /** Shown, not changeable (Fixed cost budget, payer locked to you). */
  readOnly?: boolean
  onPress?: () => void
}

export function Pill({ label, value, empty, icon, tag, readOnly, onPress }: PillProps) {
  const cls = ['pill', 'ck-pill', empty ? 'pill--empty' : '', readOnly ? 'pill--static' : ''].filter(Boolean).join(' ')
  const body = (
    <>
      {icon && <span className="ck-pill__icon" aria-hidden="true">{icon}</span>}
      <span className="ck-pill__text">
        <span className="ck-pill__label">{label}</span>
        <span className="ck-pill__value">{value}</span>
        {tag && <span className="ck-pill__tag">{tag}</span>}
      </span>
    </>
  )
  if (readOnly || !onPress) {
    return <span className={cls} aria-label={`${label}: ${value}`}>{body}</span>
  }
  return (
    <button type="button" className={cls} onClick={onPress} aria-label={`${label}: ${value}${tag ? `, ${tag}` : ''}. Change`}>
      {body}
      <ChevronDownIcon />
    </button>
  )
}
```

`web/src/ui/ToggleRow.tsx`:

```tsx
import { useId } from 'react'
import './composer-kit.css'

export interface ToggleRowProps {
  label: string
  hint?: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}

export function ToggleRow({ label, hint, checked, onChange, disabled }: ToggleRowProps) {
  const hintId = useId()
  return (
    <div className="ck-toggle-row">
      <span className="ck-toggle-row__text">
        <span className="ck-toggle-row__label">{label}</span>
        {hint && <span id={hintId} className="ck-toggle-row__hint">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        aria-describedby={hint ? hintId : undefined}
        disabled={disabled}
        className={checked ? 'toggle on' : 'toggle'}
        onClick={() => onChange(!checked)}
      />
    </div>
  )
}
```

Append to `composer-kit.css`:
- `.ck-pill`: `display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 6px 12px 6px 6px; border-radius: var(--r-pill); border: 1px solid var(--line); background: var(--surface); color: var(--ink); font: 600 14px var(--font-body); max-width: 100%;` `.ck-pill__label` is visually hidden (`ck-visually-hidden` rules) since the pill row reads as values, the aria-label carries the label; `.ck-pill__value` ellipsises; `.ck-pill__tag`: 11 px `var(--accent)`; `.pill--empty`: `border-style: dashed; color: var(--muted); background: transparent`; `.pill--static` has no chevron and `cursor: default`; `.ck-pill__icon`: 26 px circle `var(--surface-2)`.
- `.ck-toggle-row`: flex row, `min-height: 56px; gap: 12px; justify-content: space-between`; label 15 px `var(--ink)`, hint 13 px `var(--muted)`; `.toggle` comes from 2a's `ui.css` (mock `.toggle`/`.toggle.on`); add `.ck-toggle-row .toggle { min-width: 46px }` and a 44 px hit area with `::before { inset: -8px }`; `.toggle:disabled { opacity: .5 }`.

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/ui/Pill.test.tsx src/ui/ToggleRow.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/ui/Pill.tsx web/src/ui/ToggleRow.tsx web/src/ui/composer-kit.css web/src/ui/Pill.test.tsx web/src/ui/ToggleRow.test.tsx
git commit -m "feat(ui): Pill and ToggleRow"
```

---

## Stream C2: core composer

C2-1 is pure TypeScript with no imports from 2a: it can start now, in the C2 worktree. C2-2 to C2-4 are pure too, but their types come from 2a's `data/types.ts` (through the bridge), so they start once C1-1 is in.

### Task C2-1: `amount.ts`, `dates.ts`, `currencies.ts`

**Stream:** C2 · **Depends on:** nothing

**Files:**
- Create: `web/src/features/composer/amount.ts`, `web/src/features/composer/dates.ts`, `web/src/features/composer/currencies.ts`
- Test: `web/src/features/composer/amount.test.ts`, `web/src/features/composer/dates.test.ts`

**Interfaces:**
- Produces:
  - `amount.ts`: `type AmountKey` (same union as `KeypadKey`), `MAX_INT_DIGITS = 7`, `MAX_DECIMALS = 2`, `pressKey(v: string, k: AmountKey): string`, `toCents(v: string): number`, `centsToString(c: number): string`, `toApiAmount(v: string): string`, `fromApiAmount(n: number | string): string`, `displayAmount(v: string): string`, `parseScaled(s: string, decimals: number): bigint | null`, `parseRate(s: string): bigint | null` (micro-units), `convertCents(cents: number, rateMicros: bigint): number`, `parseFuelPrice(s: string): bigint | null` (thousandths), `litresMilli(cents: number, priceMilli: bigint): bigint`, `formatLitres(milli: bigint): string`.
  - `dates.ts`: `todayLocal(now?: Date): string`, `addDays(iso: string, n: number): string`, `dayLabel(iso: string, today: string): string` ("Today", "Yesterday", "Mon 5 Oct"), `shortDate(iso: string): string` ("7 Oct"), `rangeLabel(start: string | null, end: string | null): string` ("12–19 Aug", "30 Sep – 2 Oct").
  - `currencies.ts`: `CURRENCIES` (the 10 codes), `currencySymbol(code)`, `currencyName(code)` ("euro"), `formatCents(cents: number, currency: string): string` ("€4.10"), `spokenMoney(cents: number, currency: string): string` ("4 euro 10").

- [ ] **Step 1: Write the failing tests**

`web/src/features/composer/amount.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  centsToString, convertCents, displayAmount, formatLitres, fromApiAmount, litresMilli, parseFuelPrice,
  parseRate, pressKey, toApiAmount, toCents, type AmountKey,
} from './amount'

const type = (keys: AmountKey[], from = '') => keys.reduce(pressKey, from)

describe('pressKey', () => {
  it('builds an amount and caps decimals at 2', () => {
    expect(type(['4', '.', '1', '0', '9'])).toBe('4.10')
  })
  it('one decimal point; "." first gives "0."', () => {
    expect(type(['.'])).toBe('0.')
    expect(type(['1', '.', '.', '5'])).toBe('1.5')
  })
  it('no leading zeros: "007" shows "7", "0" stays "0"', () => {
    expect(type(['0', '0', '7'])).toBe('7')
    expect(type(['0', '0'])).toBe('0')
    expect(type(['0', '.', '5'])).toBe('0.5')
  })
  it('at most 7 integer digits', () => {
    expect(type(['1', '2', '3', '4', '5', '6', '7', '8'])).toBe('1234567')
    expect(type(['9', '9', '9', '9', '9', '9', '9', '.', '9', '9'])).toBe('9999999.99')
  })
  it('backspace and clear', () => {
    expect(type(['4', '.', '1', 'back'])).toBe('4.')
    expect(type(['.', 'back'])).toBe('0')
    expect(type(['back'])).toBe('')
    expect(type(['1', '2', 'clear'])).toBe('')
  })
})

describe('cents', () => {
  it('parses keypad and API strings without floats', () => {
    expect(toCents('4.1')).toBe(410)
    expect(toCents('0.')).toBe(0)
    expect(toCents('')).toBe(0)
    expect(toCents('.')).toBe(0)
    expect(toCents('9999999.99')).toBe(999999999)
    expect(toCents('abc')).toBe(0)
  })
  it('formats for the API', () => {
    expect(centsToString(410)).toBe('4.10')
    expect(centsToString(-5)).toBe('-0.05')
    expect(toApiAmount('3')).toBe('3.00')
  })
  it('reads server numbers back into keypad strings', () => {
    expect(fromApiAmount(4.1)).toBe('4.10')
    expect(fromApiAmount(3)).toBe('3')
    expect(fromApiAmount('64.20')).toBe('64.20')
    expect(fromApiAmount(0.29)).toBe('0.29')
  })
  it('groups the integer part for display', () => {
    expect(displayAmount('')).toBe('0')
    expect(displayAmount('1234567.5')).toBe('1,234,567.5')
    expect(displayAmount('0.')).toBe('0.')
  })
})

describe('rates and fuel', () => {
  it('rate: >0, at most 1,000,000, at most 6 decimals, comma accepted', () => {
    expect(parseRate('1.153')).toBe(1_153_000n)
    expect(parseRate('1,5')).toBe(1_500_000n)
    expect(parseRate('0')).toBeNull()
    expect(parseRate('1000000')).toBe(1_000_000_000_000n)
    expect(parseRate('1000000.000001')).toBeNull()
    expect(parseRate('0.0000001')).toBeNull()
    expect(parseRate('')).toBeNull()
  })
  it('converts to household cents half-up, exactly at the extremes', () => {
    expect(convertCents(2000, parseRate('1.153')!)).toBe(2306)
    expect(convertCents(1, parseRate('0.5')!)).toBe(1) // 0.5 cent rounds up
    expect(convertCents(999_999_999, parseRate('1000000')!)).toBe(999_999_999_000_000)
  })
  it('fuel price: >0, at most 3 decimals', () => {
    expect(parseFuelPrice('1.789')).toBe(1789n)
    expect(parseFuelPrice('0')).toBeNull()
    expect(parseFuelPrice('1.7891')).toBeNull()
  })
  it('litres = amount / price, half-up to 3 decimals, as the server does', () => {
    expect(formatLitres(litresMilli(5000, 1600n))).toBe('31.25')
    expect(formatLitres(litresMilli(1000, 3000n))).toBe('3.333')
    expect(formatLitres(litresMilli(1, 4000n))).toBe('0.003') // 0.0025 rounds up
    expect(formatLitres(litresMilli(6000, 2000n))).toBe('30')
  })
})
```

`web/src/features/composer/dates.test.ts`:

```ts
import { afterEach, expect, it } from 'vitest'
import { addDays, dayLabel, rangeLabel, shortDate, todayLocal } from './dates'

const TZ = process.env.TZ
afterEach(() => { process.env.TZ = TZ })

it('todayLocal is the device calendar day, not the UTC one (Athens just after midnight)', () => {
  process.env.TZ = 'Europe/Athens'
  // 22:30 UTC on 7 Oct is 01:30 on 8 Oct in Athens (UTC+3 in October).
  expect(todayLocal(new Date('2026-10-07T22:30:00Z'))).toBe('2026-10-08')
})

it('addDays crosses months and years in local time', () => {
  expect(addDays('2026-10-01', -1)).toBe('2026-09-30')
  expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
})

it('labels', () => {
  expect(dayLabel('2026-10-07', '2026-10-07')).toBe('Today')
  expect(dayLabel('2026-10-06', '2026-10-07')).toBe('Yesterday')
  expect(dayLabel('2026-10-05', '2026-10-07')).toBe('Mon 5 Oct')
  expect(shortDate('2026-10-07')).toBe('7 Oct')
  expect(rangeLabel('2026-08-12', '2026-08-19')).toBe('12–19 Aug')
  expect(rangeLabel('2026-09-30', '2026-10-02')).toBe('30 Sep – 2 Oct')
  expect(rangeLabel(null, null)).toBe('')
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && grep -n "pool" vite.config.ts; npm test -- src/features/composer/amount.test.ts src/features/composer/dates.test.ts`
Expected: no `pool` line (Vitest 4's default `forks` pool, where assigning `process.env.TZ` takes effect; under `threads` it does not, so run that file with `TZ=Europe/Athens` instead), then FAIL with "Failed to resolve import ./amount".

- [ ] **Step 3: Implement**

`web/src/features/composer/amount.ts`:

```ts
/**
 * Money is typed as a string and computed in integer cents. Never parseFloat a money value:
 * cents fit a Number exactly (at most 999,999,999), and anything multiplied by a rate or divided
 * by a fuel price goes through BigInt.
 */
export type AmountKey = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back' | 'clear'

export const MAX_INT_DIGITS = 7
export const MAX_DECIMALS = 2

export function pressKey(v: string, k: AmountKey): string {
  if (k === 'clear') return ''
  if (k === 'back') return v.slice(0, -1)
  const dot = v.indexOf('.')
  if (k === '.') {
    if (dot !== -1) return v
    return v === '' ? '0.' : `${v}.`
  }
  if (dot !== -1) return v.length - dot - 1 >= MAX_DECIMALS ? v : v + k
  if (v === '0') return k
  return v.length >= MAX_INT_DIGITS ? v : v + k
}

export function toCents(v: string): number {
  const m = /^(\d*)(?:\.(\d{0,2}))?$/.exec(v.trim())
  if (!m || (m[1] === '' && !m[2])) return 0
  return Number(m[1] || '0') * 100 + Number(`${m[2] ?? ''}00`.slice(0, 2))
}

export function centsToString(c: number): string {
  const a = Math.abs(c)
  return `${c < 0 ? '-' : ''}${Math.floor(a / 100)}.${String(a % 100).padStart(2, '0')}`
}

export const toApiAmount = (v: string): string => centsToString(toCents(v))

/** A stored amount (a JSON number with at most 2 decimals) as a keypad string: 3 → "3", 4.1 → "4.10". */
export function fromApiAmount(n: number | string): string {
  const c = Math.round(Number(n) * 100)
  return c % 100 === 0 ? String(c / 100) : centsToString(c)
}

export function displayAmount(v: string): string {
  if (v === '') return '0'
  const [i, f] = v.split('.')
  const grouped = (i || '0').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return f === undefined ? grouped : `${grouped}.${f}`
}

/** "1.153" at 6 decimals → 1153000n. Accepts "," as the decimal mark; null if malformed or too precise. */
export function parseScaled(s: string, decimals: number): bigint | null {
  const m = /^(\d*)(?:[.,](\d*))?$/.exec(s.trim())
  if (!m || (m[1] === '' && !m[2])) return null
  const frac = m[2] ?? ''
  if (frac.length > decimals) return null
  const scale = 10n ** BigInt(decimals)
  return BigInt(m[1] || '0') * scale + BigInt((frac + '0'.repeat(decimals)).slice(0, decimals) || '0')
}

const MICRO = 1_000_000n
const MAX_RATE_MICROS = 1_000_000n * MICRO

/** Units of household currency per 1 unit, in millionths: > 0 and at most 1,000,000. */
export function parseRate(s: string): bigint | null {
  const r = parseScaled(s, 6)
  return r !== null && r > 0n && r <= MAX_RATE_MICROS ? r : null
}

/** Household-currency cents for `cents` of a foreign currency, half-up. */
export function convertCents(cents: number, rateMicros: bigint): number {
  return Number((BigInt(cents) * rateMicros * 2n + MICRO) / (2n * MICRO))
}

/** Price per litre in thousandths, > 0. */
export function parseFuelPrice(s: string): bigint | null {
  const p = parseScaled(s, 3)
  return p !== null && p > 0n ? p : null
}

/** Litres in thousandths: (cents / 100) / (price / 1000), half-up (the server's litres_for). */
export function litresMilli(cents: number, priceMilli: bigint): bigint {
  return (BigInt(cents) * 10000n * 2n + priceMilli) / (2n * priceMilli)
}

export function formatLitres(milli: bigint): string {
  return `${milli / 1000n}.${String(milli % 1000n).padStart(3, '0')}`.replace(/\.?0+$/, '')
}
```

`web/src/features/composer/dates.ts`:

```ts
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const parse = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** The device's local calendar day. Never toISOString(): that is the UTC day. */
export const todayLocal = (now: Date = new Date()): string => iso(now)

export function addDays(day: string, n: number): string {
  const d = parse(day)
  d.setDate(d.getDate() + n)
  return iso(d)
}

export const shortDate = (day: string): string => {
  const d = parse(day)
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

export function dayLabel(day: string, today: string): string {
  if (day === today) return 'Today'
  if (day === addDays(today, -1)) return 'Yesterday'
  return `${DAYS[parse(day).getDay()]} ${shortDate(day)}`
}

export function rangeLabel(start: string | null, end: string | null): string {
  if (!start || !end) return start ? shortDate(start) : ''
  const a = parse(start)
  const b = parse(end)
  return a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()
    ? `${a.getDate()}–${b.getDate()} ${MONTHS[b.getMonth()]}`
    : `${shortDate(start)} – ${shortDate(end)}`
}
```

`web/src/features/composer/currencies.ts`:

```ts
/** Mirrors settings.currencies on the server. */
export const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY', 'AUD', 'CAD', 'SEK', 'NOK', 'DKK'] as const

const NAMES: Record<string, string> = {
  EUR: 'euro', USD: 'US dollars', GBP: 'pounds', CHF: 'Swiss francs', JPY: 'yen',
  AUD: 'Australian dollars', CAD: 'Canadian dollars', SEK: 'Swedish kronor', NOK: 'Norwegian kroner', DKK: 'Danish kroner',
}

export const currencyName = (code: string): string => NAMES[code] ?? code

const money = (currency: string) =>
  new Intl.NumberFormat('en-IE', {
    style: 'currency', currency, currencyDisplay: 'narrowSymbol', minimumFractionDigits: 2, maximumFractionDigits: 2,
  })

export function currencySymbol(code: string): string {
  return money(code).formatToParts(0).find((p) => p.type === 'currency')?.value ?? code
}

/** Display only; cents / 100 is exact enough for two printed decimals. */
export const formatCents = (cents: number, currency: string): string => money(currency).format(cents / 100)

/** "4 euro 10", "3 euro": for accessible names. */
export function spokenMoney(cents: number, currency: string): string {
  const rest = cents % 100
  return `${Math.floor(cents / 100)} ${currencyName(currency)}${rest ? ` ${rest}` : ''}`
}
```

- [ ] **Step 4: Run the tests**

Run: `cd web && npm test -- src/features/composer/amount.test.ts src/features/composer/dates.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/amount.ts web/src/features/composer/dates.ts web/src/features/composer/currencies.ts web/src/features/composer/amount.test.ts web/src/features/composer/dates.test.ts
git commit -m "feat(composer): amount keypad logic, integer-cent maths, local dates, currencies"
```

### Task C2-2: `types.ts` and `state.ts`

**Stream:** C2 · **Depends on:** C2-1, C1-1 (2a's types through the bridge)

**Files:**
- Create: `web/src/features/composer/types.ts`, `web/src/features/composer/state.ts`
- Test: `web/src/features/composer/state.test.ts`

**Interfaces:**
- Consumes: `pressKey`, `fromApiAmount`, `AmountKey` (C2-1).
- Produces:
  - `types.ts`: re-exports 2a's `Bucket`, `Category`, `Member`, `Household` (as extended in C1-1); adds the composer's own narrowed shapes, because the generated response types are `unknown`: `TxnSplit`, `Txn` (the full row for edit), `CashMovements`, `Rule`, `QrReceipt`, `Duplicate`.
  - `state.ts`: `TxnType`, `Method`, `METHODS`, `TookFrom`, `SplitMode`, `DefaultField`, `ReceiptField`, `Share { user_id: string; amount: string }`, `Remembered`, `ComposerState`, `Action`, `blankState(p: BlankInput): ComposerState`, `fill(s, r, except)`, `reduce(s, a): ComposerState`.

- [ ] **Step 1: Write the failing test**

`web/src/features/composer/state.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { blankState, reduce, type ComposerState } from './state'

const base = (over: Partial<ComposerState> = {}): ComposerState => ({
  ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'c1', meId: 'u1' }),
  bucketId: 'b-day', categoryId: 'c-coffee', paidBy: 'u1', method: 'card',
  ...over,
})

describe('re-defaulting respects touched', () => {
  it('picking a category fills budget, payer and method that were not picked by hand', () => {
    const s = reduce(base({ touched: ['payer'] }), {
      type: 'pickCategory', id: 'c-fuel', remembered: { bucket_id: 'b-car', paid_by: 'u2', payment_method: 'cash' },
    })
    expect(s).toMatchObject({ categoryId: 'c-fuel', bucketId: 'b-car', paidBy: 'u1', method: 'cash' })
    expect(s.touched).toEqual(['payer', 'category'])
  })
  it('picking a budget fills category, payer and method; a hand-picked category stays', () => {
    const s = reduce(base({ touched: ['category'] }), {
      type: 'pickBucket', id: 'b-car', remembered: { category_id: 'c-fuel', paid_by: 'u2', payment_method: 'apple_pay' },
    })
    expect(s).toMatchObject({ bucketId: 'b-car', categoryId: 'c-coffee', paidBy: 'u2', method: 'apple_pay' })
  })
  it('a merchant rule sets an untouched category and labels it; a touched one stays', () => {
    const rule = { pattern: 'coffee island', category_id: 'c-coffee2' }
    expect(reduce(base(), { type: 'setMerchant', value: 'Coffee Island', rule })).toMatchObject({
      categoryId: 'c-coffee2', ruleLabel: 'rule: coffee island',
    })
    expect(reduce(base({ touched: ['category'] }), { type: 'setMerchant', value: 'Coffee Island', rule }).categoryId).toBe('c-coffee')
  })
  it('a filled method that is not cash clears "Took from"', () => {
    const s = reduce(base({ method: 'cash', tookFrom: 'bank' }), { type: 'pickCategory', id: 'c-x', remembered: { payment_method: 'card' } })
    expect(s).toMatchObject({ method: 'card', tookFrom: 'none' })
  })
})

describe('modes and fields', () => {
  it('cash from wallet sets cash, my wallet and locks the payer to me; off restores the method', () => {
    const on = reduce(base({ paidBy: 'u2' }), { type: 'setCashMode', on: true, meId: 'u1', defaultMethod: 'apple_pay' })
    expect(on).toMatchObject({ cashMode: true, method: 'cash', tookFrom: 'stash', paidBy: 'u1', ownShare: false })
    expect(reduce(on, { type: 'setCashMode', on: false, meId: 'u1', defaultMethod: 'apple_pay' })).toMatchObject({
      cashMode: false, method: 'apple_pay', tookFrom: 'none',
    })
  })
  it('switching to income resets the pills from the income defaults; edit cannot switch', () => {
    const s = reduce(base({ splitOn: true, splits: [{ user_id: 'u1', amount: '1.00' }], touched: ['bucket'] }), {
      type: 'setType', value: 'income', defaults: { paid_by: 'u2' },
    })
    expect(s).toMatchObject({ type: 'income', bucketId: null, categoryId: null, paidBy: 'u2', method: 'transfer', splitOn: false, splits: [], touched: [] })
    expect(reduce(base({ mode: 'edit' }), { type: 'setType', value: 'income', defaults: {} }).type).toBe('expense')
  })
  it('own share drops the single payer and any took-from', () => {
    const shares = [{ user_id: 'u1', amount: '5.00' }, { user_id: 'u2', amount: '5.00' }]
    expect(reduce(base({ method: 'cash', tookFrom: 'stash' }), { type: 'setOwnShare', splits: shares })).toMatchObject({
      ownShare: true, paidBy: null, tookFrom: 'none', splits: shares,
    })
  })
  it('picking a currency uses the last rate, or "1" for the household currency', () => {
    expect(reduce(base(), { type: 'pickCurrency', code: 'GBP', householdCurrency: 'EUR', lastRate: '1.15' }).rate).toBe('1.15')
    expect(reduce(base(), { type: 'pickCurrency', code: 'USD', householdCurrency: 'EUR', lastRate: undefined }).rate).toBe('')
    expect(reduce(base({ currency: 'GBP', rate: '1.15' }), { type: 'pickCurrency', code: 'EUR', householdCurrency: 'EUR', lastRate: undefined }).rate).toBe('1')
  })
  it('caps notes at 500 and merchant at 100', () => {
    expect(reduce(base(), { type: 'setNotes', value: 'x'.repeat(600) }).notes).toHaveLength(500)
    expect(reduce(base(), { type: 'setMerchant', value: 'y'.repeat(150), rule: null }).merchant).toHaveLength(100)
  })
})

describe('scan', () => {
  const result = { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' }
  it('fills the receipt fields and tags them until edited', () => {
    const s = reduce(base(), { type: 'applyScan', result, householdCurrency: 'EUR', today: '2026-10-07' })
    expect(s).toMatchObject({ amount: '12.50', merchant: 'Test Taverna', categoryId: 'c-eat', date: '2026-10-05', source: 'qr', scanCategoryId: 'c-eat', rememberRule: true })
    expect(s.fromReceipt).toEqual(['amount', 'currency', 'date', 'merchant', 'category'])
    expect(reduce(s, { type: 'key', key: '0' }).fromReceipt).not.toContain('amount')
  })
  it('no total: amount stays empty and the hint flag is set; a future date is ignored', () => {
    const s = reduce(base(), { type: 'applyScan', result: { ...result, amount: null, date: '2026-12-01' }, householdCurrency: 'EUR', today: '2026-10-07' })
    expect(s).toMatchObject({ amount: '', scanNoTotal: true, date: '2026-10-07' })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/state.test.ts`
Expected: FAIL with "Failed to resolve import ./state".

- [ ] **Step 3: Implement**

`web/src/features/composer/types.ts`:

```ts
/** 2a's shared shapes (data/types.ts, with C1-1's fields); type-only, so pure modules stay React-free. */
export type { Bucket, Category, Household, Member } from './bridge'

/** The full transaction for edit and copy (app/api/transactions.py _txn_dict); 2a's TransactionRow is a subset. */
export interface TxnSplit { user_id: string; amount: number; is_settled: boolean }
export interface Txn {
  id: string
  bucket_id: string | null
  household_id: string
  amount: number
  currency: string
  exchange_rate: number
  type: 'expense' | 'income' | 'transfer'
  paid_by: string | null
  payer_mode: string | null
  category_id: string | null
  notes: string | null
  transaction_date: string | null
  receipt_path: string | null
  payment_method: string | null
  merchant: string | null
  fuel_price_per_litre: number | null
  fuel_litres: number | null
  exclude_from_forecast: boolean
  exclude_from_settlement: boolean
  recurring_bill_id: string | null
  created_at: string | null
  splits: TxnSplit[]
}
export interface CashMovements { items: unknown[]; stash: number }
/** 2d's GET /settings/category-rules row; 2b reads only these three fields. */
export interface Rule { id: string; pattern: string; category_id: string }
/** POST /api/v1/transactions/scan/qr (B1); kept local so the pure modules do not need generated types. */
export interface QrReceipt {
  amount: number | null
  currency: string
  date: string | null
  merchant: string | null
  category_hint: string | null
  category_id: string | null
}
/** GET /api/v1/transactions/check-duplicate row (B2). */
export interface Duplicate {
  id: string
  amount: number
  currency: string
  date: string
  notes: string | null
  merchant: string | null
  bucket: string | null
  paid_by: string | null
  same_bucket: boolean
}
```

`web/src/features/composer/state.ts`:

```ts
import { type AmountKey, fromApiAmount, pressKey } from './amount'
import type { QrReceipt } from './types'

export type TxnType = 'expense' | 'income'
export type Method = 'card' | 'cash' | 'apple_pay' | 'transfer' | 'other'
export const METHODS: readonly Method[] = ['card', 'cash', 'apple_pay', 'transfer', 'other']
export type TookFrom = 'none' | 'stash' | 'bank'
export type SplitMode = 'equal' | 'amounts' | 'percent'
export type DefaultField = 'bucket' | 'category' | 'payer' | 'method'
export type ReceiptField = 'amount' | 'currency' | 'date' | 'merchant' | 'category'
export interface Share { user_id: string; amount: string }
/** What the defaults store remembers for a context (last entry, a category, a budget). */
export interface Remembered {
  bucket_id?: string | null
  category_id?: string | null
  paid_by?: string | null
  payment_method?: Method
}

export interface ComposerState {
  mode: 'new' | 'edit'
  editId: string | null
  /** Create only; one per composer, reused for every attempt (spec §5.1). */
  clientId: string | null
  type: TxnType
  /** Keypad string, e.g. "4.1". */
  amount: string
  currency: string
  /** Typed rate string; "1" for the household currency, "" when unknown. */
  rate: string
  merchant: string
  bucketId: string | null
  /** Expense linked to a recurring item with no budget: Budget shows "Fixed cost", sent as null. */
  fixedCost: boolean
  categoryId: string | null
  /** "rule: coffee island" when a household rule chose the category. */
  ruleLabel: string | null
  paidBy: string | null
  ownShare: boolean
  method: Method
  tookFrom: TookFrom
  cashMode: boolean
  date: string
  notes: string
  fuelPrice: string
  splitOn: boolean
  splitMode: SplitMode
  /** Every member's share, adding up to the total (split or own share). */
  splits: Share[]
  countInForecast: boolean
  /** Edit only: the stored value, sent back untouched. */
  excludeFromSettlement: boolean
  receipt: File | null
  storedReceiptPath: string | null
  source: 'manual' | 'qr' | 'photo'
  fromReceipt: ReceiptField[]
  scanCategoryId: string | null
  scanNoTotal: boolean
  rememberRule: boolean
  touched: DefaultField[]
}

export interface BlankInput { type: TxnType; currency: string; date: string; clientId: string | null; meId: string }

export function blankState(p: BlankInput): ComposerState {
  return {
    mode: 'new', editId: null, clientId: p.clientId, type: p.type,
    amount: '', currency: p.currency, rate: '1', merchant: '',
    bucketId: null, fixedCost: false, categoryId: null, ruleLabel: null,
    paidBy: p.meId, ownShare: false, method: p.type === 'income' ? 'transfer' : 'card',
    tookFrom: 'none', cashMode: false, date: p.date, notes: '', fuelPrice: '',
    splitOn: false, splitMode: 'equal', splits: [], countInForecast: true, excludeFromSettlement: false,
    receipt: null, storedReceiptPath: null, source: 'manual', fromReceipt: [], scanCategoryId: null,
    scanNoTotal: false, rememberRule: false, touched: [],
  }
}

export type Action =
  | { type: 'key'; key: AmountKey }
  | { type: 'setType'; value: TxnType; defaults: Remembered }
  | { type: 'setMerchant'; value: string; rule: { pattern: string; category_id: string } | null }
  | { type: 'pickBucket'; id: string | null; remembered: Remembered }
  | { type: 'pickCategory'; id: string | null; remembered: Remembered }
  | { type: 'pickPayer'; id: string }
  | { type: 'setOwnShare'; splits: Share[] }
  | { type: 'pickMethod'; method: Method }
  | { type: 'setTookFrom'; value: TookFrom }
  | { type: 'setCashMode'; on: boolean; meId: string; defaultMethod: Method }
  | { type: 'pickCurrency'; code: string; householdCurrency: string; lastRate: string | undefined }
  | { type: 'setRate'; value: string }
  | { type: 'setDate'; value: string }
  | { type: 'setNotes'; value: string }
  | { type: 'setFuelPrice'; value: string }
  | { type: 'setSplit'; on: boolean; mode: SplitMode; splits: Share[] }
  | { type: 'setForecast'; on: boolean }
  | { type: 'setReceipt'; file: File | null }
  | { type: 'applyScan'; result: QrReceipt; householdCurrency: string; today: string }
  | { type: 'attachPhoto'; file: File }
  | { type: 'setRemember'; on: boolean }
  | { type: 'replace'; state: ComposerState }

const add = <T,>(xs: readonly T[], x: T): T[] => (xs.includes(x) ? [...xs] : [...xs, x])
const drop = <T,>(xs: readonly T[], x: T): T[] => xs.filter((y) => y !== x)

/** Fill the default fields the user has not picked by hand (spec §4.3 "re-defaulting"). */
export function fill(s: ComposerState, r: Remembered, except: DefaultField): ComposerState {
  const free = (f: DefaultField) => f !== except && !s.touched.includes(f)
  const method = free('method') && !s.cashMode && s.type === 'expense' && r.payment_method ? r.payment_method : s.method
  const category = free('category') && r.category_id ? r.category_id : s.categoryId
  return {
    ...s,
    bucketId: free('bucket') && !s.fixedCost && r.bucket_id ? r.bucket_id : s.bucketId,
    categoryId: category,
    ruleLabel: category !== s.categoryId ? null : s.ruleLabel,
    paidBy: free('payer') && !s.cashMode && !s.ownShare && r.paid_by ? r.paid_by : s.paidBy,
    method,
    tookFrom: method === 'cash' ? s.tookFrom : 'none',
  }
}

export function reduce(s: ComposerState, a: Action): ComposerState {
  switch (a.type) {
    case 'key':
      return { ...s, amount: pressKey(s.amount, a.key), fromReceipt: drop(s.fromReceipt, 'amount'), scanNoTotal: false }
    case 'setType': {
      if (s.mode === 'edit' || s.type === a.value) return s
      return {
        ...s, type: a.value, touched: [], ownShare: false, splitOn: false, splits: [], cashMode: false,
        tookFrom: 'none', fuelPrice: '', ruleLabel: null,
        bucketId: a.defaults.bucket_id ?? null,
        categoryId: a.defaults.category_id ?? null,
        paidBy: a.defaults.paid_by ?? s.paidBy,
        method: a.defaults.payment_method ?? (a.value === 'income' ? 'transfer' : 'card'),
      }
    }
    case 'setMerchant': {
      const next = { ...s, merchant: a.value.slice(0, 100), fromReceipt: drop(s.fromReceipt, 'merchant') }
      if (a.rule && !s.touched.includes('category')) {
        return { ...next, categoryId: a.rule.category_id, ruleLabel: `rule: ${a.rule.pattern}` }
      }
      return { ...next, ruleLabel: a.rule ? s.ruleLabel : null }
    }
    case 'pickBucket':
      return fill({ ...s, bucketId: a.id, touched: add(s.touched, 'bucket') }, a.remembered, 'bucket')
    case 'pickCategory':
      return fill(
        { ...s, categoryId: a.id, ruleLabel: null, touched: add(s.touched, 'category'), fromReceipt: drop(s.fromReceipt, 'category') },
        a.remembered,
        'category',
      )
    case 'pickPayer':
      return { ...s, paidBy: a.id, ownShare: false, splits: s.ownShare ? [] : s.splits, touched: add(s.touched, 'payer') }
    case 'setOwnShare':
      return { ...s, ownShare: true, paidBy: null, splitOn: false, splits: a.splits, cashMode: false, tookFrom: 'none', touched: add(s.touched, 'payer') }
    case 'pickMethod':
      return {
        ...s, method: a.method, tookFrom: a.method === 'cash' ? s.tookFrom : 'none',
        cashMode: a.method === 'cash' && s.cashMode, touched: add(s.touched, 'method'),
      }
    case 'setTookFrom':
      return { ...s, tookFrom: a.value }
    case 'setCashMode':
      return a.on
        ? { ...s, cashMode: true, method: 'cash', tookFrom: 'stash', paidBy: a.meId, ownShare: false, splits: s.ownShare ? [] : s.splits }
        : { ...s, cashMode: false, method: a.defaultMethod, tookFrom: 'none' }
    case 'pickCurrency':
      return {
        ...s, currency: a.code, rate: a.code === a.householdCurrency ? '1' : (a.lastRate ?? ''),
        fromReceipt: drop(s.fromReceipt, 'currency'),
      }
    case 'setRate':
      return { ...s, rate: a.value }
    case 'setDate':
      return { ...s, date: a.value, fromReceipt: drop(s.fromReceipt, 'date') }
    case 'setNotes':
      return { ...s, notes: a.value.slice(0, 500) }
    case 'setFuelPrice':
      return { ...s, fuelPrice: a.value }
    case 'setSplit':
      return { ...s, splitOn: a.on, splitMode: a.mode, splits: a.on ? a.splits : [] }
    case 'setForecast':
      return { ...s, countInForecast: a.on }
    case 'setReceipt':
      return { ...s, receipt: a.file }
    case 'applyScan': {
      const r = a.result
      const from: ReceiptField[] = []
      const next: ComposerState = { ...s, source: 'qr', scanCategoryId: r.category_id, scanNoTotal: r.amount == null, rememberRule: true }
      if (r.amount != null) { next.amount = fromApiAmount(r.amount); from.push('amount') }
      if (r.currency) { next.currency = r.currency; next.rate = r.currency === a.householdCurrency ? '1' : ''; from.push('currency') }
      if (r.date && r.date <= a.today) { next.date = r.date; from.push('date') }
      if (r.merchant) { next.merchant = r.merchant.slice(0, 100); from.push('merchant') }
      if (r.category_id) { next.categoryId = r.category_id; next.ruleLabel = null; from.push('category') }
      return { ...next, fromReceipt: from }
    }
    case 'attachPhoto':
      return { ...s, receipt: a.file, source: 'photo' }
    case 'setRemember':
      return { ...s, rememberRule: a.on }
    case 'replace':
      return a.state
  }
}
```

- [ ] **Step 4: Run the test**

Run: `cd web && npm test -- src/features/composer/state.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/types.ts web/src/features/composer/state.ts web/src/features/composer/state.test.ts
git commit -m "feat(composer): state reducer with touched-aware re-defaulting, cash mode and scan fill"
```

### Task C2-3: `defaults.ts` (smart defaults, rule matching, the rules-API gate)

**Stream:** C2 · **Depends on:** C2-2

**Files:**
- Create: `web/src/features/composer/defaults.ts`
- Test: `web/src/features/composer/defaults.test.ts`

**Interfaces:**
- Consumes: `cacheGet`, `cachePut`, `db` (`web/src/offline/db.ts`), `paths` (`web/src/api/schema.d.ts`), C2-1, C2-2.
- Produces: `DefaultsRecord`, `EMPTY_DEFAULTS`, `defaultsKey(hh)`, `loadDefaults(hh): Promise<DefaultsRecord>`, `saveDefaults(hh, rec): Promise<void>`, `interface LookupCtx { buckets: Bucket[]; categories: Category[]; memberIds: string[]; type: TxnType }`, `sanitize(r: Remembered | undefined, ctx: LookupCtx): Remembered`, `interface NewCtx { defaults; buckets; categories; memberIds; meId; householdCurrency; type; today; clientId; cash: boolean }`, `initialNew(c: NewCtx): ComposerState`, `interface LearnCtx { householdCurrency: string; fuelCategoryId: string | null }`, `learn(rec, s, ctx: LearnCtx): DefaultsRecord`, `fold(text)`, `matchRule(merchant, rules): Rule | null`, `suggestMerchants(query, merchants): string[]`, `RULES_API_READY`, `shouldOfferRemember(s, ready: boolean): boolean`, `fuelCategoryId(categories): string | null`.

- [ ] **Step 1: Write the failing test**

`web/src/features/composer/defaults.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import { db, wipe } from '../../offline/db'
import {
  EMPTY_DEFAULTS, defaultsKey, fold, initialNew, learn, loadDefaults, matchRule, sanitize, saveDefaults,
  shouldOfferRemember, suggestMerchants, type DefaultsRecord,
} from './defaults'
import { blankState, type ComposerState } from './state'
import type { Bucket, Category } from './types'

const bucket = (id: string, over: Partial<Bucket> = {}): Bucket => ({
  id, name: id, kind: 'monthly', status: 'active', budget: null, start_date: null, end_date: null, show_income: false, ...over,
})
const category = (id: string, over: Partial<Category> = {}): Category => ({
  id, name: id, icon: null, color: null, system_key: null, ...over,
})
const BUCKETS = [bucket('b-day'), bucket('b-old', { status: 'archived' }), bucket('b-salary', { show_income: true })]
const CATEGORIES = [category('c-coffee'), category('c-fuel', { system_key: 'fuel' })]
const ctx = (defaults: DefaultsRecord, type: 'expense' | 'income' = 'expense', cash = false) => ({
  defaults, buckets: BUCKETS, categories: CATEGORIES, memberIds: ['u1', 'u2'], meId: 'u1',
  householdCurrency: 'EUR', type, today: '2026-10-07', clientId: 'c1', cash,
})

beforeEach(() => wipe())

describe('initial defaults', () => {
  it('first use: no budget (dashed), payer me, method card, household currency, today', () => {
    expect(initialNew(ctx(EMPTY_DEFAULTS))).toMatchObject({
      bucketId: null, categoryId: null, paidBy: 'u1', method: 'card', currency: 'EUR', rate: '1', date: '2026-10-07', clientId: 'c1',
    })
  })
  it('uses the last entry, dropping an archived budget, a missing category and a former member', () => {
    const d = { ...EMPTY_DEFAULTS, last: { bucket_id: 'b-old', category_id: 'c-gone', paid_by: 'u9', payment_method: 'apple_pay' as const } }
    expect(initialNew(ctx(d))).toMatchObject({ bucketId: null, categoryId: null, paidBy: 'u1', method: 'apple_pay' })
    const ok = { ...EMPTY_DEFAULTS, last: { bucket_id: 'b-day', category_id: 'c-coffee', paid_by: 'u2', payment_method: 'cash' as const } }
    expect(initialNew(ctx(ok))).toMatchObject({ bucketId: 'b-day', categoryId: 'c-coffee', paidBy: 'u2', method: 'cash' })
  })
  it('income uses lastIncome, only show_income budgets, and transfer', () => {
    const d = { ...EMPTY_DEFAULTS, lastIncome: { bucket_id: 'b-day', category_id: null, paid_by: 'u2' } }
    expect(initialNew(ctx(d, 'income'))).toMatchObject({ type: 'income', bucketId: null, paidBy: 'u2', method: 'transfer' })
    expect(sanitize({ bucket_id: 'b-salary' }, { buckets: BUCKETS, categories: CATEGORIES, memberIds: ['u1'], type: 'income' })).toEqual({ bucket_id: 'b-salary' })
  })
  it('cash mode from the start', () => {
    expect(initialNew(ctx(EMPTY_DEFAULTS, 'expense', true))).toMatchObject({ cashMode: true, method: 'cash', tookFrom: 'stash', paidBy: 'u1' })
  })
})

describe('learning', () => {
  const s = (over: Partial<ComposerState>): ComposerState => ({
    ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'c1', meId: 'u1' }), ...over,
  })
  it('remembers last, per category, per budget, recent categories (max 4), rate and fuel price', () => {
    let rec = { ...EMPTY_DEFAULTS, recentCategoryIds: ['a', 'b', 'c', 'd'] }
    rec = learn(rec, s({ bucketId: 'b-car', categoryId: 'c-fuel', paidBy: 'u2', method: 'card', currency: 'GBP', rate: '1.15', fuelPrice: '1.789' }), { householdCurrency: 'EUR', fuelCategoryId: 'c-fuel' })
    expect(rec.last).toEqual({ bucket_id: 'b-car', category_id: 'c-fuel', paid_by: 'u2', payment_method: 'card' })
    expect(rec.byCategory['c-fuel']).toEqual({ bucket_id: 'b-car', paid_by: 'u2', payment_method: 'card' })
    expect(rec.byBucket['b-car']).toEqual({ category_id: 'c-fuel', paid_by: 'u2', payment_method: 'card' })
    expect(rec.recentCategoryIds).toEqual(['c-fuel', 'a', 'b', 'c'])
    expect(rec.rates).toEqual({ GBP: '1.15' })
    expect(rec.fuelPrice).toBe('1.789')
  })
  it('own share keeps the previous payer; income writes only lastIncome; edits teach nothing', () => {
    const rec = { ...EMPTY_DEFAULTS, last: { paid_by: 'u2' } }
    expect(learn(rec, s({ ownShare: true, paidBy: null, bucketId: 'b-day' }), { householdCurrency: 'EUR', fuelCategoryId: null }).last?.paid_by).toBe('u2')
    const inc = learn(EMPTY_DEFAULTS, s({ type: 'income', bucketId: null, paidBy: 'u2', method: 'transfer' }), { householdCurrency: 'EUR', fuelCategoryId: null })
    expect(inc.last).toBeUndefined()
    expect(inc.lastIncome).toEqual({ bucket_id: null, category_id: null, paid_by: 'u2', payment_method: 'transfer' })
    expect(learn(rec, s({ mode: 'edit', bucketId: 'b-x' }), { householdCurrency: 'EUR', fuelCategoryId: null })).toBe(rec)
  })
  it('round-trips through the encrypted cache; an unreadable record gives empty defaults', async () => {
    await saveDefaults('h1', { ...EMPTY_DEFAULTS, fuelPrice: '1.7' })
    expect((await loadDefaults('h1')).fuelPrice).toBe('1.7')
    await db.cache.put({ key: defaultsKey('h2'), iv: new Uint8Array(12), data: new ArrayBuffer(8), updatedAt: 0 })
    expect(await loadDefaults('h2')).toEqual(EMPTY_DEFAULTS)
  })
})

describe('rules', () => {
  it('fold: case, accents, final sigma, spaces (mirrors the server)', () => {
    expect(fold('ΣΚΛΑΒΕΝΙΤΗΣ')).toBe('σκλαβενιτησ')
    expect(fold('  Καφέ   Ιsland ')).toBe('καφε ιsland')
    expect(fold(null)).toBe('')
  })
  it('matches a substring, the longest pattern wins', () => {
    const rules = [
      { id: 'r1', pattern: 'island', category_id: 'c-travel' },
      { id: 'r2', pattern: 'coffee island', category_id: 'c-coffee' },
      { id: 'r3', pattern: 'σκλαβενιτης', category_id: 'c-food' },
    ]
    expect(matchRule('COFFEE ISLAND Kifisia', rules)?.id).toBe('r2')
    expect(matchRule('Σκλαβενίτης', rules)?.id).toBe('r3')
    expect(matchRule('c', rules)).toBeNull()
  })
  it('suggests up to 5 recent merchants after 2 characters', () => {
    const merchants = ['Coffee Island', 'Coffeeway', 'Lidl', 'Cosmote', 'Coffee Lab', 'Cofix', 'Coffee Berry']
    expect(suggestMerchants('c', merchants)).toEqual([])
    expect(suggestMerchants('cof', merchants)).toEqual(['Coffee Island', 'Coffeeway', 'Coffee Lab', 'Cofix', 'Coffee Berry'])
    expect(suggestMerchants('Lidl', merchants)).toEqual([])
  })
  it('offers Remember only for a QR review whose category differs from the server suggestion', () => {
    const qr = { ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'c', meId: 'u1' }), source: 'qr' as const, merchant: 'Taverna', categoryId: 'c-eat', scanCategoryId: 'c-food' }
    expect(shouldOfferRemember(qr, true)).toBe(true)
    expect(shouldOfferRemember(qr, false)).toBe(false)
    expect(shouldOfferRemember({ ...qr, categoryId: 'c-food' }, true)).toBe(false)
    expect(shouldOfferRemember({ ...qr, merchant: 'T' }, true)).toBe(false)
    expect(shouldOfferRemember({ ...qr, source: 'manual' }, true)).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/defaults.test.ts`
Expected: FAIL with "Failed to resolve import ./defaults".

- [ ] **Step 3: Implement `web/src/features/composer/defaults.ts`**

```ts
import type { paths } from '../../api/schema'
import { cacheGet, cachePut } from '../../offline/db'
import { parseFuelPrice, parseRate } from './amount'
import { blankState, type ComposerState, METHODS, type Remembered, reduce, type TxnType } from './state'
import type { Bucket, Category, Rule } from './types'

/**
 * 2d owns /api/v1/settings/category-rules (2d spec §7.4). The Remember toggle and rule matching stay
 * off until that path is in the generated types. `false` stops type-checking the moment 2d's types land
 * ('false' is not assignable to 'true'): then set it to `true`, and back again would fail the same way.
 */
type HasRulesApi = '/api/v1/settings/category-rules' extends keyof paths ? true : false
export const RULES_API_READY: HasRulesApi = false

export interface DefaultsRecord {
  v: 1
  last?: Remembered
  lastIncome?: Remembered
  byCategory: Record<string, Remembered>
  byBucket: Record<string, Remembered>
  recentCategoryIds: string[]
  /** Last rate typed per currency code. */
  rates: Record<string, string>
  fuelPrice?: string
}

export const EMPTY_DEFAULTS: DefaultsRecord = { v: 1, byCategory: {}, byBucket: {}, recentCategoryIds: [], rates: {} }

/** Plaintext key (db.ts NOTE): no sensitive values in it, only the household id. */
export const defaultsKey = (hh: string) => `composer.defaults:${hh}`

export async function loadDefaults(hh: string): Promise<DefaultsRecord> {
  try {
    const r = await cacheGet<DefaultsRecord>(defaultsKey(hh))
    return r && r.v === 1 ? { ...EMPTY_DEFAULTS, ...r } : EMPTY_DEFAULTS
  } catch {
    return EMPTY_DEFAULTS // unreadable or wiped: start empty, never fail (spec §8)
  }
}

export async function saveDefaults(hh: string, rec: DefaultsRecord): Promise<void> {
  try {
    await cachePut(defaultsKey(hh), rec)
  } catch {
    // A wipe mid-write: the next save writes again.
  }
}

export interface LookupCtx { buckets: Bucket[]; categories: Category[]; memberIds: string[]; type: TxnType }

/** Keep only what still exists: an active (for income, income-tracking) budget, a category, a member. */
export function sanitize(r: Remembered | undefined, ctx: LookupCtx): Remembered {
  if (!r) return {}
  const out: Remembered = {}
  const b = r.bucket_id ? ctx.buckets.find((x) => x.id === r.bucket_id) : undefined
  if (b && b.status === 'active' && (ctx.type === 'expense' || b.show_income)) out.bucket_id = b.id
  if (r.category_id && ctx.categories.some((c) => c.id === r.category_id)) out.category_id = r.category_id
  if (r.paid_by && ctx.memberIds.includes(r.paid_by)) out.paid_by = r.paid_by
  if (r.payment_method && METHODS.includes(r.payment_method)) out.payment_method = r.payment_method
  return out
}

export interface NewCtx {
  defaults: DefaultsRecord
  buckets: Bucket[]
  categories: Category[]
  memberIds: string[]
  meId: string
  householdCurrency: string
  type: TxnType
  today: string
  clientId: string
  cash: boolean
}

export function initialNew(c: NewCtx): ComposerState {
  const lookup = { buckets: c.buckets, categories: c.categories, memberIds: c.memberIds, type: c.type }
  const rem = sanitize(c.type === 'income' ? c.defaults.lastIncome : c.defaults.last, lookup)
  const s: ComposerState = {
    ...blankState({ type: c.type, currency: c.householdCurrency, date: c.today, clientId: c.clientId, meId: c.meId }),
    bucketId: rem.bucket_id ?? null,
    categoryId: rem.category_id ?? null,
    paidBy: rem.paid_by ?? c.meId,
    method: rem.payment_method ?? (c.type === 'income' ? 'transfer' : 'card'),
  }
  return c.cash && c.type === 'expense'
    ? reduce(s, { type: 'setCashMode', on: true, meId: c.meId, defaultMethod: s.method })
    : s
}

export interface LearnCtx { householdCurrency: string; fuelCategoryId: string | null }

/** Rewritten when Save is tapped, online or queued (spec §4.3). Edits of old entries teach nothing. */
export function learn(rec: DefaultsRecord, s: ComposerState, ctx: LearnCtx): DefaultsRecord {
  if (s.mode !== 'new') return rec
  const rates = s.currency !== ctx.householdCurrency && parseRate(s.rate) !== null ? { ...rec.rates, [s.currency]: s.rate.trim() } : rec.rates
  if (s.type === 'income') {
    return { ...rec, rates, lastIncome: { bucket_id: s.bucketId, category_id: s.categoryId, paid_by: s.paidBy, payment_method: s.method } }
  }
  const who: Remembered = s.ownShare ? {} : { paid_by: s.paidBy }
  const how: Remembered = { ...who, payment_method: s.method }
  const isFuel = ctx.fuelCategoryId !== null && s.categoryId === ctx.fuelCategoryId
  return {
    ...rec,
    rates,
    last: { ...rec.last, bucket_id: s.bucketId, category_id: s.categoryId, ...how },
    byCategory: s.categoryId ? { ...rec.byCategory, [s.categoryId]: { bucket_id: s.bucketId, ...how } } : rec.byCategory,
    byBucket: s.bucketId ? { ...rec.byBucket, [s.bucketId]: { category_id: s.categoryId, ...how } } : rec.byBucket,
    recentCategoryIds: s.categoryId
      ? [s.categoryId, ...rec.recentCategoryIds.filter((id) => id !== s.categoryId)].slice(0, 4)
      : rec.recentCategoryIds,
    fuelPrice: isFuel && parseFuelPrice(s.fuelPrice) !== null ? s.fuelPrice.trim() : rec.fuelPrice,
  }
}

/** Mirrors app/services/category_rules.fold: case-fold, strip accents, final ς → σ, collapse spaces. */
export function fold(text: string | null | undefined): string {
  if (!text) return ''
  const stripped = text.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
  return stripped.replace(/ς/g, 'σ').split(/\s+/).filter(Boolean).join(' ')
}

/** The household rule whose folded pattern is inside the folded merchant; the longest pattern wins. */
export function matchRule(merchant: string, rules: Rule[]): Rule | null {
  const m = fold(merchant)
  if (m.length < 2) return null
  let best: Rule | null = null
  let bestLen = 0
  for (const r of rules) {
    const p = fold(r.pattern)
    if (p.length >= 2 && m.includes(p) && p.length > bestLen) {
      best = r
      bestLen = p.length
    }
  }
  return best
}

export function suggestMerchants(query: string, merchants: string[]): string[] {
  const q = fold(query)
  if (q.length < 2) return []
  return merchants.filter((m) => fold(m).includes(q) && fold(m) !== q).slice(0, 5)
}

export function shouldOfferRemember(s: ComposerState, ready: boolean): boolean {
  return ready && s.source === 'qr' && fold(s.merchant).length >= 2 && s.categoryId !== null && s.categoryId !== s.scanCategoryId
}

export const fuelCategoryId = (categories: Category[]): string | null =>
  categories.find((c) => c.system_key === 'fuel')?.id ?? null
```

- [ ] **Step 4: Run the test and the type check**

Run: `cd web && npm test -- src/features/composer/defaults.test.ts && npm run typecheck`
Expected: PASS. (If 2d's rules path is already in `schema.d.ts`, typecheck fails on `RULES_API_READY`: set it to `true`, rerun, and note it in the commit message.)

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/defaults.ts web/src/features/composer/defaults.test.ts
git commit -m "feat(composer): smart defaults in the encrypted cache, rule matching, rules-API type gate"
```

### Task C2-4: `model.ts` (state ↔ API, validation)

**Stream:** C2 · **Depends on:** C2-2 (C2-3 only for `fuelCategoryId` in tests)

**Files:**
- Create: `web/src/features/composer/model.ts`
- Test: `web/src/features/composer/model.test.ts`

**Interfaces:**
- Consumes: `components['schemas']['TransactionCreate' | 'TransactionUpdate']` from `web/src/api/schema.d.ts`; C2-1; C2-2.
- Produces: `type CreateBody`, `type UpdateBody`, `interface ModelCtx { householdCurrency: string; fuelCategoryId: string | null }`, `isFuel(s, ctx)`, `toCreateBody(s, ctx): CreateBody`, `toUpdateBody(s, ctx): UpdateBody`, `fromTransaction(t: Txn, c: { householdCurrency: string; meId: string }): ComposerState`, `copyOf(s, c: { clientId: string; today: string }): ComposerState`, `type Problem = 'amount'|'bucket'|'date'|'rate'|'fuel'|'split'|'wallet'|'payer'`, `interface ValidateCtx extends ModelCtx { today: string; stashCents: number | null; meId: string }`, `validate(s, c): { ok: boolean; problems: Partial<Record<Problem, string>> }`, `firstProblem(problems): string | null` (never the amount), `isDirtyNew(s): boolean`, `moreDirty(s, c: ModelCtx & { today: string }): boolean`, `homeCents(s, householdCurrency): number | null`.

- [ ] **Step 1: Write the failing test**

`web/src/features/composer/model.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { copyOf, firstProblem, fromTransaction, isDirtyNew, moreDirty, toCreateBody, toUpdateBody, validate } from './model'
import { blankState, type ComposerState } from './state'
import type { Txn } from './types'

const CTX = { householdCurrency: 'EUR', fuelCategoryId: 'c-fuel' }
const V = { ...CTX, today: '2026-10-07', stashCents: null, meId: 'u1' }
const expense = (over: Partial<ComposerState> = {}): ComposerState => ({
  ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'cid-1', meId: 'u1' }),
  amount: '4.1', bucketId: 'b-day', categoryId: 'c-coffee', ...over,
})

describe('toCreateBody: one test per row of the spec §4.10 field map', () => {
  it('type, amount (decimal string), currency, rate "1", date, client_id, settlement false', () => {
    expect(toCreateBody(expense(), CTX)).toMatchObject({
      type: 'expense', amount: '4.10', currency: 'EUR', exchange_rate: '1', transaction_date: '2026-10-07',
      client_id: 'cid-1', exclude_from_settlement: false, exclude_from_forecast: false, payer_mode: 'single',
      bucket_id: 'b-day', category_id: 'c-coffee', paid_by: 'u1', payment_method: 'card', splits: [], took_cash: false,
    })
  })
  it('blank merchant and notes send null; filled ones are trimmed', () => {
    expect(toCreateBody(expense({ merchant: '  ', notes: '' }), CTX)).toMatchObject({ merchant: null, notes: null })
    expect(toCreateBody(expense({ merchant: ' Lidl ', notes: ' milk ' }), CTX)).toMatchObject({ merchant: 'Lidl', notes: 'milk' })
  })
  it('income: bucket optional (null), received by, transfer', () => {
    const s = expense({ type: 'income', bucketId: null, paidBy: 'u2', method: 'transfer', amount: '700' })
    expect(toCreateBody(s, CTX)).toMatchObject({ type: 'income', bucket_id: null, paid_by: 'u2', payment_method: 'transfer', amount: '700.00', splits: [] })
  })
  it('foreign currency sends the typed rate', () => {
    expect(toCreateBody(expense({ currency: 'GBP', rate: '1,153' }), CTX)).toMatchObject({ currency: 'GBP', exchange_rate: '1.153' })
  })
  it('fuel sends the price only for the fuel category', () => {
    expect(toCreateBody(expense({ categoryId: 'c-fuel', fuelPrice: '1.789' }), CTX).fuel_price_per_litre).toBe('1.789')
    expect(toCreateBody(expense({ categoryId: 'c-coffee', fuelPrice: '1.789' }), CTX)).not.toHaveProperty('fuel_price_per_litre')
  })
  it('split sends every member share', () => {
    const splits = [{ user_id: 'u1', amount: '2.05' }, { user_id: 'u2', amount: '2.05' }]
    expect(toCreateBody(expense({ splitOn: true, splits }), CTX)).toMatchObject({ splits, payer_mode: 'single', paid_by: 'u1' })
  })
  it('own share: payer_mode own_share, paid_by null, splits', () => {
    const splits = [{ user_id: 'u1', amount: '3.00' }, { user_id: 'u2', amount: '1.10' }]
    expect(toCreateBody(expense({ ownShare: true, paidBy: null, splits }), CTX)).toMatchObject({ payer_mode: 'own_share', paid_by: null, splits })
  })
  it('cash from wallet: took_cash and take_from stash; bank; not tracked sends neither', () => {
    expect(toCreateBody(expense({ method: 'cash', tookFrom: 'stash', cashMode: true }), CTX)).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash' })
    expect(toCreateBody(expense({ method: 'cash', tookFrom: 'bank' }), CTX)).toMatchObject({ took_cash: true, take_from: 'bank' })
    const none = toCreateBody(expense({ method: 'cash', tookFrom: 'none' }), CTX)
    expect(none.took_cash).toBe(false)
    expect(none).not.toHaveProperty('take_from')
  })
  it('count in forecast off sends exclude_from_forecast true', () => {
    expect(toCreateBody(expense({ countInForecast: false }), CTX).exclude_from_forecast).toBe(true)
  })
  it('a Fixed cost sends bucket_id null', () => {
    expect(toCreateBody(expense({ fixedCost: true, bucketId: null }), CTX).bucket_id).toBeNull()
  })
})

const STORED: Txn = {
  id: 't9', bucket_id: 'b-old', household_id: 'h1', amount: 64.2, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: 'u2', payer_mode: 'single', category_id: 'c-fuel', notes: 'full tank', transaction_date: '2026-10-01',
  receipt_path: 'abc.jpg', payment_method: 'card', merchant: 'Shell', fuel_price_per_litre: 1.789, fuel_litres: 35.886,
  exclude_from_forecast: true, exclude_from_settlement: true, recurring_bill_id: null, created_at: null,
  splits: [{ user_id: 'u1', amount: 32.1, is_settled: false }, { user_id: 'u2', amount: 32.1, is_settled: false }],
}

describe('edit', () => {
  it('fromTransaction then toUpdateBody round-trips a stored transaction unchanged', () => {
    const body = toUpdateBody(fromTransaction(STORED, { householdCurrency: 'EUR', meId: 'u1' }), CTX)
    expect(body).toEqual({
      type: 'expense', amount: '64.20', currency: 'EUR', exchange_rate: '1', bucket_id: 'b-old', category_id: 'c-fuel',
      merchant: 'Shell', paid_by: 'u2', payer_mode: 'single', payment_method: 'card', took_cash: false,
      transaction_date: '2026-10-01', notes: 'full tank', exclude_from_forecast: true, exclude_from_settlement: true,
      fuel_price_per_litre: '1.789', splits: [{ user_id: 'u1', amount: '32.10' }, { user_id: 'u2', amount: '32.10' }],
    })
    expect(body).not.toHaveProperty('client_id')
    expect(body).not.toHaveProperty('take_from')
  })
  it('edit sends fuel_price_per_litre null when cleared, and the own-share mode explicitly', () => {
    const s = { ...fromTransaction(STORED, { householdCurrency: 'EUR', meId: 'u1' }), fuelPrice: '' }
    expect(toUpdateBody(s, CTX).fuel_price_per_litre).toBeNull()
    const own = fromTransaction({ ...STORED, payer_mode: 'own_share', paid_by: null }, { householdCurrency: 'EUR', meId: 'u1' })
    expect(toUpdateBody(own, CTX)).toMatchObject({ payer_mode: 'own_share', paid_by: null })
  })
  it('a Fixed cost (no budget, linked to an item) is read-only and stays null', () => {
    const s = fromTransaction({ ...STORED, bucket_id: null, recurring_bill_id: 'r1' }, { householdCurrency: 'EUR', meId: 'u1' })
    expect(s.fixedCost).toBe(true)
    expect(toUpdateBody(s, CTX).bucket_id).toBeNull()
  })
  it('foreign currency keeps the stored rate', () => {
    const s = fromTransaction({ ...STORED, currency: 'GBP', exchange_rate: 1.153 }, { householdCurrency: 'EUR', meId: 'u1' })
    expect(toUpdateBody(s, CTX).exchange_rate).toBe('1.153')
  })
  it('copyOf makes a new entry dated today with a new client_id and no receipt', () => {
    const c = copyOf(fromTransaction(STORED, { householdCurrency: 'EUR', meId: 'u1' }), { clientId: 'cid-2', today: '2026-10-07' })
    expect(c).toMatchObject({ mode: 'new', editId: null, clientId: 'cid-2', date: '2026-10-07', storedReceiptPath: null, excludeFromSettlement: false, amount: '64.20' })
  })
})

describe('validate', () => {
  it('amount > 0, expense needs a budget, no future date', () => {
    const v = validate(expense({ amount: '', bucketId: null, date: '2026-10-08' }), V)
    expect(v.ok).toBe(false)
    expect(v.problems).toMatchObject({ amount: 'Enter an amount', bucket: 'Choose a budget', date: "Date can't be in the future" })
    expect(firstProblem(v.problems)).toBe('Choose a budget')
    expect(validate(expense({ type: 'income', bucketId: null }), V).ok).toBe(true)
    expect(validate(expense({ fixedCost: true, bucketId: null }), V).ok).toBe(true)
  })
  it('a foreign currency needs a valid rate', () => {
    expect(validate(expense({ currency: 'USD', rate: '' }), V).problems.rate).toBe('Enter the rate')
    expect(validate(expense({ currency: 'USD', rate: '0.92' }), V).ok).toBe(true)
  })
  it('a fuel price, if entered, is above 0', () => {
    expect(validate(expense({ categoryId: 'c-fuel', fuelPrice: '0' }), V).problems.fuel).toBe('Price must be above 0')
    expect(validate(expense({ categoryId: 'c-fuel', fuelPrice: '' }), V).ok).toBe(true)
  })
  it('splits within the total; own share must add up to the total within a cent', () => {
    const over = [{ user_id: 'u1', amount: '3.00' }, { user_id: 'u2', amount: '2.00' }]
    expect(validate(expense({ splitOn: true, splits: over }), V).problems.split).toBe('Fix the split')
    const short = [{ user_id: 'u1', amount: '2.00' }, { user_id: 'u2', amount: '2.00' }]
    expect(validate(expense({ ownShare: true, paidBy: null, splits: short }), V).problems.split).toBe('Fix the split')
    const ok = [{ user_id: 'u1', amount: '2.05' }, { user_id: 'u2', amount: '2.04' }]
    expect(validate(expense({ ownShare: true, paidBy: null, splits: ok }), V).ok).toBe(true)
  })
  it('my wallet: blocked above a known stash (converted), allowed when the stash is unknown', () => {
    const s = expense({ amount: '60', method: 'cash', tookFrom: 'stash', cashMode: true })
    expect(validate(s, { ...V, stashCents: 5000 }).problems.wallet).toBe('Your wallet has €50.00')
    expect(validate(s, V).ok).toBe(true)
    expect(validate({ ...s, currency: 'GBP', rate: '0.8' }, { ...V, stashCents: 5000 }).ok).toBe(true) // £60 at 0.8 = €48
  })
  it('cash taken must be paid by you (Review Focus 4)', () => {
    expect(validate(expense({ method: 'cash', tookFrom: 'bank', paidBy: 'u2' }), V).problems.payer).toBe('Cash taken must be paid by you')
    expect(validate(expense({ method: 'cash', tookFrom: 'none', paidBy: 'u2' }), V).ok).toBe(true)
  })
})

describe('dirty', () => {
  it('a new entry is dirty once it has an amount, merchant or notes', () => {
    expect(isDirtyNew(expense({ amount: '' }))).toBe(false)
    expect(isDirtyNew(expense({ amount: '0.' }))).toBe(false)
    expect(isDirtyNew(expense({ amount: '', notes: 'x' }))).toBe(true)
  })
  it('More shows a dot when something inside differs from its default', () => {
    const c = { ...CTX, today: '2026-10-07' }
    expect(moreDirty(expense(), c)).toBe(false)
    expect(moreDirty(expense({ date: '2026-10-06' }), c)).toBe(true)
    expect(moreDirty(expense({ countInForecast: false }), c)).toBe(true)
    expect(moreDirty(expense({ currency: 'GBP' }), c)).toBe(true)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/model.test.ts`
Expected: FAIL with "Failed to resolve import ./model".

- [ ] **Step 3: Implement `web/src/features/composer/model.ts`**

```ts
import type { components } from '../../api/schema'
import { centsToString, convertCents, fromApiAmount, parseFuelPrice, parseRate, toCents } from './amount'
import { formatCents } from './currencies'
import { blankState, type ComposerState, type Method, METHODS } from './state'
import type { Txn } from './types'

export type CreateBody = components['schemas']['TransactionCreate']
export type UpdateBody = components['schemas']['TransactionUpdate']
export interface ModelCtx { householdCurrency: string; fuelCategoryId: string | null }

const decimal = (s: string) => s.trim().replace(',', '.')

export const isFuel = (s: ComposerState, ctx: ModelCtx): boolean =>
  s.type === 'expense' && ctx.fuelCategoryId !== null && s.categoryId === ctx.fuelCategoryId

const tookCash = (s: ComposerState) => s.type === 'expense' && s.method === 'cash' && s.tookFrom !== 'none' && !s.ownShare

export function toCreateBody(s: ComposerState, ctx: ModelCtx): CreateBody {
  const body: CreateBody = {
    type: s.type,
    amount: centsToString(toCents(s.amount)),
    currency: s.currency,
    exchange_rate: s.currency === ctx.householdCurrency ? '1' : decimal(s.rate),
    bucket_id: s.fixedCost ? null : s.bucketId,
    category_id: s.categoryId,
    merchant: s.merchant.trim() || null,
    paid_by: s.ownShare ? null : s.paidBy,
    payer_mode: s.ownShare ? 'own_share' : 'single',
    payment_method: s.method,
    took_cash: tookCash(s),
    transaction_date: s.date,
    notes: s.notes.trim() || null,
    splits: s.type === 'expense' && (s.ownShare || s.splitOn) ? s.splits.map((x) => ({ user_id: x.user_id, amount: x.amount })) : [],
    exclude_from_forecast: !s.countInForecast,
    exclude_from_settlement: false,
    client_id: s.clientId,
  }
  if (body.took_cash) body.take_from = s.tookFrom
  if (isFuel(s, ctx) && s.fuelPrice.trim() !== '') body.fuel_price_per_litre = decimal(s.fuelPrice)
  return body
}

/** Full replacement (spec §4.10): no client_id or take, stored settlement flag, fuel price explicit. */
export function toUpdateBody(s: ComposerState, ctx: ModelCtx): UpdateBody {
  const { client_id: _client, take_from: _take, fuel_price_per_litre: _fuel, ...rest } = toCreateBody(s, ctx)
  return {
    ...rest,
    took_cash: false,
    exclude_from_settlement: s.excludeFromSettlement,
    fuel_price_per_litre: isFuel(s, ctx) && s.fuelPrice.trim() !== '' ? decimal(s.fuelPrice) : null,
  }
}

const asMethod = (m: string | null): Method => (METHODS as readonly string[]).includes(m ?? '') ? (m as Method) : 'card'

export function fromTransaction(t: Txn, c: { householdCurrency: string; meId: string }): ComposerState {
  const ownShare = t.payer_mode === 'own_share'
  const splits = t.splits.map((x) => ({ user_id: x.user_id, amount: centsToString(Math.round(Number(x.amount) * 100)) }))
  return {
    ...blankState({ type: t.type === 'income' ? 'income' : 'expense', currency: t.currency, date: t.transaction_date ?? '', clientId: null, meId: c.meId }),
    mode: 'edit',
    editId: t.id,
    amount: fromApiAmount(t.amount),
    rate: t.currency === c.householdCurrency ? '1' : String(t.exchange_rate),
    merchant: t.merchant ?? '',
    bucketId: t.bucket_id,
    fixedCost: t.type === 'expense' && t.bucket_id === null && t.recurring_bill_id !== null,
    categoryId: t.category_id,
    paidBy: ownShare ? null : t.paid_by,
    ownShare,
    method: asMethod(t.payment_method),
    notes: t.notes ?? '',
    fuelPrice: t.fuel_price_per_litre == null ? '' : String(t.fuel_price_per_litre),
    splitOn: !ownShare && splits.length > 0,
    splitMode: 'amounts',
    splits,
    countInForecast: !t.exclude_from_forecast,
    excludeFromSettlement: t.exclude_from_settlement,
    storedReceiptPath: t.receipt_path,
    touched: ['bucket', 'category', 'payer', 'method'],
  }
}

/** /new?from=<id>: the old "Duplicate" action. */
export function copyOf(s: ComposerState, c: { clientId: string; today: string }): ComposerState {
  return {
    ...s, mode: 'new', editId: null, clientId: c.clientId, date: c.today, storedReceiptPath: null, receipt: null,
    excludeFromSettlement: false, fixedCost: false, bucketId: s.fixedCost ? null : s.bucketId,
  }
}

/** The amount in household cents, or null when a foreign rate is missing. */
export function homeCents(s: ComposerState, householdCurrency: string): number | null {
  const cents = toCents(s.amount)
  if (s.currency === householdCurrency) return cents
  const rate = parseRate(s.rate)
  return rate === null ? null : convertCents(cents, rate)
}

export type Problem = 'amount' | 'bucket' | 'date' | 'rate' | 'fuel' | 'split' | 'wallet' | 'payer'
export interface ValidateCtx extends ModelCtx { today: string; stashCents: number | null; meId: string }
export interface Validation { ok: boolean; problems: Partial<Record<Problem, string>> }

export function validate(s: ComposerState, c: ValidateCtx): Validation {
  const p: Partial<Record<Problem, string>> = {}
  const cents = toCents(s.amount)
  if (cents <= 0) p.amount = 'Enter an amount'
  if (s.type === 'expense' && !s.bucketId && !s.fixedCost) p.bucket = 'Choose a budget'
  if (s.date > c.today) p.date = "Date can't be in the future"
  if (s.currency !== c.householdCurrency && parseRate(s.rate) === null) p.rate = 'Enter the rate'
  if (isFuel(s, c) && s.fuelPrice.trim() !== '' && parseFuelPrice(s.fuelPrice) === null) p.fuel = 'Price must be above 0'
  if (s.type === 'expense' && (s.splitOn || s.ownShare)) {
    const sum = s.splits.reduce((a, x) => a + toCents(x.amount), 0)
    if (s.ownShare ? Math.abs(sum - cents) > 1 : sum > cents) p.split = 'Fix the split'
  }
  if (tookCash(s) && s.paidBy !== c.meId) p.payer = 'Cash taken must be paid by you'
  if (tookCash(s) && s.tookFrom === 'stash' && c.stashCents !== null) {
    const home = homeCents(s, c.householdCurrency)
    if (home !== null && home > c.stashCents) p.wallet = `Your wallet has ${formatCents(c.stashCents, c.householdCurrency)}`
  }
  return { ok: Object.keys(p).length === 0, problems: p }
}

const HINT_ORDER: Problem[] = ['bucket', 'rate', 'date', 'split', 'wallet', 'payer', 'fuel']

/** The reason shown above the keypad when Save is disabled (an empty amount needs no words). */
export const firstProblem = (p: Validation['problems']): string | null =>
  HINT_ORDER.map((k) => p[k]).find((x) => x !== undefined) ?? null

export const isDirtyNew = (s: ComposerState): boolean =>
  toCents(s.amount) > 0 || s.notes.trim() !== '' || s.merchant.trim() !== ''

export function moreDirty(s: ComposerState, c: ModelCtx & { today: string }): boolean {
  return (
    s.date !== c.today ||
    s.notes.trim() !== '' ||
    (isFuel(s, c) && s.fuelPrice.trim() !== '') ||
    s.currency !== c.householdCurrency ||
    s.splitOn ||
    !s.countInForecast ||
    s.receipt !== null ||
    s.storedReceiptPath !== null
  )
}
```

- [ ] **Step 4: Run the test and the type check**

Run: `cd web && npm test -- src/features/composer/model.test.ts && npm run typecheck`
Expected: PASS. If typecheck complains that a `TransactionUpdate` field is required (openapi-typescript marks defaulted fields required), add that field to `toUpdateBody`'s returned object with the value `toCreateBody` already produces.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/model.ts web/src/features/composer/model.test.ts
git commit -m "feat(composer): state to API mapping, edit round-trip, validation"
```

### Task C2-5: Data and save hooks (`useComposerData`, `useDefaults`, `pendingStore`, `useSaveTransaction`, undo)

**Stream:** C2 · **Depends on:** C1-1, C2-3, C2-4

**Files:**
- Create: `web/src/features/composer/hooks/useComposerData.ts`, `hooks/useDefaults.ts`, `hooks/pendingStore.ts`, `hooks/useSaveTransaction.ts`, `hooks/undo.ts`
- Test: `web/src/features/composer/hooks/useSaveTransaction.test.tsx`

**Interfaces:**
- Consumes: `api` (`web/src/api/client.ts`), `enqueue` (`web/src/offline/queue.ts`), `useSession` (`me.id`, `me.household_id`), the bridge (C1-1), `toCreateBody`/`toUpdateBody`/`CreateBody`/`UpdateBody` (C2-4), `learn`/`saveDefaults`/`loadDefaults`/`shouldOfferRemember`/`RULES_API_READY`/`fuelCategoryId` (C2-3).
- Produces:
  - `useComposerData.ts`: `interface ComposerData { hh; meId; buckets: Bucket[]; categories: Category[]; members: Member[]; householdCurrency: string; rules: Rule[]; merchants: string[]; fuelCategoryId: string | null; ready: boolean }`; `useComposerData(): ComposerData`; `useStash(): number | null` (cents, null when unknown); `useTransaction(id: string): { txn: Txn | undefined; status: 'loading' | 'ready' | 'missing' | 'offline' }`.
  - `useDefaults.ts`: `useDefaults(hh: string): DefaultsRecord | undefined`.
  - `pendingStore.ts`: `interface PendingRow { key; id: string | null; client_id: string | null; type: 'expense'|'income'; amount: string; currency; bucket_id; category_id; merchant; transaction_date; state: 'sending' | 'waiting' }`; `pendingStore.{subscribe, snapshot, addInFlight, removeInFlight, hide, unhide, markJustSaved, reset}`; `interface BodyLike`; `rowFromBody(body, state, id?)`. C5-2 and C5-3 read it.
  - `useSaveTransaction.ts`: `interface SaveCtx { hh: string; householdCurrency: string; fuelCategoryId: string | null; meId: string }`; `type SaveOutcome = { status: 'done'; id: string } | { status: 'queued' } | { status: 'failed'; detail: string } | { status: 'busy' }`; `useSaveTransaction(state, ctx, defaults): { saveNew(): Promise<SaveOutcome>; saveEdit(): Promise<SaveOutcome>; deleteEntry(): Promise<SaveOutcome>; saving: boolean }`.
  - `undo.ts`: `useUndoCreate(): (id: string) => Promise<void>`.

- [ ] **Step 1: Write the failing test**

`web/src/features/composer/hooks/useSaveTransaction.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db, wipe } from '../../../offline/db'
import { setIdentity } from '../../../offline/identity'
import { replay } from '../../../offline/queue'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv, setOnline, testQueryClient } from '../../../test/render'
import { ToastHost } from '../bridge'
import { EMPTY_DEFAULTS, loadDefaults } from '../defaults'
import { blankState, type ComposerState } from '../state'
import { goOffline, loose, writes } from '../testHelpers'
import { pendingStore } from './pendingStore'
import { type SaveOutcome, useSaveTransaction } from './useSaveTransaction'

const CTX = { hh: 'h1', householdCurrency: 'EUR', fuelCategoryId: null, meId: 'u1' }
const STATE: ComposerState = {
  ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'cid-1', meId: 'u1' }),
  amount: '3', bucketId: 'b-day',
}
const CREATED = { id: 't1', amount: 3, currency: 'EUR', type: 'expense' }

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
})
afterEach(resetTestEnv)

function setup(state: ComposerState = STATE) {
  const qc = testQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}><ToastHost>{children}</ToastHost></QueryClientProvider>
  )
  return renderHook(() => useSaveTransaction(state, CTX, EMPTY_DEFAULTS), { wrapper })
}
type Hook = ReturnType<typeof setup>
async function saveNew(h: Hook): Promise<SaveOutcome> {
  let r!: SaveOutcome
  await act(async () => { r = await h.result.current.saveNew() })
  return r
}

it('online success returns the id; the optimistic row is replaced by the highlight', async () => {
  let during: string[] = []
  const api = fakeApi(loose({
    'POST /api/v1/transactions': () => {
      during = pendingStore.snapshot().inFlight.map((r) => r.key)
      return Response.json(CREATED, { status: 201 })
    },
  }))
  expect(await saveNew(setup())).toEqual({ status: 'done', id: 't1' })
  expect(during).toEqual(['cid-1'])
  expect(pendingStore.snapshot()).toMatchObject({ inFlight: [], justSaved: 't1' })
  expect(writes(api)).toHaveLength(1)
})

it('a network error queues the body with the same client_id; the defaults are written anyway', async () => {
  goOffline()
  expect(await saveNew(setup())).toEqual({ status: 'queued' })
  expect(await db.queue.count()).toBe(1)
  expect((await loadDefaults('h1')).last?.bucket_id).toBe('b-day')
})

it('the replay of a request whose response was lost gets 200 for the same client_id: one row', async () => {
  goOffline()
  await saveNew(setup())
  vi.restoreAllMocks()
  setOnline(true)
  const api = fakeApi(loose({
    'GET /api/v1/auth/me': { id: 'u1', household_id: 'h1' },
    'POST /api/v1/transactions': () => Response.json(CREATED, { status: 200 }), // already created server-side
  }))
  expect(await replay({ force: true })).toMatchObject({ sent: 1, failed: 0 })
  expect(await db.queue.count()).toBe(0)
  expect(writes(api).map((c) => (c.body as { client_id: string }).client_id)).toEqual(['cid-1'])
})

it('a second save while one is in flight is refused: one POST', async () => {
  let release: (() => void) | undefined
  const api = fakeApi(loose({
    'POST /api/v1/transactions': () =>
      new Promise<Response>((resolve) => { release = () => resolve(Response.json(CREATED, { status: 201 })) }),
  }))
  const h = setup()
  let first!: Promise<SaveOutcome>
  let second!: Promise<SaveOutcome>
  act(() => {
    first = h.result.current.saveNew()
    second = h.result.current.saveNew()
  })
  await vi.waitFor(() => expect(release).toBeDefined())
  release!()
  await act(async () => { await first })
  expect(await second).toEqual({ status: 'busy' })
  expect(await first).toEqual({ status: 'done', id: 't1' })
  expect(writes(api)).toHaveLength(1)
})

it('delete: a 404 counts as success, without an error toast', async () => {
  fakeApi(loose({ 'DELETE /api/v1/transactions/t9': () => Response.json({ detail: 'Transaction not found' }, { status: 404 }) }))
  const h = setup({ ...STATE, mode: 'edit', editId: 't9', clientId: null })
  let r!: SaveOutcome
  await act(async () => { r = await h.result.current.deleteEntry() })
  expect(r).toEqual({ status: 'done', id: 't9' })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/hooks/useSaveTransaction.test.tsx`
Expected: FAIL with "Failed to resolve import ./pendingStore".

- [ ] **Step 3: Implement**

`hooks/useComposerData.ts`:

```ts
import { api } from '../../../api/client'
import { useSession } from '../../../session/SessionProvider'
import {
  ApiError, type Bucket, type Category, editKey, keys, type Member, merchantsKey, toTransactionPage, unwrap,
  useBuckets, useCachedQuery, useCategories, useHousehold,
} from '../bridge'
import { fuelCategoryId, RULES_API_READY } from '../defaults'
import type { CashMovements, Rule, Txn } from '../types'

export interface ComposerData {
  hh: string
  meId: string
  buckets: Bucket[]
  categories: Category[]
  members: Member[]
  householdCurrency: string
  rules: Rule[]
  /** Distinct recent merchants, newest first (suggestions only). */
  merchants: string[]
  fuelCategoryId: string | null
  /** Buckets, categories and household have data or are definitely unavailable: the composer can open. */
  ready: boolean
}

/**
 * 2d's list (2d spec §7.4); stored as the server sends it, since 2d's Settings shares this key.
 * Empty until RULES_API_READY: the path is not in the generated types before that.
 */
async function fetchRules(signal: AbortSignal): Promise<Rule[]> {
  if (!RULES_API_READY) return []
  const raw = await unwrap(
    api.GET('/api/v1/settings/category-rules' as never, { signal } as never) as Promise<{ data?: unknown; error?: unknown; response: Response }>,
  )
  return Array.isArray(raw) ? (raw as Rule[]) : []
}

export function useComposerData(): ComposerData {
  const { me } = useSession()
  const household = useHousehold()
  const buckets = useBuckets()
  const categories = useCategories()
  const rules = useCachedQuery(keys.categoryRules(), fetchRules)
  const recent = useCachedQuery(merchantsKey, async (signal) =>
    toTransactionPage(await unwrap(api.GET('/api/v1/transactions', { params: { query: { page_size: 200 } }, signal }))),
  )
  const cats = categories.data ?? []
  const merchants = [...new Set((recent.data?.items ?? []).map((t) => t.merchant).filter((m): m is string => !!m))]
  return {
    hh: me?.household_id ?? '',
    meId: me?.id ?? '',
    buckets: buckets.data ?? [],
    categories: cats,
    members: household.data?.members ?? [],
    householdCurrency: household.data?.default_currency ?? 'EUR',
    rules: rules.data ?? [],
    merchants,
    fuelCategoryId: fuelCategoryId(cats),
    ready: !buckets.isLoading && !categories.isLoading && !household.isLoading,
  }
}

/** The signed-in user's wallet in cents; null when never loaded. Mount only where cash is in play. */
export function useStash(): number | null {
  const q = useCachedQuery(keys.cashStash(), async (signal) =>
    (await unwrap(api.GET('/api/v1/cash/movements', { params: { query: { limit: 1 } }, signal }))) as CashMovements,
  )
  return q.data ? Math.round(Number(q.data.stash) * 100) : null
}

/** The stored transaction for edit and copy; a 404 is cached as null ("This entry no longer exists"). */
export function useTransaction(id: string): { txn: Txn | undefined; status: 'loading' | 'ready' | 'missing' | 'offline' } {
  const q = useCachedQuery<Txn | null>(editKey(id), async (signal) => {
    try {
      return (await unwrap(api.GET('/api/v1/transactions/{txn_id}', { params: { path: { txn_id: id } }, signal }))) as Txn
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  })
  if (q.data === null) return { txn: undefined, status: 'missing' }
  if (q.data) return { txn: q.data, status: 'ready' }
  return { txn: undefined, status: q.noData ? 'offline' : 'loading' }
}
```

`hooks/useDefaults.ts`:

```ts
import { useEffect, useState } from 'react'
import { type DefaultsRecord, loadDefaults } from '../defaults'

export function useDefaults(hh: string): DefaultsRecord | undefined {
  const [rec, setRec] = useState<DefaultsRecord>()
  useEffect(() => {
    let live = true
    void loadDefaults(hh).then((r) => { if (live) setRec(r) })
    return () => { live = false }
  }, [hh])
  return rec
}
```

`hooks/pendingStore.ts`:

```ts
/**
 * In-memory rows for saves in flight, ids hidden by a delete, and the id to highlight on Home
 * (spec §4.12, §5.3). Queued writes that survive a reload come from the queue itself (C5-2).
 */
export interface PendingRow {
  /** client_id for a create, the transaction id for an edit. */
  key: string
  id: string | null
  client_id: string | null
  type: 'expense' | 'income'
  /** Decimal string as sent, e.g. "3.00". */
  amount: string
  currency: string
  bucket_id: string | null
  category_id: string | null
  merchant: string | null
  transaction_date: string
  state: 'sending' | 'waiting'
}

interface Snapshot { inFlight: readonly PendingRow[]; hidden: ReadonlySet<string>; justSaved: string | null }

const HIGHLIGHT_MS = 2000
const EMPTY: Snapshot = { inFlight: [], hidden: new Set(), justSaved: null }
let snap: Snapshot = EMPTY
const listeners = new Set<() => void>()
const set = (next: Partial<Snapshot>) => {
  snap = { ...snap, ...next }
  listeners.forEach((l) => l())
}

export const pendingStore = {
  subscribe(l: () => void): () => void {
    listeners.add(l)
    return () => { listeners.delete(l) }
  },
  snapshot: (): Snapshot => snap,
  addInFlight(row: PendingRow) { set({ inFlight: [row, ...snap.inFlight.filter((r) => r.key !== row.key)] }) },
  removeInFlight(key: string) { set({ inFlight: snap.inFlight.filter((r) => r.key !== key) }) },
  hide(id: string) { set({ hidden: new Set([...snap.hidden, id]) }) },
  unhide(id: string) {
    const h = new Set(snap.hidden)
    h.delete(id)
    set({ hidden: h })
  },
  markJustSaved(id: string) {
    set({ justSaved: id })
    setTimeout(() => { if (snap.justSaved === id) set({ justSaved: null }) }, HIGHLIGHT_MS)
  },
  reset() { set(EMPTY) },
}

export interface BodyLike {
  client_id?: string | null
  type?: string
  amount: string | number
  currency: string
  bucket_id?: string | null
  category_id?: string | null
  merchant?: string | null
  transaction_date?: string | null
}

export function rowFromBody(body: BodyLike, state: PendingRow['state'], id: string | null = null): PendingRow {
  return {
    key: id ?? body.client_id ?? '',
    id,
    client_id: body.client_id ?? null,
    type: body.type === 'income' ? 'income' : 'expense',
    amount: String(body.amount),
    currency: body.currency,
    bucket_id: body.bucket_id ?? null,
    category_id: body.category_id ?? null,
    merchant: body.merchant ?? null,
    transaction_date: body.transaction_date ?? '',
    state,
  }
}
```

`hooks/useSaveTransaction.ts` (bodies are passed as `run(vars)`, so a send never uses a stale render):

```ts
import { useRef, useState } from 'react'
import { type ActionResult, afterTxnWrite, editKey, keys, toast, useAction } from '../bridge'
import { type DefaultsRecord, learn, RULES_API_READY, saveDefaults, shouldOfferRemember } from '../defaults'
import { type CreateBody, toCreateBody, toUpdateBody, type UpdateBody } from '../model'
import type { ComposerState } from '../state'
import type { Txn } from '../types'
import { pendingStore, rowFromBody } from './pendingStore'

export interface SaveCtx { hh: string; householdCurrency: string; fuelCategoryId: string | null; meId: string }
export type SaveOutcome =
  | { status: 'done'; id: string }
  | { status: 'queued' }
  | { status: 'failed'; detail: string }
  | { status: 'busy' }

export function useSaveTransaction(state: ComposerState, ctx: SaveCtx, defaults: DefaultsRecord) {
  const id = state.editId ?? ''
  const create = useAction<CreateBody, Txn>({
    method: 'POST', path: '/api/v1/transactions', body: (b) => b, invalidates: afterTxnWrite,
  })
  const update = useAction<UpdateBody, Txn>({
    method: 'PUT',
    path: `/api/v1/transactions/${id}`,
    body: (b) => b,
    invalidates: afterTxnWrite,
    pendingId: id,
    // Stays inside `invalidates` (editKey is under transactions.all), so 2a's rollback restores it.
    optimistic: (qc, b) =>
      qc.setQueryData<Txn | null>(editKey(id), (old) =>
        old
          ? {
              ...old,
              amount: Number(b.amount),
              currency: b.currency,
              bucket_id: b.bucket_id ?? null,
              category_id: b.category_id ?? null,
              merchant: b.merchant ?? null,
              notes: b.notes ?? null,
              paid_by: b.paid_by ?? null,
              transaction_date: b.transaction_date ?? old.transaction_date,
            }
          : old,
      ),
  })
  const remove = useAction<void, null>({
    method: 'DELETE',
    path: `/api/v1/transactions/${id}`,
    invalidates: afterTxnWrite,
    pendingId: id,
    toastRejections: false, // a 404 means "already gone"; other rejections are toasted below
    optimistic: () => pendingStore.hide(id),
  })
  const rule = useAction<{ pattern: string; category_id: string }>({
    method: 'POST', path: '/api/v1/settings/category-rules', body: (b) => b, invalidates: [keys.categoryRules()],
  })

  const busy = useRef(false)
  const [saving, setSaving] = useState(false)
  async function guard(fn: () => Promise<SaveOutcome>): Promise<SaveOutcome> {
    if (busy.current) return { status: 'busy' }
    busy.current = true
    setSaving(true)
    try {
      return await fn()
    } finally {
      busy.current = false
      setSaving(false)
    }
  }
  const outcome = (r: ActionResult<unknown>, knownId?: string): SaveOutcome =>
    r.status === 'done'
      ? { status: 'done', id: knownId ?? (r.data as { id: string }).id }
      : r.status === 'queued'
        ? { status: 'queued' }
        : { status: 'failed', detail: r.detail }

  const saveNew = () =>
    guard(async () => {
      const body = toCreateBody(state, ctx)
      const key = state.clientId ?? ''
      pendingStore.addInFlight(rowFromBody(body, 'sending'))
      try {
        // Spec §4.3: written when Save is tapped, whether the save goes online or is queued.
        await saveDefaults(ctx.hh, learn(defaults, state, ctx))
        const r = outcome(await create.run(body))
        if (r.status === 'done') pendingStore.markJustSaved(r.id)
        if (r.status !== 'failed' && state.rememberRule && state.categoryId && shouldOfferRemember(state, RULES_API_READY)) {
          await rule.run({ pattern: state.merchant.trim(), category_id: state.categoryId })
        }
        return r
      } finally {
        pendingStore.removeInFlight(key)
      }
    })

  const saveEdit = () => guard(async () => outcome(await update.run(toUpdateBody(state, ctx)), id))

  const deleteEntry = () =>
    guard(async () => {
      const r = await remove.run()
      if (r.status === 'rejected' && r.code === 404) return { status: 'done', id }
      if (r.status === 'rejected') {
        pendingStore.unhide(id)
        if (r.code !== 401) toast(r.detail, { tone: 'error' })
      }
      return outcome(r, id)
    })

  return { saveNew, saveEdit, deleteEntry, saving }
}
```

`hooks/undo.ts`:

```ts
import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '../../../api/client'
import { enqueue } from '../../../offline/queue'
import { afterTxnWrite } from '../bridge'
import { pendingStore } from './pendingStore'

/** Undo of an online save (spec §4.12): DELETE the new row. Runs from a toast, after the composer closed. */
export function useUndoCreate(): (id: string) => Promise<void> {
  const qc = useQueryClient()
  return useCallback(
    async (id: string) => {
      pendingStore.hide(id)
      try {
        const { response } = await api.DELETE('/api/v1/transactions/{txn_id}', { params: { path: { txn_id: id } } })
        if (!response.ok && response.status !== 404) pendingStore.unhide(id)
      } catch {
        await enqueue({ method: 'DELETE', path: `/api/v1/transactions/${id}` }).catch(() => pendingStore.unhide(id))
      }
      await Promise.all(afterTxnWrite.map((queryKey) => qc.invalidateQueries({ queryKey })))
    },
    [qc],
  )
}
```

- [ ] **Step 4: Run the test**

Run: `cd web && npm test -- src/features/composer/hooks/useSaveTransaction.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/hooks
git commit -m "feat(composer): cached reads, defaults loader, pending rows, save/edit/delete with client_id, undo"
```

### Task C2-6: Duplicate check and receipt upload hooks

**Stream:** C2 · **Depends on:** C1-1, C3-2 (generated `check-duplicate` types)

**Files:**
- Create: `web/src/features/composer/receipt.ts`, `hooks/useDuplicateCheck.ts`, `hooks/useReceiptUpload.ts`
- Test: `web/src/features/composer/receipt.test.ts`, `web/src/features/composer/hooks/sideCalls.test.tsx`

**Interfaces:**
- Produces: `RECEIPT_MAX_BYTES`, `RECEIPT_EXTENSIONS`, `RECEIPT_ACCEPT = 'image/*,application/pdf'`, `receiptProblem(file: File): 'Max 10 MB' | 'Unsupported file type' | null`; `DUPLICATE_TIMEOUT_MS = 2000`; `useDuplicateCheck(): (q: { amount: string; transaction_date: string; bucket_id: string | null }) => Promise<Duplicate[]>` (never rejects; `[]` offline, on error or after 2 s); `useReceiptUpload(): (id: string, file: File) => Promise<'ok' | 'failed'>`.

- [ ] **Step 1: Write the failing tests**

`web/src/features/composer/receipt.test.ts`:

```ts
import { expect, it } from 'vitest'
import { receiptProblem } from './receipt'

const file = (name: string, size = 10) => {
  const f = new File(['x'], name)
  Object.defineProperty(f, 'size', { value: size })
  return f
}

it('accepts the server extensions up to 10 MB', () => {
  for (const n of ['a.jpg', 'a.JPEG', 'a.png', 'a.gif', 'a.webp', 'a.pdf', 'a.heic', 'a.HEIF']) expect(receiptProblem(file(n))).toBeNull()
  expect(receiptProblem(file('a.jpg', 10 * 1024 * 1024))).toBeNull()
})
it('refuses other types and anything over 10 MB', () => {
  expect(receiptProblem(file('a.txt'))).toBe('Unsupported file type')
  expect(receiptProblem(file('noext'))).toBe('Unsupported file type')
  expect(receiptProblem(file('a.jpg', 10 * 1024 * 1024 + 1))).toBe('Max 10 MB')
})
```

`web/src/features/composer/hooks/sideCalls.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../../../test/render'
import { goOffline, loose } from '../testHelpers'
import { useDuplicateCheck } from './useDuplicateCheck'
import { useReceiptUpload } from './useReceiptUpload'

afterEach(resetTestEnv)

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={testQueryClient()}>{children}</QueryClientProvider>
)
const DUP = { id: 't7', amount: 3, currency: 'EUR', date: '2026-10-06', notes: null, merchant: 'Coffee Island', bucket: 'Day to day', paid_by: 'Maria', same_bucket: true }
const Q = { amount: '3.00', transaction_date: '2026-10-07', bucket_id: 'b-day' }

it('duplicate check returns the server matches and sends the query', async () => {
  const api = fakeApi(loose({ 'GET /api/v1/transactions/check-duplicate': { duplicates: [DUP] } }))
  const { result } = renderHook(() => useDuplicateCheck(), { wrapper })
  expect(await result.current(Q)).toEqual([DUP])
  expect(Object.fromEntries(api.calls[0].query)).toEqual({ amount: '3.00', transaction_date: '2026-10-07', bucket_id: 'b-day' })
})

it('duplicate check gives up after 2 seconds, and ignores errors and offline', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  fakeApi(loose({ 'GET /api/v1/transactions/check-duplicate': () => new Promise<Response>(() => {}) }))
  const { result } = renderHook(() => useDuplicateCheck(), { wrapper })
  const p = result.current(Q)
  await vi.advanceTimersByTimeAsync(2000)
  expect(await p).toEqual([])
  vi.useRealTimers()
  vi.restoreAllMocks()
  fakeApi(loose({ 'GET /api/v1/transactions/check-duplicate': () => new Response('boom', { status: 500 }) }))
  expect(await result.current(Q)).toEqual([])
  vi.restoreAllMocks()
  goOffline()
  expect(await result.current(Q)).toEqual([])
})

it('receipt upload posts the file as multipart and reports failures', async () => {
  let status = 200
  const api = fakeApi(loose({
    'POST /api/v1/transactions/{txn_id}/receipt': () =>
      status === 200 ? Response.json({ receipt_path: 'x.jpg' }) : Response.json({ detail: 'File too large (max 10 MB)' }, { status }),
  }))
  const { result } = renderHook(() => useReceiptUpload(), { wrapper })
  const file = new File(['img'], 'r.jpg', { type: 'image/jpeg' })
  let r!: string
  await act(async () => { r = await result.current('t1', file) })
  expect(r).toBe('ok')
  expect(api.calls[0].path).toBe('/api/v1/transactions/t1/receipt')
  expect((api.calls[0].body as FormData).get('file')).toBeInstanceOf(File)
  status = 413
  await act(async () => { r = await result.current('t1', file) })
  expect(r).toBe('failed')
})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && npm test -- src/features/composer/receipt.test.ts src/features/composer/hooks/sideCalls.test.tsx`
Expected: FAIL with "Failed to resolve import ./receipt".

- [ ] **Step 3: Implement**

`web/src/features/composer/receipt.ts`:

```ts
/** Mirrors app/api/transactions.py: MAX_RECEIPT_SIZE and ALLOWED_RECEIPT_EXTENSIONS. */
export const RECEIPT_MAX_BYTES = 10 * 1024 * 1024
export const RECEIPT_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.heic', '.heif']
export const RECEIPT_ACCEPT = 'image/*,application/pdf'

export function receiptProblem(file: File): 'Max 10 MB' | 'Unsupported file type' | null {
  const ext = /\.[^.]+$/.exec(file.name.toLowerCase())?.[0] ?? ''
  if (!RECEIPT_EXTENSIONS.includes(ext)) return 'Unsupported file type'
  if (file.size > RECEIPT_MAX_BYTES) return 'Max 10 MB'
  return null
}
```

`hooks/useDuplicateCheck.ts`:

```ts
import { useCallback } from 'react'
import { api } from '../../../api/client'
import type { Duplicate } from '../types'

export const DUPLICATE_TIMEOUT_MS = 2000

/** Advisory, never blocking (spec §4.11): offline, an error or 2 s without an answer all mean "none". */
export function useDuplicateCheck() {
  return useCallback(async (q: { amount: string; transaction_date: string; bucket_id: string | null }): Promise<Duplicate[]> => {
    if (!navigator.onLine) return []
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<Duplicate[]>((resolve) => {
      timer = setTimeout(() => {
        ctl.abort()
        resolve([])
      }, DUPLICATE_TIMEOUT_MS)
    })
    const request = api
      .GET('/api/v1/transactions/check-duplicate', {
        params: { query: { amount: q.amount, transaction_date: q.transaction_date, bucket_id: q.bucket_id ?? '' } },
        signal: ctl.signal,
      })
      .then(({ data, response }) => (response.ok && data ? (data.duplicates as Duplicate[]) : []))
      .catch(() => [] as Duplicate[])
    try {
      return await Promise.race([request, timeout])
    } finally {
      clearTimeout(timer)
    }
  }, [])
}
```

`hooks/useReceiptUpload.ts`:

```ts
import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { readCsrf } from '../../../api/client'
import { editKey } from '../bridge'

/**
 * POST /transactions/{id}/receipt (multipart). Raw fetch because the queue holds JSON only and the
 * typed client would JSON-encode the body; receipts therefore need a connection (spec §5.4).
 */
export function useReceiptUpload() {
  const qc = useQueryClient()
  return useCallback(
    async (id: string, file: File): Promise<'ok' | 'failed'> => {
      const form = new FormData()
      form.append('file', file, file.name)
      try {
        const res = await fetch(`/api/v1/transactions/${encodeURIComponent(id)}/receipt`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'X-CSRF-Token': readCsrf() },
          body: form,
        })
        if (!res.ok) return 'failed'
        await qc.invalidateQueries({ queryKey: editKey(id) })
        return 'ok'
      } catch {
        return 'failed'
      }
    },
    [qc],
  )
}
```

- [ ] **Step 4: Run the tests**

Run: `cd web && npm test -- src/features/composer/receipt.test.ts src/features/composer/hooks/sideCalls.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/receipt.ts web/src/features/composer/receipt.test.ts web/src/features/composer/hooks/useDuplicateCheck.ts web/src/features/composer/hooks/useReceiptUpload.ts web/src/features/composer/hooks/sideCalls.test.tsx
git commit -m "feat(composer): non-blocking duplicate check and receipt upload"
```

### Task C2-7: Picker sheets

**Stream:** C2 · **Depends on:** C1-1 (`Sheet`), C1-3, C2-2, C2-1 (`dates.ts`, `currencies.ts`)

**Files:**
- Create: `web/src/features/composer/pickers/labels.ts`, `BucketSheet.tsx`, `CategorySheet.tsx`, `PayerSheet.tsx`, `MethodSheet.tsx`, `CurrencySheet.tsx`, `DateSheet.tsx`, `pickers.css`
- Test: `web/src/features/composer/pickers/pickers.test.tsx`

**Interfaces:**
- Produces (every sheet closes itself after a pick by calling `onPick` then `onClose`, except "Each paid own share", which calls `onOwnShare()` only so the parent decides what opens next; every option carries `aria-pressed`, `"true"` for the current value):
  - `labels.ts`: `METHOD_LABELS: Record<Method, string>`, `memberName(m: Member | undefined): string` (`display_name ?? username ?? 'Member'`).
  - `BucketSheet({ open, onClose, buckets: Bucket[], type: TxnType, selectedId: string | null, onPick(id: string | null) })`: title "Budget". Active buckets only. Income: a "None" option first, then only `show_income` buckets; expense has no "None". Event buckets (`kind === 'event'`) show `rangeLabel(start_date, end_date)` as a second line.
  - `CategorySheet({ open, onClose, categories, recentIds: string[], suggestion: { id: string; reason: string } | null, selectedId, onPick(id: string) })`: title "Category". A search input (label "Search categories", 16 px, `type="search"`) filters by `fold` substring across all sections. Sections in order: **Suggested** (only with a suggestion: the category plus its reason, e.g. "rule: coffee island"), **Recent** (up to 4 from `recentIds` that still exist), **All** (every category). The Fuel category (`system_key === 'fuel'`) shows the second line "Asks for price per litre".
  - `PayerSheet({ open, onClose, title: 'Payer' | 'Received by', members, selectedId: string | null, ownShare: boolean, allowOwnShare: boolean, onPick(userId: string), onOwnShare() })`: one option per member (`memberName`); "Each paid own share" last, only when `allowOwnShare` (expense, more than one member, Took from is Not tracked).
  - `MethodSheet({ open, onClose, selected: Method, onPick(m: Method) })`: Card · Cash · Apple Pay · Transfer · Other.
  - `CurrencySheet({ open, onClose, selected: string, onPick(code: string) })`: the 10 `CURRENCIES`, each named `"<CODE> · <currencyName>"`.
  - `DateChips({ value: string, today: string, onPick(iso: string) })`: chips Today · Yesterday · the day before (`dayLabel`, e.g. "Mon 5 Oct") and a native `<input type="date" aria-label="Pick a date" max={today}>`; a typed date after today is not passed on. `DateSheet({ open, onClose, value, today, onPick })` wraps `DateChips` in a Sheet titled "Date" (used by the income Date pill).

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Mock screen 2 (category picker) is the reference for every sheet's list rows.

- [ ] **Step 2: Write the failing test**

`web/src/features/composer/pickers/pickers.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Bucket, Category, Member } from '../types'
import { BucketSheet } from './BucketSheet'
import { CategorySheet } from './CategorySheet'
import { CurrencySheet } from './CurrencySheet'
import { DateChips } from './DateSheet'
import { MethodSheet } from './MethodSheet'
import { PayerSheet } from './PayerSheet'

afterEach(cleanup)

const b = (id: string, name: string, over: Partial<Bucket> = {}): Bucket => ({
  id, name, kind: 'monthly', status: 'active', budget: null, start_date: null, end_date: null, show_income: false, ...over,
})
const BUCKETS = [
  b('b-day', 'Day to day'), b('b-old', 'Old budget', { status: 'archived' }), b('b-salary', 'Salary', { show_income: true }),
  b('b-crete', 'Crete', { kind: 'event', start_date: '2026-08-12', end_date: '2026-08-19' }),
]
const c = (id: string, name: string, over: Partial<Category> = {}): Category => ({
  id, name, icon: null, color: null, system_key: null, ...over,
})
const CATS = [c('c-coffee', 'Coffee'), c('c-eat', 'Eating out'), c('c-fuel', 'Fuel', { system_key: 'fuel' })]
const MEMBERS: Member[] = [
  { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'u2', role: 'member', display_name: 'Maria', username: 'm', avatar_color: null },
]

it('budget: active only; event range; expense has no None; picking closes', () => {
  const onPick = vi.fn()
  const onClose = vi.fn()
  render(<BucketSheet open onClose={onClose} buckets={BUCKETS} type="expense" selectedId="b-day" onPick={onPick} />)
  const sheet = screen.getByRole('dialog', { name: 'Budget' })
  expect(within(sheet).queryByRole('button', { name: /Old budget/ })).not.toBeInTheDocument()
  expect(within(sheet).queryByRole('button', { name: /^None/ })).not.toBeInTheDocument()
  expect(within(sheet).getByRole('button', { name: /Crete.*12–19 Aug/ })).toBeInTheDocument()
  expect(within(sheet).getByRole('button', { name: /Day to day/ })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(within(sheet).getByRole('button', { name: /Crete/ }))
  expect(onPick).toHaveBeenCalledWith('b-crete')
  expect(onClose).toHaveBeenCalled()
})

it('budget for income: None first, then income-tracking budgets only', () => {
  const onPick = vi.fn()
  render(<BucketSheet open onClose={() => {}} buckets={BUCKETS} type="income" selectedId={null} onPick={onPick} />)
  // Options carry aria-pressed; the sheet's own close button does not. "None" is the current choice.
  const options = screen.getAllByRole('button').filter((x) => x.hasAttribute('aria-pressed'))
  expect(options.map((x) => x.textContent)).toEqual(['None', 'Salary'])
  expect(screen.getByRole('button', { name: 'None' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'None' }))
  expect(onPick).toHaveBeenCalledWith(null)
})

it('category: suggested with its reason, recent, all, fuel hint, accent-free search', () => {
  render(
    <CategorySheet open onClose={() => {}} categories={CATS} recentIds={['c-eat', 'c-gone']}
      suggestion={{ id: 'c-coffee', reason: 'rule: coffee island' }} selectedId={null} onPick={() => {}} />,
  )
  expect(screen.getByRole('heading', { name: 'Suggested' })).toBeInTheDocument()
  expect(screen.getByText('rule: coffee island')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Recent' })).toBeInTheDocument()
  expect(screen.getByText('Asks for price per litre')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search categories'), { target: { value: 'FU' } })
  expect(screen.queryByRole('button', { name: /Coffee/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Fuel/ })).toBeInTheDocument()
})

it('payer: members, and own share only when allowed', () => {
  const onOwnShare = vi.fn()
  const { rerender } = render(
    <PayerSheet open onClose={() => {}} title="Payer" members={MEMBERS} selectedId="u1" ownShare={false} allowOwnShare onPick={() => {}} onOwnShare={onOwnShare} />,
  )
  fireEvent.click(screen.getByRole('button', { name: 'Each paid own share' }))
  expect(onOwnShare).toHaveBeenCalled()
  rerender(<PayerSheet open onClose={() => {}} title="Received by" members={MEMBERS} selectedId="u1" ownShare={false} allowOwnShare={false} onPick={() => {}} onOwnShare={onOwnShare} />)
  expect(screen.getByRole('dialog', { name: 'Received by' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Each paid own share' })).not.toBeInTheDocument()
})

it('method and currency lists', () => {
  const pickM = vi.fn()
  render(<MethodSheet open onClose={() => {}} selected="card" onPick={pickM} />)
  for (const n of ['Card', 'Cash', 'Apple Pay', 'Transfer', 'Other']) expect(screen.getByRole('button', { name: n })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Apple Pay' }))
  expect(pickM).toHaveBeenCalledWith('apple_pay')
  cleanup()
  const pickC = vi.fn()
  render(<CurrencySheet open onClose={() => {}} selected="EUR" onPick={pickC} />)
  fireEvent.click(screen.getByRole('button', { name: 'GBP · pounds' }))
  expect(pickC).toHaveBeenCalledWith('GBP')
})

it('date chips: today, yesterday, the day before, no future dates', () => {
  const onPick = vi.fn()
  render(<DateChips value="2026-10-07" today="2026-10-07" onPick={onPick} />)
  expect(screen.getByRole('button', { name: 'Today' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Mon 5 Oct' }))
  expect(onPick).toHaveBeenLastCalledWith('2026-10-05')
  const input = screen.getByLabelText('Pick a date')
  expect(input).toHaveAttribute('max', '2026-10-07')
  fireEvent.change(input, { target: { value: '2026-10-09' } })
  expect(onPick).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/pickers/pickers.test.tsx`
Expected: FAIL with "Failed to resolve import ./BucketSheet".

- [ ] **Step 4: Implement the six sheets and `labels.ts`**

Behaviour is fully given in **Interfaces** above. Shared rules:
- Each sheet renders the bridge `Sheet` with the title given. Options are `<button type="button" className="ck-option">` with the visible name, an optional second line (`<span className="ck-option__sub">`), and `aria-pressed` for the current value. A press calls `onPick(value)` then `onClose()`.
- Section headings in CategorySheet are `<h3>`.
- `labels.ts`:

```ts
import type { Method } from '../state'
import type { Member } from '../types'

export const METHOD_LABELS: Record<Method, string> = {
  card: 'Card', cash: 'Cash', apple_pay: 'Apple Pay', transfer: 'Transfer', other: 'Other',
}

export const memberName = (m: Member | undefined): string => m?.display_name ?? m?.username ?? 'Member'
```

- `pickers.css`: `.ck-option` rows at least 52 px, full width, left-aligned, `var(--surface)` background, `var(--line)` dividers; pressed row shows `CheckIcon` (from the bridge) in `var(--accent)`; `.ck-option__sub` 13 px `var(--muted)`; the search input 16 px with `var(--surface-2)` fill; date chips use the kit `.chip`/`.chip.on` classes in a horizontal scroll row.

- [ ] **Step 5: Run the test**

Run: `cd web && npm test -- src/features/composer/pickers/pickers.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/composer/pickers
git commit -m "feat(composer): budget, category, payer, method, currency and date pickers"
```

### Task C2-8: The composer screen (new expense, income, cash from wallet, save flow)

**Stream:** C2 · **Depends on:** C1-2, C1-3, C2-5, C2-6, C2-7

**Files:**
- Create: `web/src/features/composer/Composer.tsx`, `ComposerForm.tsx`, `CashControls.tsx`, `DuplicateCard.tsx`, `ConfirmSheet.tsx`, `MoreSheet.tsx`, `useClose.ts`, `composer.css`, `testing.tsx`
- Test: `web/src/features/composer/Composer.test.tsx`

**Interfaces:**
- Consumes: everything from C1 and C2-1..C2-7 by the names listed there; `CloseIcon` from `web/src/shell/icons.tsx`; `useBlocker`, `useNavigate`, `useSearchParams` from `react-router`.
- Produces:
  - `Composer()` (route component for `/new` and, after C2-9, `/edit/:id`), `ComposerSkeleton()`.
  - `ComposerForm({ initial: ComposerState; data: ComposerData; defaults: DefaultsRecord })`.
  - `MoreSheet({ open, onClose, s, dispatch, ctx: MoreCtx })` with `interface MoreCtx { today: string; online: boolean; householdCurrency: string; fuelCategoryId: string | null; members: Member[]; meId: string; problems: Validation['problems']; onOpenSplit?: () => void }`. C4-3 adds sections to it.
  - `CashControls({ s, dispatch, householdCurrency, onStash(cents: number | null) })`, `DuplicateCard({ dup, onOpen, onSaveAnyway })`, `ConfirmSheet({ open, title, confirmLabel, cancelLabel, danger?, onConfirm, onCancel })`, `useClose(): () => void`.
  - `testing.tsx`: fixtures `BUCKETS`, `CATEGORIES`, `HOUSEHOLD`, `DEFAULTS`, `TXN`, `created(over?)`, `baseRoutes()`, `renderComposer(url?, { routes?, defaults? })` returning `{ api, router }`. C2-9, C4-3 and C6-3 tests use it.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Open mock screens 1, 3, 6, 9, 10 and 11 in `docs/redesign/mocks/composer.html`.

- [ ] **Step 2: Write the test helper `web/src/features/composer/testing.tsx`**

```tsx
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { cachePut, wipe } from '../../offline/db'
import { setIdentity } from '../../offline/identity'
import { fakeApi } from '../../test/fakeApi'
import { testQueryClient } from '../../test/render'
import { type Bucket, type Category, type Household, ToastHost } from './bridge'
import { Composer } from './Composer'
import { type DefaultsRecord, defaultsKey, EMPTY_DEFAULTS } from './defaults'
import { pendingStore } from './hooks/pendingStore'
import { loose } from './testHelpers'
import type { Txn } from './types'

const bucket = (id: string, name: string, over: Partial<Bucket> = {}): Bucket => ({
  id, name, kind: 'monthly', status: 'active', budget: null, start_date: null, end_date: null, show_income: false, ...over,
})
const category = (id: string, name: string, over: Partial<Category> = {}): Category => ({
  id, name, icon: null, color: null, system_key: null, ...over,
})

export const BUCKETS: Bucket[] = [
  bucket('b-day', 'Day to day'),
  bucket('b-car', 'Car'),
  bucket('b-old', 'Old budget', { status: 'archived' }),
  bucket('b-salary', 'Salary', { show_income: true }),
  bucket('b-crete', 'Crete', { kind: 'event', start_date: '2026-08-12', end_date: '2026-08-19' }),
]
export const CATEGORIES: Category[] = [
  category('c-coffee', 'Coffee'),
  category('c-eat', 'Eating out'),
  category('c-fuel', 'Fuel', { system_key: 'fuel' }),
  category('c-food', 'Groceries'),
]
export const HOUSEHOLD: Household = {
  id: 'h1', name: 'Home', default_currency: 'EUR',
  members: [
    { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'giorgos', avatar_color: null },
    { user_id: 'u2', role: 'member', display_name: 'Maria', username: 'maria', avatar_color: null },
  ],
}
export const DEFAULTS: DefaultsRecord = {
  ...EMPTY_DEFAULTS,
  last: { bucket_id: 'b-day', category_id: 'c-coffee', paid_by: 'u1', payment_method: 'apple_pay' },
}
export const TXN: Txn = {
  id: 't9', bucket_id: 'b-day', household_id: 'h1', amount: 64.2, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: 'u2', payer_mode: 'single', category_id: 'c-eat', notes: 'dinner', transaction_date: '2026-10-01',
  receipt_path: null, payment_method: 'card', merchant: 'Taverna', fuel_price_per_litre: null, fuel_litres: null,
  exclude_from_forecast: false, exclude_from_settlement: true, recurring_bill_id: null, created_at: null, splits: [],
}

export const created = (over: Record<string, unknown> = {}) => Response.json({ ...TXN, id: 't1', ...over }, { status: 201 })

/** Plain values or handlers by "METHOD /path" (concrete paths are fine); see testHelpers.loose. */
export function baseRoutes(): Record<string, unknown> {
  return {
    'GET /api/v1/auth/me': { id: 'u1', household_id: 'h1' },
    'GET /api/v1/buckets': BUCKETS,
    'GET /api/v1/settings/categories': CATEGORIES,
    'GET /api/v1/settings/household': HOUSEHOLD,
    'GET /api/v1/transactions': { total: 2, page: 1, page_size: 200, items: [{ ...TXN, merchant: 'Coffee Island' }, { ...TXN, id: 't8', merchant: 'Coffeeway' }] },
    'GET /api/v1/cash/movements': { items: [], stash: 50 },
    'GET /api/v1/transactions/check-duplicate': { duplicates: [] },
    'POST /api/v1/transactions': () => created(),
  }
}

/** Fresh store, identity and stored defaults (null = first use), then the composer in a data router. */
export async function renderComposer(url = '/new', opts: { routes?: Record<string, unknown>; defaults?: DefaultsRecord | null } = {}) {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
  if (opts.defaults !== null) await cachePut(defaultsKey('h1'), opts.defaults ?? DEFAULTS)
  const api = fakeApi(loose({ ...baseRoutes(), ...opts.routes }))
  const router = createMemoryRouter(
    [
      { path: '/new', element: <Composer /> },
      { path: '/edit/:id', element: <Composer /> },
      { path: '/', element: <p>home screen</p> },
    ],
    { initialEntries: [url] },
  )
  render(
    <QueryClientProvider client={testQueryClient()}>
      <ToastHost>
        <RouterProvider router={router} />
      </ToastHost>
    </QueryClientProvider>,
  )
  return { api, router }
}
```

- [ ] **Step 3: Write the failing component test `web/src/features/composer/Composer.test.tsx`**

```tsx
import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { resetTestEnv, setOnline } from '../../test/render'
import { todayLocal } from './dates'
import { loadDefaults } from './defaults'
import { goOffline, writes } from './testHelpers'
import { created, renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

const ready = () => screen.findByRole('button', { name: 'Budget: Day to day. Change' })
const press = (...keys: string[]) => keys.forEach((k) => fireEvent.click(screen.getByRole('button', { name: k })))

it('two-tap path: 3 then Save sends one POST with the stored defaults, today and a client_id', async () => {
  const { api } = await renderComposer()
  await ready()
  expect(screen.getByRole('button', { name: 'Category: Coffee. Change' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Payer: Giorgos. Change' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Method: Apple Pay. Change' })).toBeInTheDocument()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: 'Save 3 euro to Day to day' }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
  expect(writes(api)[0]).toMatchObject({
    method: 'POST',
    path: '/api/v1/transactions',
    body: {
      type: 'expense', amount: '3.00', currency: 'EUR', exchange_rate: '1', bucket_id: 'b-day', category_id: 'c-coffee',
      paid_by: 'u1', payment_method: 'apple_pay', payer_mode: 'single', transaction_date: todayLocal(), splits: [],
      exclude_from_settlement: false, client_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    },
  })
  expect(await screen.findByText('Saved €3.00 to Day to day')).toBeInTheDocument()
})

it('a double tap on Save, or Enter pressed twice, sends one POST (Review Focus 1)', async () => {
  let release: (() => void) | undefined
  const { api } = await renderComposer('/new', {
    routes: { 'POST /api/v1/transactions': () => new Promise<Response>((r) => { release = () => r(created()) }) },
  })
  await ready()
  fireEvent.keyDown(document.body, { key: '3' })
  const save = screen.getByRole('button', { name: 'Save 3 euro to Day to day' })
  fireEvent.click(save)
  fireEvent.click(save)
  fireEvent.keyDown(document.body, { key: 'Enter' })
  fireEvent.keyDown(document.body, { key: 'Enter' })
  await vi.waitFor(() => expect(release).toBeDefined())
  release!()
  await screen.findByText('home screen')
  expect(writes(api).filter((c) => c.path === '/api/v1/transactions')).toHaveLength(1)
})

it('first use: the budget pill is dashed "Choose a budget" and Save stays disabled', async () => {
  await renderComposer('/new', { defaults: null })
  const pill = await screen.findByRole('button', { name: 'Budget: Choose a budget. Change' })
  expect(pill).toHaveClass('pill--empty')
  press('3')
  expect(screen.getByRole('button', { name: /^Save 3 euro/ })).toBeDisabled()
  expect(screen.getByText('Choose a budget', { selector: '.composer__problem' })).toBeInTheDocument()
})

it('income: green state, Received by, optional budget, no method pill, transfer, no duplicate check', async () => {
  const { api } = await renderComposer()
  await ready()
  fireEvent.click(screen.getByRole('radio', { name: 'Income' }))
  expect(document.querySelector('.composer[data-type="income"]')).not.toBeNull()
  expect(screen.queryByRole('button', { name: /^Method:/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Received by: Giorgos. Change' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Budget: None. Change' })).toBeInTheDocument()
  press('7', '0', '0')
  fireEvent.click(screen.getByRole('button', { name: 'Save income 700 euro' }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ type: 'income', amount: '700.00', bucket_id: null, payment_method: 'transfer', paid_by: 'u1' })
  expect(api.calls.some((c) => c.path === '/api/v1/transactions/check-duplicate')).toBe(false)
})

it('cash from wallet: payer locked to you, over-stash blocked with the wallet amount', async () => {
  const { api } = await renderComposer('/new?mode=cash')
  expect(await screen.findByLabelText('Payer: You')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /^Payer:/ })).not.toBeInTheDocument()
  expect(await screen.findByText('Wallet: €50.00')).toBeInTheDocument()
  press('6', '0')
  expect(screen.getByRole('button', { name: /^Save 60 euro/ })).toBeDisabled()
  expect(screen.getByText('Your wallet has €50.00')).toBeInTheDocument()
  press('Delete last digit')
  fireEvent.click(screen.getByRole('button', { name: /^Save 6 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ payment_method: 'cash', took_cash: true, take_from: 'stash', paid_by: 'u1' })
})

it('offline: Save queues, closes with the on-phone toast, and still learns the defaults', async () => {
  await renderComposer()
  await ready()
  goOffline()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  expect(await screen.findByText("Saved on this phone. It will sync when you're back online.")).toBeInTheDocument()
  expect(screen.getByText('home screen')).toBeInTheDocument()
  expect(await db.queue.count()).toBe(1)
  expect((await loadDefaults('h1')).last?.payment_method).toBe('apple_pay')
})

const DUP = { id: 't7', amount: 3, currency: 'EUR', date: '2026-10-06', notes: null, merchant: 'Coffee Island', bucket: 'Day to day', paid_by: 'Maria', same_bucket: true }

it('a likely duplicate stops the save; "Save anyway" sends it', async () => {
  const { api } = await renderComposer('/new', { routes: { 'GET /api/v1/transactions/check-duplicate': { duplicates: [DUP] } } })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  expect(await screen.findByText('Looks like Coffee Island €3.00 from 6 Oct. Save anyway?')).toBeInTheDocument()
  expect(writes(api)).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Save anyway' }))
  await screen.findByText('home screen')
  expect(writes(api)).toHaveLength(1)
})

it('"Open that one" drops the draft and goes to the match without asking', async () => {
  const { router } = await renderComposer('/new', { routes: { 'GET /api/v1/transactions/check-duplicate': { duplicates: [DUP] } } })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Open that one' }))
  await vi.waitFor(() => expect(router.state.location.pathname).toBe('/edit/t7'))
  expect(screen.queryByRole('dialog', { name: 'Discard this entry?' })).not.toBeInTheDocument()
})

it('receipt: disabled offline; uploaded after an online save; Retry after a failure', async () => {
  let fail = true
  const { api } = await renderComposer('/new', {
    routes: {
      'POST /api/v1/transactions/t1/receipt': () => (fail ? new Response('{}', { status: 500 }) : Response.json({ receipt_path: 'x.jpg' })),
    },
  })
  await ready()
  fireEvent.click(screen.getByRole('button', { name: /^More options/ }))
  const more = await screen.findByRole('dialog', { name: 'More' })
  act(() => setOnline(false))
  expect(within(more).getByText("Add the receipt later when you're online (Edit)")).toBeInTheDocument()
  expect(within(more).getByLabelText('Attach receipt')).toBeDisabled()
  act(() => setOnline(true))
  fireEvent.change(within(more).getByLabelText('Attach receipt'), {
    target: { files: [new File(['x'], 'r.jpg', { type: 'image/jpeg' })] },
  })
  expect(within(more).getByText('r.jpg')).toBeInTheDocument()
  fireEvent.click(within(more).getByRole('button', { name: 'Done' }))
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  expect(await screen.findByText("Saved. The receipt didn't upload.")).toBeInTheDocument()
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await vi.waitFor(() => expect(api.calls.filter((c) => c.path === '/api/v1/transactions/t1/receipt')).toHaveLength(2))
})

it('Undo on the saved toast deletes the new entry', async () => {
  const { api } = await renderComposer('/new', { routes: { 'DELETE /api/v1/transactions/t1': () => new Response(null, { status: 204 }) } })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  fireEvent.click(await screen.findByRole('button', { name: 'Undo' }))
  await vi.waitFor(() =>
    expect(writes(api).map((c) => `${c.method} ${c.path}`)).toEqual(['POST /api/v1/transactions', 'DELETE /api/v1/transactions/t1']),
  )
})

it('closing asks "Discard this entry?" only when something was typed', async () => {
  const { router } = await renderComposer()
  await ready()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  await screen.findByText('home screen')
  act(() => { void router.navigate('/new') })
  await ready()
  press('5')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Discard this entry?' })).getByRole('button', { name: 'Keep editing' }))
  expect(screen.getByText('Amount 5.00 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Discard this entry?' })).getByRole('button', { name: 'Discard' }))
  await screen.findByText('home screen')
})

it('a 400 on save keeps the composer open with everything kept', async () => {
  const { api } = await renderComposer('/new', {
    routes: { 'POST /api/v1/transactions': () => Response.json({ detail: 'Unknown category.' }, { status: 400 }) },
  })
  await ready()
  press('3')
  fireEvent.click(screen.getByRole('button', { name: /^Save 3 euro/ }))
  await vi.waitFor(() => expect(writes(api)).toHaveLength(1))
  expect(await screen.findByText('Unknown category.')).toBeInTheDocument() // 2a's useAction toast
  expect(screen.getByText('Amount 3.00 euro')).toBeInTheDocument()
  expect(screen.queryByText('home screen')).not.toBeInTheDocument()
})

it('merchant: suggestions after 2 characters, and the keypad hides while typing', async () => {
  await renderComposer()
  await ready()
  const input = screen.getByPlaceholderText('Where? (optional)')
  fireEvent.focus(input)
  expect(screen.queryByRole('button', { name: '3' })).not.toBeInTheDocument()
  fireEvent.change(input, { target: { value: 'Cof' } })
  fireEvent.click(await screen.findByRole('option', { name: 'Coffee Island' }))
  expect(input).toHaveValue('Coffee Island')
  fireEvent.blur(input)
  expect(screen.getByRole('button', { name: '3' })).toBeInTheDocument()
})
```

- [ ] **Step 4: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/Composer.test.tsx`
Expected: FAIL with "Failed to resolve import ./Composer".

- [ ] **Step 5: Implement `Composer.tsx` and `useClose.ts`**

`web/src/features/composer/useClose.ts`:

```ts
import { useNavigate } from 'react-router'

/** ✕ and Back: the previous route, or Home when the composer was opened directly. */
export function useClose(): () => void {
  const navigate = useNavigate()
  return () => {
    if ((window.history.state?.idx ?? 0) > 0) void navigate(-1)
    else void navigate('/', { replace: true })
  }
}
```

`web/src/features/composer/Composer.tsx`:

```tsx
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { ComposerForm } from './ComposerForm'
import { todayLocal } from './dates'
import { type DefaultsRecord, initialNew } from './defaults'
import { type ComposerData, useComposerData } from './hooks/useComposerData'
import { useDefaults } from './hooks/useDefaults'
import './composer.css'

export function Composer() {
  const data = useComposerData()
  const defaults = useDefaults(data.hh)
  const [params] = useSearchParams()
  if (!data.ready || !defaults) return <ComposerSkeleton />
  return <NewComposer data={data} defaults={defaults} cash={params.get('mode') === 'cash'} />
}

export function ComposerSkeleton() {
  return <div className="composer composer--loading" aria-busy="true" aria-label="Loading" />
}

function NewComposer({ data, defaults, cash }: { data: ComposerData; defaults: DefaultsRecord; cash: boolean }) {
  // One client_id per composer mount (spec §5.1).
  const [initial] = useState(() =>
    initialNew({
      defaults, buckets: data.buckets, categories: data.categories, memberIds: data.members.map((m) => m.user_id),
      meId: data.meId, householdCurrency: data.householdCurrency, type: 'expense', today: todayLocal(),
      clientId: crypto.randomUUID(), cash,
    }),
  )
  return <ComposerForm initial={initial} data={data} defaults={defaults} />
}
```

- [ ] **Step 6: Implement `ComposerForm.tsx` (logic in full; layout as listed)**

```tsx
import { useEffect, useReducer, useRef, useState } from 'react'
import { useBlocker, useNavigate } from 'react-router'
import { CloseIcon } from '../../shell/icons'
import { AmountDisplay } from '../../ui/AmountDisplay'
import { Keypad } from '../../ui/Keypad'
import { Pill } from '../../ui/Pill'
import { type AmountKey, centsToString, convertCents, displayAmount, parseRate, toApiAmount, toCents } from './amount'
import { Segmented, type ToastInput, useComposerToast, useOnline } from './bridge'
import { CashControls } from './CashControls'
import { ConfirmSheet } from './ConfirmSheet'
import { currencyName, currencySymbol, formatCents, spokenMoney } from './currencies'
import { dayLabel, todayLocal } from './dates'
import { type DefaultsRecord, matchRule, sanitize, suggestMerchants } from './defaults'
import { DuplicateCard } from './DuplicateCard'
import type { ComposerData } from './hooks/useComposerData'
import { useDuplicateCheck } from './hooks/useDuplicateCheck'
import { useReceiptUpload } from './hooks/useReceiptUpload'
import { useSaveTransaction } from './hooks/useSaveTransaction'
import { useUndoCreate } from './hooks/undo'
import { firstProblem, isDirtyNew, moreDirty, toUpdateBody, validate } from './model'
import { MoreSheet } from './MoreSheet'
import { BucketSheet } from './pickers/BucketSheet'
import { CategorySheet } from './pickers/CategorySheet'
import { CurrencySheet } from './pickers/CurrencySheet'
import { DateSheet } from './pickers/DateSheet'
import { MethodSheet } from './pickers/MethodSheet'
import { PayerSheet } from './pickers/PayerSheet'
import { METHOD_LABELS, memberName } from './pickers/labels'
import { type ComposerState, reduce, type Remembered, type TxnType } from './state'
import type { Duplicate } from './types'
import { useClose } from './useClose'

type SheetName = 'bucket' | 'category' | 'payer' | 'method' | 'currency' | 'date' | 'more'

const QUEUED = "Saved on this phone. It will sync when you're back online."
const QUEUED_NO_RECEIPT = "Saved on this phone. The receipt wasn't attached: add it when you're back online."
const UPLOAD_FAILED = "Saved. The receipt didn't upload."
const UNDO_MS = 5000

export function ComposerForm({ initial, data, defaults }: { initial: ComposerState; data: ComposerData; defaults: DefaultsRecord }) {
  const [s, dispatch] = useReducer(reduce, initial)
  const today = todayLocal()
  const online = useOnline()
  const navigate = useNavigate()
  const close = useClose()
  const toast = useComposerToast()
  const ctx = { hh: data.hh, householdCurrency: data.householdCurrency, fuelCategoryId: data.fuelCategoryId, meId: data.meId }
  const save = useSaveTransaction(s, ctx, defaults)
  const checkDuplicate = useDuplicateCheck()
  const upload = useReceiptUpload()
  const undo = useUndoCreate()
  const [sheet, setSheet] = useState<SheetName | null>(null)
  const [dup, setDup] = useState<Duplicate | null>(null)
  const [typing, setTyping] = useState(false)
  const [stashCents, setStashCents] = useState<number | null>(null)
  const v = validate(s, { ...ctx, today, stashCents })

  const memberIds = data.members.map((m) => m.user_id)
  const lookup = (type: TxnType = s.type) => ({ buckets: data.buckets, categories: data.categories, memberIds, type })
  const remembered = (r: Remembered | undefined) => sanitize(r, lookup())

  // Closing (spec §3): a dirty draft asks first; a save or "Open that one" leaves without asking.
  const [initialBody] = useState(() => (initial.mode === 'edit' ? JSON.stringify(toUpdateBody(initial, ctx)) : ''))
  const dirty = s.mode === 'new' ? isDirtyNew(s) : JSON.stringify(toUpdateBody(s, ctx)) !== initialBody
  const leaving = useRef(false)
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname,
  )
  const leave = (to?: string) => {
    leaving.current = true
    if (to) void navigate(to, { replace: true })
    else close()
  }

  const cents = toCents(s.amount)
  const money = formatCents(cents, s.currency)
  const bucketName = data.buckets.find((b) => b.id === s.bucketId)?.name

  function savedToast(id: string): ToastInput {
    if (s.mode === 'edit') return { text: 'Saved changes' }
    const text = s.type === 'income'
      ? `Saved income ${money}${bucketName ? ` to ${bucketName}` : ''}`
      : `Saved ${money} to ${s.fixedCost ? 'Fixed cost' : bucketName}`
    return { text, durationMs: UNDO_MS, action: { label: 'Undo', onPress: () => void undo(id) } }
  }

  async function uploadReceipt(id: string, file: File) {
    if ((await upload(id, file)) === 'ok') return
    toast({ text: UPLOAD_FAILED, action: { label: 'Retry', onPress: () => void uploadReceipt(id, file) } })
  }

  const submitting = useRef(false)
  async function onSave(skipDuplicate = false) {
    if (!v.ok || submitting.current) return
    submitting.current = true
    try {
      if (s.mode === 'new' && s.type === 'expense' && !skipDuplicate && online) {
        const found = await checkDuplicate({ amount: toApiAmount(s.amount), transaction_date: s.date, bucket_id: s.bucketId })
        if (found.length) {
          setDup(found[0])
          return
        }
      }
      setDup(null)
      const r = s.mode === 'new' ? await save.saveNew() : await save.saveEdit()
      if (r.status === 'busy' || r.status === 'failed') return // useAction already showed the server's detail
      const receipt = s.receipt
      leave()
      if (r.status === 'queued') {
        toast({ text: receipt ? QUEUED_NO_RECEIPT : QUEUED })
        return
      }
      toast(savedToast(r.id))
      if (receipt) void uploadReceipt(r.id, receipt)
    } finally {
      submitting.current = false
    }
  }

  // Hardware keyboard (spec §4.2): digits, "." or ",", Backspace, Enter saves. Not while a field or sheet has focus.
  const onSaveRef = useRef(onSave)
  useEffect(() => { onSaveRef.current = onSave })
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (sheet || dup || blocker.state === 'blocked') return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      let key: AmountKey | null = null
      if (/^[0-9]$/.test(e.key)) key = e.key as AmountKey
      else if (e.key === '.' || e.key === ',') key = '.'
      else if (e.key === 'Backspace') key = 'back'
      if (key) dispatch({ type: 'key', key })
      else if (e.key === 'Enter') void onSaveRef.current()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [sheet, dup, blocker.state])

  const switchType = (value: TxnType) => {
    const r = sanitize(value === 'income' ? defaults.lastIncome : defaults.last, lookup(value))
    dispatch({ type: 'setType', value, defaults: { ...r, paid_by: r.paid_by ?? data.meId } })
  }
  const toggleCash = () =>
    dispatch({ type: 'setCashMode', on: !s.cashMode, meId: data.meId, defaultMethod: remembered(defaults.last).payment_method ?? 'card' })

  const rule = matchRule(s.merchant, data.rules)
  const suggestions = typing ? suggestMerchants(s.merchant, data.merchants) : []
  const rate = parseRate(s.rate)
  const converted = s.currency !== data.householdCurrency && rate !== null
    ? `≈ ${formatCents(convertCents(cents, rate), data.householdCurrency)}`
    : null
  const hint = firstProblem(v.problems)
  const payer = data.members.find((m) => m.user_id === s.paidBy)
  const category = data.categories.find((c) => c.id === s.categoryId)
  const income = s.type === 'income'
  const saveLabel = s.mode === 'edit' ? 'Save changes' : income ? `Save income ${money}` : `Save ${money}`
  const saveName = s.mode === 'edit'
    ? 'Save changes'
    : income
      ? `Save income ${spokenMoney(cents, s.currency)}`
      : `Save ${spokenMoney(cents, s.currency)}${bucketName ? ` to ${bucketName}` : ''}`
  const allowOwnShare = false // C4-3 enables "Each paid own share" together with the split sheet

  // Layout: see Step 7.
}
```

- [ ] **Step 7: Write the `ComposerForm` layout and the small components**

`ComposerForm` returns, top to bottom (spec §4.1), inside `<div className="composer" data-type={s.type}>`:
1. `<header className="composer__bar">`: a `button` with `aria-label="Close"` and `CloseIcon`, calling `close()`; the bridge `Segmented` with `label="Entry type"`, options Expense/Income, `value={s.type}`, `onChange={switchType}`, `disabled={s.mode === 'edit'}`; when `!online`, `<span className="composer__offline">Offline</span>`.
2. Modes row, only for `s.mode === 'new' && !income`: `<div className="composer__modes" role="group" aria-label="Entry mode">` with `<button type="button" className={s.cashMode ? 'chip on' : 'chip'} aria-pressed={s.cashMode} onClick={toggleCash}>Cash from wallet</button>`.
3. `AmountDisplay` with `text={displayAmount(s.amount)}`, `symbol={currencySymbol(s.currency)}`, `currency={s.currency}`, `spoken={`Amount ${centsToString(cents)} ${currencyName(s.currency)}`}`, `tone={income ? 'income' : 'default'}`, `converted={converted}`, `onCurrency={() => setSheet('currency')}`, `tag={s.fromReceipt.includes('amount') ? 'from receipt' : null}`; under it, when `s.scanNoTotal`, `<p className="composer__hint">Couldn't find the total</p>`.
4. Merchant: `<input className="composer__merchant" aria-label="Merchant" placeholder="Where? (optional)" maxLength={100} autoComplete="off" enterKeyHint="done" value={s.merchant}>`; `onChange` dispatches `{ type: 'setMerchant', value, rule: matchRule(value, data.rules) }`; `onFocus`/`onBlur` set `typing`. While `suggestions.length > 0`: `<ul role="listbox" aria-label="Recent places">` with `<li role="option" aria-selected={false}>` items that dispatch `setMerchant` on `onMouseDown` (with `preventDefault()` so the click lands before blur). Each option's accessible name is the merchant text.
5. Pills (`<div className="pills composer__pills">`), using `Pill`:
   - Expense: **Budget**: `s.fixedCost` → `readOnly`, value "Fixed cost"; no bucket → `empty`, value "Choose a budget"; else the bucket's name from **all** buckets (an archived one keeps its name). **Category**: name or "None", `tag={s.ruleLabel ?? (s.fromReceipt.includes('category') ? 'from receipt' : null)}`. **Payer**: value `s.ownShare ? 'Each paid own share' : s.cashMode ? 'You' : memberName(payer)`, `readOnly={s.cashMode}`. **Method**: `METHOD_LABELS[s.method]`.
   - Income: **Received by** (`memberName(payer)`, opens the payer sheet with title "Received by"), **Category**, **Budget** (name or "None", optional), **Date** (`dayLabel(s.date, today)`, opens `DateSheet`).
   - Each pill's `onPress` calls `setSheet(<name>)`.
6. `CashControls` when `s.mode === 'new' && !income && s.method === 'cash'`, with `s`, `dispatch`, `householdCurrency={data.householdCurrency}` and `onStash={setStashCents}`.
7. `DuplicateCard` when `dup`: `onOpen={() => leave(`/edit/${dup.id}`)}`, `onSaveAnyway={() => void onSave(true)}`.
8. More link: `<button type="button" className="composer__more" aria-label={moreDirty(s, { ...ctx, today }) ? 'More options, changed' : 'More options'} onClick={() => setSheet('more')}>` with visible text "More: date, split, notes, receipt" (income: "More: notes, receipt") and a dot `<span className="composer__dot" aria-hidden="true" />` when `moreDirty`.
9. `hint` (when set): `<p className="composer__problem">{hint}</p>`.
10. `<Keypad onKey={(k) => dispatch({ type: 'key', key: k })} hidden={typing} />`.
11. Save: `<button type="button" className="btn btn--primary btn--lg btn--block composer__save" aria-label={saveName} disabled={!v.ok || save.saving} onClick={() => void onSave()}>{saveLabel}</button>`. Income uses `composer__save--income` (`var(--pos)` background).
12. Sheets, each `open={sheet === <name>}` and `onClose={() => setSheet(null)}`:
   - `BucketSheet` (`onPick={(id) => dispatch({ type: 'pickBucket', id, remembered: id ? remembered(defaults.byBucket[id]) : {} })}`), skipped when `s.fixedCost`;
   - `CategorySheet` (`recentIds={defaults.recentCategoryIds}`, `suggestion={rule ? { id: rule.category_id, reason: `rule: ${rule.pattern}` } : null}`, `onPick={(id) => dispatch({ type: 'pickCategory', id, remembered: remembered(defaults.byCategory[id]) })}`);
   - `PayerSheet` (`title={income ? 'Received by' : 'Payer'}`, `allowOwnShare={allowOwnShare}`, `onPick={(id) => dispatch({ type: 'pickPayer', id })}`, `onOwnShare={() => setSheet(null)}`), not rendered while `s.cashMode`;
   - `MethodSheet` (`onPick={(m) => dispatch({ type: 'pickMethod', method: m })}`);
   - `CurrencySheet` (`onPick={(code) => dispatch({ type: 'pickCurrency', code, householdCurrency: data.householdCurrency, lastRate: defaults.rates[code] })}`);
   - `DateSheet` (`value={s.date}`, `today`, `onPick={(d) => dispatch({ type: 'setDate', value: d })}`);
   - `MoreSheet` (`ctx={{ today, online, householdCurrency: data.householdCurrency, fuelCategoryId: data.fuelCategoryId, members: data.members, meId: data.meId, problems: v.problems }}`);
   - `ConfirmSheet` for discard: `open={blocker.state === 'blocked'}`, title "Discard this entry?", confirm "Discard" (`danger`, calls `blocker.proceed?.()`), cancel "Keep editing" (`blocker.reset?.()`).

`CashControls.tsx`: renders the bridge `Segmented` with `label="Took from"` and options `none` "Not tracked", `stash` "My wallet", `bank` "Bank/ATM", dispatching `setTookFrom`. When `s.tookFrom === 'stash'` it mounts a child `WalletLine` that calls `useStash()`, reports it with `useEffect(() => { onStash(stash); return () => onStash(null) }, [stash])`, and shows `Wallet: ${formatCents(stash, householdCurrency)}` when the stash is known (nothing when unknown). The household currency comes from a `householdCurrency` prop.

`DuplicateCard.tsx`: `role="alert"` card with the text `Looks like ${dup.merchant ?? dup.bucket ?? 'an entry'} ${formatCents(Math.round(dup.amount * 100), dup.currency)} from ${shortDate(dup.date)}. Save anyway?` and two buttons, "Open that one" (secondary) and "Save anyway" (primary).

`ConfirmSheet.tsx`: the bridge `Sheet` titled `title` with two full-width buttons: `cancelLabel` (`.btn`) and `confirmLabel` (`.btn .btn--danger` when `danger`, else `.btn--primary`).

`MoreSheet.tsx`: the bridge `Sheet` titled "More", a scrolling body of `<section className="ck-more__section">` blocks, each with an `<h3>`, in this order, and a footer button "Done" that calls `onClose`:
1. **Date** (expense only): `DateChips` with `onPick` dispatching `setDate`; `ctx.problems.date` under it.
2. **Notes**: `<textarea aria-label="Notes" rows={3} maxLength={500}>` (16 px), dispatching `setNotes`, with a counter `${s.notes.length}/500`.
3. **Receipt**: a `ReceiptField` defined in the same file.
   - Offline: the file input is disabled and the text "Add the receipt later when you're online (Edit)" shows.
   - With `s.storedReceiptPath`: "Receipt attached", a link "View" (`href={`/transactions/files/${s.storedReceiptPath}`}`, `target="_blank"`, `rel="noopener"`) and "Replace" (the same input).
   - Otherwise an `<input type="file" accept={RECEIPT_ACCEPT} aria-label="Attach receipt">` styled as a button labelled "Attach receipt". On change it runs `receiptProblem(file)`: on a problem it shows the message inline and keeps nothing; else it dispatches `setReceipt` and shows the file name with a "Remove" button (`setReceipt(null)`).
4. **Count in forecast**: `ToggleRow` with `label="Count in forecast"`, `hint="Turn off for one-offs"`, `checked={s.countInForecast}`, dispatching `setForecast`.

C4-3 adds "Fuel" and "Currency and rate" after Date, and "Split with <member>" after Receipt.

`composer.css` (tokens only, mock layout):
- `.composer`: a fixed full-height column (`min-height: 100dvh`), `max-width: 480px; margin: 0 auto`, padding `calc(env(safe-area-inset-top) + 8px) 16px calc(env(safe-area-inset-bottom) + 12px)`, `display: flex; flex-direction: column; gap: 12px; background: var(--bg)`. `overscroll-behavior: contain`.
- `.composer__bar`: three columns (44 px button, the segmented control centred, 44 px slot).
- The keypad and the Save bar sit at the bottom (`margin-top: auto` on the keypad).
- `.composer__merchant`: 16 px font, 48 px high, `var(--surface)` with `var(--line)` border.
- `[data-type="income"] .amount__caret` and `.composer__save--income` use `var(--pos)`.
- `.composer__problem` 13 px `var(--warn)`; `.composer__offline` a small `var(--warn-soft)` tag; `.composer__dot` 6 px `var(--accent)` dot.
- `.composer--loading`: skeleton blocks (amount, pills, keypad) in `var(--surface-2)`, with no shimmer under reduced motion.
- `@media (prefers-reduced-motion: reduce)`: no transitions in the composer.

- [ ] **Step 8: Run the test**

Run: `cd web && npm test -- src/features/composer/Composer.test.tsx`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add web/src/features/composer/Composer.tsx web/src/features/composer/ComposerForm.tsx web/src/features/composer/CashControls.tsx web/src/features/composer/DuplicateCard.tsx web/src/features/composer/ConfirmSheet.tsx web/src/features/composer/MoreSheet.tsx web/src/features/composer/useClose.ts web/src/features/composer/composer.css web/src/features/composer/testing.tsx web/src/features/composer/Composer.test.tsx
git commit -m "feat(composer): keypad-first composer for expenses and income, cash from wallet, duplicate card, receipt, undo"
```

### Task C2-9: Edit, copy and delete

**Stream:** C2 · **Depends on:** C2-8

**Files:**
- Create: `web/src/features/composer/EditTopMenu.tsx`
- Modify: `web/src/features/composer/Composer.tsx` (edit and copy loaders), `web/src/features/composer/ComposerForm.tsx` (edit menu and delete flow in the top bar)
- Test: `web/src/features/composer/Composer.edit.test.tsx`

**Interfaces:**
- Consumes: `useTransaction`, `fromTransaction`, `copyOf`, `save.deleteEntry`, `ConfirmSheet`, `useClose`.
- Produces: `/edit/:id` and `/new?from=<id>` handled inside `Composer`; `EditTopMenu({ onDelete(): void })`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.**

- [ ] **Step 2: Write the failing test `web/src/features/composer/Composer.edit.test.tsx`**

```tsx
import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { todayLocal } from './dates'
import { writes } from './testHelpers'
import { renderComposer, TXN } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

it('edit: loads the stored values, locks the type, sends a full PUT with the stored settlement flag', async () => {
  const { api } = await renderComposer('/edit/t9', { routes: { 'GET /api/v1/transactions/t9': TXN, 'PUT /api/v1/transactions/t9': TXN } })
  expect(await screen.findByText('Amount 64.20 euro')).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: 'Income' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Cash from wallet' })).not.toBeInTheDocument()
  expect(screen.getByPlaceholderText('Where? (optional)')).toHaveValue('Taverna')
  fireEvent.click(screen.getByRole('button', { name: 'Delete last digit' }))
  fireEvent.click(screen.getByRole('button', { name: '5' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  const [put] = writes(api)
  expect(put).toMatchObject({ method: 'PUT', path: '/api/v1/transactions/t9' })
  expect(put.body).toMatchObject({
    amount: '64.25', exclude_from_settlement: true, payer_mode: 'single', paid_by: 'u2', bucket_id: 'b-day', transaction_date: '2026-10-01',
  })
  expect(put.body).not.toHaveProperty('client_id')
  expect(api.calls.some((c) => c.path.endsWith('/check-duplicate'))).toBe(false)
  expect(await screen.findByText('Saved changes')).toBeInTheDocument()
})

it('an archived budget keeps its name and its id (Review Focus 3)', async () => {
  const { api } = await renderComposer('/edit/t9', {
    routes: { 'GET /api/v1/transactions/t9': { ...TXN, bucket_id: 'b-old' }, 'PUT /api/v1/transactions/t9': TXN },
  })
  expect(await screen.findByRole('button', { name: 'Budget: Old budget. Change' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ bucket_id: 'b-old' })
})

it('a Fixed cost shows a read-only budget and keeps bucket_id null', async () => {
  const { api } = await renderComposer('/edit/t9', {
    routes: { 'GET /api/v1/transactions/t9': { ...TXN, bucket_id: null, recurring_bill_id: 'r1' }, 'PUT /api/v1/transactions/t9': TXN },
  })
  expect(await screen.findByLabelText('Budget: Fixed cost')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ bucket_id: null })
})

it('Delete asks first, sends DELETE and closes; a 404 counts as done', async () => {
  const { api } = await renderComposer('/edit/t9', {
    routes: {
      'GET /api/v1/transactions/t9': TXN,
      'DELETE /api/v1/transactions/t9': () => Response.json({ detail: 'Transaction not found' }, { status: 404 }),
    },
  })
  fireEvent.click(await screen.findByRole('button', { name: 'More actions' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Entry' })).getByRole('button', { name: 'Delete' }))
  const ask = await screen.findByRole('dialog', { name: 'Delete this entry?' })
  fireEvent.click(within(ask).getByRole('button', { name: 'Delete' }))
  await screen.findByText('home screen')
  expect(writes(api)).toEqual([expect.objectContaining({ method: 'DELETE', path: '/api/v1/transactions/t9' })])
})

it('a missing entry says so, with Back', async () => {
  await renderComposer('/edit/t404', {
    routes: { 'GET /api/v1/transactions/t404': () => Response.json({ detail: 'Transaction not found' }, { status: 404 }) },
  })
  expect(await screen.findByText('This entry no longer exists')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  await screen.findByText('home screen')
})

it('offline with nothing cached: "Connect once to load this entry."', async () => {
  await renderComposer('/edit/t9', {
    routes: { 'GET /api/v1/transactions/t9': () => Promise.reject(new TypeError('Failed to fetch')) },
  })
  expect(await screen.findByText('Connect once to load this entry.')).toBeInTheDocument()
})

it('/new?from= copies an entry as a new one dated today with a fresh client_id', async () => {
  const { api } = await renderComposer('/new?from=t9', { routes: { 'GET /api/v1/transactions/t9': TXN } })
  expect(await screen.findByText('Amount 64.20 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save 64 euro 20 to Day to day' }))
  await screen.findByText('home screen')
  expect(writes(api)[0]).toMatchObject({
    method: 'POST',
    body: { amount: '64.20', merchant: 'Taverna', transaction_date: todayLocal(), client_id: expect.stringMatching(/^[0-9a-f-]{36}$/) },
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/Composer.edit.test.tsx`
Expected: FAIL (the edit route renders a new composer: "Amount 64.20 euro" is not found).

- [ ] **Step 4: Implement**

In `Composer.tsx`, read `const { id } = useParams()` and `params.get('from')`, and route before `NewComposer`:

```tsx
  if (id) return <EditLoader id={id} copy={false} data={data} defaults={defaults} />
  const from = params.get('from')
  if (from) return <EditLoader id={from} copy data={data} defaults={defaults} />
```

and add:

```tsx
function EditLoader({ id, copy, data, defaults }: { id: string; copy: boolean; data: ComposerData; defaults: DefaultsRecord }) {
  const { txn, status } = useTransaction(id)
  const [initial, setInitial] = useState<ComposerState | null>(null)
  // Initialise once: a background refetch must not wipe what the user is typing.
  if (txn && initial === null) {
    const loaded = fromTransaction(txn, { householdCurrency: data.householdCurrency, meId: data.meId })
    setInitial(copy ? copyOf(loaded, { clientId: crypto.randomUUID(), today: todayLocal() }) : loaded)
  }
  if (initial) return <ComposerForm initial={initial} data={data} defaults={defaults} />
  if (status === 'missing') return <Gone text="This entry no longer exists" />
  if (status === 'offline') return <Gone text="Connect once to load this entry." />
  return <ComposerSkeleton />
}

function Gone({ text }: { text: string }) {
  const close = useClose()
  return (
    <div className="composer composer--gone">
      <p role="alert" className="composer__gone">{text}</p>
      <button type="button" className="btn btn--block" onClick={close}>Back</button>
    </div>
  )
}
```

(imports: `useParams`, `useTransaction`, `fromTransaction`, `copyOf`, `type ComposerState`, `useClose`).

`EditTopMenu.tsx`: a 44 px icon button `aria-label="More actions"` (three-dots icon inline SVG) that opens the bridge `Sheet` titled "Entry" containing one danger button "Delete"; pressing it closes the menu and calls `onDelete()`.

In `ComposerForm.tsx`:
- In the top bar's third slot, render `<EditTopMenu onDelete={() => setConfirmDelete(true)} />` when `s.mode === 'edit'`.
- Add `const [confirmDelete, setConfirmDelete] = useState(false)` and a second `ConfirmSheet` titled "Delete this entry?", confirm "Delete" (`danger`), cancel "Cancel", whose confirm runs:

```tsx
async function onDelete() {
  setConfirmDelete(false)
  const r = await save.deleteEntry()
  if (r.status === 'done' || r.status === 'queued') {
    leave()
    toast({ text: r.status === 'queued' ? QUEUED : 'Deleted' })
  }
}
```

Edit mode already hides the modes row and "Took from" (both gated on `s.mode === 'new'`), and the type `Segmented` is disabled. The receipt section shows "Receipt attached" with View and Replace for `storedReceiptPath`, and a newly chosen file is uploaded after a successful `PUT` by the same `onSave` path.

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/features/composer/Composer.edit.test.tsx src/features/composer/Composer.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/composer/Composer.tsx web/src/features/composer/ComposerForm.tsx web/src/features/composer/EditTopMenu.tsx web/src/features/composer/Composer.edit.test.tsx
git commit -m "feat(composer): edit, copy and delete through the same screen"
```

### Task C2-10: Routes outside the tab shell (the only `router.tsx` change in 2b)

**Stream:** C2 · **Depends on:** C2-9, and 2a's D5 merged (it adds `plan/items` to `router.tsx`)

This is the only 2b task that edits `web/src/router.tsx`. 2a's D5 edits it too, so this task starts from the merged 2a router and keeps its `plan/items` route.

**Files:**
- Create: `web/src/shell/FullScreenShell.tsx`, `web/src/shell/FullScreenShell.test.tsx`
- Modify: `web/src/router.tsx`, `web/src/screens/Compose.tsx`

**Interfaces:**
- Consumes: `startReplayTriggers` (Phase 1), `installQueueBridge` (2a A7), `Toaster` (2a A3), `queryClient`.
- Produces: `FullScreenShell()` layout route: the same sign-in gate, queue bridge and replay triggers as `AppShell`, its own `<Toaster />` (2a's toast store is module-level, so a toast raised in the composer is still shown after navigating back into `AppShell`), `<Outlet />` and no tab bar; routes `/new` and `/edit/:id` as its children; `screens/Compose.tsx` re-exports `Composer` as `Compose`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Read the merged `web/src/router.tsx` and `web/src/shell/AppShell.tsx` (2a A7 wiring).

- [ ] **Step 2: Write the failing test `web/src/shell/FullScreenShell.test.tsx`**

```tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { Session } from '../session/SessionProvider'
import { FullScreenShell } from './FullScreenShell'

const stop = vi.fn()
const start = vi.fn(() => stop)
vi.mock('../offline/queue', () => ({ startReplayTriggers: () => start() }))
const bridgeStop = vi.fn()
vi.mock('../data/queueBridge', () => ({ installQueueBridge: () => bridgeStop }))

const session: Session = { status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {} }
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(() => {
  cleanup()
  start.mockClear()
  stop.mockClear()
  bridgeStop.mockClear()
})

function at(status: Session['status']) {
  session.status = status
  const router = createMemoryRouter(
    [{ element: <FullScreenShell />, children: [{ path: '/new', element: <p>composer</p> }] }],
    { initialEntries: ['/new'] },
  )
  render(<RouterProvider router={router} />)
}

it('signed in: renders the child with no tab bar, starts the replay triggers and the queue bridge', () => {
  at('signedIn')
  expect(screen.getByText('composer')).toBeInTheDocument()
  expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  expect(start).toHaveBeenCalledTimes(1)
  cleanup()
  expect(stop).toHaveBeenCalledTimes(1)
  expect(bridgeStop).toHaveBeenCalledTimes(1)
})

it('signed out: the sign-in screen, never the composer', () => {
  at('signedOut')
  expect(screen.queryByText('composer')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Sign in with Face ID/ })).toBeInTheDocument()
  expect(start).not.toHaveBeenCalled()
})

it('loading: a blank boot screen', () => {
  at('loading')
  expect(screen.queryByText('composer')).not.toBeInTheDocument()
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npm test -- src/shell/FullScreenShell.test.tsx`
Expected: FAIL with "Failed to resolve import ./FullScreenShell".

- [ ] **Step 4: Implement**

`web/src/shell/FullScreenShell.tsx`:

```tsx
import { useEffect } from 'react'
import { Outlet } from 'react-router'
import { installQueueBridge } from '../data/queueBridge'
import { startReplayTriggers } from '../offline/queue'
import { queryClient } from '../queryClient'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { Toaster } from '../ui/Toast'
import './shell.css'

/**
 * Layout for full-screen flows (the composer): the same sign-in gate, queue bridge and offline replay
 * as AppShell, without the tab bar. Auth-callback banners stay AppShell's job (callbacks land on /).
 */
export function FullScreenShell() {
  const { status } = useSession()
  useEffect(() => {
    if (status !== 'signedIn') return
    const stopBridge = installQueueBridge(queryClient)
    const stopReplay = startReplayTriggers()
    return () => {
      stopReplay()
      stopBridge()
    }
  }, [status])
  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn result={{ error: null, linked: false }} />
  return (
    <>
      <Outlet />
      <Toaster />
    </>
  )
}
```

`web/src/router.tsx`:

```tsx
import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './shell/AppShell'
import { FullScreenShell } from './shell/FullScreenShell'
import { Home } from './screens/Home'
import { Activity } from './screens/Activity'
import { Compose } from './screens/Compose'
import { Plan } from './screens/Plan'
import { Insights } from './screens/Insights'
import { Items } from './features/plan/items/Items'

export const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <AppShell />,
      children: [
        { index: true, element: <Home /> },
        { path: 'activity', element: <Activity /> },
        { path: 'plan', element: <Plan /> },
        { path: 'plan/items', element: <Items /> },
        { path: 'insights', element: <Insights /> },
        { path: '*', element: <Navigate to="/" replace /> },
      ],
    },
    // The composer sits outside AppShell so no tab bar shows while composing (2b spec §3).
    {
      element: <FullScreenShell />,
      children: [
        { path: '/new', element: <Compose /> },
        { path: '/edit/:id', element: <Compose /> },
      ],
    },
  ],
  { basename: '/app' },
)
```

If 2c or 2d have added routes under `AppShell` by the time this merges, keep them too; this task only removes the `new` child and adds the second top-level entry.

`web/src/screens/Compose.tsx`:

```tsx
export { Composer as Compose } from '../features/composer/Composer'
```

- [ ] **Step 5: Run the tests and the type check**

Run: `cd web && npm test -- src/shell/FullScreenShell.test.tsx src/shell/AppShell.test.tsx src/shell/shell.test.tsx && npm run typecheck`
Expected: PASS. (`shell.test.tsx` may assert the TabBar's `/new` link; the link is unchanged.)

- [ ] **Step 6: Commit**

```bash
git add web/src/shell/FullScreenShell.tsx web/src/shell/FullScreenShell.test.tsx web/src/router.tsx web/src/screens/Compose.tsx
git commit -m "feat(web): /new and /edit/:id as full-screen routes with their own session gate"
```

---

## Stream C4: More sheet and split

### Task C4-1: `splits.ts`

**Stream:** C4 · **Depends on:** C2-2 (pure; can run in the C4 worktree before C2 merges, rebased on C2-1/C2-2)

**Files:**
- Create: `web/src/features/composer/splits.ts`
- Test: `web/src/features/composer/splits.test.ts`

**Interfaces:**
- Consumes: `toCents`, `centsToString`, `parseScaled` (C2-1), `Share` (C2-2).
- Produces: `type ShareMap = Record<string, number>` (cents); `equalShares(total, memberIds, payer: string | null): ShareMap`; `amountShares(total, memberIds, payer: string, typed: Record<string, string>): ShareMap`; `percentShares(total, memberIds, payer: string, typed): ShareMap`; `ownShares(memberIds, typed): ShareMap`; `type SplitProblem = 'negative' | 'over' | 'mismatch' | null`; `splitProblem(total, shares, own: boolean): SplitProblem`; `toShareList(memberIds, shares): Share[]`; `typedFromShares(shares: Share[]): Record<string, string>`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { amountShares, equalShares, ownShares, percentShares, splitProblem, toShareList, typedFromShares } from './splits'

const sum = (m: Record<string, number>) => Object.values(m).reduce((a, x) => a + x, 0)

describe('equal (the server equal_split rule)', () => {
  it('rounds down to the cent; leftover cents go to the payer', () => {
    const s = equalShares(1000, ['u3', 'u1', 'u2'], 'u2')
    expect(s).toEqual({ u1: 333, u2: 334, u3: 333 })
    expect(sum(s)).toBe(1000)
  })
  it('a payer outside the members: the first id in order takes them', () => {
    expect(equalShares(1001, ['u2', 'u1'], 'zz')).toEqual({ u1: 501, u2: 500 })
  })
})

describe('amounts and percent: the payer takes the remainder', () => {
  it('amounts', () => {
    expect(amountShares(1000, ['u1', 'u2'], 'u1', { u2: '3.50' })).toEqual({ u1: 650, u2: 350 })
    expect(splitProblem(1000, amountShares(1000, ['u1', 'u2'], 'u1', { u2: '12' }), false)).toBe('negative')
  })
  it('percent rounds each share down to the cent and still sums to the total', () => {
    const s = percentShares(1000, ['u1', 'u2', 'u3'], 'u1', { u2: '33.33', u3: '33.33' })
    expect(s).toEqual({ u1: 334, u2: 333, u3: 333 })
    expect(sum(s)).toBe(1000)
    expect(splitProblem(1000, percentShares(1000, ['u1', 'u2'], 'u1', { u2: '120' }), false)).toBe('negative')
  })
})

describe('own share', () => {
  it('everyone types; must add up to the total within a cent', () => {
    expect(splitProblem(1000, ownShares(['u1', 'u2'], { u1: '6', u2: '4' }), true)).toBeNull()
    expect(splitProblem(1000, ownShares(['u1', 'u2'], { u1: '6', u2: '3.99' }), true)).toBeNull()
    expect(splitProblem(1000, ownShares(['u1', 'u2'], { u1: '6', u2: '3' }), true)).toBe('mismatch')
  })
})

it('to and from the API list, in member order, every member present', () => {
  const list = toShareList(['u1', 'u2'], { u2: 350, u1: 650 })
  expect(list).toEqual([{ user_id: 'u1', amount: '6.50' }, { user_id: 'u2', amount: '3.50' }])
  expect(typedFromShares(list)).toEqual({ u1: '6.50', u2: '3.50' })
})
```

Save it as `web/src/features/composer/splits.test.ts`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/splits.test.ts`
Expected: FAIL with "Failed to resolve import ./splits".

- [ ] **Step 3: Implement `web/src/features/composer/splits.ts`**

```ts
import { centsToString, parseScaled, toCents } from './amount'
import type { Share } from './state'

/** Shares in cents by user id. */
export type ShareMap = Record<string, number>

/** total / n rounded down to the cent; leftover cents to the payer when a member, else the first id (server equal_split). */
export function equalShares(total: number, memberIds: string[], payer: string | null): ShareMap {
  const ids = [...new Set(memberIds)].sort()
  if (!ids.length) return {}
  const per = Math.floor(total / ids.length)
  const out: ShareMap = Object.fromEntries(ids.map((id) => [id, per]))
  out[payer && payer in out ? payer : ids[0]] += total - per * ids.length
  return out
}

/** Typed amounts for everyone but the payer; the payer's share is what is left (negative = invalid). */
export function amountShares(total: number, memberIds: string[], payer: string, typed: Record<string, string>): ShareMap {
  const out: ShareMap = {}
  let rest = total
  for (const id of memberIds) {
    if (id === payer) continue
    out[id] = toCents(typed[id] ?? '')
    rest -= out[id]
  }
  out[payer] = rest
  return out
}

/** Percent (up to 2 decimals) for non-payers, each rounded down to the cent; the payer takes the rest. */
export function percentShares(total: number, memberIds: string[], payer: string, typed: Record<string, string>): ShareMap {
  const out: ShareMap = {}
  let rest = total
  for (const id of memberIds) {
    if (id === payer) continue
    const hundredths = parseScaled(typed[id] ?? '', 2)
    out[id] = hundredths === null ? 0 : Number((BigInt(total) * hundredths) / 10000n)
    rest -= out[id]
  }
  out[payer] = rest
  return out
}

/** "Each paid own share": everyone's typed amount, no remainder. */
export function ownShares(memberIds: string[], typed: Record<string, string>): ShareMap {
  return Object.fromEntries(memberIds.map((id) => [id, toCents(typed[id] ?? '')]))
}

export type SplitProblem = 'negative' | 'over' | 'mismatch' | null

export function splitProblem(total: number, shares: ShareMap, own: boolean): SplitProblem {
  const values = Object.values(shares)
  if (values.some((x) => x < 0)) return 'negative'
  const sum = values.reduce((a, x) => a + x, 0)
  if (own) return Math.abs(sum - total) <= 1 ? null : 'mismatch'
  return sum > total ? 'over' : null
}

export const toShareList = (memberIds: string[], shares: ShareMap): Share[] =>
  memberIds.map((id) => ({ user_id: id, amount: centsToString(shares[id] ?? 0) }))

export const typedFromShares = (shares: Share[]): Record<string, string> =>
  Object.fromEntries(shares.map((s) => [s.user_id, s.amount]))
```

- [ ] **Step 4: Run the test**

Run: `cd web && npm test -- src/features/composer/splits.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/splits.ts web/src/features/composer/splits.test.ts
git commit -m "feat(composer): split maths (equal, amounts, percent, own share) matching the server"
```

### Task C4-2: `SplitSheet`

**Stream:** C4 · **Depends on:** C4-1, C1-1 (`Sheet`, `Segmented`), C1-3

**Files:**
- Create: `web/src/features/composer/SplitSheet.tsx`, `web/src/features/composer/split.css`
- Test: `web/src/features/composer/SplitSheet.test.tsx`

**Interfaces:**
- Produces: `SplitSheet(props: SplitSheetProps)`:

```ts
export interface SplitSheetProps {
  open: boolean
  onClose: () => void
  /** 'split': the payer takes the remainder. 'own': "Who paid what", every amount typed. */
  variant: 'split' | 'own'
  totalCents: number
  currency: string
  members: Member[]
  /** The payer (split variant); null for own share. */
  payerId: string | null
  initial: { mode: SplitMode; shares: Share[] }
  onDone: (r: { mode: SplitMode; shares: Share[] }) => void
}
```

Behaviour (spec §4.6):
- Title "Split" or "Who paid what"; a "Total €64.20" line.
- Split variant: a `Segmented` labelled "Split by" with Equal · Amounts · Percent (start at `initial.mode`). Own variant: no mode control, always amounts.
- One row per member (household order): name; for Equal, the computed amount; for Amounts/Percent, an input for every non-payer (`aria-label="<name> amount"` or `"<name> percent"`, `inputMode="decimal"`, 16 px, JetBrains Mono) and the payer's computed remainder shown read-only. Own variant: an input for every member.
- Initial typed values come from `typedFromShares(initial.shares)` in Amounts and Own modes.
- A bar (`role="img"`, `aria-label` listing each member and amount) with one segment per member, widths proportional to the shares.
- Split variant: the line "<payer name> covers the remaining <payer share>". Own variant: "Left to assign <total − sum>".
- **Done** (a primary button) is disabled while `splitProblem(...)` is not null; it calls `onDone({ mode, shares: toShareList(memberIds, shares) })` then `onClose()`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Mock screen 4 (split editor).

- [ ] **Step 2: Write the failing test `web/src/features/composer/SplitSheet.test.tsx`**

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { SplitSheet, type SplitSheetProps } from './SplitSheet'
import type { Member } from './types'

afterEach(cleanup)

const MEMBERS: Member[] = [
  { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'u2', role: 'member', display_name: 'Maria', username: 'm', avatar_color: null },
]
const props = (over: Partial<SplitSheetProps> = {}): SplitSheetProps => ({
  open: true, onClose: () => {}, variant: 'split', totalCents: 1001, currency: 'EUR', members: MEMBERS,
  payerId: 'u2', initial: { mode: 'equal', shares: [] }, onDone: vi.fn(), ...over,
})

it('equal: shares to the cent with the leftover cent on the payer; Done sends every member', () => {
  const p = props()
  render(<SplitSheet {...p} />)
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'equal', shares: [{ user_id: 'u1', amount: '5.00' }, { user_id: 'u2', amount: '5.01' }] })
})

it('amounts: the payer covers the rest; Done is disabled when shares exceed the total', () => {
  const p = props({ totalCents: 1000, payerId: 'u1' })
  render(<SplitSheet {...p} />)
  fireEvent.click(screen.getByRole('radio', { name: 'Amounts' }))
  const maria = screen.getByLabelText('Maria amount')
  fireEvent.change(maria, { target: { value: '12.00' } })
  expect(screen.getByRole('button', { name: 'Done' })).toBeDisabled()
  fireEvent.change(maria, { target: { value: '3.50' } })
  expect(screen.getByText('Giorgos covers the remaining €6.50')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'amounts', shares: [{ user_id: 'u1', amount: '6.50' }, { user_id: 'u2', amount: '3.50' }] })
})

it('percent: rounded down, the payer takes the remainder', () => {
  const p = props({ totalCents: 1000, payerId: 'u1' })
  render(<SplitSheet {...p} />)
  fireEvent.click(screen.getByRole('radio', { name: 'Percent' }))
  fireEvent.change(screen.getByLabelText('Maria percent'), { target: { value: '33.33' } })
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'percent', shares: [{ user_id: 'u1', amount: '6.67' }, { user_id: 'u2', amount: '3.33' }] })
})

it('own share: "Who paid what", Done only when the amounts add up to the total', () => {
  const p = props({ variant: 'own', payerId: null, totalCents: 1000, initial: { mode: 'amounts', shares: [] } })
  render(<SplitSheet {...p} />)
  expect(screen.getByRole('dialog', { name: 'Who paid what' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Giorgos amount'), { target: { value: '6' } })
  expect(screen.getByRole('button', { name: 'Done' })).toBeDisabled()
  expect(screen.getByText('Left to assign €4.00')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Maria amount'), { target: { value: '4' } })
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(p.onDone).toHaveBeenCalledWith({ mode: 'amounts', shares: [{ user_id: 'u1', amount: '6.00' }, { user_id: 'u2', amount: '4.00' }] })
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/SplitSheet.test.tsx`
Expected: FAIL with "Failed to resolve import ./SplitSheet".

- [ ] **Step 4: Implement `SplitSheet.tsx`**

The share computation, which the layout renders:

```tsx
const ids = members.map((m) => m.user_id)
const [mode, setMode] = useState<SplitMode>(variant === 'own' ? 'amounts' : initial.mode)
const [typed, setTyped] = useState<Record<string, string>>(() => typedFromShares(initial.shares))
const payer = payerId ?? ids[0]
const shares =
  variant === 'own' ? ownShares(ids, typed)
  : mode === 'equal' ? equalShares(totalCents, ids, payer)
  : mode === 'amounts' ? amountShares(totalCents, ids, payer, typed)
  : percentShares(totalCents, ids, payer, typed)
const problem = splitProblem(totalCents, shares, variant === 'own')
const assigned = Object.values(shares).reduce((a, x) => a + x, 0)
```

Switching mode clears `typed` (amounts and percents mean different things). Layout as in **Interfaces**, using the bridge `Sheet` and `Segmented`, `formatCents` for every figure and `memberName` for names. `split.css`: rows 52 px, share inputs right-aligned in `var(--font-num)` with tabular numerals and 16 px; the bar is a 10 px rounded flex row with `--c1`..`--c6` tints and text labels beside it (colour is never the only signal).

- [ ] **Step 5: Run the test**

Run: `cd web && npm test -- src/features/composer/SplitSheet.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/composer/SplitSheet.tsx web/src/features/composer/split.css web/src/features/composer/SplitSheet.test.tsx
git commit -m "feat(composer): split sheet (equal, amounts, percent) and who-paid-what"
```

### Task C4-3: More sheet fuel, currency and rate, split row; own share from the payer pill

**Stream:** C4 · **Depends on:** C2-10 merged (C2 complete), C4-2

**Files:**
- Modify: `web/src/features/composer/MoreSheet.tsx` (three sections)
- Modify: `web/src/features/composer/ComposerForm.tsx` (only: `allowOwnShare`, `onOwnShare`, the `split` sheet state, rendering `SplitSheet`, passing `onOpenSplit` to `MoreSheet`)
- Test: `web/src/features/composer/More.test.tsx`

**Interfaces:**
- Consumes: `MoreCtx` (C2-8), `SplitSheet` (C4-2), `equalShares`/`toShareList` (C4-1), `parseFuelPrice`, `litresMilli`, `formatLitres`, `parseRate`, `convertCents` (C2-1), `isFuel` (C2-4).
- Produces: the finished More sheet (spec §4.6) and own share from the payer picker.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Mock screens 3 (More), 5 (Fuel), 4 (Split).

- [ ] **Step 2: Write the failing test `web/src/features/composer/More.test.tsx`**

```tsx
import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { writes } from './testHelpers'
import { DEFAULTS, HOUSEHOLD, renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))

afterEach(resetTestEnv)

const press = (...keys: string[]) => keys.forEach((k) => fireEvent.click(screen.getByRole('button', { name: k })))
const openMore = async () => {
  fireEvent.click(screen.getByRole('button', { name: /^More options/ }))
  return screen.findByRole('dialog', { name: 'More' })
}

it('fuel: price per litre prefilled from the last one, litres shown, price sent', async () => {
  const { api } = await renderComposer('/new', {
    defaults: { ...DEFAULTS, last: { ...DEFAULTS.last, category_id: 'c-fuel' }, fuelPrice: '1.600' },
  })
  await screen.findByRole('button', { name: 'Category: Fuel. Change' })
  press('5', '0')
  const more = await openMore()
  expect(within(more).getByLabelText('Price per litre')).toHaveValue('1.600')
  expect(within(more).getByText('Litres: 31.25 L')).toBeInTheDocument()
  fireEvent.click(within(more).getByRole('button', { name: 'Done' }))
  fireEvent.click(screen.getByRole('button', { name: /^Save 50 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ category_id: 'c-fuel', fuel_price_per_litre: '1.600' })
})

it('foreign currency: Save waits for a rate; the ≈ line and the rate are sent', async () => {
  const { api } = await renderComposer()
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Currency: EUR. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'GBP · pounds' }))
  press('2', '0')
  expect(screen.getByRole('button', { name: /^Save 20 pounds/ })).toBeDisabled()
  expect(screen.getByText('Enter the rate')).toBeInTheDocument()
  const more = await openMore()
  expect(within(more).getByText('£20.00 → set a rate')).toBeInTheDocument()
  fireEvent.change(within(more).getByLabelText('Rate'), { target: { value: '1.153' } })
  expect(within(more).getByText('£20.00 → €23.06')).toBeInTheDocument()
  fireEvent.click(within(more).getByRole('button', { name: 'Done' }))
  expect(screen.getByText('≈ €23.06')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Save 20 pounds/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({ currency: 'GBP', exchange_rate: '1.153', amount: '20.00' })
})

it('split with Maria: equal shares for every member are sent', async () => {
  const { api } = await renderComposer()
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  press('1', '0')
  const more = await openMore()
  fireEvent.click(within(more).getByRole('switch', { name: 'Split with Maria' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Split' })).getByRole('button', { name: 'Done' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'More' })).getByRole('button', { name: 'Done' }))
  fireEvent.click(screen.getByRole('button', { name: /^Save 10 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({
    payer_mode: 'single', paid_by: 'u1', splits: [{ user_id: 'u1', amount: '5.00' }, { user_id: 'u2', amount: '5.00' }],
  })
})

it('each paid own share: from the payer pill, sent as own_share with no payer', async () => {
  const { api } = await renderComposer()
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  press('1', '0')
  fireEvent.click(screen.getByRole('button', { name: 'Payer: Giorgos. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Each paid own share' }))
  const who = await screen.findByRole('dialog', { name: 'Who paid what' })
  fireEvent.change(within(who).getByLabelText('Giorgos amount'), { target: { value: '7' } })
  fireEvent.change(within(who).getByLabelText('Maria amount'), { target: { value: '3' } })
  fireEvent.click(within(who).getByRole('button', { name: 'Done' }))
  expect(screen.getByRole('button', { name: 'Payer: Each paid own share. Change' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Save 10 euro/ }))
  await screen.findByText('home screen')
  expect(writes(api)[0].body).toMatchObject({
    payer_mode: 'own_share', paid_by: null, splits: [{ user_id: 'u1', amount: '7.00' }, { user_id: 'u2', amount: '3.00' }],
  })
})

it('a one-member household has no split row and no own share', async () => {
  await renderComposer('/new', { routes: { 'GET /api/v1/settings/household': { ...HOUSEHOLD, members: [HOUSEHOLD.members[0]] } } })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  const more = await openMore()
  expect(within(more).queryByRole('switch', { name: /^Split with/ })).not.toBeInTheDocument()
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/More.test.tsx`
Expected: FAIL ("Price per litre" not found).

- [ ] **Step 4: Implement**

`MoreSheet.tsx`, new sections:
- After **Date**, **Fuel** when `isFuel(s, ctx)`: `<input aria-label="Price per litre" inputMode="decimal" value={s.fuelPrice}>` (16 px, dispatching `setFuelPrice`), `ctx.problems.fuel` under it, and, when the price parses and the amount is above 0, `Litres: ${formatLitres(litresMilli(toCents(s.amount), price))} L`. The prefill happens in `ComposerForm` (below), so the price is sent even when More is never opened.
- Then **Currency and rate** when `s.currency !== ctx.householdCurrency`: the line `${formatCents(cents, s.currency)} → ${rate ? formatCents(convertCents(cents, rate), ctx.householdCurrency) : 'set a rate'}` and `<input aria-label="Rate" inputMode="decimal" value={s.rate}>` dispatching `setRate`, with the hint "Units of <household currency> per 1 <currency>" and `ctx.problems.rate` under it.
- After **Receipt**, **Split with <name>** for expenses when `ctx.members.length > 1` and not own share: `ToggleRow` labelled `Split with ${names of the other members joined by ", "}`, checked `s.splitOn`. Turning it on calls `ctx.onOpenSplit?.()`; turning it off dispatches `{ type: 'setSplit', on: false, mode: s.splitMode, splits: [] }`. When on, a line lists the shares, plus "Fix the split" from `ctx.problems.split`.

`ComposerForm.tsx` (only these edits):
- `const allowOwnShare = !income && data.members.length > 1 && s.tookFrom === 'none' && !s.cashMode`.
- Add `'split' | 'own'` to `SheetName`. `PayerSheet`'s `onOwnShare={() => setSheet('own')}`; `MoreSheet`'s `ctx.onOpenSplit = () => setSheet('split')`.
- Fuel prefill (spec §4.6, "prefilled from `fuelPrice` in defaults"), keyed on the category so a price the user cleared stays cleared:

```tsx
useEffect(() => {
  if (s.mode === 'new' && isFuel(s, ctx) && s.fuelPrice === '' && defaults.fuelPrice) {
    dispatch({ type: 'setFuelPrice', value: defaults.fuelPrice })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [s.categoryId])
```
- Render `SplitSheet` with `open={sheet === 'split' || sheet === 'own'}`, `variant={sheet === 'own' ? 'own' : 'split'}`, `totalCents={cents}`, `currency={s.currency}`, `members={data.members}`, `payerId={s.paidBy}`, `initial={{ mode: s.splitMode, shares: s.splits }}`, and:

```tsx
onDone={(r) =>
  dispatch(sheet === 'own' ? { type: 'setOwnShare', splits: r.shares } : { type: 'setSplit', on: true, mode: r.mode, splits: r.shares })
}
onClose={() => setSheet(sheet === 'split' ? 'more' : null)}
```

When the amount changes after a split was set, `validate` flags "Fix the split" if the shares no longer fit; the user reopens the sheet from More.

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/features/composer/More.test.tsx src/features/composer/Composer.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/composer/MoreSheet.tsx web/src/features/composer/ComposerForm.tsx web/src/features/composer/More.test.tsx
git commit -m "feat(composer): fuel, currency and rate, split and own share in the composer"
```

---

## Stream C5: offline surfaces

### Task C5-1: `listQueuedBodies`

**Stream:** C5 · **Depends on:** nothing (Phase 1 `db`, `crypto`, `identity` only)

**Files:**
- Create: `web/src/offline/queuedBodies.ts`
- Test: `web/src/offline/queuedBodies.test.ts`

**Interfaces:**
- Produces: `interface QueuedBody { id: number; method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; path: string; body: unknown }`; `listQueuedBodies(pathPrefix: string): Promise<QueuedBody[]>` (pending rows only, oldest first, the signed-in account's only, undecryptable rows skipped).

- [ ] **Step 1: Write the failing test**

```ts
import { afterEach, beforeEach, expect, it } from 'vitest'
import { db, wipe } from './db'
import { setIdentity } from './identity'
import { enqueue } from './queue'
import { listQueuedBodies } from './queuedBodies'

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
})
afterEach(() => setIdentity(null))

it('lists pending bodies under a path prefix, oldest first, decrypted', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/done', body: {} })
  await enqueue({ method: 'DELETE', path: '/api/v1/transactions/t9' })
  expect(await listQueuedBodies('/api/v1/transactions')).toEqual([
    { id: expect.any(Number), method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } },
    { id: expect.any(Number), method: 'DELETE', path: '/api/v1/transactions/t9', body: undefined },
  ])
})

it("skips failed rows, another account's rows and rows it cannot decrypt", async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'failed' } })
  const [row] = await db.queue.toArray()
  await db.queue.put({ ...row, status: 'failed' })
  setIdentity({ user_id: 'u2', household_id: 'h1' })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'theirs' } })
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  await db.queue.add({ iv: new Uint8Array(12), data: new ArrayBuffer(8), createdAt: 0, attempts: 0, nextAttemptAt: 0, status: 'pending' })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'mine' } })
  expect((await listQueuedBodies('/api/v1/transactions')).map((b) => (b.body as { client_id: string }).client_id)).toEqual(['mine'])
})

it('signed out: nothing', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: {} })
  setIdentity(null)
  expect(await listQueuedBodies('/api/v1/transactions')).toEqual([])
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/offline/queuedBodies.test.ts`
Expected: FAIL with "Failed to resolve import ./queuedBodies".

- [ ] **Step 3: Implement `web/src/offline/queuedBodies.ts`**

```ts
import { open } from './crypto'
import { db } from './db'
import { getIdentity, type Identity } from './identity'

export interface QueuedBody { id: number; method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; path: string; body: unknown }
interface Stored { method: QueuedBody['method']; path: string; body?: unknown; owner?: Identity }

/**
 * Decrypted pending writes under `pathPrefix`, oldest first (2b spec §3.1). Rebuilds "Waiting to sync"
 * rows after a reload, since optimistic patches live only in memory. Read-only: never sends or deletes.
 */
export async function listQueuedBodies(pathPrefix: string): Promise<QueuedBody[]> {
  const me = getIdentity()
  if (!me) return []
  const rows = await db.queue.where('status').equals('pending').sortBy('id')
  const out: QueuedBody[] = []
  for (const row of rows) {
    try {
      const req = await open<Stored>(row)
      if (req.owner?.user_id !== me.user_id || req.owner?.household_id !== me.household_id) continue
      if (!req.path.startsWith(pathPrefix)) continue
      out.push({ id: row.id!, method: req.method, path: req.path, body: req.body })
    } catch {
      // Undecryptable or wiped mid-read: the drain handles it; just don't show it.
    }
  }
  return out
}
```

- [ ] **Step 4: Run the test**

Run: `cd web && npm test -- src/offline/queuedBodies.test.ts src/offline/queue.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/offline/queuedBodies.ts web/src/offline/queuedBodies.test.ts
git commit -m "feat(offline): listQueuedBodies reads pending writes back for Waiting-to-sync rows"
```

### Task C5-2: `usePendingTransactions`

**Stream:** C5 · **Depends on:** C5-1, C2-5 (`pendingStore`)

**Files:**
- Create: `web/src/features/composer/hooks/usePendingTransactions.ts`
- Test: `web/src/features/composer/hooks/usePendingTransactions.test.tsx`

**Interfaces:**
- Consumes: `listQueuedBodies` (C5-1), `pendingStore`, `rowFromBody`, `PendingRow` (C2-5), `db` (Phase 1).
- Produces: `interface PendingView { rows: PendingRow[]; edits: ReadonlyMap<string, PendingRow>; hiddenIds: ReadonlySet<string>; waitingCount: number; justSaved: string | null }`; `pendingFromQueue(queued: QueuedBody[]): { creates: PendingRow[]; edits: Map<string, PendingRow>; deletes: Set<string> }`; `usePendingTransactions(): PendingView`. `rows` are newest first: saves in flight (`state: 'sending'`), then queued creates (`state: 'waiting'`).

- [ ] **Step 1: Write the failing test**

```tsx
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { wipe } from '../../../offline/db'
import { setIdentity } from '../../../offline/identity'
import { enqueue } from '../../../offline/queue'
import { pendingStore, rowFromBody } from './pendingStore'
import { usePendingTransactions } from './usePendingTransactions'

const BODY = { client_id: 'c-1', type: 'expense', amount: '3.00', currency: 'EUR', bucket_id: 'b-day', category_id: null, merchant: 'Coffee Island', transaction_date: '2026-10-07' }

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
})
afterEach(() => setIdentity(null))

it('rebuilds Waiting-to-sync rows from the queue after a reload', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: BODY })
  await enqueue({ method: 'PUT', path: '/api/v1/transactions/t8', body: { ...BODY, client_id: undefined, amount: '9.00' } })
  await enqueue({ method: 'DELETE', path: '/api/v1/transactions/t9' })
  await enqueue({ method: 'POST', path: '/api/v1/transactions/t7/receipt', body: {} })
  const { result } = renderHook(() => usePendingTransactions())
  await waitFor(() => expect(result.current.rows).toHaveLength(1))
  expect(result.current.rows[0]).toMatchObject({ key: 'c-1', amount: '3.00', merchant: 'Coffee Island', state: 'waiting' })
  expect(result.current.edits.get('t8')).toMatchObject({ amount: '9.00', state: 'waiting' })
  expect([...result.current.hiddenIds]).toEqual(['t9'])
  expect(result.current.waitingCount).toBe(3)
})

it('shows a save in flight, and the same client_id only once once it is queued', async () => {
  const { result } = renderHook(() => usePendingTransactions())
  act(() => pendingStore.addInFlight(rowFromBody(BODY, 'sending')))
  expect(result.current.rows).toEqual([expect.objectContaining({ key: 'c-1', state: 'sending' })])
  await act(async () => { await enqueue({ method: 'POST', path: '/api/v1/transactions', body: BODY }) })
  await waitFor(() => expect(result.current.rows).toEqual([expect.objectContaining({ key: 'c-1', state: 'waiting' })]))
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/hooks/usePendingTransactions.test.tsx`
Expected: FAIL with "Failed to resolve import ./usePendingTransactions".

- [ ] **Step 3: Implement**

```ts
import { useLiveQuery } from 'dexie-react-hooks'
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { db } from '../../../offline/db'
import { listQueuedBodies, type QueuedBody } from '../../../offline/queuedBodies'
import { type BodyLike, type PendingRow, pendingStore, rowFromBody } from './pendingStore'

const PREFIX = '/api/v1/transactions'
const ONE = /^\/api\/v1\/transactions\/([^/]+)$/

export interface PendingView {
  /** Newest first: saves in flight, then queued creates. */
  rows: PendingRow[]
  /** Queued full edits by transaction id: show these values on the server row. */
  edits: ReadonlyMap<string, PendingRow>
  /** Deleted (queued or in flight): hide these server rows. */
  hiddenIds: ReadonlySet<string>
  /** Home's "N entries waiting to sync". */
  waitingCount: number
  justSaved: string | null
}

export function pendingFromQueue(queued: QueuedBody[]) {
  const creates: PendingRow[] = []
  const edits = new Map<string, PendingRow>()
  const deletes = new Set<string>()
  for (const q of queued) {
    const one = ONE.exec(q.path)
    if (q.method === 'POST' && q.path === PREFIX) creates.push(rowFromBody(q.body as BodyLike, 'waiting'))
    else if (one && q.method === 'PUT') edits.set(one[1], rowFromBody(q.body as BodyLike, 'waiting', one[1]))
    else if (one && q.method === 'DELETE') deletes.add(one[1])
  }
  return { creates, edits, deletes }
}

export function usePendingTransactions(): PendingView {
  // Dexie live query on the raw row ids only; decryption runs outside it (WebCrypto is not a Dexie promise).
  const ids = useLiveQuery(() => db.queue.where('status').equals('pending').primaryKeys(), [], [] as number[])
  const sig = ids.join(',')
  const [queued, setQueued] = useState<QueuedBody[]>([])
  useEffect(() => {
    let live = true
    void listQueuedBodies(PREFIX).then((b) => { if (live) setQueued(b) })
    return () => { live = false }
  }, [sig])
  const snap = useSyncExternalStore(pendingStore.subscribe, pendingStore.snapshot)
  return useMemo(() => {
    const q = pendingFromQueue(queued)
    const waitingKeys = new Set(q.creates.map((r) => r.key))
    return {
      rows: [...snap.inFlight.filter((r) => !waitingKeys.has(r.key)), ...q.creates.reverse()],
      edits: q.edits,
      hiddenIds: new Set([...snap.hidden, ...q.deletes]),
      waitingCount: q.creates.length + q.edits.size + q.deletes.size,
      justSaved: snap.justSaved,
    }
  }, [queued, snap])
}
```

- [ ] **Step 4: Run the test**

Run: `cd web && npm test -- src/features/composer/hooks/usePendingTransactions.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/composer/hooks/usePendingTransactions.ts web/src/features/composer/hooks/usePendingTransactions.test.tsx
git commit -m "feat(composer): usePendingTransactions merges in-flight and queued transaction writes"
```

### Task C5-3: Home › Recent shows pending rows; "N entries waiting to sync"

**Stream:** C5 · **Depends on:** C5-2, 2a stream E merged (`features/home/Home.tsx`, `features/home/RecentActivity.tsx`)

**Files:**
- Create: `web/src/features/home/mergePending.ts`, `web/src/features/home/mergePending.test.ts`, `web/src/features/home/RecentActivity.pending.test.tsx`
- Modify: `web/src/features/home/RecentActivity.tsx`, `web/src/features/home/Home.tsx`, and 2a's Home stylesheet (`features/home/*.css`)

**Interfaces:**
- Consumes: `usePendingTransactions`, `PendingView`, `PendingRow` (C5-2); bridge `Badge`.
- Produces: `type RecentItem<T> = { kind: 'server'; txn: T; edit: PendingRow | null; highlight: boolean } | { kind: 'pending'; row: PendingRow }`; `mergePending<T extends { id: string }>(server: T[], view: PendingView, limit?: number): RecentItem<T>[]`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Read 2a's `RecentActivity.tsx` and `Home.tsx` (row component, query, styles) first; mock screen 11 (offline) shows the badge.

- [ ] **Step 2: Write the failing tests**

`web/src/features/home/mergePending.test.ts`:

```ts
import { expect, it } from 'vitest'
import type { PendingView } from '../composer/hooks/usePendingTransactions'
import type { PendingRow } from '../composer/hooks/pendingStore'
import { mergePending } from './mergePending'

const row = (key: string, over: Partial<PendingRow> = {}): PendingRow => ({
  key, id: null, client_id: key, type: 'expense', amount: '3.00', currency: 'EUR', bucket_id: null, category_id: null,
  merchant: 'Coffee Island', transaction_date: '2026-10-07', state: 'waiting', ...over,
})
const view = (over: Partial<PendingView> = {}): PendingView => ({
  rows: [], edits: new Map(), hiddenIds: new Set(), waitingCount: 0, justSaved: null, ...over,
})
const server = [{ id: 't1' }, { id: 't2' }, { id: 't3' }]

it('pending rows first, hidden rows dropped, edits attached, the new one highlighted, capped', () => {
  const items = mergePending(server, view({
    rows: [row('c-1')], hiddenIds: new Set(['t2']), edits: new Map([['t3', row('t3', { id: 't3', amount: '9.00' })]]), justSaved: 't1',
  }), 3)
  expect(items.map((i) => (i.kind === 'pending' ? i.row.key : i.txn.id))).toEqual(['c-1', 't1', 't3'])
  expect(items[1]).toMatchObject({ kind: 'server', highlight: true, edit: null })
  expect(items[2]).toMatchObject({ kind: 'server', edit: { amount: '9.00' } })
})
```

`web/src/features/home/RecentActivity.pending.test.tsx` (2a's test kit; `RecentActivity` reads `keys.transactions.recent()` through 2a's `useRecentTransactions`):

```tsx
import { screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { page, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, TEST_IDENTITY } from '../../test/render'
import { RecentActivity } from './RecentActivity'

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('a queued save shows at the top of Recent with "Waiting to sync", and is not a link', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/transactions': () => page([]) })
  await enqueue({
    method: 'POST', path: '/api/v1/transactions',
    body: { client_id: 'c-1', type: 'expense', amount: '3.00', currency: 'EUR', bucket_id: 'b1', merchant: 'Coffee Island', transaction_date: '2026-10-07' },
  })
  renderWithProviders(<RecentActivity />)
  expect(await screen.findByText('Coffee Island')).toBeInTheDocument()
  expect(screen.getByText('Waiting to sync')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Coffee Island/ })).not.toBeInTheDocument()
})
```

If 2a's `RecentActivity` takes props, render it the way 2a's own `RecentActivity.test.tsx` does and keep the three assertions.

- [ ] **Step 3: Run them to verify they fail**

Run: `cd web && npm test -- src/features/home/mergePending.test.ts src/features/home/RecentActivity.pending.test.tsx`
Expected: FAIL with "Failed to resolve import ./mergePending", then "Unable to find an element with the text: Coffee Island".

- [ ] **Step 4: Implement**

`web/src/features/home/mergePending.ts`:

```ts
import type { PendingRow } from '../composer/hooks/pendingStore'
import type { PendingView } from '../composer/hooks/usePendingTransactions'

export type RecentItem<T> =
  | { kind: 'server'; txn: T; edit: PendingRow | null; highlight: boolean }
  | { kind: 'pending'; row: PendingRow }

/** Home › Recent: pending rows on top, deleted rows hidden, queued edits shown, the new row highlighted. */
export function mergePending<T extends { id: string }>(server: T[], view: PendingView, limit = 10): RecentItem<T>[] {
  const pending: RecentItem<T>[] = view.rows.map((row) => ({ kind: 'pending', row }))
  const rest: RecentItem<T>[] = server
    .filter((t) => !view.hiddenIds.has(t.id))
    .map((t) => ({ kind: 'server', txn: t, edit: view.edits.get(t.id) ?? null, highlight: t.id === view.justSaved }))
  return [...pending, ...rest].slice(0, limit)
}
```

`RecentActivity.tsx` (2a file), additive:
- Call `const pending = usePendingTransactions()` and render `mergePending(items, pending)` instead of `items`.
- A `pending` item renders like 2a's row with the merchant (or the bucket name, or "Expense"/"Income"), the amount (`row.amount` in `row.currency`), the date, and a `Badge` (tone `neutral`) holding a small clock icon and the text "Waiting to sync". It is not a link: no id exists yet, so it cannot be edited (spec §4.8).
- A `server` item with `edit` shows the edit's merchant, amount and date, plus the same badge.
- A `server` item with `highlight` gets the class `is-new`: a 2-second `var(--accent-soft)` background fade, with no animation under `prefers-reduced-motion` (add the rule to 2a's Home stylesheet).
- Server rows link to `/edit/<id>` if 2a's rows are links. If 2a's rows are read-only (2a spec §5.3), leave them read-only; 2c adds editing from Activity.

`Home.tsx` (2a file), additive: under the header's "In … · Out …" line, when `pending.waitingCount > 0`, render `<p className="home__waiting">{n === 1 ? '1 entry waiting to sync' : `${n} entries waiting to sync`}</p>`. The header figure itself is not patched (spec §5.3).

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/features/home`
Expected: PASS (2a's Home tests included).

- [ ] **Step 6: Commit**

```bash
git add web/src/features/home
git commit -m "feat(home): pending and queued saves in Recent, waiting-to-sync count, new-row highlight"
```

---

## Stream C6: scan

### Task C6-1: `qr.ts`, `image.ts`, the `qr-scanner` dependency, and the worker CSP

**Stream:** C6 · **Depends on:** nothing (can start now)

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (add `qr-scanner`)
- Create: `web/src/features/composer/scan/qr.ts`, `web/src/features/composer/scan/image.ts`
- Test: `web/src/features/composer/scan/qr.test.ts`, `web/src/features/composer/scan/image.test.ts`
- Modify only if Step 1 says so: `app/web_app.py` (`APP_CSP`), `tests/test_web_app.py`

**Interfaces:**
- Produces: `interface QrSession { stop(): void }`; `startQr(video: HTMLVideoElement, onDecode: (text: string) => void): Promise<QrSession>` (rejects when the camera is denied or missing); `isReceiptUrl(text: string): boolean` (an `https://` URL); `MAX_SIDE = 2000`, `JPEG_QUALITY = 0.85`, `fitWithin(w, h, max?): { w: number; h: number }`, `jpegName(name: string): string`, `shrinkImage(file: File): Promise<File>` (never rejects; returns the original file when it cannot decode or encode).

- [ ] **Step 1: Add the dependency and check how it starts its worker**

Run: `cd web && npm install qr-scanner@^1.4.2 && grep -l "createObjectURL" node_modules/qr-scanner/*.js`
- If a file is listed, the decoder runs in a `blob:` worker, which `APP_CSP`'s `worker-src 'self'` blocks on iPhones (no native `BarcodeDetector`). Then in `app/web_app.py` change `worker-src 'self'` to `worker-src 'self' blob:` inside `APP_CSP`, and add to `tests/test_web_app.py`:

```python
def test_app_csp_allows_the_qr_decoder_worker():
    from app import web_app

    assert "worker-src 'self' blob:" in web_app.APP_CSP
```

  and run `.venv/bin/python -m pytest tests/test_web_app.py -o addopts="" -p no:cacheprovider -q` (expected: PASS). Record the change in the commit message: it is the one header change 2b needs.
- If nothing is listed, leave the CSP alone.

- [ ] **Step 2: Write the failing tests**

`web/src/features/composer/scan/qr.test.ts`:

```ts
import { afterEach, expect, it, vi } from 'vitest'

const scanner = vi.hoisted(() => ({ start: vi.fn(async () => {}), stop: vi.fn(), destroy: vi.fn(), cb: null as null | ((r: { data: string }) => void) }))
vi.mock('qr-scanner', () => ({
  default: class {
    constructor(_video: HTMLVideoElement, cb: (r: { data: string }) => void) { scanner.cb = cb }
    start = scanner.start
    stop = scanner.stop
    destroy = scanner.destroy
  },
}))

import { isReceiptUrl, startQr } from './qr'

afterEach(() => vi.clearAllMocks())

it('only https URLs count as receipt QRs', () => {
  expect(isReceiptUrl(' https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=x ')).toBe(true)
  expect(isReceiptUrl('http://www1.aade.gr/x')).toBe(false)
  expect(isReceiptUrl('WIFI:S:home;P:secret;;')).toBe(false)
})

it('decodes continuously and stops cleanly', async () => {
  const onDecode = vi.fn()
  const session = await startQr(document.createElement('video'), onDecode)
  scanner.cb!({ data: 'https://example.gr/r' })
  expect(onDecode).toHaveBeenCalledWith('https://example.gr/r')
  session.stop()
  expect(scanner.stop).toHaveBeenCalled()
  expect(scanner.destroy).toHaveBeenCalled()
})

it('a denied camera rejects and releases the scanner', async () => {
  scanner.start.mockRejectedValueOnce(new Error('NotAllowedError'))
  await expect(startQr(document.createElement('video'), () => {})).rejects.toThrow('NotAllowedError')
  expect(scanner.destroy).toHaveBeenCalled()
})
```

`web/src/features/composer/scan/image.test.ts`:

```ts
import { afterEach, expect, it, vi } from 'vitest'
import { fitWithin, jpegName, shrinkImage } from './image'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('fits the longest side within 2000 px, never enlarging', () => {
  expect(fitWithin(4000, 3000)).toEqual({ w: 2000, h: 1500 })
  expect(fitWithin(1500, 3000)).toEqual({ w: 1000, h: 2000 })
  expect(fitWithin(800, 600)).toEqual({ w: 800, h: 600 })
})

it('names the result .jpg', () => {
  expect(jpegName('IMG_0001.HEIC')).toBe('IMG_0001.jpg')
  expect(jpegName('.png')).toBe('receipt.jpg')
})

it('re-encodes as JPEG 0.85 at the fitted size', async () => {
  const close = vi.fn()
  vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 4000, height: 3000, close })))
  const drawImage = vi.fn()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D)
  const toBlob = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (cb) {
    cb(new Blob(['jpeg'], { type: 'image/jpeg' }))
  })
  const out = await shrinkImage(new File(['big'], 'IMG_0001.HEIC', { type: 'image/heic' }))
  expect(out.name).toBe('IMG_0001.jpg')
  expect(out.type).toBe('image/jpeg')
  expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 2000, 1500)
  expect(toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.85)
  expect(close).toHaveBeenCalled()
})

it('falls back to the original file when it cannot decode', async () => {
  vi.stubGlobal('createImageBitmap', vi.fn(async () => { throw new Error('decode') }))
  const f = new File(['x'], 'r.heic')
  expect(await shrinkImage(f)).toBe(f)
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd web && npm test -- src/features/composer/scan/qr.test.ts src/features/composer/scan/image.test.ts`
Expected: FAIL with "Failed to resolve import ./qr".

- [ ] **Step 4: Implement**

`web/src/features/composer/scan/qr.ts`:

```ts
export interface QrSession { stop(): void }

/** Lazy-loads qr-scanner (its own chunk) and decodes continuously from the back camera; no shutter. */
export async function startQr(video: HTMLVideoElement, onDecode: (text: string) => void): Promise<QrSession> {
  const { default: QrScanner } = await import('qr-scanner')
  const scanner = new QrScanner(video, (r) => onDecode(r.data), {
    preferredCamera: 'environment',
    maxScansPerSecond: 5,
    returnDetailedScanResult: true,
  })
  try {
    await scanner.start()
  } catch (e) {
    scanner.destroy()
    throw e
  }
  return {
    stop: () => {
      scanner.stop()
      scanner.destroy()
    },
  }
}

export function isReceiptUrl(text: string): boolean {
  try {
    return new URL(text.trim()).protocol === 'https:'
  } catch {
    return false
  }
}
```

`web/src/features/composer/scan/image.ts`:

```ts
export const MAX_SIDE = 2000
export const JPEG_QUALITY = 0.85

export function fitWithin(w: number, h: number, max = MAX_SIDE): { w: number; h: number } {
  const scale = Math.min(1, max / Math.max(w, h))
  return { w: Math.round(w * scale), h: Math.round(h * scale) }
}

export const jpegName = (name: string): string => `${name.replace(/\.[^.]*$/, '') || 'receipt'}.jpg`

/** Shrinks a receipt photo for upload (spec §4.7). Never reads anything from the image. */
export async function shrinkImage(file: File): Promise<File> {
  if (typeof createImageBitmap !== 'function') return file
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const { w, h } = fitWithin(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return file
    }
    ctx.drawImage(bitmap, 0, 0, w, h)
    bitmap.close()
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
    return blob ? new File([blob], jpegName(file.name), { type: 'image/jpeg' }) : file
  } catch {
    return file // e.g. HEIC where the browser cannot decode it: upload it as it is
  }
}
```

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/features/composer/scan/qr.test.ts src/features/composer/scan/image.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/src/features/composer/scan/qr.ts web/src/features/composer/scan/image.ts web/src/features/composer/scan/qr.test.ts web/src/features/composer/scan/image.test.ts app/web_app.py tests/test_web_app.py
git commit -m "feat(scan): lazy qr-scanner session and receipt photo shrink"
```

### Task C6-2: `ScanScreen` and `useQrLookup`

**Stream:** C6 · **Depends on:** C6-1, C1-1, C3-1 + C3-2 (generated `scan/qr` types), C2-6 (`receipt.ts`)

**Files:**
- Create: `web/src/features/composer/scan/ScanScreen.tsx`, `scan/useQrLookup.ts`, `scan/scan.css`
- Test: `web/src/features/composer/scan/ScanScreen.test.tsx`

**Interfaces:**
- Consumes: `startQr`, `isReceiptUrl`, `shrinkImage` (C6-1), `receiptProblem`, `RECEIPT_ACCEPT` (C2-6), `QrReceipt` (C2-2), bridge `Segmented`.
- Produces:
  - `useQrLookup(): (url: string) => Promise<{ status: 'ok'; data: QrReceipt } | { status: 'error'; message: string }>` (never rejects).
  - `ScanScreen({ online: boolean; onResult(r: QrReceipt): void; onPhoto(file: File): void; onClose(): void })`.

Behaviour (spec §4.7, §8):
- A full-screen overlay `role="dialog" aria-modal="true" aria-label="Scan receipt"`, dark, white-on-dark controls, safe-area padding.
- A `Segmented` labelled "Scan mode": QR · Photo (QR first).
- **QR:** a `<video muted playsInline aria-label="Camera">`. On mount (QR mode, online) it calls `startQr`; it stops the session on unmount and on a mode switch.
  - A decoded value that is not a receipt URL shows "That is not a receipt QR" and scanning goes on.
  - A receipt URL calls the lookup once; while it runs, more decodes are ignored, as is a value that just failed.
  - Success calls `onResult(data)`.
  - An error shows the server message and the hint "No QR? Use Photo to attach the receipt", and scanning goes on.
- **Camera denied or missing** (`startQr` rejects): "Camera not available"; Photo, "Upload file" and "Type it instead" stay usable.
- **Photo:** a button-styled `<label>` "Take photo" wrapping `<input type="file" accept="image/*" capture="environment" aria-label="Take photo">`. The chosen file goes through `shrinkImage`, then `onPhoto(file)`.
- **Upload file:** a link-styled `<label>` wrapping `<input type="file" accept={RECEIPT_ACCEPT} aria-label="Upload file">`. Run `receiptProblem` first and show "Max 10 MB" or "Unsupported file type" inline on a problem. A PDF goes straight to `onPhoto(file)`; an image is shrunk first.
- **Type it instead:** a button that calls `onClose()`.
- **Offline:** "Scanning needs a connection. Type it instead"; the camera does not start, and Photo and Upload file are disabled (a receipt can only be uploaded online).
- There is no OCR and no call to `/scan/parse`.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Mock screen 7 (scan camera).

- [ ] **Step 2: Write the failing test `web/src/features/composer/scan/ScanScreen.test.tsx`**

```tsx
import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../../../test/render'
import { loose, writes } from '../testHelpers'
import { ScanScreen } from './ScanScreen'

const cam = vi.hoisted(() => ({ decode: null as null | ((t: string) => void), stop: vi.fn(), fail: false, started: 0 }))
vi.mock('./qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./qr')>()),
  startQr: vi.fn(async (_video: HTMLVideoElement, onDecode: (t: string) => void) => {
    cam.started++
    if (cam.fail) throw new Error('NotAllowedError')
    cam.decode = onDecode
    return { stop: cam.stop }
  }),
}))
vi.mock('./image', () => ({ shrinkImage: vi.fn(async () => new File(['small'], 'shrunk.jpg', { type: 'image/jpeg' })) }))

afterEach(async () => {
  await resetTestEnv()
  Object.assign(cam, { decode: null, fail: false, started: 0 })
})

const AADE = 'https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc'
const RESULT = { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' }

function show(over: Partial<Parameters<typeof ScanScreen>[0]> = {}) {
  const props = { online: true, onResult: vi.fn(), onPhoto: vi.fn(), onClose: vi.fn(), ...over }
  render(<QueryClientProvider client={testQueryClient()}><ScanScreen {...props} /></QueryClientProvider>)
  return props
}

it('a QR receipt URL is looked up and fills the result', async () => {
  const api = fakeApi(loose({ 'POST /api/v1/transactions/scan/qr': RESULT }))
  const p = show()
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!(AADE))
  await waitFor(() => expect(p.onResult).toHaveBeenCalledWith(RESULT))
  expect(writes(api)).toEqual([expect.objectContaining({ path: '/api/v1/transactions/scan/qr', body: { url: AADE } })])
})

it('another kind of QR says so and keeps scanning, with no request', async () => {
  const api = fakeApi({})
  show()
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!('WIFI:S:home;;'))
  expect(await screen.findByText('That is not a receipt QR')).toBeInTheDocument()
  expect(api.calls).toHaveLength(0)
  expect(cam.stop).not.toHaveBeenCalled()
})

it('a 502 shows the server message and the Photo hint, and the camera stays on', async () => {
  fakeApi(loose({ 'POST /api/v1/transactions/scan/qr': () => Response.json({ detail: 'Could not read the receipt from AADE' }, { status: 502 }) }))
  show()
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!(AADE))
  expect(await screen.findByText('Could not read the receipt from AADE')).toBeInTheDocument()
  expect(screen.getByText('No QR? Use Photo to attach the receipt')).toBeInTheDocument()
  expect(cam.stop).not.toHaveBeenCalled()
})

it('camera denied: "Camera not available", Photo and Type it instead remain', async () => {
  cam.fail = true
  const p = show()
  expect(await screen.findByText('Camera not available')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Type it instead' }))
  expect(p.onClose).toHaveBeenCalled()
  fireEvent.click(screen.getByRole('radio', { name: 'Photo' }))
  expect(screen.getByLabelText('Take photo')).toBeEnabled()
})

it('Photo attaches the shrunk image and calls nothing on the server', async () => {
  const api = fakeApi({})
  const p = show()
  fireEvent.click(screen.getByRole('radio', { name: 'Photo' }))
  fireEvent.change(screen.getByLabelText('Take photo'), { target: { files: [new File(['big'], 'IMG.HEIC')] } })
  await waitFor(() => expect(p.onPhoto).toHaveBeenCalledWith(expect.objectContaining({ name: 'shrunk.jpg' })))
  expect(api.calls).toHaveLength(0)
})

it('Upload file takes a PDF as it is and refuses other types', async () => {
  const p = show()
  const upload = screen.getByLabelText('Upload file')
  fireEvent.change(upload, { target: { files: [new File(['x'], 'notes.txt')] } })
  expect(await screen.findByText('Unsupported file type')).toBeInTheDocument()
  const pdf = new File(['%PDF'], 'r.pdf', { type: 'application/pdf' })
  fireEvent.change(upload, { target: { files: [pdf] } })
  await waitFor(() => expect(p.onPhoto).toHaveBeenCalledWith(pdf))
})

it('offline: no camera, Photo and Upload disabled', async () => {
  show({ online: false })
  expect(screen.getByText('Scanning needs a connection. Type it instead')).toBeInTheDocument()
  expect(cam.started).toBe(0)
  expect(screen.getByLabelText('Upload file')).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: 'Photo' }))
  expect(screen.getByLabelText('Take photo')).toBeDisabled()
})
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd web && npm test -- src/features/composer/scan/ScanScreen.test.tsx`
Expected: FAIL with "Failed to resolve import ./ScanScreen".

- [ ] **Step 4: Implement**

`web/src/features/composer/scan/useQrLookup.ts`:

```ts
import { useCallback } from 'react'
import { api } from '../../../api/client'
import type { QrReceipt } from '../types'

export type QrLookup = { status: 'ok'; data: QrReceipt } | { status: 'error'; message: string }

/** POST /api/v1/transactions/scan/qr (B1): AADE lookup by the URL in the receipt's QR. */
export function useQrLookup() {
  return useCallback(async (url: string): Promise<QrLookup> => {
    try {
      const { data, error, response } = await api.POST('/api/v1/transactions/scan/qr', { body: { url } })
      if (response.ok && data) return { status: 'ok', data }
      const detail = (error as { detail?: unknown } | undefined)?.detail
      return { status: 'error', message: typeof detail === 'string' ? detail : 'Could not read the receipt' }
    } catch {
      return { status: 'error', message: 'Scanning needs a connection. Type it instead' }
    }
  }, [])
}
```

`ScanScreen.tsx` decode handling (the rest is layout as specified above):

```tsx
const lookup = useQrLookup()
const busy = useRef(false)
const lastFailed = useRef<string | null>(null)
const [message, setMessage] = useState<{ text: string; hint?: string } | null>(null)

// The parent passes inline callbacks; keep them in refs so a parent re-render never restarts the camera.
const onResultRef = useRef(onResult)
useEffect(() => { onResultRef.current = onResult })

const onDecode = useCallback(async (text: string) => {
  if (busy.current || text === lastFailed.current) return
  if (!isReceiptUrl(text)) {
    setMessage({ text: 'That is not a receipt QR' })
    return
  }
  busy.current = true
  const r = await lookup(text.trim())
  busy.current = false
  if (r.status === 'ok') return onResultRef.current(r.data)
  lastFailed.current = text
  setMessage({ text: r.message, hint: 'No QR? Use Photo to attach the receipt' })
}, [lookup])

useEffect(() => {
  if (mode !== 'qr' || !online || !video.current) return
  let session: QrSession | null = null
  let live = true
  startQr(video.current, (t) => void onDecode(t)).then(
    (s) => { if (live) session = s; else s.stop() },
    () => { if (live) setCamera('unavailable') },
  )
  return () => {
    live = false
    session?.stop()
  }
}, [mode, online, onDecode]) // onDecode is stable (lookup is a stable useCallback)
```

`scan.css`: `position: fixed; inset: 0; z-index` above the composer; `background: #000; color: #fff`; the video fills the screen (`object-fit: cover`) with a centred square frame; controls at the bottom in a translucent bar with 44 px targets; messages in a readable white-on-dark card; no animation under reduced motion.

- [ ] **Step 5: Run the test**

Run: `cd web && npm test -- src/features/composer/scan/ScanScreen.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/composer/scan/ScanScreen.tsx web/src/features/composer/scan/useQrLookup.ts web/src/features/composer/scan/scan.css web/src/features/composer/scan/ScanScreen.test.tsx
git commit -m "feat(scan): camera screen with QR lookup, photo and file attach, offline and denied states"
```

### Task C6-3: Scan in the composer: chip, overlay, review banner, Remember rule

**Stream:** C6 · **Depends on:** C6-2, C4-3 (the last task to edit `ComposerForm.tsx` before this one); for the Remember toggle to show in the product, 2d stream B (its rules endpoints in the generated types)

**Files:**
- Create: `web/src/features/composer/scan/ReviewBanner.tsx`
- Modify: `web/src/features/composer/ComposerForm.tsx` (three bounded edits: the Scan chip, the scan overlay, the banner)
- Test: `web/src/features/composer/Scan.test.tsx`, `web/src/features/composer/ScanRemember.test.tsx`

**Interfaces:**
- Consumes: `ScanScreen` (C6-2); actions `applyScan`, `attachPhoto`, `setRemember` (C2-2); `shouldOfferRemember`, `RULES_API_READY` (C2-3); the save hook already posts the rule when `rememberRule` is on and `shouldOfferRemember` holds (C2-5).
- Produces: `ReviewBanner({ s: ComposerState; categories: Category[]; rulesReady: boolean; onRemember(on: boolean): void })`:
  - `s.source === 'qr'`: a banner "Read from myDATA QR".
  - `s.source === 'photo'`: "Receipt attached. Type the details."
  - When `shouldOfferRemember(s, rulesReady)`: a `ToggleRow` labelled `Remember "<merchant>" → "<category name>"`, `checked={s.rememberRule}`.
  - Nothing for a manual entry.

- [ ] **Step 1: Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.** Mock screen 8 (scan review).

- [ ] **Step 2: Write the failing tests**

`web/src/features/composer/Scan.test.tsx`:

```tsx
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv, setOnline } from '../../test/render'
import { writes } from './testHelpers'
import { renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))
const cam = vi.hoisted(() => ({ decode: null as null | ((t: string) => void) }))
vi.mock('./scan/qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./scan/qr')>()),
  startQr: vi.fn(async (_v: HTMLVideoElement, onDecode: (t: string) => void) => {
    cam.decode = onDecode
    return { stop: () => {} }
  }),
}))
vi.mock('./scan/image', () => ({ shrinkImage: vi.fn(async () => new File(['small'], 'shrunk.jpg', { type: 'image/jpeg' })) }))

afterEach(async () => {
  await resetTestEnv()
  cam.decode = null
})

const AADE = 'https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc'
const RESULT = { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' }

async function scan(result: object) {
  const r = await renderComposer('/new', { routes: { 'POST /api/v1/transactions/scan/qr': result } })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!(AADE))
  await screen.findByText('Read from myDATA QR')
  return r
}

it('a QR success fills the form, tags the fields, and saves after the duplicate check', async () => {
  const { api, router } = await scan(RESULT)
  expect(router.state.location.search).toBe('')
  expect(screen.queryByRole('dialog', { name: 'Scan receipt' })).not.toBeInTheDocument()
  expect(screen.getByText('Amount 12.50 euro')).toBeInTheDocument()
  expect(screen.getByPlaceholderText('Where? (optional)')).toHaveValue('Test Taverna')
  expect(screen.getByRole('button', { name: 'Category: Eating out, from receipt. Change' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Save 12 euro 50/ }))
  await screen.findByText('home screen')
  expect(api.calls.some((c) => c.path === '/api/v1/transactions/check-duplicate')).toBe(true)
  expect(writes(api).map((c) => c.path)).toEqual(['/api/v1/transactions/scan/qr', '/api/v1/transactions'])
  expect(writes(api)[1].body).toMatchObject({ amount: '12.50', merchant: 'Test Taverna', category_id: 'c-eat', transaction_date: '2026-10-05' })
})

it('no total: the amount stays empty with "Couldn\'t find the total"', async () => {
  await scan({ ...RESULT, amount: null })
  expect(screen.getByText("Couldn't find the total")).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Save/ })).toBeDisabled()
})

it('the Remember toggle is hidden while the rules API is not in the generated types', async () => {
  await scan(RESULT)
  fireEvent.click(screen.getByRole('button', { name: 'Category: Eating out, from receipt. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Coffee/ }))
  expect(screen.queryByRole('switch', { name: /^Remember/ })).not.toBeInTheDocument()
})

it('Photo attaches the shrunk image, opens an empty composer, and never calls /scan/parse', async () => {
  const { api } = await renderComposer('/new', { routes: { 'POST /api/v1/transactions/t1/receipt': { receipt_path: 'x.jpg' } } })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  fireEvent.click(await screen.findByRole('radio', { name: 'Photo' }))
  fireEvent.change(screen.getByLabelText('Take photo'), { target: { files: [new File(['big'], 'IMG.HEIC')] } })
  expect(await screen.findByText('Receipt attached. Type the details.')).toBeInTheDocument()
  expect(screen.getByText('Amount 0.00 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '8' }))
  fireEvent.click(screen.getByRole('button', { name: /^Save 8 euro/ }))
  await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/transactions/t1/receipt')).toBe(true))
  const upload = api.calls.find((c) => c.path === '/api/v1/transactions/t1/receipt')!
  expect(((upload.body as FormData).get('file') as File).name).toBe('shrunk.jpg')
  expect(api.calls.some((c) => c.path.endsWith('/scan/parse'))).toBe(false)
})

it('offline: the scan screen says it needs a connection', async () => {
  await renderComposer('/new')
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  act(() => setOnline(false))
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  expect(await screen.findByText('Scanning needs a connection. Type it instead')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Type it instead' }))
  expect(screen.queryByRole('dialog', { name: 'Scan receipt' })).not.toBeInTheDocument()
})
```

`web/src/features/composer/ScanRemember.test.tsx` (same mocks as `Scan.test.tsx`, plus the gate forced on):

```tsx
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv, setOnline } from '../../test/render'
import { writes } from './testHelpers'
import { renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))
vi.mock('./defaults', async (importOriginal) => ({ ...(await importOriginal<typeof import('./defaults')>()), RULES_API_READY: true }))
const cam = vi.hoisted(() => ({ decode: null as null | ((t: string) => void) }))
vi.mock('./scan/qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./scan/qr')>()),
  startQr: vi.fn(async (_v: HTMLVideoElement, onDecode: (t: string) => void) => {
    cam.decode = onDecode
    return { stop: () => {} }
  }),
}))

afterEach(resetTestEnv)

it('changing the scanned category offers Remember, on by default; Save sends one rule POST', async () => {
  const { api } = await renderComposer('/new', {
    routes: {
      'GET /api/v1/settings/category-rules': [],
      'POST /api/v1/transactions/scan/qr': { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' },
      'POST /api/v1/settings/category-rules': () => Response.json({ id: 'r1', pattern: 'test taverna', category_id: 'c-coffee' }, { status: 201 }),
    },
  })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!('https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc'))
  await screen.findByText('Read from myDATA QR')
  expect(screen.queryByRole('switch', { name: /^Remember/ })).not.toBeInTheDocument() // same as the server's suggestion
  fireEvent.click(screen.getByRole('button', { name: 'Category: Eating out, from receipt. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Coffee/ }))
  expect(screen.getByRole('switch', { name: 'Remember "Test Taverna" → "Coffee"' })).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(screen.getByRole('button', { name: /^Save 12 euro 50/ }))
  await screen.findByText('home screen')
  const rules = writes(api).filter((c) => c.path === '/api/v1/settings/category-rules')
  expect(rules).toEqual([expect.objectContaining({ body: { pattern: 'Test Taverna', category_id: 'c-coffee' } })])
})
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd web && npm test -- src/features/composer/Scan.test.tsx src/features/composer/ScanRemember.test.tsx`
Expected: FAIL ("Unable to find role button named Scan receipt").

- [ ] **Step 4: Implement**

`scan/ReviewBanner.tsx`: as specified in **Interfaces**; the banner is a `role="status"` card with a small receipt icon; the toggle uses `ToggleRow`.

`ComposerForm.tsx`, three bounded edits only:
1. Add `const [params, setParams] = useSearchParams()` and `const scanOpen = params.get('mode') === 'scan'`, plus a helper that opens or closes the overlay without adding history (so Back and Save still return to where the composer was opened from):

```tsx
const setScan = (open: boolean) =>
  setParams((p) => {
    if (open) p.set('mode', 'scan')
    else p.delete('mode')
    return p
  }, { replace: true })
```

   In the modes row, before "Cash from wallet", add `<button type="button" className="chip" onClick={() => setScan(true)}>Scan receipt</button>`.
2. Render the overlay when `scanOpen`:

```tsx
{scanOpen && (
  <ScanScreen
    online={online}
    onResult={(r) => {
      dispatch({ type: 'applyScan', result: r, householdCurrency: data.householdCurrency, today })
      setScan(false)
    }}
    onPhoto={(file) => {
      dispatch({ type: 'attachPhoto', file })
      setScan(false)
    }}
    onClose={() => setScan(false)}
  />
)}
```

   and add `scanOpen` to the hardware-keyboard effect's early return and its dependency list.
3. Above `AmountDisplay`: `<ReviewBanner s={s} categories={data.categories} rulesReady={RULES_API_READY} onRemember={(on) => dispatch({ type: 'setRemember', on })} />`.

A search-param change keeps the pathname, so the discard blocker does not fire and the draft survives "Type it instead".

- [ ] **Step 5: Run the tests**

Run: `cd web && npm test -- src/features/composer/Scan.test.tsx src/features/composer/ScanRemember.test.tsx src/features/composer/Composer.test.tsx src/features/composer/More.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/features/composer/scan/ReviewBanner.tsx web/src/features/composer/ComposerForm.tsx web/src/features/composer/Scan.test.tsx web/src/features/composer/ScanRemember.test.tsx
git commit -m "feat(composer): scan entry mode with QR review, photo receipt and the Remember rule"
```

---

## Stream C7: integration

### Task C7-1: Full checks and the manual pass at 390×844

**Stream:** C7 · **Depends on:** every task above merged in order (C3, C1, C2, then C4, C5, C6)

**Files:**
- Modify: only what the checks below find broken (each fix with a test in the owning file).

- [ ] **Step 1: Generated types are current**

Run: `cd web && npm run gen:api && git diff --exit-code src/api`
Expected: no diff. If 2d's rules path appears in `schema.d.ts` now, `npm run typecheck` fails on `RULES_API_READY`: set it to `true` in `defaults.ts`, rerun `npm test -- src/features/composer`, and commit "chore(composer): enable the Remember rule now that 2d's rules API is in the types".

- [ ] **Step 2: Frontend checks**

Run: `cd web && npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass. Then `ls dist/assets | grep -i qr` shows a separate `qr-scanner` chunk (the composer bundle does not include it), and `grep -c "<script>" dist/index.html` and `grep -c "<style" dist/index.html` both print `0` (the strict CSP holds).

- [ ] **Step 3: Backend checks**

Run: `.venv/bin/python -m pytest -n 8 -o addopts="" -p no:cacheprovider -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: all pass.

- [ ] **Step 4: Manual pass in Chrome at 390×844 (light and dark)**

Load skill `chrome-devtools-mcp:chrome-devtools` (or use the Chrome DevTools MCP tools directly). Run the backend with `NEW_APP_ENABLED=true DEBUG=true .venv/bin/uvicorn app.main:app --port 8000` and `npm run dev` in `web/`; sign in to the old UI at `http://localhost:5173/login`, then open `http://localhost:5173/app/new`. Emulate 390×844 with touch. In light and in dark, check and screenshot each:
1. The two-tap save: open ＋, press 3, Save. The toast reads "Saved €3.00 to <budget>" with Undo, the tab bar is hidden while composing, and the new row is highlighted on Home.
2. Income: green amount and Save, Received by, no method pill.
3. Foreign currency: GBP, rate, the "≈ €" line.
4. Fuel: price per litre and litres.
5. Split with the partner, and Each paid own share.
6. Cash from wallet: payer "You", the wallet line, over-stash blocked.
7. Edit from `/app/edit/<id>`: values loaded, type locked, Save changes; Delete with confirm.
8. Discard confirm on ✕ after typing.
9. Look for overflow at 360 and 430 px wide, text over 16 px in inputs (no zoom), 44 pt targets, the keypad hiding while the merchant field has focus, and contrast in both themes.

- [ ] **Step 5: Manual offline pass**

DevTools → Network → Offline. Save an expense; the toast reads "Saved on this phone. It will sync when you're back online." Reload: Home › Recent shows the row with "Waiting to sync" and Home shows "1 entry waiting to sync". Go online: one row appears (check the Network tab: one POST to `/api/v1/transactions`, `201` or `200`), the badge goes away, and a match suggestion appears on Home when the amount matches a due entry. The Scan chip offline shows "Scanning needs a connection. Type it instead", and More shows "Add the receipt later when you're online (Edit)".

- [ ] **Step 6: Built app under the real CSP**

Run `cd web && npm run build`, start the backend so it serves `web/dist` at `/app/`, open `/app/new`, open Scan receipt and allow the camera (Chrome can use a fake camera: `--use-fake-device-for-media-stream`). Confirm the Console shows no CSP violation (in particular none for `worker-src`).

- [ ] **Step 7: Hand-over notes**

Report to the user, who does the real-device check: the camera, the `capture` photo input and the keypad with the iOS keyboard on an iPhone home-screen install (spec §9), plus anything the manual pass found and fixed.

- [ ] **Step 8: Commit any fixes**

```bash
git add -A
git commit -m "fix(composer): integration pass fixes"
```

(Skip the commit when nothing changed.)
