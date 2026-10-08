# Phase 2a: Plan and Home screens (design)

- **Date:** 2026-10-07
- **Status:** approved in conversation (approach A), awaiting written-spec review.
- **Builds on:**
  - the Phase 1 shell (`web/`);
  - the planning redesign APIs, live since 9df646d (spec `2026-10-06-planning-redesign-design.md`, here "planning spec").
- **Visual source:** the Vault mocks in `docs/redesign/mocks/`. Use `plan.html` and `access-home.html` for layout; `tokens.css` and `components.css` hold the design tokens and components.

## 1. Purpose

This phase delivers the first screens the user sees and uses on the phone. Its main goal is information, and decisions come second:

- what comes in and goes out this month and over the next 30 days;
- what is due;
- what needs a tap.

**Household facts the screens must handle** (planning spec §2):
- Salary on the 26th, or the earliest business day before it.
- The partner's salary on the last working day of the month.
- Christmas and Easter bonuses.
- Ticket restaurant, counted as income.
- One budget number per bucket.
- Match suggestions confirmed with one tap.

**Success means** on an iPhone home-screen install:
1. The user can open Plan and Home offline and see the last data they loaded.
2. They can set up their salaries with the right business-day rule.
3. They can mark entries paid or received, skip them and undo them, including while offline.
4. They can confirm or dismiss match suggestions.
5. Home shows the month's projected Net plus only what needs attention.

## 2. Scope

**In scope:**
- Plan tab: Upcoming, Month, Year, Budgets and Items.
- Home tab.
- The shared UI kit those screens need.
- Cached reads and queued writes.
- One small backend addition: the rule preview (§6).

**Out of scope:**
- ＋ Composer (2b).
- Activity and bulk changes (2c).
- Insights and Settings (2d).
- The Cash and Pantry segments.
- A default payment method on bills (backlog).
- Charts beyond CSS bars.
- Editing transactions.

## 3. Architecture

```
web/src/
  ui/                 shared kit (no data access)
    Money.tsx         formats EUR, tabular numerals, sign, "≈" for estimates
    Sheet.tsx         bottom sheet: focus trap, Esc/backdrop close, safe-area padding
    ListRow.tsx, Segmented.tsx, ProgressBar.tsx, Badge.tsx, Toast.tsx (+ useToast)
    ui.css            ported from mocks/components.css on tokens.css
  data/
    cachedQuery.ts    useCachedQuery(key, fetcher): TanStack Query + encrypted cache
    action.ts         useAction(): online → API; offline/network error → queue
    keys.ts           query keys; which keys each action invalidates
  features/plan/      Plan.tsx (segments), Upcoming/Month/Year/Budgets/Items,
                      EntrySheet.tsx, ItemSheet.tsx (+ RulePicker), hooks.ts
  features/home/      Home.tsx, NeedsAttention.tsx, RecentActivity.tsx, hooks.ts
```

- Screens use the kit and the `features/*/hooks.ts` hooks only. They never call `api` directly.
- `screens/Plan.tsx` and `screens/Home.tsx` become one-line re-exports of the feature screens, so `router.tsx` doesn't change.

### 3.1 Reads: `useCachedQuery`

- It wraps `useQuery` with `networkMode: 'offlineFirst'`.
- **On success:** it writes the data to the Phase 1 encrypted cache with `cachePut(key, data)`.
- **On mount:** it seeds `initialData` from `cacheGet(key)`, so screens render instantly, online or offline.
- **Stale or offline state:** it exposes `dataUpdatedAt` and whether the shown data is from the cache.
  - The screen shows a thin banner, "Offline · updated 14:02", while offline or after a failed refetch of cached data.
- **Isolation:** the cache is already wiped on sign-out and on account switch (Phase 1). Keys include the household id, so a household switch never shows another household's data.

### 3.2 Writes: `useAction`

`useAction({ method, path, body, optimistic, invalidates })` behaves like this:

1. **Optimistic:** apply `optimistic(queryClient)`, which patches the affected cached queries. One example: an entry becomes `done` and the running net moves.
2. **Online:** call the API through `api`.
   - On 2xx, invalidate `invalidates`.
   - On 409 or 400, roll back the patch, show the server's `detail` as a toast, then invalidate.
3. **Offline, or the request failed at the network level:** `enqueue({method, path, body})` through the Phase 1 queue.
   - Keep the optimistic patch.
   - Mark the row "queued". The marker comes from a small in-memory set of pending row ids keyed by entry id.
   - Queue replay (Phase 1) sends it later. When the queue drains, invalidate the plan and home keys.
4. **Failed after replay:** a queued action that fails permanently (4xx) appears in Home › Needs attention as "1 change couldn't be saved", with the server message and a Dismiss button.

**Rules:**
- Only actions whose result doesn't need a server-generated id may be queued. In 2a every action qualifies: done, skip, amount, undo, match link and dismiss, and item create, update and delete.
- Item create while offline shows the item as "pending" until replay.

## 4. Plan tab

