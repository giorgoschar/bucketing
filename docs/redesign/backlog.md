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
