# Planning Redesign — Design

**Status:** approved in conversation on 2026-10-06, section by section. This document is up for written review.
**Lands:** backend first, as its own implementation plan, after new-app Phase 1 and before Phase 2 (Home). The Phase 2 Home and Phase 3 Plan screens are built on it.
**Evidence:** the process audit in `docs/redesign/process-audit.md`.

## 1. Purpose

The household uses the app for **information and decision-making**: tracking as much of its income and spending as it can, seeing what's coming, and noticing when spending runs above normal.

The app does **not** know bank balances. It must never present a leftover as "money saved" or "money you have". Every projected figure is labelled as a projection and shows what it is made of.

Success means:
- Both salaries, rent-in and every bill appear on their own as expected entries, on the right dates.
- Home shows a trustworthy month picture: so far, still to come, projected.
- Yearly costs and extra salaries are visible months ahead.
- A charge logged by Apple Pay never double-counts a bill.
- **None of the existing data is lost or changes meaning.** The live app keeps working on the same database until cutover.

## 2. Household facts the design must support

From the user, 2026-10-06:

**Income**
- **User's salary:** fixed, on the 26th or the earliest business day before it.
- **Partner's salary:** fixed, on the last working day of the month.
- **Christmas and Easter salaries.** Greek Orthodox Easter moves every year.
- **Rent received:** monthly.
- **Freelance:** irregular. Logged by hand, not scheduled.
- **Ticket Restaurant:** recorded as ordinary income with no special category.
- Income is recorded **per person** but counted in **one household picture**.

**Bills** are paid by direct debit or standing order, by card or Apple Pay (often already logged by the Shortcut), by manual e-banking transfer, or in cash.

**Budgets**
- Keeping per-category budgets up to date is too much effort.
- The user wants **one monthly number per bucket**, with categories compared against **their own history**.
- Today's five bucket types are confusing.

**Out of scope by request:** savings progress and savings rate as headline figures.

## 3. Recurring items

### 3.1 Model

Today's `RecurringBill` becomes a **recurring item** with a `direction`:
- `out`: DEH, Cosmote, rent paid, insurance.
- `in`: salaries, Christmas and Easter salaries, rent received, Ticket Restaurant.

Irregular income (freelance) is not a recurring item.

Fields that stay as they are: `amount` (NULL = variable), `currency`, `category_id`, `bucket_id` (out items only; optional), `paid_by_default` (for `in` items this is "received by"), `payer_mode` and default shares (out only), `is_auto_pay` (out only), `is_active`, `start_date`, `end_date`, `total_occurrences` and `contract_end_date`.

### 3.2 Schedule rules

A rule is `kind` plus parameters. Every rule produces dates on or after `start_date`, then stops at `end_date` or after `total_occurrences`.