The top of the tab has a segmented control: **Upcoming · Month · Year · Budgets**. An **Items** button in the top bar opens the item list.

### 4.1 Upcoming (`GET /api/v1/plan/upcoming?days=30`)

- Days grouped under a date header ("Mon 26 Oct").
- Each row shows: name, a direction marker (in = positive tint, out = neutral), the amount, and "≈" when estimated.
- Each day header shows the running "net this month" (planning spec §5.2; it resets at a month boundary).
- Overdue entries are not shown here. They live in Home › Needs attention (planning spec §5.1).
- **Tapping a row opens the Entry sheet (§4.6).**
- **Empty state:** "Nothing due in the next 30 days", with an "Add a recurring item" button.

### 4.2 Month (`GET /api/v1/plan/month?month=YYYY-MM`, `GET /api/v1/insights/categories-vs-usual?month=`)

- A month switcher (‹ Oct 2026 ›) covers the current month and up to 11 months forward or back.
- **Table:** In, Out · Fixed and Out · Buckets, each as so far / still to come / projected. Then **Net (projected)**, which is the big figure.
- **Buckets:** a row per bucket, expandable, with budget / so far / projected.
- **Separate lines, outside Net:** "Trips & events: €X" (`events_spent`) and "Cash not yet logged: €X" (`cash`).
- **"Categories vs usual":** each category's this-month amount against its usual. Rows that are `flagged` get a warning tint. Rows with no usual show "—".
- **"≈":** shown when `estimated` is true.

### 4.3 Year (`GET /api/v1/plan/year`)

- **Bars:** 12 rows (month, in bar, out bar, net). Bars are scaled to the largest in or out value of the year and drawn with CSS widths, not a chart library.
- **Labels:** each row's values are written out next to it.
- **Footer:** "Yearly and quarterly bills average €X/month" (`infrequent_monthly_average`).
- **"≈":** shown on months with estimates.

### 4.4 Budgets (`GET /api/v1/plan/budgets`, `GET /api/v1/plan/pace`)

- **Per bucket:**
  - name;
  - "€904 of €1,200";
  - a progress bar (tint changes at 80% and 100%);
  - from day 7, "on pace for €1,310", with an over-pace marker when `over_pace`.
- **Event buckets** show their date range and days left, plus "Archive?" when `archive_suggested`. Archiving belongs to 2d, so this is a label only.

### 4.5 Items (`GET/POST /api/v1/recurring`, `GET/PUT/DELETE /api/v1/recurring/{id}`)

- **The list has two groups, In and Out.** Each row shows:
  - the name;
  - a schedule summary, for example "26th, or the business day before" or "Last business day";
  - the amount, or "variable";
  - the next date (`next_entry`).
- **Paused items** sit greyed at the bottom of their group.
- **Tapping a row** opens the Item sheet (§4.7). **＋** opens it empty.

### 4.6 Entry sheet

Opened from Upcoming, Home or Items. It shows the name, due date, amount (with "≈") and status.

**Actions by state:**

| State | Out entry | In entry |
|---|---|---|
| Expected | **Paid** (amount, who, method), Set amount, Skip | **Received** (amount, who), Set amount, Skip |
| Done or skipped | Undo | Undo |

- **Undo of a paid out entry** asks: "Keep the expense" or "Delete the expense". A 409 for a Fixed cost (planning spec Ruling 8) shows the server message and offers "Delete the expense".
- **Endpoints:** `POST /api/v1/recurring/entries/{id}/done|skip|amount|undo`. Body fields come from the generated types.
- **"Who"** defaults to the item's `paid_by_default`. The member list comes from `GET /api/v1/settings/household` (`members`; its response is an untyped dict, so the hook narrows it with a small local type).
- **Method** defaults to card for out entries and transfer for in entries.

### 4.7 Item sheet and rule picker

