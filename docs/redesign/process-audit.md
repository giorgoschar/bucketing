# Process audit: income, bills, buckets and planning (2026-10-06)

I read the code to map the user processes, not the tech stack. References are to `app/` as of the cleanup branch. "Inference" marks conclusions drawn from the code rather than seen directly. This audit is the evidence for `docs/superpowers/specs/2026-10-06-planning-redesign-design.md`.

## Income
- Income is a `Transaction` with `type=income`. Its bucket is optional; the database check is "bucket unless income" (`models.py`).
- **Choosing the recipient:**
  - The HTML form lets you choose who received it (`routes/income.py`).
  - The API always records the caller (`api/income.py`).
- **Where income counts:**
  - It counts in In/Out/Net and in the savings rate.
  - Income sitting in a bucket counts only while that bucket has `show_income` on.
  - It isn't used in the forecast or the `/me` view.
- **No recurring or expected income exists.** Salaries have to be typed in every month.

## Bills
- **Frequency:** `frequency` is cosmetic, and dates come only from `interval_months` (`services/bills.py`).
  - The list shows "Monthly" whatever the interval.
  - There's no weekly, business-day or yearly rule.
- **Occurrence generation:**
  - Occurrences are generated only on create or edit, up to 10 years ahead (capped at 600). Nothing extends that window later.
  - An edit deletes the unpaid future occurrences and regenerates them. Amounts set on those occurrences are lost (inference).
  - A start date in the past creates past unpaid occurrences, which auto-pay then pays with backdated expenses (inference).
- **Paying:**
  - Paying a bill that has a bucket creates an expense.
  - **Paying a bill without a bucket only marks it paid, with no expense** (`settle_occurrence`). "No bucket" is the form's default.
- **Undo:**
  - There's no un-pay or un-skip.
  - Deleting a bill's expense leaves the occurrence marked paid.
- **Pausing (`is_active`)** only affects the scheduler. Upcoming, overdue and "Bills due" still include paused bills (`services/dashboard.py`, `services/insights.py`).
- **"Bills due"** covers the whole calendar month, including bills already paid and paused bills. Non-EUR amounts are added at face value.
- **Scheduler:**
  - Auto-pay at 00:05.
  - Reminders 3 days before the due date.
  - Overdue reminders at 1, 3, 7, 14 and 30 days.
  - Contract expiry reminders at 30 and 10 days.
  - Drift alerts at >25% and >€5 against the average of the last 3. In practice these only fire for variable bills. (Phase A replaced this: at least 20% and €10 against the same month a year earlier, else the median of the last 3; see `app/services/bill_change.py`.)
- **Payment method:** there is no per-bill default; auto-pay always records card.
- **Matching:** there's no link between a manual or Apple Pay expense and an unpaid occurrence, so the same bill can be counted twice.

## Buckets and budgets
- **Types:** `day2day`, `trip`, `bills`, `savings` and `custom`. Only trip and savings have their own behaviour. `bills` only acts as an insights filter.
- **The budget is one number with no period, so it means different things on different screens:**
  - Dashboard and scheduler: this month.
  - Insights: the selected period.
  - Bucket detail and trip remaining: all-time.
- **Savings:** "saved" is income minus expenses in the bucket. Contributions are therefore logged as income, which inflates In and the savings rate (inference). The `transfer` type is unused.
- **Not connected:** upcoming bills never reduce a bucket's available amount. Categories have no budgets.
- **Bulk changes:** the only bulk action is setting the payer.

## Forecast
- `get_forecast` is a straight-line extrapolation of spending so far against a 3-month average. It ignores bills and income, and appears only on Insights.
- Rent paid on the 1st gets extrapolated across the month (inference).
- There's no expected income, safe-to-spend figure, cash-flow calendar or 12-month outlook.

## Cash and stock
- Cash taken counts as spent. Cash not yet logged appears as its own line, outside every bucket.
- Marking stock as bought only offers a pre-filled expense form; it doesn't create the expense.

## Top gaps (ranked)
1. No recurring or expected income.
2. The forecast ignores bills and income.
3. The budget has no period and three meanings.
4. Paused bills still show as due.
5. Bills without a bucket record no expense.
6. No bill↔expense matching, so double counting is possible.
7. No un-pay or un-skip, and deleting a bill's expense leaves it marked paid.
8. Editing a bill is destructive and can lead to backdated auto-pay.
9. Monthly intervals only, with no yearly view.
10. No bulk move, and savings are logged as income.
