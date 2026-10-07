# Phase 2b: the ＋ Composer (design)

- **Date:** 2026-10-07
- **Status:** drafted for review. Calls the author made are listed in "Decisions made in this spec" at the end.
- **Builds on:**
  - the Phase 1 shell (`web/`): encrypted cache, offline queue and `api` client;
  - Phase 2a (spec `2026-10-07-phase-2a-plan-home-design.md`, here "2a"): its UI kit (`web/src/ui`), `useCachedQuery`, `useAction` and `keys.ts`. This spec reuses them and does not redefine them. Additions are named explicitly (§3.1).
- **Visual source:** `docs/redesign/mocks/composer.html` (all 11 screens), with `tokens.css` and `components.css`.
- **Product decisions already made:**
  - one composer for create and edit, keypad-first;
  - a €3 coffee saves in 2 taps;
  - an Expense/Income toggle;
  - a smart-defaults row: budget · category · payer · method;
  - "More" holds split, fuel, notes, receipt and FX;
  - Scan and Cash are entry modes of the same composer;
  - it works offline through the queue, with `client_id` for idempotency;
  - settle-up is removed; payer and per-member shares stay.

## 1. Purpose

The composer is the one place where money is typed in. It replaces the old 4-step expense wizard, the long edit form, the separate income page, the scan confirmation form and the cash "take and spend" form.

**Success means** on an iPhone home-screen install:
1. Opening ＋, typing `3` and tapping **Save** records a €3 expense with a budget, category, payer and method already filled from the last entry. That is two taps.
2. Income, foreign-currency, split, own-share, fuel and cash expenses can all be entered and edited without the old app.
3. A Greek receipt QR fills the form from AADE and the user checks it and saves; a photo is attached as the receipt and opens the composer for manual entry.
4. With no signal, Save still works. The entry shows in Home and Activity as "Waiting to sync" and is sent exactly once when the connection returns, however many times it is retried.
5. Editing an existing transaction uses the same screen, with every stored field round-tripped.

## 2. Scope

**In scope:**
- Create and edit of expenses and income (`POST /transactions`, `PUT /transactions/{id}`), plus Delete from the edit screen.
- Entry modes: Scan receipt (QR, Photo) and Cash from wallet.
- Smart defaults kept in the encrypted local store.
- Receipt photo/PDF upload (needs a connection, §5.4).
- Duplicate check on Save.
- "Remember merchant → category" rules, taught from the composer. The rules API belongs to 2d (§6.1); the composer only consumes it.
- Two small backend additions (§6). No migration.

**Existing behaviour, not new work:** after a save, the server (`create_transaction` → `_suggest_match`) looks for a due entry the new transaction may pay or receive and records a match suggestion. Home › Needs attention (2a §5) already shows it with **Link** and **Not this**. The composer only invalidates the matches query after a save (§5.3).

**Out of scope:**
- Activity list and bulk changes (2c). Edit is reached from Activity through the route `/edit/:id`, which this spec provides.
- Insights, Settings and category/bucket management (2d). The composer never creates buckets or categories.
- Cash wallet management (adding/withdrawing cash, 2c/2d). The composer only records "spent from cash" through `took_cash` / `take_from`.
- Settle-up in any form. `exclude_from_settlement` is never offered; edit sends back the stored value unchanged.
- OCR of any kind (no on-phone text recognition; no `tesseract.js`), a live FX rate lookup, and recurring entry creation (that is Plan › Items).
- The category-rules endpoints themselves (2d owns them).

## 3. Architecture

```
web/src/
  ui/                       2a kit, plus these additions (no data access):
    Keypad.tsx              12 keys (0-9 . backspace), 48 px rows, haptic-free
    AmountDisplay.tsx       big amount with caret, currency chip, "≈ €x" line
    Pill.tsx                the default-pill button (label, value, optional dashed "empty" state)
    ToggleRow.tsx           label, hint, switch (Split with Maria, Count in forecast)
  features/composer/
    Composer.tsx            full screen: top bar, modes row, amount, merchant, pills, More link, Save bar
    state.ts                useReducer state, actions, "touched" set
    amount.ts               keypad reducer and decimal helpers (no floats)
    model.ts                state <-> API: toCreateBody, toUpdateBody, fromTransaction, validate
    splits.ts               equal / amounts / percent maths, own-share rules
    defaults.ts             load/save smart defaults, rule matching (fold)
    hooks.ts                useComposerData, useSaveTransaction, useDuplicateCheck,
                            useReceiptUpload, usePendingTransactions
    pickers/                BucketSheet, CategorySheet, PayerSheet, MethodSheet, CurrencySheet, DateSheet
    MoreSheet.tsx           date, fuel price, FX, notes, receipt, split row, forecast toggle
    SplitSheet.tsx
    scan/                   ScanScreen.tsx (QR | Photo), qr.ts, image.ts (shrink), ScanReview banner
```

