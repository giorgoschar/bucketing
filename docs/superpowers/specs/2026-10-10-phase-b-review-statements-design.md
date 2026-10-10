# Phase B: month review and statements — design

Approved by the user on 2026-10-10 (chat), with these decisions:

- A statement is **always live**: the month recalculated each time it is opened. Nothing is frozen and no month is locked.
- A month closes **by itself after 5 days**. The user can also mark it reviewed earlier.
- **No budget carry-forward.** Budgets that ran over are shown, and nothing is changed.
- **No export** (no PDF, no CSV).

Roadmap: `docs/redesign/roadmap.md`, Phase B.

## 1. Goal

On the 1st of a month the user wants to look back at the month that just ended: what was planned and what happened, which budgets ran over, which bills changed, what cash is still unlogged. Every past month stays readable later, like a bank statement.

Out of scope: carry-forward, export, frozen numbers, locking, a per-member statement (the Insights "Me" lens already covers that), changes to the old Jinja app.

## 2. Terms

- **Month:** a calendar month, `YYYY-MM`, in the household's local time (`local_today()`).
- **Review window:** days 1 to 5 of a month, for the month before it.
- **Reviewed:** a member pressed Done for that month. Household-wide.
- **Closed:** reviewed, or the review window has passed (today is the 6th or later of the following month, or any later month).
- **Statement:** the page for one past month. The review and the statement are the same page.

## 3. Server (stream S)

### 3.1 Migration

One revision, `d6e7f8a9b0c1`, `down_revision = "c5d6e7f8a9b0"`:

- New table `month_reviews`: `id` (string pk), `household_id` (fk households, cascade, not null), `month` (`String(7)`, not null), `reviewed_at` (datetime, not null), `reviewed_by` (fk users, `SET NULL`, nullable). Unique on (`household_id`, `month`).
- New notification type `month_review`. On PostgreSQL this is `ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'month_review'`, done the way `a5b6c7d8e9f0_stock_and_prices.py` does it. `tests/test_migrations.py::test_notification_enum_members_are_all_migrated` must pass.
- Downgrade drops the table. The enum value stays (PostgreSQL cannot drop one); the downgrade deletes `month_review` notifications first, so the old code never reads a value it does not know.

### 3.2 The statement (`app/services/statement.py`)

`GET /api/v1/insights/statements/{month}` → `StatementOut`. `month` must be `YYYY-MM` and strictly before the current month; otherwise 400 (bad format) or 404 (current or future month). Household only: the lens and the Insights filters do not apply.

It is built from the existing services, each asked for that month, so its numbers agree with the screens that already show them:

```json
{"month": "2026-09", "label": "September 2026",
 "reviewed_at": null, "reviewed_on": null, "reviewed_by": null, "reviewed_by_name": null,
 "closed": false, "days_left": 3,
 "totals": {"in": 3000.00, "out": 2240.00, "net": 760.00,
            "previous": {"month": "2026-08", "in": 3000.00, "out": 2000.00, "net": 1000.00}},
 "planned": {"in":  {"planned": 3000.00, "actual": 3000.00},
             "out": {"planned": 910.00,  "actual": 934.00},
             "open": [{"entry_id": "…", "item_id": "…", "name": "Gym", "direction": "out",
                       "due_date": "2026-09-28", "amount": 35.00, "estimated": false, "status": "expected"}]},
 "budgets_over": [{"bucket_id": "…", "name": "Daily", "budget": 1200.00, "spent": 1310.00, "over": 110.00}],
 "bills_changed": [{"item_id": "…", "name": "Electricity", "entry_id": "…", "due_date": "2026-09-14",
                    "amount": 84.00, "usual": 61.00, "basis": "last_year", "direction": "up",
                    "pct": 38, "reason": null, "reason_pct": null}],
 "cash": [{"member_id": "…", "name": "Giorgos", "not_yet_logged": 45.00}],
 "categories_over": [{"category_id": "…", "name": "Eating out", "icon": "🍽", "amount": 370.00, "usual": 240.00}],
 "biggest": [{"transaction_id": "…", "date": "2026-09-03", "label": "IKEA", "category": "Home", "amount": 420.00}]}
```

