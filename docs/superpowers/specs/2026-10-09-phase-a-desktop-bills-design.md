# Phase A: desktop layout, bill history, bill-change alerts — design

Approved by the user on 2026-10-09 (chat), with these decisions:

- Wide layouts in Phase A: Insights, Activity and Add. Home, Plan and Settings get the sidebar and a centred column.
- Bills record the amount plus an optional usage number (kWh, m³ …).
- Bill history lives in Insights, and the bill in Plan links to it.
- An unusual bill shows as a Home row and a push.

Roadmap: `docs/redesign/roadmap.md`, Phase A.

## 1. Goal

The user works on the desktop a lot, to add expenses and above all to read statistics. Today the app is a 480 px column on every screen.

Phase A delivers three things:

1. A real desktop layout.
2. A history for each recurring item (electricity, water, internet …): graph, year against year, table.
3. A better "this bill changed" alert.

Out of scope:

- Wide layouts for Home, Plan, Cash, Pantry and Settings.
- Month-end review and statements (Phase B).
- Importing past usage in bulk. One entry at a time is in scope (§3.3).
- Changes to the old Jinja app, apart from keeping it working.

## 2. Terms

- **Item:** a `RecurringBill` row. The new app calls it a recurring item and reaches it through `/api/v1/recurring`.
- **Entry:** a `BillOccurrence` row.
- **Done entry:** an entry with status `paid`.
- **Entry amount** (used everywhere in this spec), in the household currency: `occ.amount`; when that is null, the linked transaction's amount converted to base; when there is no transaction, the item's `amount`. It is the whole payment, never one member's share (test with `payer_mode = own_share`).
- **Desktop:** viewport width ≥ 1024 px. Everything narrower is **phone** and must not change.

## 3. Server (stream S)

### 3.1 Migration

One revision, `a3b4c5d6e7f8`, `down_revision = "f2a3b4c5d6e7"`:

- `recurring_bills.usage_unit`: `String(12)`, nullable. Null means the item does not track usage.
- `bill_occurrences.usage`: `Numeric(12, 3)`, nullable.

The downgrade drops both columns. No data is rewritten. No enum changes: the alert reuses the existing `bill_drift` notification type.

### 3.2 Items and entries carry usage

