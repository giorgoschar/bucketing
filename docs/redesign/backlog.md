# New app backlog

Gaps found in the current app that the new app (web/) must cover.

## Bills

- **Default payment method on a bill.** A bill has no payment method of its own.
  Today you can only choose one when paying (`POST /api/v1/bills/{id}/pay` accepts
  `payment_method`, default `card`). That means every auto-paid or one-tap payment is
  recorded as card.
  - Backend: add `RecurringBill.payment_method` (enum `PaymentMethod`, default `card`)
    with a migration, accept it on bill create/update in `app/api/bills.py`, and use
    it as the default in `app/services/bills.py` `pay_occurrence` when the request
    doesn't send one. Scheduler auto-pay (`_auto_pay_due_bills` →
    `settle_occurrence`) must pass it too.
  - New app: a payment method field in the New/Edit bill form, preselected in the
    Pay sheet.

## Activity

- **Bulk changes ("Move & edit many").** Example: you create a new bucket and want
  older payments moved into it. Today only a web-only bulk "Set payer" exists
  (`app/routes/transactions_search.py` `bulk_set_payer`); there is no bulk move or
  bulk edit in the API.
  - Ways to pick what changes:
    1. **Hand-picked:** multi-select in Activity (the bulk bar in the mocks).
    2. **By filter:** category, merchant, bucket, date range, payer or payment method.
       Shows "N payments match" before anything changes.
    3. **By bill:** every payment made for a bill, plus an option to move the bill
       itself so future payments land in the new bucket (`RecurringBill.bucket_id`).
  - Changes it can make: bucket, category, payer, payment method. One or more at once.
  - Flow: pick → choose changes → **preview** (count, total, before/after per bucket)
    → apply → toast with **Undo** for the whole batch.
  - Backend: `POST /api/v1/transactions/bulk` taking either `ids` or a `filter`, plus
    `changes`, with a `dry_run` flag for the preview. It returns a `batch_id`, and
    `POST /api/v1/transactions/bulk/{batch_id}/undo` restores the previous values (store
    old values per row). Household isolation on every id. Skip soft-deleted rows. Income
    can't be moved into a non-income bucket. Report skipped rows with a reason, the same
    way bulk payer does.
  - Edge cases: cash take-and-spend links and bill-linked transactions keep their links.
    Moving a trip/savings bucket's payments changes its progress, and the preview shows
    this.

## Polish batch after Cash and Pantry (noted 2026-10-08, user: do them all together then)

- **Insights month picker** wobbles and overflows; the top of the selected circle is cut off. Reproduce at 390×844 first.
- **Activity filter total:** when a filter or search is active, a small discreet line above the list, e.g. "23 entries · Out €412.30 · In €0". Server-computed over all matches, not only loaded rows. Hidden when unfiltered.
- **Appearance setting:** Settings › Appearance with System / Light / Dark (per device). Today the app follows the iPhone setting only.
- **P3 final-review minors M1–M8** (`.superpowers/sdd/phase2/p3-final-review.md` in ~/expenses-p2): "All" selection can include pending/mid-delete rows; no router errorElement for a failed lazy chunk; "Paid out vs share" spins forever offline when uncached; Activity detail offline ignores the cached list row; swipe-delete Undo at exactly 5 s can fail; shared-device push 409 can orphan the other user's subscription; swipe/long-press untested on device; mocks use the old light `--warn`.
- Not needed (user decision): the full Shortcut guide on the Apple Pay screen.
- **Cash follow-ups (final review 2026-10-08):** cash saves have no idempotency key, so a lost reply followed by a retry can double a take-and-log (m1). The wallet card sum omits server terms in cross-month cases, and your own "Took" can show a negative number (m2, m3). After logging offline from Home, the cash row stays until sync (m5). Two simultaneous recounts aren't locked. The top-bar avatar contrast in dark mode is 4.10, just under AA.
- **Pantry follow-ups (final review 2026-10-08):**
  - Untick should target the stock item, not the tick id, so a replayed tick that met another phone's tick unticks correctly.
  - `addLine` should be queued `'always'`, since creates are idempotent.
  - Online writes to the same row should be serialised (a fast double tap or an Add-to-pantry while a tick is in flight).
  - The apply-ticked "before" figure should be read under the row lock.
  - `POST /stock` shouldn't wait on PosoKanei: move the snapshot to the background.
  - Add an index on `shopping_lines.stock_item_id`.
  - Find the one flaky vitest test (CI should log its name).
  - The pantry letter tile contrast in light mode is 2.4–3.8 (decorative).
  - The barcode scanner has not been tested on a real iPhone.
