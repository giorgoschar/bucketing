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
