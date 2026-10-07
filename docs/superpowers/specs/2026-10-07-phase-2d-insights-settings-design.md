# Phase 2d: Insights, Settings and the bill payment method (design)

- **Date:** 2026-10-07
- **Status:** written for review; every open question is resolved in §11.
- **Builds on:**
  - the Phase 1 shell (`web/`);
  - Phase 2a (`2026-10-07-phase-2a-plan-home-design.md`, here "2a"): the UI kit `web/src/ui`, `useCachedQuery`, `useAction`, Plan and Home;
  - the planning spec (`2026-10-06-planning-redesign-design.md`, §4.2 and §5.5).
- **Visual source:** `docs/redesign/mocks/insights-settings.html`, `tokens.css`, `components.css`.
- **Binding input:** "Default payment method on a bill" in `docs/redesign/backlog.md`.

## 1. Purpose

- **Insights:** one period, one lens, everything on the same numbers.
- **Settings:** a short hub with one screen per job.
- **Bill payment method:** without it every auto-paid and one-tap payment is recorded as "card". It is a backend change other phases depend on.

**Success means** on an iPhone home-screen install:
1. Insights opens offline with the last data loaded for that period and lens.
2. Switching Household / Me / partner changes every figure.
3. A category opens to six months, its shops and its rules.
4. The user can change password, set up or turn off 2FA, link or unlink the passkey, and sign out.
5. Categories and their rules can be edited, Apple Pay tokens managed, alerts chosen.
6. A bill set to "transfer" is recorded as transfer when paid, auto-paid or completed.

## 2. Scope