- **Apple Pay follow-ups (2026-10-09):**
  - "Remember for this merchant" was removed from the Shortcut token for security (rule poisoning). Instead, after a signed-in user sets the category on an Apple Pay expense, offer "Always use X for <merchant>?" in the app.
  - In-app and online Apple Pay payments don't trigger the iOS "tap" automation. Idea: a manual "Log Apple Pay purchase" shortcut (share sheet or Back Tap) using the same API.
  - Ask PosoKanei / the Ministry for API access (email draft offered to the user); Open Food Facts for barcode → name and size (offered, not yet approved).
- **Polish round follow-ups (final review 2026-10-09, verdict Ship, 0C/0I/10M; full list in `.superpowers/sdd/polish/final-review.md`):**
  - M-1: set a `lock_timeout` in migrations that touch `transactions`.
  - M-2: a manually logged price today makes the daily PosoKanei refresh skip that product (`app/scheduler.py:564`). Count only `source='posokanei'` rows.
  - M-5: the bundle guard should sum the entry chunk plus its modulepreloads, and eager JS should be measured against the previous release.
  - Confirm Coolify's Traefik overwrites `X-Forwarded-For` (per-IP ingest limits trust it).
  - Legacy raw `ingest_attempts` rows are hidden but still stored. A wipe step exists (commit df3bd31, reverted) and needs the user's explicit OK.
  - The ingest limiter uses in-memory storage per worker unless `RATE_LIMIT_STORAGE_URI` is set.
  - The Apple Pay token row's sub line truncates at 390 px when the badge shows.
  - Two no-merchant purchases with the same amount in the same minute merge into one.
- **Open Food Facts follow-ups (re-review 2026-10-09, verdict Ship, 5 minors; full list in `.superpowers/sdd/off/rereview.md`):**
  - N-4: the 30/min barcode limit is checked before the pantry match, so past the limit a scan of something already in the pantry gets a 429 and loses "In pantry · Open". Move the limit to just before the Open Food Facts call.
  - N-1: without `RATE_LIMIT_STORAGE_URI` the limit is per worker, so one user gets up to 60/min at 2 workers. Say so in the docs; recommend Redis.
  - N-3: `WEB_CONCURRENCY` is not documented in compose, `.env.example` or the settings table. A non-numeric value stops the container; a value above 2 makes the Open Food Facts budget assumption wrong unless the client reads the same value.
  - N-2: the deadline closes the socket from another thread. Verify once in the production image (Linux, TLS), or `shutdown()` before the close.
  - N-5: a `Thread.start()` failure escapes as a 500.
  - The old site's `/stock` barcode lookup does not use Open Food Facts (only the new app does).

## Phase A follow-ups (integration 2026-10-10; reviews in `.superpowers/sdd/phase-a/`)

- **Activity / Add panel (D review):**
  - D7: a `/new…` or `/edit/:id` link on desktop unmounts and remounts the screen behind; translate the link before navigating (a `useComposeLink()` for the five call sites).
  - D9: the currency button is a Tab stop the spec does not list, and new copy ("New entry", "Undone", "Type to filter", "Filter budgets / methods / people") needs approval; the desktop panel's offline note says "Saved on this phone…".
  - D12: each panel open and close leaves a dead history entry (push `?add=1`, close with `replace`); close with `navigate(-1)` when this session pushed it.
  - D13: after "stay open" the new entry takes category and method from the pre-save defaults, keeps the entry type, and a Fixed-cost entry leaves no budget picked.
  - Idle preload of the Activity chunk (it is lazy since Phase A) so the first tap on Activity is not a network wait; also assert it is precached in `check-sw.mjs`.