**Fields:**
- name;
- direction (In/Out; locked once the item has history, since the server returns 409);
- amount (blank = variable);
- currency (EUR by default);
- schedule;
- bucket (out only; event buckets aren't offered);
- category;
- who (`paid_by_default`);
- auto-pay (out only);
- start date and optional end date;
- notes;
- an active toggle (pause/resume).

**Schedule choices** (planning spec §3.2), each with plain-language labels:

| Choice | Maps to |
|---|---|
| "On day N of the month", adjust: none / business day before / business day after | `monthly_day` |
| "Last business day of the month" | `last_business_day` |
| "Every year on DD Month" | `yearly` |
| "Easter ± N days" (Orthodox Easter) | `easter_offset` |
| "Every N weeks on <weekday>" | `weekly` |
| "Every N months from the start date" | `monthly_interval` |

- **Preview:** under the schedule, "Next: 26 Oct, 25 Nov, 23 Dec", from the rule preview endpoint (§6), refreshed as fields change (debounced 300 ms). Offline it shows "Preview needs a connection".
- **Delete:** available only without history. Otherwise the server's 409 message is shown with a "Pause instead" button.

## 5. Home tab

1. **Header figure:** this month's **Net (projected)** from `plan/month`, labelled "projected". Under it: "In €X so far · Out €Y so far".
2. **Needs attention.** Only shown when it isn't empty, in this order:
   1. Match suggestions (`GET /api/v1/matches`): "Card payment €38.90 at Cosmote on 3 Oct looks like **Cosmote** due 5 Oct", with **Link** and **Not this**.
   2. Overdue entries: from `GET /api/v1/recurring/entries?from=<first of last month>&to=<yesterday>`, filtered to `overdue`. Tapping one opens the Entry sheet.
   3. Entries missing an amount in the next 7 days (variable items, status expected, `estimated` true). Tap → Set amount.
   4. Budgets at 80% or more (`plan/budgets`), with "€1,050 of €1,200".
   5. Categories above usual (`flagged`), at most 3.
   6. Queued changes that failed (§3.2), with Dismiss.

   When everything is clear it shows "All clear" with a check.
3. **Recent activity:** the last 10 transactions (`GET /api/v1/transactions?page_size=10`, newest first), each with date, label, amount and bucket, read-only. A "See all" link goes to Activity (still a placeholder until 2c).

## 6. Backend addition: rule preview

`POST /api/v1/recurring/preview`
- **Body:** the schedule fields of `RecurringItemIn` (rule_kind, rule_day, rule_month, rule_adjust, rule_days, rule_weekday, rule_interval_weeks, interval_months, start_date, end_date), plus `count` (1–12, default 3).
- **Response:** `{ "dates": ["YYYY-MM-DD", ...] }`.
- **Validation:** through `validate_rule`; a `RuleError` gives 400 with the message.
- **Behaviour:** dates from today or `start_date`, whichever is later. It uses `app/core/schedule.py` and needs the cookie or Bearer auth. It writes nothing.
- **Afterwards:** regenerate the web types (`npm run gen:api`).

## 7. Look and accessibility

- **Vault tokens:** dark-first, with light mode. Fonts: Sora for figures, Plus Jakarta Sans for text, JetBrains Mono for numbers in tables.
- **Numbers:** tabular numerals on every figure.
- **Safe areas:** sheets and the tab bar respect them.
- **Tap targets:** 44 pt minimum.
- **Sheets:** they open with a short slide, which is disabled under `prefers-reduced-motion`.
- **Colour:** never the only signal. Overdue also says "Overdue"; over-pace also says "over pace".
- **Labels:** every interactive element has an accessible name.
- **Screen width:** 360–430 px is the target. Wider screens get a centred 480 px column; desktop layouts come later.

## 8. Errors

| Case | Behaviour |
|---|---|
| Offline with cache | Data shown, plus the banner "Offline · updated HH:MM" |
| Offline without cache | "No saved data yet. Connect once to load Plan." |
| 401 | The Phase 1 session handles it (sign-in screen; the encrypted cache is kept) |
| 409 / 400 on an action | Roll back, toast the server `detail`, refetch |
| 5xx / network on an action | Queue it (§3.2) |
| Queue item fails on replay | Needs attention row (§5) |

## 9. Testing

- **Unit:**
  - `useCachedQuery`: seeds from the cache, writes on success, shows the offline banner state.
  - `useAction`: online success, 409 rollback, offline enqueue with the optimistic patch kept, invalidation after replay.
- **Components** (Vitest and Testing Library, against a typed fake `fetch` built from the OpenAPI types):
  - Upcoming grouping and running net.
  - Entry sheet actions by state, including the undo choice and the Fixed-cost 409.
  - Item sheet: the rule picker maps every choice to the right `rule_*` fields; the preview is debounced.
  - Home Needs attention: ordering and the empty state.
  - Budgets thresholds.
- **Backend:** pytest for `/recurring/preview`:
  - the salary rule;
  - last business day;
  - Easter offset;
  - an invalid rule returns 400;
  - auth is required.
- **Before handover:**
  - `npm run typecheck`, `npm test` and `npm run build`;
  - the full pytest suite once;
  - a manual pass in Chrome at 390×844 in light and dark mode against a local server with seeded data. Screenshots are checked for overflow and contrast.

## 10. Delivery

- **Execution:** subagent-driven, in speed mode.
- **Parallel streams.** Each stream works in its own git worktree and branch, and they are merged in order.
  - **Stream A:** the UI kit, plus the data layer (`cachedQuery`, `action`, `keys`).
  - **Stream B:** the backend rule preview endpoint and regenerated types.
  - **Stream C (after A):** Plan Upcoming, Month, Year and Budgets, plus the Entry sheet.
  - **Stream D (after A and B):** Items and the Item sheet.
  - **Stream E (after A):** Home.

  C, D and E touch different folders and run at the same time.
- **Skills:** UI tasks load `frontend-design`, `mobile-native` and `apple-design`. The final review runs on the most capable model.
- **Merge:** to `main` by the user (`git push`), as before. Nothing here needs a database migration.