- **Routes** (change to `router.tsx`):
  - `/new` and `/new?mode=scan|cash` become top-level routes beside `AppShell`, so the tab bar is hidden while composing.
  - `/new?from=<txnId>` opens a copy of a transaction (the old "Duplicate" action), with a new `client_id` and today's date.
  - `/edit/:id` is the edit route.
  - `screens/Compose.tsx` becomes a one-line re-export of `features/composer/Composer`.
  - The TabBar link to `/new` is unchanged.
- **Closing:** the ✕ button and the browser Back go to the previous route, or `/` if there is none. If the amount is above zero or notes/merchant are filled, a confirm sheet asks "Discard this entry?". The draft is not kept after the app is closed.
- Screens use hooks and the kit only. They never call `api` directly, as in 2a.

### 3.1 Additions to 2a's modules (named, additive)

| Where | Addition | Why |
|---|---|---|
| `data/action.ts` | `run()` resolves `{ status: 'done', data } \| { status: 'queued' }` | the composer needs the new transaction id when the call went online (Undo, receipt upload). If 2a already returns this, no change. |
| `data/keys.ts` | `transactions.recent`, `transactions.one(id)`, `buckets`, `categories`, `household`, `categoryRules` (reads 2d's endpoint), `cashStash`, `matches` (the last may already exist) | reads the composer needs; saves invalidate `transactions.recent`, `matches`, `plan.*`, `home.*` |
| `offline/queue.ts` | `listQueuedBodies(pathPrefix): Promise<{id, method, path, body}[]>` (decrypts pending rows) | rebuilds "Waiting to sync" rows after an app reload, since the optimistic patch lives only in memory |
| `data/cachedQuery.ts` | none | `useCachedQuery` is used as is |

Composer reads: `GET /buckets`, `GET /settings/categories`, `GET /settings/household` (members, default currency), `GET /settings/category-rules` (2d, §6.1), `GET /transactions?page_size=200` (merchant suggestions only), `GET /transactions/{id}` (edit), `GET /cash/movements?limit=1` (stash balance, cash mode only). All go through `useCachedQuery`, so the composer opens fully populated offline after one online session.

## 4. Screens and flows

### 4.1 Composer layout (top to bottom)

1. **Top bar:** ✕ · segmented **Expense | Income** (income selected turns the amount and Save green, `--pos`) · overflow menu (edit mode: Delete; new mode: none).
2. **Modes row** (new expense only): chips **Scan receipt** and **Cash from wallet**. A chip toggles its mode; the active chip is filled.
3. **Amount:** `AmountDisplay` with a caret, 62 px (44 px above 9 characters), and a currency chip (default EUR) that opens the currency sheet.
4. **Merchant** text input ("Where? (optional)"), with up to 5 suggestions from recent merchants once 2 characters are typed.
5. **Smart-defaults row (pills):** Budget · Category · Payer · Method. For income: Received by · Category · Budget (optional) · Date. Each pill shows its current value and opens a picker sheet; one tap picks and closes.
6. **More** link (shows a dot when anything inside it differs from its default), opening the More sheet.
7. **Keypad** pinned to the bottom, and the **Save bar** below it: "Save €4.10" ("Save income €700.00").

### 4.2 Amount entry

- Keys: `0-9`, `.`, backspace (long press clears). A hardware keyboard works the same, and Enter triggers Save.
- Rules: at most 2 decimals, at most 7 integer digits, one decimal point, no leading zeros ("007" shows "7"). `.` first gives "0.".
- The value is kept as a string and parsed as a decimal in `amount.ts`; floats are never used for money. The API receives it as a string (`"4.10"`), which `TransactionCreate` accepts.
- Save is disabled while the amount is zero or empty.

### 4.3 Defaults and the two-tap path

**On open (new expense)**, each pill takes its value from the `composer.defaults` record in the encrypted cache (`cachePut`/`cacheGet`):

| Pill | Default |
|---|---|
| Budget | `last.bucket_id`, if that bucket is still active; otherwise empty (dashed pill, Save disabled, label "Choose a budget") |
| Category | `last.category_id`, if it still exists; otherwise none (category is optional) |
| Payer | `last.paid_by` if still a member, else the signed-in user |
| Method | `last.payment_method`, else `card` |
| Date | today on the device (§5.2) |
| Currency | household `default_currency` |

**Learning.** The defaults record is `{ last, byCategory, byBucket, recentCategoryIds (max 4), rates, fuelPrice }`. It is rewritten when Save is tapped, whether the save goes online or is queued (not on server success), so it is available offline.

**Re-defaulting while composing.** A `touched` set records fields the user picked by hand in this session.
- Picking a category fills Budget, Payer and Method from `byCategory[category]` for untouched fields only.
- Picking a budget fills Category, Payer and Method from `byBucket[bucket]` for untouched fields only (a fuel bucket remembers Fuel).
- Typing a merchant that matches a household rule sets Category if untouched, and the Category pill shows "rule: coffee island". Rules come from 2d's `GET /settings/category-rules`; without that endpoint no rules are loaded and no rule suggestion shows. Matching mirrors the server: fold both sides (case-fold, strip accents, final ς to σ, collapse spaces) and test substring; the longest pattern wins.

**Income** has its own `lastIncome` record (`category_id`, `bucket_id` (default none), `paid_by`). Income method is sent as `transfer` unless `lastIncome` says otherwise; there is no method pill for income.

### 4.4 Pickers

- **Budget** (`GET /buckets`): active buckets only. Event buckets show their date range. For income only buckets with `show_income = true` are listed, plus "None" (the default); expense has no "None".
- **Category** (`GET /settings/categories`): search box, then **Suggested** (the rule match, with its reason), **Recent** (up to 4), **All**. The Fuel category (`system_key = "fuel"`) shows "Asks for price per litre". Picking closes the sheet.
- **Payer** (`household.members`): each member, plus **Each paid own share** (expense only, hidden for cash-from-wallet; sends `payer_mode: "own_share"`, §4.6). For income the pill reads "Received by" and lists members only.
- **Method:** Card · Cash · Apple Pay · Transfer · Other (`payment_method` values `card`, `cash`, `apple_pay`, `transfer`, `other`).
  - Choosing **Cash** (not through the mode chip) shows a "Took from" control under the pills: **Not tracked** (default; `took_cash` false) · **My wallet** (`took_cash` true, `take_from: "stash"`) · **Bank/ATM** (`take_from: "bank"`).
- **Currency:** EUR, USD, GBP, CHF, JPY, AUD, CAD, SEK, NOK, DKK (a constant in the web code that mirrors `settings.currencies`).

### 4.5 Cash from wallet mode

The chip sets Method to Cash and "Took from" to My wallet, and locks Payer to the signed-in user (the server answers 400 for a take paid by someone else).
- The Payer pill shows "You" with no chevron, and **Each paid own share** is unavailable.
- Under the pills it shows "Wallet: €X" from the cached `GET /cash/movements?limit=1` (`stash`). If the source is My wallet and the amount (converted to EUR) exceeds a known stash, Save is disabled with "Your wallet has €X". If the stash is unknown, Save stays enabled and the server decides.
- Turning the chip off returns Method and Took-from to their defaults.
- Wallet management stays out of scope. Cash mode is only entry.

### 4.6 More sheet

All fields below live in one scroll, in this order.

| Field | Behaviour |
|---|---|
| **Date** | Chips Today · Yesterday · the day before (weekday + date) · "Pick a date" (native `<input type=date>`). No future dates beyond today (validation, §4.9). |
| **Fuel** | Shown only when the category is Fuel and type is expense. Field **Price per litre** (decimal, 3 decimals, prefilled from `fuelPrice` in defaults). Below it, "Litres: 31.2 L", computed as amount ÷ price, half-up to 3 decimals. The server stores its own value and ignores any client litres. |
| **Currency and rate** | Shown when currency is not the household's. Shows "£20.00 → €23.06" and a **Rate** field (units of household currency per 1 unit of the chosen currency, up to 6 decimals, greater than 0 and at most 1,000,000). Prefilled from `rates[currency]` (the last rate used); with none, the field is empty and Save is disabled with "Enter the rate". There is no live rate lookup, because the backend has none. |
| **Notes** | Multi-line, up to 500 characters, 16 px font. |
| **Receipt** | "Attach receipt" (Photo or PDF) opens the file picker (`accept="image/*,application/pdf"`). In edit mode with `receipt_path` it reads "Receipt attached" with View (opens `/transactions/files/<receipt_path>`) and Replace. Needs a connection (§5.4). |
| **Split with <member>** | Expense only. A toggle row that opens the split sheet. Off means no `splits`: all of it is the payer's share. Shown with a single member in the household: hidden. |
| **Count in forecast** | Toggle, on by default; off sends `exclude_from_forecast: true`. Hint "Turn off for one-offs". |

**Split sheet.** Header "Split" · Done. It shows the total and the members.
- **Equal:** shares are `total / n` rounded down to the cent, and the leftover cents go to the payer (the same rule as the server's `equal_split`).
- **Amounts:** the user types every member's amount except the payer's; the payer's share is the remainder.
- **Percent:** the user types percents for the non-payers; amounts are rounded down to the cent; the payer takes the remainder.
- A bar shows the shares and a line reads "Giorgos covers the remaining €0.00".
- **Done** is disabled while any share is negative or the shares exceed the total.
- Sent as `splits: [{user_id, amount}]` for **every** member, adding up to the total exactly.
- **Each paid own share** opens the same sheet with the title "Who paid what", in Amounts mode, where every member's amount is typed. Done requires the amounts to add up to the total to the cent. Sent as `payer_mode: "own_share"`, `paid_by: null` and the splits. Not available for income or while `took_cash` is on.

### 4.7 Scan entry (Scan receipt chip → `/new?mode=scan`)

A full-screen camera with a segmented **QR | Photo**, an "Upload file" link and "Type it instead" (back to the composer, nothing lost). There is no OCR: the two modes are a lookup and an attachment.
- **QR** (the main path for Greek receipts). `qr.ts` lazy-loads the `qr-scanner` package (a separate chunk) and decodes continuously, with no shutter.
  - The first decoded value that is an `https://` URL is sent to `POST /api/v1/transactions/scan/qr` (new, §6) with `{ url }`.
  - Another kind of QR shows "That is not a receipt QR" and keeps scanning.
  - A 400 or 502 shows the server's message and the hint "No QR? Use Photo to attach the receipt", and keeps the camera running.
- **Photo.** An `<input type=file accept="image/*" capture="environment">` takes the picture. `image.ts` shrinks it (longest side 2000 px, JPEG quality 0.85) and sets it as the receipt attachment. The composer then opens empty for manual entry, with the hint "Receipt attached. Type the details." Nothing is read from the image, and `POST /transactions/scan/parse` is not called.
- **PDF:** only through "Upload file", and only as an attachment, as for Photo.
- **Permission denied or no camera:** the screen shows "Camera not available", with Photo and "Type it instead".
- **Offline:** the screen shows "Scanning needs a connection. Type it instead" and disables QR. Photo is disabled too, because a receipt can only be uploaded online (§5.4).

**Review (QR).** On success the composer opens in review state with these set from the response: `amount`, `currency`, `date`, `merchant`, `category_id`. Budget, Payer and Method come from the defaults.
- A banner reads "Read from myDATA QR". Fields filled from the receipt carry a small "from receipt" tag until edited.
- If the response had no amount (null), the amount stays empty and a hint says "Couldn't find the total".
- **Remember "<merchant>" → "<category>"** toggle: shown when the merchant has at least 2 characters and the chosen category differs from the server's suggestion. It is on by default. On Save, it sends `POST /api/v1/settings/category-rules` (2d, §6.1), queued like any write. **It depends on 2d's endpoint:** if 2d has not merged, the toggle is hidden. The flag is a constant `RULES_API_READY` in `defaults.ts`, true only when `/api/v1/settings/category-rules` is in the generated API types at build time (a type-level assertion fails `npm run typecheck` if the constant and the types disagree).
- The review is a normal composer: everything is editable, and Save works exactly as in §4.9.

### 4.8 Edit mode (`/edit/:id`)

- Loads `GET /transactions/{id}` through `useCachedQuery`, with a skeleton and no keypad until it is ready. No data and offline: "Connect once to load this entry." with a Back button.
- The Expense/Income toggle is locked (shown, not tappable). Modes chips are hidden. The keypad is up with the stored amount.
- The saved `exclude_from_settlement` value is sent back untouched. The "Took from" control is hidden, because the API ignores `took_cash` on edit (an existing take follows the amount and date by itself).
- A transaction linked to a recurring item with no budget (a **Fixed cost**) shows the Budget pill as "Fixed cost" and read-only, and sends `bucket_id: null`. A bill payment that has a budget keeps a normal Budget pill.
- Save sends `PUT /transactions/{id}` with the full body (§4.10). The button reads "Save changes".
- **Delete:** the overflow menu → a confirm sheet "Delete this entry?" → `DELETE /transactions/{id}` (queued when offline, with the row hidden at once). A 404 means it is already gone and counts as success.
- An entry that is still "Waiting to sync" has no id and cannot be opened for editing.

### 4.9 Validation (client first, server is the authority)

| Rule | Where it shows |
|---|---|
| Amount greater than 0 | Save disabled |
| Expense needs a budget | Budget pill dashed "Choose a budget", Save disabled |
| Income budget is optional; if set it must track income | picker only lists such budgets |
| Date not later than today | Date chip row; Save disabled with "Date can't be in the future" |
| Non-household currency needs a rate | Save disabled "Enter the rate" |
| Fuel price, if entered, greater than 0 | inline error under the field |
| Splits within the total; own-share adds up to the total (±0.01) | split sheet Done disabled; More shows "Fix the split" |
| Cash from wallet: payer is you; amount within a known stash | §4.5 |
| Notes at most 500 characters; merchant at most 100 | counter / input limit |

Server `422`/`400` messages that slip through are shown as a toast (§8) and the composer stays open with everything kept.

### 4.10 Save, and the field map

**Save steps (new):**
1. If online, the type is expense and a duplicate check applies, call it (§4.11).
2. Build the body with `toCreateBody` and call `useAction` (POST `/api/v1/transactions`).
3. Write the defaults record (§4.3), then close the composer and show the toast.
4. Online and a receipt chosen: upload it (§5.4).

**Composer field to API field** (`TransactionCreate` for create, `TransactionUpdate` for edit):

| Composer field | API field | Notes |
|---|---|---|
| Expense/Income toggle | `type` | `expense` or `income` (never `transfer`) |
| Amount | `amount` | decimal string |
| Currency chip | `currency` | default is the household currency |
| Rate | `exchange_rate` | `"1"` when the currency is the household's |
| Budget pill | `bucket_id` | required for expense; null for income without a budget and for Fixed costs |
| Category pill | `category_id` | optional |
| Merchant | `merchant` | blank sends null; the server cleans it |
| Payer / Received by | `paid_by` | member id; null with own-share |
| "Each paid own share" | `payer_mode: "own_share"` | otherwise `"single"`; on edit always sent explicitly |
| Method pill | `payment_method` | `card`/`cash`/`apple_pay`/`transfer`/`other` |
| Took from (cash) | `took_cash`, `take_from` | create only; `take_from` is `stash` or `bank` |
| Date | `transaction_date` | always sent as `YYYY-MM-DD` from the device (§5.2) |
| Notes | `notes` | blank sends null |
| Split sheet | `splits` | `[{user_id, amount}]`, empty when off |
| Price per litre | `fuel_price_per_litre` | only for Fuel; on edit sent explicitly (null when cleared) |
| Litres | none | computed by the server; displayed only |
| Count in forecast | `exclude_from_forecast` | inverse of the toggle |
| (none) | `exclude_from_settlement` | create: `false`; edit: the stored value |
| (none) | `client_id` | create only (§5.1) |
| Receipt | `POST /transactions/{id}/receipt` | multipart `file`, separate call |

The composer uses `POST /transactions` for income too, not `POST /income`, because `IncomeIn` has neither `client_id` nor a payer.

### 4.11 Duplicate check

- When Save is tapped for a new expense, online, `GET /api/v1/transactions/check-duplicate?amount=&transaction_date=&bucket_id=` (new, §6) runs with a 2 second timeout.
- With matches: nothing is saved; an inline card says "Looks like <merchant or bucket> <€> from <date>. Save anyway?" for the first match, with **Open that one** (goes to `/edit/<id>`; the typed draft is dropped) and **Save anyway** (continues from step 2).
- No matches, an error, a timeout or offline: save directly. The check never blocks. It does not run for income or for edits. It does run for scan review saves, because a duplicated scan is the common case.

### 4.12 After saving

- The composer closes and a toast shows "Saved €64.20 to Day to day" with **Undo** for 5 seconds.
  - Undo (online saves only) sends `DELETE /transactions/{id}` and removes the row from the lists.
  - A queued save has no Undo. Its toast reads "Saved on this phone. It will sync when you're back online."
- The new row appears at the top of Home › Recent, highlighted for 2 seconds (disabled under reduced motion).
- Match suggestions: existing behaviour, see §2.

## 5. Offline and idempotency

### 5.1 `client_id`

- `crypto.randomUUID()` is generated when a new composer mounts (36 characters, within the API's 64-character limit) and sent as `client_id` on create. Edit does not send one.
- The server enforces `unique (household_id, client_id)`, and `create_transaction` answers a replay with `200` and the existing row, never a second row. A replay of an entry that was since deleted answers `409`, and the Phase 1 queue drops it without retry, so a deleted entry is never resurrected.
- The same id is used for every attempt of one entry: a double tap on Save, an online request whose response is lost (which `useAction` then queues), and the queue replay. Save is also disabled while a save is in flight.

### 5.2 What is sent when

- The date is always sent, taken from the device's local calendar day when the entry was created. Left blank, the server would use the day of the replay.
- The amount, rate, split amounts and fuel price are fixed in the body at creation. A queued entry is never recomputed on replay.

### 5.3 Using `useAction`

- **Create** `useAction({ method: 'POST', path: '/api/v1/transactions', body, optimistic, invalidates })`.
  - `optimistic` inserts a row into `transactions.recent` marked `pending` and keyed by `client_id`.
  - `invalidates`: `transactions.recent`, `matches`, `plan.*`, `home.*`, `buckets`.
- **Edit** is `PUT /api/v1/transactions/{id}`; `optimistic` patches the cached `transactions.one(id)` and the list row. Delete is a `DELETE`; `optimistic` hides the row. Both queue when offline, since their ids are known.
- **Category rule** is `POST /api/v1/settings/category-rules` (2d). The server upserts by pattern (201 new, 200 existing), so it is idempotent and queueable.
- **Reload while queued:** `usePendingTransactions` calls `listQueuedBodies('/api/v1/transactions')`, builds rows from the bodies (labelled with a "Waiting to sync" badge) and merges them into Home › Recent. The Home header figure is not patched; Home shows "1 entry waiting to sync" under it. After the queue drains, 2a invalidates the plan and home keys.
- **Failure after replay:** a 4xx on a queued create (for example "Your wallet has less cash") appears in Home › Needs attention as "1 change couldn't be saved" with the server message, as in 2a §3.2.
- **Last write wins for edits:** a queued `PUT` replaces the whole row, so an edit the partner made in the meantime is overwritten. Accepted for a two-person household.

### 5.4 Receipts

Receipts are multipart uploads and the queue only holds JSON, so they need a connection.
- **Offline:** "Attach receipt" is disabled with "Add the receipt later when you're online (Edit)". If the connection is lost after a file was chosen and the save is queued, the file is dropped and the toast reads "Saved on this phone. The receipt wasn't attached: add it when you're back online."
- **Online:** after a successful create (or an edit), the app calls `POST /transactions/{id}/receipt`. Up to 10 MB; `.jpg .jpeg .png .gif .webp .pdf .heic .heif` are accepted by the server and the picker; the client checks size and extension first.
- **Upload failure:** the entry is already saved. The toast reads "Saved. The receipt didn't upload." with **Retry**. The file stays in memory until the toast is dismissed or the page is closed, and the edit screen can attach it later.
- **Replacing** a receipt sends the same call; the server deletes the old file.

### 5.5 Reads offline

All composer reads are cached (§3.1). Only these need a connection: scanning, duplicate check, receipt upload and wallet balance freshness.

## 6. Backend changes

Two small, additive additions, with **no migration**. The `down_revision` rule (`c9d0e1f2a3b4`) does not come into play. The web types are regenerated afterwards with `npm run gen:api`.

| # | Endpoint | Why | Behaviour |
|---|---|---|---|
| B1 | `POST /api/v1/transactions/scan/qr` | the QR lookup exists only as an HTML route (`/transactions/scan/qr`, cookie+CSRF page auth, not in the API). | Same body `{url}` and response as today (`amount, currency, date, merchant, category_hint, category_id`). The logic moves into a shared function used by both routes. `require_api_auth`; the same SSRF checks and 400/502 messages. |
| B2 | `GET /api/v1/transactions/check-duplicate` | the check exists only on the HTML side. | Query `amount`, `transaction_date`, `bucket_id` (optional), `exclude_id` (optional). Returns `{ duplicates: [{id, amount, currency, date, notes, merchant, bucket, paid_by, same_bucket}] }` (at most 5), from `find_duplicate_candidates`. Blank or invalid input returns an empty list. Advisory only. |

`POST /api/v1/transactions/scan/parse` is not used by the composer (there is no OCR text to send). It stays exactly as it is.

### 6.1 Category rules come from 2d

2d owns `/api/v1/settings/category-rules` (2d §7.4). The composer consumes two calls at that path and adds nothing of its own:
- `GET` list `[{id, pattern, category_id, ...}]`, used for rule matching (§4.3);
- `POST {pattern, category_id}`, an upsert by pattern returning the rule (201 new, 200 existing), 400 for a pattern under 2 characters or another household's category, used by the Remember toggle (§4.7).

If 2d has not merged, the list is empty and the toggle is hidden (§4.7).

The old HTML routes stay until the old app is removed; the shared functions mean no duplicated logic. The receipt view link (`/transactions/files/<receipt_path>`) also lives on the HTML side; if that route is removed later, an API file route must replace it first (listed in the backlog, not done here).

Existing behaviour relied on, unchanged: `client_id` idempotency (§5.1), the take rules (`took_cash` needs a cash expense paid by the submitter), `fuel_fields` (litres computed server-side), `own_share` checks, and the match suggestion hook.

## 7. Look and accessibility

- **Vault tokens** from 2a. The composer uses the mock's layout: a fixed column, the keypad pinned to the bottom (`.keypad.tight`, 48 px rows), and the amount caret blinking in `--accent` (`--pos` for income). The caret does not blink under `prefers-reduced-motion`.
- **Sheets** are 2a's `Sheet` (focus trap, Esc/backdrop close, safe-area padding). Pickers close on selection.
- **Camera screen:** full-bleed, white-on-dark controls, a visible text alternative for every control.
- **Numbers:** tabular numerals, Sora for the amount and JetBrains Mono for share boxes.
- **Tap targets:** 44 pt minimum; the keypad keys are at least 48 px high.
- **Inputs:** 16 px font or larger, so iOS never zooms. When a text input is focused, the keypad hides (visual viewport resize) and returns on blur.
- **Names and live regions:**
  - the amount is a `role="status"` element reading "Amount 4.10 euro";
  - each key has an accessible name ("Delete last digit" for backspace);
  - each pill reads "Budget: Day to day. Change";
  - Save reads "Save 4 euro 10 to Day to day".
- **Colour never alone:** income also says "Income" in the toggle and Save; errors carry text.
- **Offline:** an "Offline" tag in the top bar, and a "Waiting to sync" badge (text plus icon) on pending rows.
- **Width:** 360 to 430 px; wider screens get the centred 480 px column from 2a.

## 8. Errors

| Case | Behaviour |
|---|---|
| Validation (client) | Save disabled, with the reason beside the field (§4.9) |
| 400 / 422 on an online save | Toast with the server `detail`; the composer stays open, nothing is lost, `client_id` is kept |
| 409 on a replay | Entry was deleted since: the queue drops it silently (Phase 1) |
| 5xx / network on save | Queued (§5.3), toast "Saved on this phone" |
| 401 | The Phase 1 session handles it; the draft is in memory only and is lost if the user signs out |
| Queued create fails (4xx) | Needs attention row on Home (2a §3.2) |
| Scan: unreadable QR / 400 / 502 | Message plus "Use Photo to attach the receipt"; camera stays on |
| Scan: QR response has no amount | Composer opens with an empty amount and the hint "Couldn't find the total" |
| Scan offline | "Scanning needs a connection. Type it instead" |
| Camera permission denied | "Camera not available", Photo and "Type it instead" stay |
| Duplicate check fails or times out | Ignored; save goes on |
| Receipt too big / wrong type | Inline "Max 10 MB" / "Unsupported file type" before upload |
| Receipt upload fails after save | Toast with Retry (§5.4) |
| Edit: entry not found (404) | "This entry no longer exists", then Back; on delete, 404 is success |
| Edit offline with no cached entry | "Connect once to load this entry." |
| Wallet short | Save disabled when the stash is known (§4.5), server 400 otherwise |
| Defaults store unreadable or wiped | Composer opens with empty defaults, Budget dashed; nothing fails |

## 9. Testing

- **Unit (Vitest):**
  - `amount.ts`: digit and decimal limits, leading zeros, backspace, 7-integer-digit cap.
  - `splits.ts`: equal split with leftover cents to the payer, percent rounding, amounts remainder, own-share total check; each against the server rule (sum equals total).
  - `defaults.ts`: initial defaults, re-defaulting respects `touched`, rule matching with Greek final sigma and accents, longest pattern wins.
  - `model.ts`: `toCreateBody` and `toUpdateBody` for expense, income, foreign currency, fuel, split, own-share, cash from wallet and Fixed cost; one test per row of the §4.10 table; `fromTransaction` then `toUpdateBody` round-trips a stored transaction unchanged.
- **Hooks:** `useSaveTransaction`:
  - online success returns the id;
  - a network error queues with the same `client_id`;
  - a retry with the same `client_id` and a `200` duplicate does not add a second row;
  - the optimistic row is replaced;
  - the defaults are written even when queued.
  - `usePendingTransactions` rebuilds rows from queued bodies after a reload.
- **Components** (Testing Library, with the typed fake `fetch` from 2a):
  - **two-tap path:** with defaults stored, press `3` then Save sends one `POST` with the stored bucket, category, payer, method, today's date and a `client_id`;
  - income: green state, no method pill, bucket optional, payer label "Received by";
  - the budget pill is empty on first use and Save is disabled;
  - the foreign currency needs a rate;
  - the Fuel price shows litres;
  - the split sheet blocks Done when shares exceed the total;
  - cash from wallet locks the payer and blocks over-stash;
  - the duplicate card shows, and "Save anyway" sends;
  - scan: a QR success fills the form and shows the badge; the photo path attaches the shrunk image, opens an empty composer and makes no `/scan/parse` call; offline disables both; the Remember toggle sends one `POST` to category-rules, and is hidden when `RULES_API_READY` is false;
  - the receipt: offline disabled, upload after save, Retry after failure;
  - edit: loads values, locks the type, sends the stored `exclude_from_settlement`, Delete confirm;
  - a Fixed-cost transaction keeps `bucket_id: null`;
  - the discard confirm.
  - The camera is mocked behind `qr.ts`, and image shrinking behind `image.ts`.
- **Backend (pytest):**
  - B1: QR route parity with the HTML route (same payload), `401` without auth, a disallowed URL gives 400;
  - B2: finds a same-amount transaction within 3 days, empty on a blank amount, household isolation;
  - the rules endpoints are tested in 2d, not here;
  - one regression test that `POST /transactions` with the same `client_id` twice gives `201` then `200` with the same id (existing behaviour, pinned).
- **Before handover:**
  - `npm run typecheck`, `npm test`, `npm run build` and the full pytest suite once;
  - a manual pass in Chrome at 390×844 in light and dark: the two-tap save, income, foreign currency, fuel, split, own-share, cash, edit and delete;
  - a manual offline pass: go offline in devtools, save, reload, see "Waiting to sync", go online, and check one row appears and the match suggestion shows on Home;
  - a real-device check on iPhone for the camera, `capture` input and the keypad with the keyboard.

## 10. Delivery

- **Execution:** subagent-driven, in speed mode, each stream in its own worktree and branch, merged in order, as in 2a.
- **Dependencies on 2a stream A:** the UI kit (`Sheet`, `Segmented`, `Toast`, `Badge`, `Money`, `ListRow`), `useCachedQuery`, `useAction` and `keys.ts` must be merged first. The additions in §3.1 are made by stream C1 below, in files stream A owns, so they are small, additive commits to be merged right after A. Home (2a stream E) needs the `usePendingTransactions` merge in `RecentActivity`, done by stream C5.

| Stream | Work | Needs | Weight |
|---|---|---|---|
| **C1** | UI kit additions (`Keypad`, `AmountDisplay`, `Pill`, `ToggleRow`) and §3.1 additions | 2a A | 5 |
| **C2** | Core composer: state, `amount.ts`, `model.ts`, pickers, defaults, Save, create and edit, routes, toast and Undo | C1 | 14 |
| **C3** | Backend B1–B2, tests, `gen:api` | none (starts now) | 3 |
| **C4** | More sheet: date, fuel, FX, notes, forecast, split sheet and own-share, cash from wallet | C2 | 10 |
| **C5** | Offline surfaces: `listQueuedBodies`, `usePendingTransactions`, Home Recent integration, duplicate check, receipt upload | C2, C3 (duplicate check) | 7 |
| **C6** | Scan: `qr.ts`, `image.ts`, camera screen, QR review, Photo attach, Remember rule (toggle hidden until 2d's rules endpoints are in the generated types) | C2, C3; 2d stream B for the toggle | 7 |
| **C7** | Tests not covered inside streams, manual and device pass, fixes | all | 5 |

- **Parallel:** C3 runs now, alongside 2a. After C2, streams C4, C5 and C6 run at the same time (different folders: `MoreSheet`/`SplitSheet`, `hooks.ts`/Home, `scan/`).
- The last column is the relative weight of each stream, not an hour count. Each stream carries its own tests inside its weight, except C7.
- **Estimate:** agent build time, with streams in parallel: about 3 hours.
- **Skills:** UI tasks load `frontend-design`, `mobile-native` and `apple-design`. The final review runs on the most capable model.
- **Merge:** to `main` by the user (`git push`), as before. No migration, so there is nothing to order against 2c or 2d. The one soft dependency is the Remember toggle on 2d's rules endpoints (§4.7): C6 can merge first, with the toggle hidden.

## Decisions made in this spec

1. **Routes:** `/new` (and `?mode=scan|cash`, `?from=<id>`) and `/edit/:id` sit outside `AppShell`, so no tab bar shows while composing.
2. **Scan has two modes:** QR goes to `scan/qr` (a URL lookup at AADE), the main path for Greek receipts. The brief said "QR → /scan/parse", but `/scan/parse` only takes OCR text; `/scan/qr` exists only on the HTML side, so B1 adds it to the API. `scan/parse` is not used by the composer and is left unchanged.
3. **No on-phone OCR.** `tesseract.js` and `ocr.ts` are dropped. Photo only attaches the shrunk image as the receipt and opens the composer for manual entry; PDF is attachment-only too. The mock's OCR state is not built.
4. **No live FX rate.** The backend has no rate source, so the rate is typed, prefilled from the last rate used for that currency (the mock's "today's ECB rate" is not built).
5. **Income uses `POST /transactions`** (not `/income`) to get `client_id`, payer and method. Income method is `transfer`, with no pill.
6. **Date is always sent from the device,** so a queued entry keeps the day it was created.
7. **Receipts need a connection;** an offline file is dropped with a message and added later through edit. No encrypted blob storage in the queue.
8. **Undo is online only;** queued saves have no Undo (the queue cannot cancel or know the id).
9. **Home's header figure is not patched offline;** only Recent shows pending rows, and Home says "N entries waiting to sync".
10. **Cash:** method "Cash" by itself defaults to "Not tracked"; the **Cash from wallet** chip sets "My wallet", locks the payer to you and blocks an amount above a known stash.
11. **Type is locked in edit,** and edit hides "Took from", because the API ignores `took_cash` on update.
12. **Edit offline is last-write-wins** (a queued full `PUT`).
13. **Delete** is offered in the edit menu, with a confirm and no Undo.
14. **Duplicate check** runs on Save for new expenses (including scan review), online only, never blocking; "Open that one" drops the draft.
15. **Remember rule** is offered only in QR scan review, on by default when the user changes the category, and hidden until 2d's rules endpoints exist in the generated types; rule matching in the composer mirrors the server's `fold`, longest pattern first.
16. **Splits** always send every member's share summing to the total; the payer takes the remainder or the leftover cents. Hidden when the household has one member.
17. **Limits:** 7 integer digits, 2 decimals, notes 500 characters, no future dates.
18. **Defaults store** holds last, per-category, per-budget, recent categories, last rates and last fuel price, and is written when Save is tapped (even if queued).
19. **Vehicle ("Yaris") in the mock** is not a feature: a car is a budget, and the Fuel category plus the budget's remembered defaults do the job.
20. **Settlement:** the composer never offers `exclude_from_settlement`; edit round-trips the stored value.
21. **Receipt viewing** uses the existing HTML file route until an API route replaces it.
22. **2d owns the category-rules API.** The composer consumes its `GET` list and its `POST` upsert by pattern at `/api/v1/settings/category-rules`, and adds no backend for rules (no B-item for it here).