- **Bills / Insights (H review):**
  - H5: the history "Usual" tile falls back to the median of the last 3 including the latest, while the server's baseline excludes it; decide, and if it is the baseline use `points.slice(-4, -1)`.
  - H13: the desktop Months table fetches `/insights` a second time with `months=12`; consider one desktop request feeding both.
  - HN1: the test "F2: an empty period still shows the Bills card (phone) and panel (desktop)" renders only the phone; rename it or add a `stubDesktop(true)` case.
- **Server (S review):**
  - S9: a bare `NaN` in a JSON body is a 500 (building the 422 fails on non-finite floats); predates Phase A, affects every `Decimal` field.
  - S11c: foreign-currency items mix the item's currency with base-converted transaction amounts; they agree today only because `pay_occurrence` sets no rate.
  - SN1: the scheduler's bill-change job reloads each bill with its own query after the first 200-item chunk commit; collect the fields up front.
  - SN3: the bill-change transaction lookup loads every linked entry for all time and could pass the parameter limit at huge sizes; select only the needed columns and batch the ids.
- **Whole-branch review (`.superpowers/sdd/phase-a/final-review.md`):**
  - F4: the first scheduler run after deploy can send several bill alerts at once (the new rule also covers fixed-amount items and a 20% / EUR 10 gate); tell the household to expect them. No code change.
  - F6: a queued Pay or Set amount that carries `usage` is rejected whole (422) if the other member turned the unit off meanwhile; decide whether `/done` and `/amount` should ignore `usage` for an item with no unit (departs from spec section 3.2).
  - F7: Home's bill row and the history note format money as `EUR1200` where the push says `EUR1,200` (and use the default currency); format with `Intl.NumberFormat('en-IE', ...)`, wrap the figures in `ui-num`.
  - F8: until a phone takes the update, its old service worker maps `/app/insights/bills/{id}` to Home, so the first bill push opens Home; self-corrects, no change.
  - F9: a 404 from the history route shows "Couldn't load this." (or stale saved history for ever); show "This bill no longer exists" with a link to Bills, as the composer's `Gone` does.
  - F10: Home's "See why" is a button that navigates; make it a `Link`.
  - F11: missing tests where streams meet: `afterTxnWrite` covers `keys.insightsBills()` and `keys.itemHistory('x')`; the Add panel over `/insights/bills/:id` and over Plan; `router.tsx` registering `insights/bills/:id`.
- **Add panel, a different `copy` id over a dirty panel:** an add → add navigation whose `copy` differs remounts the form without asking. Nothing in the app produces it today. Block when the next `copy` is set and differs (final re-review R1).

## Phase B follow-ups (integration 2026-10-10; reviews in `.superpowers/sdd/phase-b/`)

- **Server (S review):**
  - S5: `in_out_by_month` is a second composition of the monthly series next to `monthly_in_out`; now guarded by the agreement test, merge them when next touched.
  - S6 leftover: a done entry with no amount still counts its estimate under `planned` (and 0 under `actual`), so the row can read "planned about 30, actual 0".
  - S7 leftover: POST review still accepts any long-closed month after the first data month, and a household with no data at all; GET before the first data month returns 200 with zeros while POST returns 404.
  - S10: the thread test for two concurrent reviews does not prove the race path (the simulated lost-race test does); hold the first transaction open or drop it.
  - S12: `monthly_overruns` shares only the two-predicate filter with `bucket_spent`; document that it uses the bucket's current budget and that a budget of 0 is never "over".
  - S13: `biggest` can list a negative expense in a thin month; check whether a negative expense can be stored, and if so filter on a positive base amount.
- **Web (W review):**
  - "Log it" from a past month's cash row saves the expense dated today, so the amount moves from that month's Out to this month's.
  - The statement page is not window-aware offline: a copy saved on the 5th still says "Review by 5 October" with Done disabled on the 7th (Home is fixed).
  - "Couldn't open this entry." does not name the row that was tapped.
  - `ui-num` trailing comma: the amount in a running sentence ("usually €61,") carries the comma inside the number span or beside it; tidy the span boundary.
  - `src/shell/AddPanel.test.tsx` "resize with a typed amount...": flaky, noted only if it recurred during integration (see the integration report).