- `RecurringItemIn` / `RecurringItemOut`: `usage_unit: str | None`. Trimmed; empty becomes null; longer than 12 characters is 422. Control characters are 422.
- `EntryOut`: `usage: number | None`, `usage_unit: str | None` (the item's).
- `EntryDoneIn` and `EntryAmountIn`: optional `usage`. It must be ≥ 0 and at most 9 digits before the point. Sending `usage` for an item with no `usage_unit` is 422. Omitting it leaves the stored value alone.
- Undo keeps `usage`, as it keeps `amount`. Skip keeps it too.
- The offline queue already carries the Pay and Set amount bodies; `usage` rides in the same body. No new queue kind.

### 3.3 Set usage on any entry

`PUT /api/v1/recurring/entries/{entry_id}/usage`, body `{"usage": number | null}` → `EntryOut`.

- Works on an expected, done or skipped entry of an item that has a `usage_unit`; otherwise 422.
- `null` clears it.
- Household isolation as in the other entry routes (404 for another household's entry).

### 3.4 The comparison rule (`app/services/bill_change.py`)

One pure function, used by the history endpoint, the Bills list and the scheduler. Input: an item's done entries, oldest first, each with due date, period, entry amount and usage. Output for the **latest** done entry: `None`, or

```
{"entry_id", "amount", "usual", "basis": "last_year" | "recent",
 "delta", "pct", "direction": "up" | "down",
 "reason": "usage" | "price" | None, "reason_pct": number | None}
```

Rules:

1. **Baseline.**
   - `last_year`: a done entry of the same item whose due date falls in the same calendar month one year earlier. Only for items whose rule gives at most one entry a month (not weekly rules). Its entry amount is the usual.
   - Otherwise `recent`: the median of the entry amounts of the 3 done entries before the latest. Fewer than 3: no result.
2. **Gates, both required:** `|pct| ≥ 20` and `|delta| ≥ 10` (household currency). `usual ≤ 0`: no result.
3. **Reason**, only when the latest entry has `usage > 0` and every baseline entry has `usage > 0`:
   - baseline usage = that entry's usage (`last_year`) or the median usage (`recent`);
   - unit price = amount ÷ usage on each side;
   - `reason = "usage"` when the usage change in percent is at least as large in size as the unit-price change, else `"price"`; `reason_pct` is that change, signed.
4. Items with `direction = in` are never assessed. Paused items are.
5. Arithmetic in `Decimal`. Percentages rounded half-up to whole numbers at the edge, not inside the gates.

The old constants (`25 %`, `€5`, mean of 3) go away.

### 3.5 History endpoint

`GET /api/v1/recurring/{item_id}/history` → `ItemHistoryOut`:

```json
{"item": {"id": "…", "name": "Electricity", "direction": "out", "currency": "EUR",
          "usage_unit": "kWh", "category_id": "…", "is_active": true},
 "points": [{"entry_id": "…", "due_date": "2026-09-14", "amount": 84.00,
             "usage": 412.0, "unit_price": 0.2039, "transaction_id": "…"}],
 "change": null}
```

- `points`: done entries, oldest first, the most recent 240. `amount` is the entry amount. `unit_price` is `amount ÷ usage` to 4 places, null without usage or with usage 0.
- `change`: §3.4 for the latest done entry.
- 404 for another household's item. Money is JSON numbers, as in the other planning routes.

### 3.6 Bills list for Insights

`GET /api/v1/insights/bills` → a list, one row per item with `direction = out` that is active or has at least one done entry:

```json
{"item_id": "…", "name": "Electricity", "category_id": "…", "usage_unit": "kWh",
 "is_active": true, "last": {"entry_id": "…", "due_date": "2026-09-14", "amount": 84.00},
 "recent": [61.0, 58.5, 70.2, 84.0], "total_12m": 790.40, "average_12m": 65.87,
 "change": null}
```

- `recent`: the entry amounts of the last 12 done entries, oldest first.
- `total_12m` / `average_12m`: done entries with a due date in the 12 calendar months ending this month; the average divides by the number of those entries. Null without any.
- `change`: §3.4, but only when the latest done entry's due date is within the last 35 days. This is what Home shows.
- Order: rows with a `change` first, then by `total_12m` descending, then name.
- Must not run one query per item per entry: at most a fixed number of queries for the household.

### 3.7 The alert

`_notify_bill_drift` in `app/scheduler.py` keeps its place in the daily job and its notification type, and switches to §3.4:

- Items: `direction = out`, active.
- Only a latest done entry with a due date in the last 35 days (unchanged).
- Dedupe key unchanged: `bill_drift:{occ.id}`. An entry that already produced a notification under the old rule is not notified again.
- Title: `Electricity was €84, usually €61`.
- Body, by case:
  - `last_year`: `Same month last year: €61.`
  - `recent`: `Usual from the last 3 payments: €61.`
  - plus, when there is a reason: ` You used 30% more kWh.` or ` The price per kWh went up 12%.` (`less` / `went down` for negatives).
- Link: `/app/insights/bills/{item_id}`.
- The mute stays "Bills · Amount changed" in `notification_prefs`. No new preference.

### 3.8 Activity sorting

`GET /api/v1/transactions` gains `sort`: `date_desc` (default, today's order), `date_asc`, `amount_desc`, `amount_asc`. Anything else is 400. Amount sorts use the base-currency amount, with the current order as tie-break. Every existing filter and the pagination work with every sort. `day_totals` is returned only for the date sorts; for amount sorts it is an empty list.

### 3.9 Longer month series

`GET /api/v1/insights` gains `months`: `6` (default) | `12` | `24`, which sets the length of `monthly_in_out`. Anything else is 400.

### 3.10 Types

Every new or changed route has a `response_model`. Run `npm run gen:api` after stream S lands, so `web/src/api/schema.d.ts` is real for stream H.

## 4. Desktop layout (stream D)

### 4.1 Rules that protect the phone

- One breakpoint: `@media (min-width: 1024px)`. Every desktop rule sits inside it. The shell's `max-width: 480px` is lifted only inside it.
- One hook, `useIsDesktop()` (`matchMedia`, updates on resize), for behaviour that CSS cannot express.
- The existing phone tests, and the `planCss` / `insightsCss` tests, pass unchanged.

### 4.2 Sidebar

On desktop the tab bar is replaced by a fixed left sidebar, 232 px:

- Tameio name.
- **Add** button (primary). Shortcut: `N`, when no field has focus and no sheet is open.
- Home, Activity, Plan, Insights: the same destinations and active-state rules as the tabs.
- At the bottom: Settings, and the avatar that the top bar shows on the phone.

It is a `<nav aria-label="Main">`; the current destination has `aria-current="page"`. The phone top bar's avatar is hidden on desktop, since the sidebar has it. Sheets on desktop are centred dialogs, at most 560 px wide, with the same focus trap.

### 4.3 Content width

- Home, Plan (all views), Settings and the detail screens: a centred column, at most 720 px.
- Activity and Insights: up to 1280 px (§4.4, §5.4).

### 4.4 Activity: table and detail pane

- Columns: Date, What (merchant or description, with the same badges as the feed rows), Category, Bucket, Paid by, Method, Amount (right-aligned, `ui-num`).
- Date and Amount headers sort (§3.8). The header is a button with `aria-sort`. Sort is kept in the query string (`?sort=amount_desc`).
- The existing search, filter chips, totals line, "load more" and bulk select all work. Bulk select uses a checkbox column.
- Clicking a row opens `/activity/:id` **beside** the table: the table stays, the detail fills a 420 px pane on the right, and the row is marked selected. Up/Down move between rows, Enter opens, Esc closes the pane.
- On the phone, `/activity/:id` stays a full screen, as today.
- Swipe actions do not exist on desktop; the same actions are buttons in the pane.

### 4.5 Add: a side panel

- On desktop, Add opens the composer as a right-hand panel, 440 px, over the screen the user is on. The screen behind stays visible and refreshes after a save.
- It is driven by the query string, so it survives a reload: `?add=1`, or `?edit=<id>`. Any link to `/new…` or `/edit/:id` on desktop opens the panel over the current screen with the same parameters (`mode`, `take`, `amount` …). On the phone those routes are unchanged.
- The same composer logic is used, not a copy: same defaults, same validation, same offline queue, same pantry prompt.
- Keyboard first:
  - focus starts in the amount, a text field using the composer's own amount parser (comma or point);
  - the on-screen keypad is not shown;
  - Tab order: amount, Expense/Income, description, bucket, category, payer, method, date, More;
  - pickers open as lists that filter as you type; Enter picks;
  - `Enter` or `⌘/Ctrl + Enter` in any field saves; `Esc` closes, and asks first when something was typed.
- **Stays open:** after a save in add mode, the panel clears to a new entry, keeping the date, bucket and payer, and shows "Saved · €12.40 Lidl" with an Undo that works as today's toast Undo does. Edit mode closes after a save.
- Scan mode on desktop is whatever works today (file pick); not changed here.

## 5. Bill history and desktop Insights (stream H)

### 5.1 Tracking usage

- Item form (Plan › Items): a field "Track usage" with the choices Off, kWh, m³, L, GB and Other (free text, 12 characters). Off sends `usage_unit: null`.
- Pay and Set amount sheets (`EntrySheet`): for an item with a unit, one optional field under the amount: "Usage (kWh)". Decimal comma accepted. Empty sends nothing.

### 5.2 Bills list: `/insights/bills`

- Reached from a new **Bills** card on Insights. The card shows the three items with the highest `total_12m`, each with its last amount, and "All bills".
- One row per item: name, last amount and date, a sparkline of `recent`, the 12-month total and, when `change` is set, a label "↑ 38% vs usual" or "↓ 22% vs usual" (text and arrow, not colour alone).
- Paused items are listed last, under "Paused".
- Empty state: "No recurring bills yet", with a link to Plan › Items.
- The Bills pages ignore the Insights lens and period: a bill's history is the household's, for all time. They say so in one line.

### 5.3 Bill history: `/insights/bills/:id`

Works on the phone and on desktop. Top to bottom on the phone; on desktop the charts sit in two columns over a full-width table.

1. **Header:** the item's name; tiles for Last, Usual (`change.usual`, else the median of the last 3), 12-month total and Average.
2. **Change note,** when `change` is set: the same sentence as the notification (§3.7).
3. **Amount by month:** bars for one year, with a year picker (‹ 2026 ›). A lighter bar beside each for the same month a year earlier, when it exists. A month with two entries shows their sum.
4. **Price per unit,** only when at least two points have a unit price: a line over the same year.
5. **Usage,** only when at least two points have usage: bars over the same year.
6. **Table,** newest first: Date, Amount, Usage, Per unit, Against last year (the difference in € and %, or "—"). A row with a transaction links to `/activity/:id`.
   - Each row has **Edit usage** (items with a unit): a small sheet that calls §3.3. Online only, disabled offline with "Connect to change usage".
7. Fewer than 2 done entries: the charts are replaced by "Not enough history yet. It fills in as you pay this bill."

Charts follow the fuel screen's approach (hand-drawn SVG, theme tokens, tabular numbers). Every chart has a text alternative: the table is that alternative, and each `<svg>` gets a `<title>` naming what it shows.

**Entry points:** the Bills list; the item sheet in Plan › Items ("History"); the entry sheet in Plan ("History"); the notification link.

### 5.4 Desktop Insights dashboard

On desktop, `/insights` becomes a grid, up to 1280 px:

- The lens and period controls stay at the top, in one row.
- The existing cards are laid out in 12 columns, charts side by side. The same components and data are used; the fixed order stays as the reading order.
- **Desktop only:**
  - **Bills panel:** the Bills list (§5.2) inline, up to 8 rows, with "All bills".
  - **Months table:** the last 12 months (`?months=12`): Month, In, Out, Net, with the net's sign shown as text too.
  - **Categories table:** every category in the period: amount, share of spending, and against its usual, in place of the top few the card shows.

The phone's Insights is unchanged, except for the new Bills card.

### 5.5 Home › Needs attention

- New kind `billChange`: one row per item in `/insights/bills` with a `change`.
- Text: "Electricity was €84, usually €61". Action: **See why**, which opens the bill's history.
- Dismiss: an ✕ on the row. Dismissed entry ids are kept in `localStorage`, on this device only. A dismissed row returns only for a newer entry.
- Order: after `missingAmount`, before `cash`.
- When the Bills query has nothing cached, the row is not shown and no error appears.

### 5.6 Notification link

`web/src/pwa/appRoute.ts`: a link under `/app/insights/bills` opens that route in the app. Old `bill_drift` notifications with `/bills` keep opening Plan.

### 5.7 Data, offline, invalidation

- New keys, added to `web/src/data/keys.ts` without changing existing ones: `insightsBills()`, `itemHistory(id)`.
- Reads use `useCachedQuery`; offline they render from cache with "Offline · showing saved history".
- After Pay, Undo, Skip, Set amount, Edit usage, an item edit or delete, and after accepting a match: invalidate both keys, plus what those writes already invalidate.

## 6. Accessibility and layout

- 390 × 844 and 1440 × 900, light and dark, with no horizontal page scroll. The Activity table scrolls inside its own container below 1180 px.
- Every desktop control is reachable by keyboard, with a visible focus ring.
- 44 px targets on the phone. On desktop, table rows are at least 36 px.
- Amounts use `ui-num`, wrapped where they sit in running text.
- `prefers-reduced-motion`: the panel and pane appear without sliding.

## 7. Tests (must exist)

**Server**

- Migration up and down on Postgres. One alembic head.
- `usage_unit` validation. `usage` accepted on Pay, Set amount and §3.3; 422 for an item with no unit; undo keeps it; another household gets 404.
- `bill_change`, as a table of cases:
  - same month last year exists, or not;
  - fewer than 3 prior entries;
  - each gate failing alone;
  - up and down;
  - a weekly item never uses `last_year`;
  - reason `usage`, reason `price`, and no reason when a baseline entry lacks usage;
  - usage 0;
  - an `in` item.
- Entry amount falls back to the transaction, then the item, and is the whole payment under `own_share`.
- History: order, the 240 cap, `unit_price`, isolation.
- Bills list: the 35-day window for `change`, the order, a bounded query count.
- Scheduler: title and body for each case; dedupe; nothing for a muted member; an entry notified under the old key is not notified again.
- `sort` and `months`: each value, a bad value is 400, pagination under an amount sort has no duplicates or gaps.
- Postgres run of the new tests, serially.

**Web**

- Phone: the existing suites pass unchanged; the tab bar is present and the sidebar absent below 1024 px.
- Desktop shell: sidebar destinations and `aria-current`; `N` opens Add, and does not while typing in a field.
- Activity table: columns, sort and its query string, pane open and close, keyboard movement, bulk select.
- Add panel:
  - opens from `?add=1` and from a `/new?mode=cash&take=none&amount=45.00` link with those values;
  - saves from the keyboard;
  - stays open with the date, bucket and payer kept;
  - Esc asks when the form is dirty;
  - edit mode closes after a save.
- Item form sends `usage_unit`; the entry sheet sends `usage` only for items with a unit.
- Bills list: states (empty, paused, changed, offline).
- History: year picker, last-year bars, the hidden charts without usage, the table's against-last-year arithmetic, Edit usage and its offline state, fewer than 2 entries.
- Home: the `billChange` row, its order, dismiss, and its return for a newer entry.
- `appRoute` for the new link, tested through `routerPathFromSwMessage`.
- Bundle: the main chunk stays under the 340 kB guard; the Bills screens are lazy.