| `kind` | Parameters | Example |
|---|---|---|
| `monthly_interval` (legacy) | `interval_months`; the day is taken from `start_date` | Every existing bill: same day, every N months, no adjustment (identical to today) |
| `monthly_day` | `day` (1–31, clamped to the month's length), `interval_months`, `adjust` | User's salary: day 26, adjust = previous business day |
| `last_business_day` | `interval_months` | Partner's salary |
| `yearly` | `month`, `day`, `adjust` | Christmas salary: 21 Dec, previous business day |
| `easter_offset` | `days` (relative to Orthodox Easter Sunday), `adjust` | Easter salary: −4 (Holy Wednesday) |
| `weekly` | `interval_weeks`, `weekday` | Weekly cleaner |

`adjust` is one of `none`, `previous_business_day` or `next_business_day`.

**Business days** are Monday to Friday, minus Greek public holidays:
- Fixed: 1 Jan, 6 Jan, 25 Mar, 1 May, 15 Aug, 28 Oct, 25 Dec, 26 Dec.
- Moving, relative to Orthodox Easter: Clean Monday (−48), Good Friday (−2), Easter Monday (+1), Whit Monday (+50).

Orthodox Easter comes from `dateutil.easter.easter(year, EASTER_ORTHODOX)`; dateutil is already a dependency. The calendar lives in one module (`app/core/calendar_gr.py`) with no database access.

The date engine is **one shared function** used by the old app, the new API and the scheduler, so both UIs always produce identical dates.

### 3.3 Expected entries

Today's `bill_occurrences` rows are the expected entries. The table, its rows and its unique `(bill_id, due_date)` constraint stay.

- **Statuses shown to users:** `expected` (stored `unpaid`), `done` (stored `paid`) and `skipped`. Stored values are unchanged for compatibility.
- **Rolling horizon:** entries exist from `start_date` to 13 months from today. A daily scheduler job tops up every active item. Existing rows beyond the horizon (from the old 10-year generation) are kept and are harmless.
- **Done:** an `out` entry is done when an expense is linked; an `in` entry is done when an income transaction is linked. Linking happens through Pay / Mark received, which creates the transaction, or by confirming a match suggestion (§3.5).
- **Undo:** done → expected unlinks the transaction (the user chooses whether to delete it too). Skipped → expected.
- **Deleting a linked transaction** (soft delete) puts its entry back to expected.
- **Variable amounts:** an entry without an amount shows an estimate, the average of the last 3 done amounts for that item. It's labelled "≈". Setting the real amount stores it on the entry.

### 3.4 Lifecycle fixes (from the audit)

1. **Paused (`is_active = false`) items are hidden** from every list, total and projection, in both apps. Their entries stay in the database.
2. **Paying an `out` entry always creates an expense.** With no bucket, the expense is a **Fixed cost**: allowed with no bucket because it is linked to a recurring item (§6.1).
3. **Editing an item regenerates only future entries that are `expected` and have no amount set.** Done and skipped entries, and entries with an amount set, are never touched.
4. **Creating or editing never produces expected entries dated before today.** For a past `start_date`, the form asks "Already paid up to today?" and creates nothing in the past.
5. **Auto-pay only pays entries due within the last 3 days.** It never backfills older ones.

### 3.5 Matching

When an expense or income is created from any source (Apple Pay ingest, manual, scan, offline replay), and once a day for the last 14 days of transactions, the app looks for an expected entry that:
- has the same direction (expense ↔ out, income ↔ in);
- falls within **−3 to +7 days** of the due date;
- for a fixed amount, is within **±15%**; for a variable amount, within ±50% of the estimate, **or** has a similar merchant/description to the item's name (case-insensitive containment, with Greek accents stripped).

A match becomes a row in `match_suggestions`. It shows in **Needs attention** as "Looks like Cosmote · Oct · €38.90", with **Link** and **Not this**.
- **Link** marks the entry done and sets `transactions.recurring_bill_id`.
- **Not this** sets `dismissed`, and that suggestion is never shown again.
- Nothing is linked without a tap.

## 4. Buckets and budgets

### 4.1 Two kinds

- **Monthly:** the budget is per **calendar month** in the household timezone and resets on the 1st. The same meaning applies everywhere: Home, bucket detail, warnings at 80% and 100%, and insights.
- **Event:** the budget is a **total** over `start_date` to `end_date` (the end is optional). The bucket shows spent vs total and days left. When the end date passes, it offers to archive the bucket (`status = archived`, which already exists).

### 4.2 Bills, income and categories

- An `out` recurring item may point at a **monthly** bucket. Its payments then count toward that bucket's budget. With no bucket, they are **Fixed costs**.
- **Income has no bucket.** Existing income that sits in a bucket keeps it, and the bucket shows it for reference. Planning counts all income the same way.
- **Categories have no budgets.**
  - Each category is compared with its **usual**: the median of its spend over the last 3 full months, counting months with zero spend.
  - A category is flagged in Needs attention and Insights only when this month is **at least 20% and at least €20 above usual**.
  - Only months the household has data for are counted. Fewer than 2 such months means no flag.
- **Dropped:** savings goals and progress, and transfers as a planning concept.

## 5. Planning views

All figures are household-wide, in base currency (`exchange_rate` applied, as today). Each figure is tappable down to the transactions or entries behind it.

### 5.1 Home: month picture

| Row | So far | Still to come | Projected |
|---|---|---|---|
| In | income this month | `in` entries still expected this month | sum |
| Out · Fixed | expenses linked to recurring items with no bucket | `out` entries with no bucket still expected | sum |
| Out · Buckets | expenses in monthly buckets (including bills that point at a bucket) | budget − spent, floored at 0 | **max(budget, spent)** per bucket, summed |
| Net | | | In projected − Out projected, labelled "projected" |

- Spending in Event buckets and unlogged cash are shown as separate lines and are not in Net. Events span months, and cash is already "spent" when taken, as today.
- Below the table: **Needs attention** (match suggestions, overdue entries, entries missing an amount, categories above usual, budgets at ≥80%), then recent activity.

### 5.2 Plan › Upcoming

The next 30 days of expected entries, day by day, with a running "net this month" (the projected In − Out up to that day).

Row actions:
- `out` entries: Pay, Set amount, Skip.
- `in` entries: Mark received, Set amount, Skip.

### 5.3 Plan › Year

The next 12 months: expected In and expected Out per month, from recurring items only. Variable amounts use their estimate, marked "≈". Under the table goes one line: "Yearly and quarterly bills average **€X/month**". That is the sum over the next 12 months of `out` entries from items with an interval > 1 month or a yearly rule, ÷ 12. It's for information only.

### 5.4 Bucket pace

For each monthly bucket from day 7 of the month: "€904 of €1,200 · on pace for €1,310". Pace counts only spend that isn't linked to a recurring item: (that spend ÷ days elapsed × days in month) + the bucket's recurring-linked spend for the month. Pace replaces `get_forecast`'s straight line in the new app. The old app keeps its forecast until cutover.

### 5.5 Insights

These stay: In/Out by month, category vs usual (§4.2), and the per-person lens (who paid / who received), now including income.

## 6. Data and compatibility

### 6.1 One additive migration

| Table | Change | Backfill |
|---|---|---|
| `recurring_bills` | add `direction` (`out`/`in`, default `out`), `rule_kind` (default `monthly_interval`), `rule_day`, `rule_month`, `rule_adjust` (default `none`), `rule_days` (Easter offset), `rule_weekday`, `rule_interval_weeks` (all nullable) | all rows: `out`, `monthly_interval` (dates identical to today) |
| `buckets` | add `kind` (`monthly`/`event`, NOT NULL) | `trip` → `event`; `day2day`, `custom`, `bills`, `savings` → `monthly` |
| `transactions` | add `recurring_bill_id` (FK, nullable, SET NULL on delete), index | from `bill_occurrences.transaction_id` of paid rows |
| `transactions` CHECK | `bucket_id IS NOT NULL OR type = 'income'` → `… OR recurring_bill_id IS NOT NULL` | none |
| new `match_suggestions` | `id`, `household_id`, `transaction_id`, `occurrence_id`, `dismissed` (bool), `created_at`; unique (`transaction_id`, `occurrence_id`) | empty |

Nothing is dropped:
- `buckets.type`, `goal_amount` and `show_income`, and the `interval_months`/`frequency` fields, stay and keep working for the old app.
- They are cleaned up at cutover, after a CSV export, in the same migration that drops settlements.

### 6.2 Old app during the transition

1. Bills pages, the dashboard and the scheduler's bill reminders query `direction = 'out'` only.
2. Items with `rule_kind != 'monthly_interval'` or `direction = 'in'` are read-only in the old app, with "Edit in the new app" shown.
3. Fixes §3.4 (1, 3, 4, 5) live in the shared services, so the old app gets them too. The old app's "paused bill still shows" bug is fixed there as well.
4. The old app's pay route keeps today's behaviour for bucket-less bills (claim only) until cutover. Only the new API creates Fixed-cost expenses. This keeps the old dashboard's numbers stable.

### 6.3 API (new, under `/api/v1`)

- `/recurring`: CRUD with rule fields and direction. `GET` lists items with their next entry.
- `/recurring/entries?from&to`: expected entries in a range (powers Upcoming and Year).
- `POST /recurring/entries/{id}/done` (creates and links a transaction), `/undo`, `/skip`, `/amount`.
- `/matches`: open suggestions, plus `POST /matches/{id}/link` and `/dismiss`.
- `/plan/month?month=YYYY-MM`: the §5.1 table. `/plan/year`: §5.3. `/plan/pace`: §5.4.
- `/insights/categories-vs-usual?month=`
- `/buckets` gains `kind`. Monthly vs event semantics apply in the new endpoints.

All of these require `require_api_auth` (cookie or Bearer), apply household isolation, and have response models so the TypeScript types are generated.

## 7. Testing and safety

- **Date engine:**
  - Orthodox Easter 2026-04-12 and 2027-05-02.
  - Last business day of Dec 2026 (Thu 31 Dec).
  - A 26th falling on a Saturday becomes Friday the 25th.
  - A 26th before a holiday.
  - Day 31 in a 30-day month.
  - Legacy `monthly_interval` produces exactly the old generator's dates over 10 years for a sample of interval/start combinations.
- **Lifecycle:** done/undo/skip, a soft delete reopens the entry, a pause hides it everywhere, editing keeps set amounts, no past entries, the auto-pay 3-day window.
- **Matching:** the window edges, amount tolerance, Greek accent-insensitive names, dismissal persists, no auto-link.
- **Views:** `max(budget, spent)`, event buckets excluded from Net, category usual with fewer than 2 months.
- **Compatibility:**
  - The **full existing suite passes unchanged** on SQLite and Postgres 18.
  - Migration round-trip.
  - The production-shaped upgrade test (prod schema + seed → head): old-app smoke checks and TOTP login, as done for the v2 deploy.
- **Deploy:** the usual pre-migrate `pg_dump`. Rollback means restoring the dump.

## 8. Out of scope

- Bank balances and account syncing.
- Savings goals and the savings rate as headline figures.
- Transfers.
- Per-category budgets.
- Automatic linking without a tap.
- Scheduling irregular (freelance) income.
- Bulk move/edit and default payment method on bills: these are separate backlog items (`docs/redesign/backlog.md`). A default payment method fits naturally on recurring items and is a candidate for the same plan.