**In:** Insights (overview, lens, category drill-down, fuel per car, range sheet); the Settings hub and five subscreens; the bill payment method (backend plus the field in 2a's sheets); the endpoints in §7; the service-worker change push needs; the Archive button for event buckets in Plan › Budgets (2a left a label).

**Out:**
- Settle up, in any form.
- Export, switch or add household, leave household, transfer ownership, reset a member's 2FA, quiet hours, budget alert thresholds, an Appearance setting. These stay on the old app.
- Widget customisation, Activity and bulk changes (2c), the Composer (2b), unarchiving a bucket (no endpoint).

## 3. Architecture

```
web/src/
  ui/               2a kit reused unchanged (Money, Sheet, ListRow, Segmented, ProgressBar, Badge, Toast)
    Chips.tsx       NEW  single or multi select chips
    Toggle.tsx      NEW  role="switch" with busy state
    charts/         NEW  HBarList, MonthBars, LineChart, StackBar (SVG and CSS)
  data/             2a cachedQuery, action, keys; keys.ts gains the keys below
  features/insights/  Insights.tsx, period.ts, lens.ts, widgets/*, CategoryScreen, FuelScreen, RangeSheet, hooks.ts
  features/settings/  Settings.tsx, Profile, Household, Categories, Automations, Notifications, palette.ts, hooks.ts
```

- Screens use the kit and their feature's `hooks.ts` only, never `api`. `screens/Insights.tsx` becomes a re-export.
- New routes: `settings`, `settings/{profile,household,categories,automations,notifications}`, `insights/category/:id`, `insights/fuel`.
- **Entry to Settings:** a "Settings" row above "Sign out" in the Phase 1 account sheet (`TopBar.tsx`).

### 3.1 Period and lens

- Both live in the URL query (deep links and Back restore them) and the last values are kept in `localStorage` (try/catch) as the fallback. `usePeriod()` and `useLens()` are the only readers, on Insights and every drill-down.
- **Period `?p=`:** `this_month` (default), `last_month`, `last_3m`, `last_6m`, `this_year`, `custom` with `from` and `to`; exactly the `preset` values `GET /insights` accepts. Pinned chip row; Custom opens `RangeSheet`.
- **Lens `?lens=`:** `household` (default) or a member's `user_id`. A `Segmented` built from `GET /settings/household`: "Household", "Me", then each other member by first name.

### 3.2 Charts

No chart library: none is installed, and the shapes needed (bars, one line, one stacked bar) are small SVG components.
- Colours are the token series `--c1`..`--c6`, which already switch with the theme.
- Every chart has a text equivalent: values printed on or under the bars, or a visually hidden table. No hover tooltips.
- Cash not yet logged is hatched and also labelled "not logged".

## 4. Insights

Reads `GET /api/v1/insights` with `preset`, `start_date`, `end_date`, `paid_by` (the lens user; absent for Household) and optional `bucket_ids`, `category_ids`. Cached per household, period, lens and filters.

**Fixed order**, one card each:

| # | Widget | Source | Notes |
|---|---|---|---|
| 1 | Headline "Spent · Oct 1 – 6" | `total_spent`, `kpis.change_pct`, `kpis.previous_total` | "−8% vs the previous period"; no badge when `change_pct` is null |
| 2 | On track | `GET /plan/month` (2a) | This month and Household only. "On track for €2,310 by Oct 31" is Out projected, not the straight-line `forecast` (it ignores bills and income) |
| 3 | In / Out / Net | `in_out` | Under a member lens, In is income that person received (planning spec §5.5) |
| 4 | Where it went | `categories` | `HBarList`, top 8 plus hatched cash; each row opens §4.1 |
| 5 | In and Out by month | `monthly_in_out` (§7.3) | `MonthBars`, two series, 6 months; In, Out and Net written under it |
| 6 | Spend trend | `monthly_trend` | `MonthBars`; average as text |
| 7 | Biggest expense | `kpis.largest` | One row |
| 8 | How you paid | `by_method`, `cash_share` | `StackBar` plus list; "Leaves out the €45 cash not logged yet" |
| 9 | Budgets | `budget_status` | `ProgressBar` per bucket; link to Plan › Budgets |
| 10 | Savings rate | `kpis.savings_rate` | Hidden when null |
| 11 | Categories vs usual | `GET /insights/categories-vs-usual` | Household only; flagged first, as in 2a Month |
| 12 | Fuel | `fuel` | Hidden when null; one row per car opens §4.2 |

- **Member lens:** an identity row, then a **Paid out vs my share** card under the headline: two bars and one sentence, "You paid €141.20 more than your share this month" ("less", or "about the same" under €1). Source: `GET /insights/person` (§7.1). Widgets 2 and 11 are hidden (household figures). No debt, no action.
- **Empty period:** "No spending in this period", with a link to the previous period when `kpis.previous_total` > 0.
- **Filters button** opens `RangeSheet`: From and To (native date inputs, From ≤ To, both required) and chips for budgets and categories. Apply writes `p`, `from`, `to`, `bucket_ids`, `category_ids` to the URL; Reset clears them. "Paid by" is the lens, so it is not repeated.

### 4.1 Category drill-down (`/insights/category/:id`, §7.2)

- Same period chips and lens. Header: period total and "Average €395/mo". `MonthBars` of six months. Top 5 shops with count and total. Rules as chips "sklaven 48", with "Edit rules" to Settings › Categories. The latest 10 expenses. `id` may be `uncategorised`.
- "See all" opens Activity with `category_id`; hidden until 2c ships Activity.

### 4.2 Fuel per car (`/insights/fuel`)

- Data is `fuel` from `GET /insights`; no new endpoint. Chips: one per car (`fuel.cars`) plus "All cars"; `?car=<bucket_id>`.
- Cards: last fill (date, litres, price per litre, total); `LineChart` of price per litre over the last 6 `refuels`; two small `MonthBars` (litres, spend per month); stat tiles (average price, litres, spend).
- `fuel` null: "No fill-ups with litres in this period." `unpriced_count` > 0: "N fill-ups have no price and are left out".

## 5. Settings

**Hub (`/settings`):** a card (avatar, name, email; opens Profile & security), then rows with live subtitles from the cached queries (so they work offline):

| Row | Subtitle example | Opens |
|---|---|---|
| Profile & security | "2FA on · passkey linked" | `/settings/profile` |
| Household | "Home · 2 members · EUR" | `/settings/household` |
| Categories & rules | "11 categories · 96 rules" | `/settings/categories` |
| Automations | "Apple Pay Shortcut · 1 token" | `/settings/automations` |
| Notifications | "Push on · 9 of 9 alerts" | `/settings/notifications` |

Below: **Sign out** (Phase 1 `signOut`) and the build string.

### 5.1 Profile & security

All writes are online only (§6.2). Sections, top to bottom:
1. **Profile:** display name (1–100 characters), email (optional; 409 shows the server message), avatar colour from the 8 swatches in `palette.ts`. `PUT /settings/profile`.
2. **Password:** current and new (at least 12 characters, checked before sending). `POST /settings/profile/password`. The sheet warns first: "You'll be signed out everywhere and your Apple Pay tokens will stop working." On 204 the app signs out locally and shows "Password changed. Sign in again."
3. **Two-factor** (`GET /settings/security`, §7.5):
   - **Off:** "Set up" opens a sheet: the secret in groups of four with Copy, an "Open in authenticator" link to the `otpauth://` URI, and a 6-digit field. The 8 backup codes appear once, with Copy all and "I've saved these"; backdrop tap does not close that sheet.
   - **On:** "N backup codes left" and "Turn off" (password and code; warns that tokens stop working). The user stays signed in.
4. **Passkey** (only when `passkey_available`): a native `<form method="post">` to `/app/auth/link` (fields `password`, `totp_code`, hidden `_csrf_token` from the `csrf_token` cookie, `return_to=app`) because the server redirects to the identity provider. When linked, "Unlink" is a native form POST to `/app/auth/unlink` with the same hidden fields. The server redirects to `/app/settings/profile?passkey=linked|unlinked|error`; the screen toasts it once ("Couldn't link the passkey. Check your password and code." for `error`, never naming the wrong factor) and removes the parameter. On a passkey-only session (`password_session` false) both are replaced by "Sign in with your password and 2FA to change this."
5. **Sign out.**

### 5.2 Household

- Name: inline edit, owner only (`PUT /settings/household`; currency shown "EUR · Fixed", sent unchanged).
- Members from `GET /settings/household`: avatar, name, "(you)", role badge. The owner gets a menu on other members: "Remove from household", with a confirm sheet (`DELETE .../members/{id}`).
- **Invite** (owner): "New link" calls `POST /settings/household/invite` and shows `<origin>/join/<token>`, Copy, "Expires in 7 days · single use". It is not stored. 429 toasts "Too many links, wait a minute."
- Non-owners see no edit, menu or invite controls.

### 5.3 Categories & rules

- Rows from `GET /settings/categories` (icon, name, colour, "System" badge when `locked`), each with its rules as chips "pattern N" (`match_count`) from `GET /settings/category-rules`. Rules sit next to their category, not on a separate screen.
- **Edit:** tap expands in place: name, 8 swatches, icon, Save, Cancel (`PUT /settings/categories/{id}`). Locked categories say "The composer needs this one to ask for litres." and are not editable.
- **Add:** top-bar plus (`POST /settings/categories`).
- **Delete** (not for default or locked): "N expenses will become uncategorised and its N rules will be deleted."
- **Rules:** tap a chip to edit pattern and category or delete; "＋ Rule" in the expanded row. Help text: "Matches any merchant containing this text, ignoring case and accents. Minimum 2 characters." The saved pattern is shown as stored. Server errors (too short; on edit, a pattern another rule already uses) appear as the field's error. Adding a pattern that already exists re-points that rule to the chosen category instead of failing (POST is an upsert, §7.4).

### 5.4 Automations

- The three Apple Pay setup steps in the order done on the phone.
- Tokens from `GET /settings/tokens`: name, prefix, default bucket, "Last used 2h ago", **Revoke** (confirm; `DELETE`).
- **Create:** name (1–60 characters), optional default bucket (`GET /buckets`). `POST /settings/tokens` returns the token once, in a warning card with Copy token. It lives in component state only: never in the query cache, the encrypted store or the URL; navigating away discards it.
- Footer: "Purchases arrive tagged Apple Pay with no payer. You pick who paid from Home."

### 5.5 Notifications

- **Push on this device:** a `Toggle`. On: iOS permission, subscribe with the key from `GET /push/vapid-public-key`, `POST /push/subscribe`. Off: `DELETE /push/subscribe`. "Send test": `POST /push/test` with this endpoint. Permission denied: disabled, "Allowed in iOS Settings". In a browser tab (not installed): "Add Tameio to your Home Screen to get push alerts."
- These push routes are the existing cookie-and-CSRF ones outside OpenAPI; the hook types them locally.
- **Alert types** (`GET /settings/notifications`, §7.6), each a `Toggle`, grouped: Bills (due in 3 days, overdue, paid automatically, contract ending, amount changed), Budgets (budget limit reached), Pantry (running low, price drops), Apple Pay (each new purchase). Off stops both the in-app notification and the push, for this user in this household.

### 5.6 Payment method in 2a's screens

- **Item sheet** (2a §4.7): "Payment method" for out items, `Segmented` over card / cash / Apple Pay / transfer / other, default card. Hidden for in items (transfer).
- **Entry sheet** (2a §4.6): Method is preselected from the entry's `payment_method`, replacing "card for out, transfer for in". Still changeable per payment.
- **Plan › Budgets:** an event bucket with `archive_suggested` gets an **Archive** button instead of the label. A confirm sheet (it says there is no undo) calls `POST /buckets/{id}/archive`, online only, then invalidates the budgets keys.

## 6. Offline, errors, push

### 6.1 Reads

All reads use `useCachedQuery`, so Insights and Settings open offline with the last data and the 2a banner "Offline · updated HH:MM". A period or lens never loaded shows "No saved data for this view. Connect once to load it."

### 6.2 Writes: none queued

Insights is read-only. Every Settings write is **online only**: it needs a fresh credential check, a server secret or uniqueness check, or the push service, or it is irreversible. That covers password, 2FA, passkey, profile, household, members, invites, tokens, categories, rules, notification toggles, push, and Archive.

`useAction` is not used. A `useOnlineAction` wrapper in `features/settings/hooks.ts` blocks the call when `navigator.onLine` is false or the request fails at the network level, toasts "You're offline. This change needs a connection." and changes nothing. The buttons stay enabled so the reason is shown.

### 6.3 Errors

| Case | Behaviour |
|---|---|
| Offline with cache | Data plus the banner |
| Offline without cache | "No saved data yet. Connect once to load Insights." (or Settings) |
| 400, 403, 404, 409 on a write | Toast the server `detail`; the sheet stays open with the input |
| 429 | "Too many attempts. Try again in a minute." |
| 401 | Phase 1 session handling |
| 5xx or network on a write | The offline toast |
| `/insights/person` fails, `/insights` succeeds | The rest renders; the share card shows "Couldn't load this" and Retry |

### 6.4 Service worker

The Phase 1 worker is generated (`generateSW`) and has no push handler for the `/app/` scope. `vite-plugin-pwa` switches to `injectManifest` with `web/src/sw.ts`: the same precache globs, navigate fallback and denylist, plus `push` and `notificationclick`. The click handler maps the server's `link` with `appRoute(link)`: `/bills` and `/buckets*` to `/app/plan`, `/transactions*` and `/search*` to `/app/activity`, `/settings*` to `/app/settings`, anything else to `/app/`. `static/sw.js` is untouched.

## 7. Backend

All under `/api/v1`, `require_api_auth`, scoped to the caller's household. A `user_id` outside the household is 404. **Checked first:** `GET /insights` already honours `paid_by` for spend, shares, cash and income; tokens, categories and household have endpoints; fuel per car is in `fuel.cars`; push routes exist. Only the items below are missing.

### 7.0 Payment method on a bill (Stream M; ships first and alone)

It depends on nothing else in 2d. **2c's migration depends on it.** The migration chain is `b8c9d0e1f2a3` (this, payment method) → 2c `c9d0e1f2a3b4` → 2d mutes `d0e1f2a3b4c5` (§7.6).

**Migration** `alembic/versions/b8c9d0e1f2a3_bill_payment_method.py`, `revision = "b8c9d0e1f2a3"`, `down_revision = "a7b8c9d0e1f2"`:
- Add `recurring_bills.payment_method`, `String(16)`, NOT NULL, server default `card` (batch mode as in `a7b8c9d0e1f2`; plain varchar like `transactions.payment_method`, so no `ALTER TYPE`).
- Backfill in the same migration:
  - `direction = 'in'` gets `transfer` (what `receive_occurrence` always recorded);
  - other items get the method of their most recent active linked transaction (`recurring_bill_id`, by `transaction_date` then `created_at`);
  - items with none keep `card`.
- Downgrade drops the column. Nothing else changes.

**Code:**

| Where | Change |
|---|---|
| `models.py` `RecurringBill` | the column, default `card` |
| `services/bills.py` `pay_occurrence` | `payment_method: str \| None = None`; uses `payment_method or bill.payment_method` |
| `settle_occurrence` | forwards it unchanged |
| `receive_occurrence` | records `bill.payment_method` instead of the fixed `transfer` |
| `complete_entry` | `payment_method` defaults to None and is forwarded; an explicit value wins |
| `scheduler.py` auto-pay | pending rows carry `payment_method`, passed to `settle_occurrence` |
| `api/recurring.py` | `RecurringItemIn.payment_method: str \| None` (validated by `parse_payment_method`; absent means `transfer` for in items, `card` for out); `EntryDoneIn.payment_method` default `"card"` becomes None |
| `api/bills.py` | `BillIn.payment_method` likewise; `PayOccurrenceIn.payment_method` default None; `_bill_dict` returns it |
| `api/planning_models.py` | `RecurringItemOut.payment_method` and `EntryOut.payment_method` (the item's) |
| `routes/bills.py` (old UI) | the pay form's field becomes optional (blank means the bill's); the bill form is unchanged |

An invalid value is 400 (existing message). Create or edit never rewrites recorded transactions. Then `npm run gen:api`.

### 7.1 `GET /insights/person`

Query: `user_id` (required), `preset`, `start_date`, `end_date`. Wraps `get_person_summary`:
`{ user_id, paid_out, my_share, balance, share_pct, household_total, largest: {amount, notes, date} | null, shared_count, transaction_count }`, with `balance = paid_out - my_share`. The service's settle-up `net` and `by_bucket` are not returned.

### 7.2 `GET /insights/categories/{category_id}`

Query: `preset`, `start_date`, `end_date`, `paid_by` (optional). `category_id` may be `uncategorised`; an unknown id is 404.
```
{ category: {id, name, icon, color} | null, total, count, avg_per_month,
  months:    [{year, month, label, total}],   // 6 calendar months ending at the period end, oldest first
  merchants: [{merchant, count, total}],      // top 5 by total; no merchant is grouped as "Other"
  recent:    [{id, date, merchant, notes, amount, paid_by}],   // latest 10 in the period
  rules:     [{id, pattern, match_count}] }
```
Amounts honour lens shares exactly as `/insights` does.

### 7.3 `monthly_in_out` on `GET /insights`

A new array: `[{year, month, label, in, out, net}]`, the six calendar months ending with the current one, oldest first. Lens-aware, ignores the period, built from the same income and spend functions as `in_out` (so the current month equals `in_out` for `this_month`). Service function `monthly_in_out(db, household_id, n_months, paid_by)`.

### 7.4 Category rules (`/settings/category-rules`)

2d **owns** the rules API. 2b's composer consumes two calls from it: the list (to match merchants) and the create/upsert by pattern (the "Remember merchant → category" toggle). Their shapes below are binding for 2b.

| Call | Body | Result |
|---|---|---|
| `GET` | | `[{id, pattern, category_id, match_count, created_at}]`, most used first (`list_rules`). 2b reads `{id, pattern, category_id}` |
| `POST` | `{pattern, category_id}` | An **upsert by pattern** (`learn_rule`, matched on the folded pattern): 201 and the rule when new, 200 and the rule when the folded pattern already exists (its category is re-pointed, `match_count` kept). 400 for a pattern under 2 characters (after `normalise_pattern`) or a category of another household: "Enter at least 2 characters and pick a category from this household." Idempotent, so it can be queued |
| `PUT /{id}` | same | rule, `match_count` kept; 400; 404 other household; 409 collision with another rule's folded pattern |
| `DELETE /{id}` | | 204; 404 |

Patterns go through `normalise_pattern` (2 to 200 characters). The old form routes keep working.

### 7.5 Security (`/settings/security`)

| Call | Body | Result |
|---|---|---|
| `GET` | | `{totp_enabled, backup_codes_remaining, passkey_available, passkey_linked, password_session}` |
| `POST /totp/setup` | | `{secret, otpauth_uri}`; reuses the pending secret; 409 if 2FA is on; 10/min |
| `POST /totp/enable` | `{code}` | `{backup_codes: [8]}`; 400 "Invalid code. Please try again."; 409 if on; 10/min |
| `POST /totp/disable` | `{current_password, code}` | 204; same effects as the old route (secret and codes cleared, sessions and tokens revoked), then the caller's cookie is reissued so they stay signed in; 400; 429 when locked; 5/min |

The pending-secret and backup-code logic moves from `routes/settings.py` into a shared helper; the HTML routes behave as before.

**Passkey redirects:** `POST /app/auth/link` and `/app/auth/unlink` accept an optional form field `return_to`; only the literal `app` is honoured. With it, their redirects, and the callback that completes a link (remembered in the session), go to `/app/settings/profile?passkey=linked|unlinked|error`. Without it nothing changes.

### 7.6 Notification preferences

- **Table** `notification_mutes(user_id, household_id, type)`, primary key on all three, FKs `ON DELETE CASCADE`. A row means muted; the default is everything on.
- `GET /settings/notifications`: `{types: [{type, group, label, enabled}], push_devices}`: every `NotificationType` except `general`.
- `PUT /settings/notifications`: `{disabled: [type, ...]}` replaces the caller's set for this household; unknown or `general` is 400.
- `create_notification` returns `None` (no row, no push) when the recipient muted the type. Scheduler callers already handle `None`.
- **Migration** `alembic/versions/d0e1f2a3b4c5_notification_mutes.py`, `revision = "d0e1f2a3b4c5"`, `down_revision = "c9d0e1f2a3b4"` (2c's bulk migration), creates the table; the downgrade drops it. The chain is fixed: `b8c9d0e1f2a3` → `c9d0e1f2a3b4` → `d0e1f2a3b4c5`, and `test_single_head` guards it. It therefore cannot merge before 2c's B1 (§10).

## 8. Look and accessibility

- **Vault tokens** as 2a §7: dark-first with light mode; Sora figures, Plus Jakarta Sans text, JetBrains Mono tables; tabular numerals.
- Safe areas; 44 pt tap targets, including chips, toggles and swatches.
- **Colour is never the only signal:** "over", "above usual", "not logged" and the delta sign are also words. Chart colours pass 3:1 on the card in both themes. Nothing animates on load; sheets do not slide under `prefers-reduced-motion`.
- Toggles are `role="switch"` with `aria-checked`; chips use `aria-pressed`; the lens is a labelled radio group.
- Sheets showing a secret (backup codes, new token) ignore backdrop taps. Secrets are `user-select: all`, never stored, cleared on unmount. Password fields carry `autocomplete="current-password"` or `"new-password"`; the code field `one-time-code` with `inputmode="numeric"`.
- 360–430 px target; a centred 480 px column on wider screens.

## 9. Testing

- **Backend (pytest on SQLite; Postgres CI runs the same suite):**
  - `b8c9d0e1f2a3` upgrades a seeded database with the right backfill (in → transfer, out → latest method, none → card), round-trips down and up, and passes `test_single_head` and `test_schema_matches_models`.
  - Payment method: `pay_occurrence` uses the bill's when none is sent and an explicit one wins; auto-pay, `complete_entry` and `receive_occurrence` use it; `/recurring` and `/bills` create, update and return it; invalid is 400; `EntryOut` carries it.
  - `/insights/person` (figures equal `get_person_summary`, no `net`, non-member 404), `/insights/categories/{id}` (merchants, months, `uncategorised`, lens shares, foreign category 404), `monthly_in_out` (current month equals `in_out`).
  - Rules CRUD: length (a 1-character pattern is 400), `POST` upsert (201 new, then 200 with the same id and the category re-pointed, `match_count` kept), foreign category 400, `PUT` collision 409, re-point keeps `match_count`, other household 404, deleting a category removes its rules.
  - Security: setup reuses the secret; enable needs a valid code; disable needs password and code and keeps the caller signed in; rate limits; `return_to=app` redirects and an unknown value is ignored.
  - Mutes: a muted type creates no row and no push; `general` cannot be muted; per household. `d0e1f2a3b4c5` has `down_revision` `c9d0e1f2a3b4`, round-trips down and up, and the chain has a single head.
- **Frontend (Vitest, Testing Library, typed fake `fetch`):**
  - `usePeriod` and `useLens`: URL round trip, storage fallback, From after To rejected.
  - Insights: widget order, widgets hidden under a member lens or on null data, the three paid-out sentences; each chart has its text equivalent and survives an all-zero series; category and fuel screens (two cars, none).
  - Settings: each write is blocked offline with the toast and sends nothing; the new token never reaches the cache; the passkey form posts the CSRF field and `return_to`; the backup-code sheet ignores a backdrop tap; password change ends signed out.
  - `appRoute` for every link the scheduler creates; the Item sheet sends `payment_method` for out items only; the Entry sheet preselects the entry's method.
- **Before handover:** `npm run typecheck`, `npm test`, `npm run build`, the full pytest suite, `ruff format --check`, a manual pass in Chrome at 390×844 in light and dark on seeded data (overflow, contrast, offline reload), and push checked once on an installed iPhone.

## 10. Delivery

- **Execution:** subagent-driven, in speed mode, one git worktree and branch per stream, merged in order.

| Stream | Content | Needs | Weight |
|---|---|---|---|
| M | §7.0 migration `b8c9d0e1f2a3`, services, scheduler, API, tests | nothing; **starts now and can ship alone** | 3 |
| B | §7.1–7.5 (person, category detail, `monthly_in_out`, rules CRUD with the upsert POST, security, passkey `return_to`) and tests; no migration | nothing | 7 |
| N | §7.6 mutes: table, migration `d0e1f2a3b4c5`, `create_notification` change, endpoints, tests | **2c's B1 merged** (`c9d0e1f2a3b4` must exist); B only for the shared test helpers | 2 |
| F1 | `Chips`, `Toggle`, `charts/*`, `period.ts`, `lens.ts` | 2a stream A | 5 |
| F2 | Insights, widgets, `RangeSheet`, category and fuel screens | F1, B | 9 |
| F3 | Settings hub, Profile & security, Household | 2a stream A, B | 8 |
| F4 | Categories & rules, Automations, Notifications, `sw.ts`, push | F1, B; N for the Notifications screen | 8 |
| F5 | §5.6: payment method in the Item and Entry sheets, Archive | M merged, 2a streams C and D | 2 |

- The last column is the relative weight of each stream, not an hour count.
- **Estimate:** agent build time, with streams in parallel: about 3–4 hours. M and B run beside 2a; F1 and F3 start when 2a stream A merges; F5 is the only stream that edits 2a files and waits for them.
- **Migration order:** `b8c9d0e1f2a3` (M, payment method) → 2c `c9d0e1f2a3b4` → 2d mutes `d0e1f2a3b4c5` (N). If 2d must ship before 2c, M, B and the F streams ship without the mutes: N ships later, in its own stream, after 2c's B1 merges, and until then the Notifications screen shows the push toggle only (no alert-type toggles).
- **Merge order:** M (before 2c's migration), B, F1, F2/F3/F4 in any order, F5; N after 2c's B1.
- **2b dependency:** 2b's composer uses `GET` and `POST /settings/category-rules` from stream B. B ships early so 2b can regenerate its types; until then 2b hides its "Remember merchant" toggle.
- **Skills:** UI tasks load `frontend-design`, `mobile-native`, `apple-design`; chart tasks also `dataviz`. The final review runs on the most capable model.
- **Merge** to `main` by the user (`git push`). Production runs 2d's two additive migrations (and 2c's between them); the old app keeps working. Push needs the `VAPID_*` settings the old app already uses.
- **Main risk:** web push in the installed `/app/` scope. A subscription made in the old app is separate; this screen makes its own and leaves the old one alone.

## 11. Decisions made in this spec

1. **No chart library:** none is installed; four small SVG components cover the shapes, each with a text equivalent.
2. **Period and lens in the URL**, with a `localStorage` fallback, so drill-downs inherit them.
3. **Lens = `paid_by`.** Income under a lens is what that person received.
4. **Settle up stays removed; "paid out vs my share" stays** for member lenses. The endpoint drops the settle-up `net`.
5. **On track uses `/plan/month` Out projected**, not the straight-line `forecast`; shown for this month and Household only.
6. **Categories vs usual and On track are hidden under a member lens** (household-only sources).
7. **Filters:** custom range plus budget and category chips; no live "Show N expenses" count (no endpoint).
8. **Minimal new endpoints:** person, category detail, `monthly_in_out`, rules CRUD, security, mutes. Fuel per car needs none. **2d owns the rules API:** 2b consumes its `GET` list and its `POST` upsert by pattern at the same path, `/settings/category-rules`, and adds no rules endpoints of its own.
9. **2FA setup uses an `otpauth://` link and a copyable secret**, not a QR, since the phone being set up holds the authenticator.
10. **Passkey link and unlink stay native form posts** with an opt-in `return_to=app`; old redirects unchanged.
11. **Notification prefs are per-type mutes** per user and household; quiet hours and thresholds are out (no storage).
12. **Muting is applied inside `create_notification`**, covering in-app and push; `general` cannot be muted.
13. **The migration chain is fixed:** `b8c9d0e1f2a3` (payment method) → 2c `c9d0e1f2a3b4` → mutes `d0e1f2a3b4c5` (`down_revision` `c9d0e1f2a3b4`). If 2d ships first, the mutes migration ships in a later stream after 2c's B1 merges.
14. **Backfill by history**, with `card` as the column default. Only an in item created without a value defaults to `transfer`, matching what it always recorded.
15. **"Not sent" means "use the bill's":** request defaults for pay, done and the old pay form change from `card` to none; an explicit method wins.
16. **Items and entries return `payment_method`**, so the Entry sheet preselects without an extra fetch.
17. **Settings writes are online only, never queued;** buttons stay enabled and explain with a toast.
18. **Tokens, TOTP secrets and backup codes never touch the cache or storage.**
19. **A password change signs the user out locally**, since the server invalidates every session.
20. **Push needs `injectManifest`** (the generated worker has no push handler); server links are mapped by `appRoute`.
21. **Export, household switching, ownership transfer, leaving, member 2FA reset and Appearance stay on the old app.**
22. **Archive is wired here**; there is no unarchive.
23. **Invite links are not listed or revoked** (no endpoint); each is shown once.