- **Reviewer fields (statement and list rows):** `reviewed_at` is naive UTC and is not shown. `reviewed_on` is the household-local date (`YYYY-MM-DD`) the month was reviewed, `reviewed_by_name` the reviewer's display name, and `reviewed_by` (a user id) is on both the statement and the list rows. All are null while unreviewed. The page's "Reviewed on …" line reads `reviewed_on`; a month with `closed` true and no `reviewed_on` reads "Closed automatically".
- **"Has data"** (the list's first month, the review banner, the notification, a statement worth showing) counts transactions and wallet cash movements only, never stash movements.
- **`totals`:** In, Out and Net exactly as Insights' `in_out` for that whole month (Out includes cash not yet logged). `previous` is the month before, or null when the household has no data in it.
- **`planned`:** from the recurring entries due in that month.
  - `planned` per direction: the sum of the entry amounts (Phase A spec §2) of every entry that is not skipped; an expected entry with no amount counts its estimate, or 0 with none.
  - `actual` per direction: the sum over done entries.
  - `planned` includes the done entries of items paused afterwards.
  - `open`: entries still expected (not done, not skipped), oldest first, at most 50. `status` is `expected`.
- **`budgets_over`:** monthly budgets (not event budgets) whose spending in that month is above the budget, largest overrun first. Uses the same spending rule as `budget_rows`. A bucket archived since then is still listed when it had a budget and spending that month.
- **`bills_changed`:** for every out item, each done entry due in that month, assessed with `bill_change.assess` against the entries before it. Only results that pass the gates. Largest `|delta|` first.
- **`cash`:** each member whose wallet for that month has `not_yet_logged > 0.005`, from `wallet_summaries`. No stash figure appears anywhere: stashes are private.
- **`categories_over`:** the flagged rows of `categories_vs_usual` for that month.
- **`biggest`:** the 5 largest expenses of the month by base amount (not soft-deleted, not income, not transfers), with the same label rule the Activity feed uses.
- **`closed` / `days_left`:** §2. `days_left` is the number of days left in the review window including today, and null when closed.
- Money is JSON numbers. A bounded number of queries: no query per entry or per transaction.

### 3.3 The list

`GET /api/v1/insights/statements` →

```json
{"review": {"month": "2026-09", "label": "September 2026", "days_left": 3},
 "months": [{"month": "2026-09", "label": "September 2026", "in": 3000.00, "out": 2240.00,
             "net": 760.00, "reviewed_at": null, "reviewed_on": null,
             "reviewed_by": null, "reviewed_by_name": null, "closed": false}]}
```

- `months`: every month from the household's first month with a transaction or a cash movement up to last month, newest first, at most 120. Months inside that range with no data are listed with zeros.
- `review`: last month, when today is in the review window, the month is not reviewed and it has any data; else null.
- Totals use the same rule as §3.2, computed for all months in a bounded number of queries (reuse or extend `monthly_in_out`).

### 3.4 Mark reviewed

`POST /api/v1/insights/statements/{month}/review` → `StatementOut`. Any member. Idempotent: a second call keeps the first `reviewed_at` and `reviewed_by`. Current or future month: 404. A concurrent double insert must not 500 (unique constraint handled).

There is no un-review.

### 3.5 The notification

A stage in the daily scheduler job:

- Runs on days 1 to 5. For each household where last month has any data and is not reviewed: notify every member.
- Type `month_review`. Dedupe key `month_review:{household_id}:{YYYY-MM}`, so it is sent once.
- Title: `September is ready to review`. Body: `In €3,000 · Out €2,240 · Net +€760` (the alert money format: no ".00"; the net carries its sign).
- Link: `/app/insights/statements/2026-09`.
- `notification_prefs`: a new row, group "Insights", label "Month ready to review".
- One household failing does not stop the others (savepoint per household, as the bill-change stage does).

### 3.6 Types

Every route has a `response_model`. Run `npm run gen:api` at the end of the stream.

## 4. Web (stream W)

### 4.1 Routes

- `/insights/statements`: the list.
- `/insights/statements/:month`: the statement. A current, future or malformed month shows "No statement for this month yet." with a link back to the list.

Both are lazy chunks. On desktop the statement page uses the 1100 px width that the bill history page uses; the list uses the 720 px column.

### 4.2 The statement page

Title: the month's label. Under it, one line by state:

- In the review window and not reviewed: "Review by 5 October · 3 days left".
- Reviewed: "Reviewed on 2 October by Giorgos" ("by you" for the viewer; no name when `reviewed_by` is null).
- Closed without a review: "Closed automatically".

And always: "Numbers are live: they change if you edit an entry from this month."

Sections, in this order. A section with nothing to show is one muted line, not hidden, so the page always reads the same:

1. **In, out and net.** Three tiles. Under each, the change from the month before ("€240 more than August"), in words and with a sign, not colour alone. No comparison line when `previous` is null.
2. **Planned vs actual.** Two rows, In and Out: planned, actual and the difference. Then "Still open" with the `open` entries; each opens that entry's sheet in Plan. Empty: "Everything planned was done or skipped."
3. **Budgets that ran over.** One row per budget: name, "€1,310 of €1,200", "€110 over". Empty: "No budget ran over."
4. **Bills that changed.** One row per result, with the Phase A sentence ("Electricity was €84, usually €61") and a link to the bill's history. Empty: "No bill changed much."
5. **Cash not logged.** One row per member. The viewer's own row has **Log it** (the existing `/new?mode=cash&take=none&amount=` link). Empty: "All cash is logged."
6. **Categories above usual.** Name, amount, "usually €240". Each opens the category screen for that month. Empty: "Nothing above its usual."
7. **Biggest expenses.** Up to 5 rows, each opening the entry.

At the bottom, only in the review window and when not reviewed: a primary **Done** button, with "Marks September as reviewed for the whole household." It calls §3.4. Online only; offline it is disabled with "Connect to finish the review". After it succeeds the page shows the reviewed line and the button is gone.

Desktop: sections 1 and 2 span the width; 3 to 7 flow in two columns (the Insights column layout). Phone: one column.

### 4.3 The list

One row per month: label, In, Out, Net (signed, as text), and a small "Reviewed" or "Open for review" mark. Rows link to the statement. The month in review is first, with "Review". Empty: "No past months yet."

### 4.4 Insights

A **Statements** card after the Bills card: the last 3 months with their net, and "All statements". On desktop it is a half-width card in the column flow. It shows in an empty period too, as the Bills card does.

### 4.5 Home › Needs attention

- New kind `monthReview`, when `review` is not null: "Review September", action **Review**, which opens the statement.
- Order: first in the list. It is the one row about the past month and it expires by itself.
- When the list query has nothing cached, the row is not shown and no error appears.

### 4.6 Notification link

`appRoute`: a link under `/app/insights/statements` opens that route. Tested through `routerPathFromSwMessage`.

### 4.7 Settings

Settings › Notifications shows the new "Insights · Month ready to review" switch. It comes from the server list; check that the screen renders a group it has not seen before.

### 4.8 Data, offline, invalidation

- New keys in `web/src/data/keys.ts`: `statements()`, `statement(month)`.
- Reads use `useCachedQuery`; offline they render from cache with "Offline · showing saved statement".
- Invalidate both after: any transaction write, any entry write (Pay, Undo, Skip, Set amount, usage), any cash write, an item edit or delete, a budget edit, and Done. Use the places that already invalidate Insights.

## 5. Accessibility and layout

- 390 × 844 and 1440 × 900, light and dark, with no horizontal page scroll.
- Headings in order (one `h1`, sections `h2`). Amounts use `ui-num`, wrapped in running text.
- Signs and directions are text, not colour alone. 44 px targets on the phone.
- Every desktop rule inside `@media (min-width: 1024px)`.

## 6. Tests (must exist)

**Server**

- Migration up and down on Postgres, one head, the enum test.
- Statement: each section against a seeded month, including: a month with no data (zeros and empty lists, not an error); `previous` null; an estimated open entry; a skipped entry left out of planned; an event budget left out; a budget on a since-archived bucket; two changed entries of one item in one month; a member with nothing unlogged left out; a soft-deleted expense left out of `biggest`; household isolation on all three routes.
- Totals equal Insights' `in_out` for the same month (one test that calls both).
- Current and future months: 404. Malformed: 400.
- `closed` and `days_left` on day 1, day 5, day 6 and a month later, with a fixed clock; December to January.
- Review: idempotent; first reviewer kept; two concurrent calls; another household's month untouched.
- List: range, zeros for empty months, the 120 cap, `review` null when reviewed, outside the window, or with no data; a bounded query count.
- Scheduler: sent once on day 1; not on day 6; not when reviewed; not for a household with no data; a muted member; title and body text; one household failing does not stop the next.
- No stash amount appears in any Phase B response (assert on a household with stashes).

**Web**

- Statement page: each state line; each section filled and empty; the month-before sentences, including a lower month and `previous` null; Done and its request, its offline state, and the page after it; a bad or current month.
- List: rows, the review row first, empty.
- Insights card, including an empty period. Home row and its place. `appRoute`.
- Offline rendering from cache. Invalidation after a transaction write and after Done.
- Bundle guard; both screens lazy and precached.
