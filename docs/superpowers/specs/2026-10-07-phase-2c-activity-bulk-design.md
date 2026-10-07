# Phase 2c: Activity and bulk changes (design)

- **Date:** 2026-10-07
- **Status:** draft, awaiting written-spec review.
- **Builds on:**
  - 2a (`2026-10-07-phase-2a-plan-home-design.md`): the UI kit, `useCachedQuery`, `useAction`, `keys.ts`;
  - 2b: `/new?from=`, `/edit/:id`, `usePendingTransactions`;
  - the planning spec (`2026-10-06-planning-redesign-design.md`);
  - 2d's migration `b8c9d0e1f2a3`.
- **Binding:** `docs/redesign/backlog.md` › Bulk changes.
- **Visual source:** `docs/redesign/mocks/access-home.html` §03 Activity, on `tokens.css` and `components.css`.

## 1. Purpose

One screen to find, check and fix transactions:
- a feed with search and filter chips ("No payer" and "Possible duplicates" are chips, not pages);
- a read-first detail with receipt, shares and history;
- swipe actions, and multi-select with a bulk bar.

**Success means:**
1. Any transaction can be found by merchant, note, category, bucket, person or exact amount.
2. Every past Cosmote payment, and the bill itself, moves into a new bucket in one flow, with the budget effect shown first and one-tap undo of the whole batch.
3. The "No payer" rows are cleared with one bulk payer change.
4. "Keep both" hides a duplicate pair for good, for both members.
5. Swipe delete and field edits work offline. A bulk change never half-applies.

## 2. Scope

**In scope:**
- the feed, chips, the Filters sheet and duplicates mode;
- the detail with per-field edits;
- swipe actions;
- selection, the bulk flow and "Recent bulk changes";
- the backend in §5.

**Out of scope:**
- Create, copy and full edit: 2b's composer (`/new?from=<id>`, `/edit/:id`) owns amount, date and shares.
- CSV export (stays in the old app).
- Bulk delete, bulk "no payer", bulk date or amount changes.
- Accent-insensitive search.
- Logging single-row edits.

## 3. Architecture

- **`ui/` additions:**
  - `Chip` (with `aria-pressed` and a count);
  - `SearchField` (250 ms debounce);
  - `SwipeRow` (wraps `ListRow`);
  - `BulkBar` (the mock's `.bulkbar`);
  - `Check`;
  - `Toast` gains `{action, durationMs}` if 2a's lacks it.
- **`data/keys.ts` additions:** `transactions.list(filter)`, `transactions.history(id)`, `transactions.counts`, `duplicates`, `bulkRecent`. 2b's `transactions.one(id)` is reused.
- **`features/activity/`:**
  - screens: `Activity`, `Feed`, `FiltersSheet`, `Duplicates`, `Detail` (with its field pickers);
  - bulk: `selection.ts`, `BulkSheet`, `BulkPreview`, `RecentBulk`;
  - plumbing: `filters.ts`, `hooks.ts`.
- Screens use the kit and `hooks.ts`, never `api` (2a §3).
- `screens/Activity.tsx` becomes a re-export; `router.tsx` adds `activity/:id`.
- **Filters live in the URL, with the API's names:** `/activity?q=&category_id=&bucket_id=&paid_by=&payment_method=&type=&recurring_bill_id=&missing_payer=1&dups=1&from_date=&to_date=&min_amount=&max_amount=`. This lets 2a's and 2d's "See all" deep-link. `filters.ts` maps URL ⇄ `TransactionFilter`.
- **2a edit (after 2a lands):** the Item sheet gets "See payments" → `/activity?recurring_bill_id=<id>`.

## 4. Screens and flows

### 4.1 Feed

- **Chips** (under the search field): **Filters** (active count), **month** (current by default; "All time" clears), **No payer N**, **Duplicates? N**, **Income**, **Cash**.
  - Counts come from `/transactions/counts`, and chips at 0 are hidden.
  - The Filters sheet covers type, category, bucket (incl. "No bucket"), payer, method, bill, dates and amount range.
- **Day groups** ("Today · Tue 6 Oct") show the day's net from `day_totals`: income − expenses, base currency, transfers excluded. It stays right across pages.
- **Row:**
  - icon;
  - title: merchant, else notes, else category;
  - subtitle: category · payer · "split", or "no payer";
  - signed amount;
  - badges: "Apple Pay", "Fixed" (bill-linked, no bucket), "Waiting to sync".
- **Paging:** 50 per page with infinite scroll, plus a "Load more" button.
- **Queued creates** (2b's `usePendingTransactions`) can't be swiped or selected. Their detail is read-only ("Saves when you're back online").
- **Empty states:** "Nothing here yet" / "No matches" + "Clear filters".

### 4.2 Duplicates mode (`dups=1`)

- The chip replaces the list with pair cards (mock "Possible duplicates"); the other chips are disabled.
- **Card:** label · amount, a gap badge ("2 min apart" when created ≤10 min apart, else "N days apart"), and the rows side by side.
- **Delete one:** tap the row to drop (it gets the "Will be deleted" outline), then confirm. Uses the single delete.
- **Keep both:** `POST /transactions/duplicates/dismiss`.
- **Empty state:** "No possible duplicates in the last 90 days".

### 4.3 Swipe

| Gesture | Action |
|---|---|
| Left past 40%, or the revealed "Delete" | Delete. Toast "Deleted · Undo" for 5 s. The DELETE is sent when the toast ends, or at once when the page is hidden; Undo cancels it locally. A bill-linked row adds "Cosmote Oct is expected again". |
| Right past 40%, or "Copy" | `/new?from=<id>` (2b) |

A long-press (500 ms) enters selection instead.

### 4.4 Detail (`/activity/:id`)

As in the mock:
- **Head:** icon, title, amount, "Tue 6 Oct · Card".
- **Receipt card:** a thumbnail and "View receipt" via `GET /transactions/{id}/receipt`. With no receipt: "Add receipt" (existing upload, online only).
- **Field rows**, each opening a picker: Category, Bucket, Paid by, Method, Notes, and the "Count in forecast" toggle.
  - Each saves via `useAction` `PUT /transactions/{id}`, with the full body from the cached row. `splits` and `payer_mode` are copied, because a PUT without `splits` deletes them.
  - The Bucket picker offers "No bucket" for income. It offers "No bucket (Fixed cost)" only when the row is already a bucket-less Fixed cost (R7): a bill payment that has a bucket keeps one, and the picker says "Bill payments keep a bucket. Move the bill instead."
- **"Edit"** opens `/edit/:id`.
- **Shares:** a read-only bar and rows.
- **Linked:** the recurring entry (opens 2a's Entry sheet), or the cash take.
- **History** (§5.2). A bulk event within its undo window has "Undo this change".
- **Footer:** Copy as new, Delete.

### 4.5 Selection and bulk

- **Enter selection** by long-press, by "Select", or by "Select all N" under the No payer chip.
- **App bar:** "Cancel · N selected · All".
  - **All** means *by filter* (server-side, not just the loaded rows), or *by bill* when a bill filter is on.
  - Unticking a row afterwards returns to hand-picked.
- **BulkBar:** "N · €X" with **Bucket**, **Category**, **Payer**, **Method**. Disabled offline ("Needs a connection").

**The Bulk sheet:**
1. **Choose** one or more changes. Payer offers the members plus "Each paid their own share".
   - *By bill* with a bucket change shows "Also move the bill, so future payments go here" (off by default).
   - That toggle is disabled for an event bucket and hidden for `in` items.
   - The Bucket choice offers "No bucket" for income, and "No bucket (Fixed cost)" only when every selected row is already a bucket-less Fixed cost (R7). A selection with any bucketed bill payment never offers it.
2. **Preview** (`dry_run`):
   - the count and total (out and in), and "N already set";
   - per bucket, `spent_before → spent_after` of the budget with its period, on 2a's ProgressBar, plus "+N from other periods, not in this budget";
   - the bill line;
   - skipped rows grouped by reason, each expandable;
   - the button reads "Apply to N", or "Nothing to change".
3. **Apply** sends `expected_count`.
   - On 200: the toast "Moved N payments · Undo" shows for 10 s.
   - On 409: re-preview.
4. **Undo** from the toast, from the detail's history, or from ⋯ › **Recent bulk changes** (the last 10). The result reads "Restored N · M changed since, left as they are".

## 5. Backend

- **Endpoints:** all under `/api/v1/transactions`.
- **Auth:** `require_api_auth` and household isolation everywhere.
- **Models:** response models throughout (`Money` from `planning_models.py`). Then run `npm run gen:api`.
- **Route order:** the literal GETs (`/counts`, `/duplicates`, `/bulk`) must be registered **before** `GET /transactions/{txn_id}`, or they answer 404 "Transaction not found". B1's `api/bulk.py` router is included ahead of the transactions router.

### 5.1 Feed: extend `GET /transactions`

- **`TransactionFilter`:** one Pydantic model, used as `Depends()` here and as `select.filter` in bulk. All fields are optional:
  - `q`, `type`, `category_id`, `bucket_id`, `no_bucket`, `paid_by`, `missing_payer`, `payment_method`, `recurring_bill_id`, `fixed`, `from_date`, `to_date`, `min_amount`, `max_amount`;
  - the existing `year` and `month` stay.
- **`q`:** a case-insensitive match on notes, merchant, category name, bucket name, and household members' names. A numeric `q` also matches the amount exactly.
- **`paid_by`:** the payer or a split holder.
- **Bad dates, amounts or enum values:** 400.
- **Response `TransactionPage`:** `{total, page, page_size, items: TransactionOut[], day_totals: {date: Money}}`.
  - `TransactionOut` = the `_txn_dict` fields plus `has_take` and `missing_payer`.
  - Page size 50 (max 200). Order: date desc, then `created_at` desc.
- **`GET /transactions/counts`** → `{no_payer, duplicate_groups}`.

### 5.2 Duplicates, receipt, history

- **`GET /transactions/duplicates`** → `{groups: [{amount, transactions}]}`, from `find_household_duplicates` (90 days, ±3 days). It drops groups whose pairs are all dismissed.
- **`POST /transactions/duplicates/dismiss`** `{ids: [≥2]}` stores every pair (smaller id first), idempotently. A foreign or inactive id gives 404.
- **`GET /transactions/{id}/receipt`:** a `FileResponse`. 404 for no receipt, deleted, another household, or a missing file. 2b's "View" should use it, since `/transactions/files/…` uses the old app's cookie.
- **`GET /transactions/{id}/history`** → `{events: [{at, kind, by, text, batch_id, can_undo}]}`.
  - Kinds: `created`, `entry_linked` (`paid_at`), `cash_taken`, `bulk_change` ("Bucket: Day to day → Bills") and `bulk_undone`.

### 5.3 Bulk endpoints

**`POST /transactions/bulk`**
```json
{ "select": {"ids": [...]} | {"filter": TransactionFilter} | {"bill_id": "…"},
  "changes": {"bucket_id"?: id|null, "category_id"?: id|null,
              "payer"?: {"mode":"single","user_id":"…"} | {"mode":"own_share"},
              "payment_method"?: "card|cash|apple_pay|transfer|other"},
  "move_bill": false, "dry_run": true, "expected_count": null }
```
- **`select`:**
  - exactly one key (422 otherwise);
  - an empty filter → 400;
  - `bill_id` selects active rows with that `recurring_bill_id`;
  - more than 1,000 matched rows → 400 ("Narrow the filter").
- **`changes`:** at least one key (400 otherwise). A key sent as `null` means "none"; an absent key means unchanged.
- **`expected_count`** (filter or bill): a mismatch with `matched` gives 409 "The selection changed: N now match. Preview again." Nothing is written.
- **Apply** is one database transaction, with rows loaded `with_for_update(of=Transaction)`. A plain `FOR UPDATE` fails on Postgres alongside `joinedload(splits)`.

**Response `BulkResult`** (the same for dry run and apply):
`{dry_run, batch_id|null, matched, changed, unchanged, total_out, total_in, skipped: [{id, code, reason}], buckets: [{bucket_id|null, name, kind, budget, period_start, period_end, spent_before, spent_after, moved_in, moved_out, outside_period}], bill: {id, name, bucket_before, bucket_after}|null, undo_until|null}`
- **`buckets`:** every source and target bucket of the changed expenses.
  - `spent_*` uses `bucket_spent`/`bucket_period`, the same numbers as 2a Budgets: this month for a monthly bucket, the event's dates for an event bucket.
  - `outside_period` counts moved rows outside that period.
  - `null` stands for "No bucket (Fixed costs)" this month.
- **`total_*`:** in base currency.
- **`changed = 0`:** no batch is created.

**`POST /transactions/bulk/{batch_id}/undo`** → `{restored, skipped, bill_restored}`.
- 404: unknown batch, or another household's.
- 409: already undone, or older than 24 h ("Changes can be undone for 24 hours").
- The batch row is locked `FOR UPDATE`, so two concurrent undos give one 200 and one 409.
- `undone_at` is set even when rows are skipped.

**`GET /transactions/bulk?limit=10`** (max 50) → `[{id, created_at, created_by, summary, row_count, undone_at, can_undo}]`.

### 5.4 Rules

A row that can't take *every* requested change is skipped whole, with a code and a reason (the `bulk_set_payer` pattern). A row already holding the targets is `unchanged` and isn't stored.

| # | Case | Result |
|---|---|---|
| R1 | An id that is missing or in another household; a target bucket, category, payer or bill outside the household | 404, whole request (indistinguishable) |
| R2 | An id of the household's own soft-deleted row | skip `deleted` |
| R3 | Target bucket archived | 400, whole request |
| R4 | Income → a bucket failing `require_takes_income` | skip `income_bucket` |
| R5 | Income → `null` | allowed |
| R6 | Expense or transfer without `recurring_bill_id` → `null` | skip `needs_bucket` (the CHECK is never hit). R7 covers bill-linked rows |
| R7 | Bill-linked expense that currently has a bucket → `null` | skip `needs_bucket`, reason "Bill payments keep a bucket; move the bill instead". A bill-linked expense that is already bucket-less stays bucket-less (`unchanged`) or may move into a monthly bucket (R8 for an event bucket). `update_transaction` is **not** changed: it keeps `fixed_cost = recurring_bill_id is not None and bucket_id is None and type == expense`, so a Fixed cost stays bucket-less only if it already was, and bulk follows the same rule |
| R8 | Expense → event bucket | allowed. The preview shows the event's progress and `outside_period` |
| R9 | `move_bill` without `select.bill_id` or without a bucket change | 400 |
| R10 | `move_bill` to an event bucket / for an `in` item | 400, the recurring API's messages |
| R11 | `move_bill` | sets `recurring_bills.bucket_id` (old value kept). Entries aren't regenerated: they read the item's bucket, so future entries count there |
| R12 | `recurring_bill_id` and the entry's `transaction_id` | never changed |
| R13 | Payer → own share or → a non-taker, on a row with an active linked take | skip `cash_take` |
| R14 | Method away from cash on a row with a linked take | skip `cash_take`; the take is never dropped |
| R15 | Method → cash on a single-mode row with no payer, and no payer in the batch | skip `cash_needs_payer` |
| R16 | Own share on income or transfer | skip `own_share_type` |
| R17 | Own share whose splits fail `own_share_problem` | skip `no_split`. Else `absorb_own_share_cent` and `paid_by = NULL` |
| R18 | Single payer on a bill-linked row | the entry's `paid_by` follows (old value kept) |
| R19 | Category away from fuel on a row with `fuel_litres` | skip `fuel_data`. Into fuel: allowed, litres NULL |
| R20 | Match suggestions | untouched: never linked, dismissed or re-suggested |
| R21 | `dry_run` | writes nothing |

**Undo**, per stored row:

| # | Case | Result |
|---|---|---|
| U1 | Soft-deleted since | skip `deleted_since` |
| U2 | Any batch field's current value ≠ the stored new value | skip `changed_since` |
| U3 | The old bucket, category or payer is gone | skip `target_gone` |
| U4 | Restoring a `null` bucket (a Fixed cost moved into a bucket by the batch) on a non-income row whose `recurring_bill_id` is now NULL (FK SET NULL) | skip `needs_bucket` |
| U5 | R13, R14 and R17 against the old values | same codes |
| U6 | Otherwise | restore, including the entry's `paid_by`. `require_takes_income` is not re-checked |
| U7 | Bill move | restored only if the item's bucket still equals the new value and the old bucket exists |
| U8 | The own-share cent | kept |

### 5.5 Migration `c9d0e1f2a3b4` (down_revision `b8c9d0e1f2a3`)

Additive, for SQLite and Postgres 18. The downgrade drops all three tables.

| Table | Columns |
|---|---|
| `bulk_batches` | `id` PK; `household_id` FK CASCADE; `created_by`, `undone_by` FK users SET NULL; `created_at` NOT NULL; `undone_at`; `selection` VARCHAR(8); `fields` VARCHAR(64); `summary` VARCHAR(200); `row_count`; `total_out`, `total_in` NUMERIC(12,4); `bill_id` FK recurring_bills SET NULL; `bill_bucket_old`, `bill_bucket_new`; `bill_moved` BOOL. Index (`household_id`, `created_at`) |
| `bulk_batch_rows` | `id` PK; `batch_id` FK CASCADE; `transaction_id` FK CASCADE; `old_`/`new_` × `bucket_id`, `category_id`, `paid_by`, `payer_mode`, `payment_method` (VARCHAR, no FKs, so history survives deletions); `occurrence_id`, `old_occurrence_paid_by`; `restored` BOOL. Unique (`batch_id`, `transaction_id`); index `transaction_id` |
| `duplicate_dismissals` | `id` PK; `household_id` FK CASCADE; `first_id`, `second_id` FK transactions CASCADE; `created_by`; `created_at`. Unique pair; CHECK `first_id < second_id` |

## 6. Offline

| Action | Behaviour |
|---|---|
| Feed, detail, duplicates, counts | `useCachedQuery`, one key per filter. A filter with no cache shows "Search needs a connection" with "Show saved list" |
| Swipe delete, field edits | `useAction`: optimistic, queued offline (no server id needed, 2a §3.2). Replay failures go to Home › Needs attention |
| Receipt | View: cached if loaded before. Add: online only |
| Bulk preview, apply and undo; dismiss | **Online only**: disabled offline. A network failure shows "Couldn't reach the server. Nothing was changed." Never queued: a batch is checked against server state and its id is server-made |

**Invalidation:**
- **After delete, edit, apply or undo:** `transactions.*`, `duplicates` and `bulkRecent`, plus 2a's `plan/*`, `budgets`, `pace` and the Home keys.
- **`move_bill`** also invalidates `recurring` and `recurring/entries`.

## 7. Look and accessibility

2a §7 applies. In addition:
- **Chips:** `aria-pressed`.
- **Selected rows:** `aria-selected` plus a tick.
- **Swipe is never the only path.** Detail has every action. SwipeRow reveals focusable "Delete" and "Copy" buttons on focus. Results are announced through the toast (`aria-live="polite"`).
- **Preview:** before → after is written as text, not only bars.
- **BulkBar:** labelled "Bulk actions for N selected", and sits above the tab bar.

## 8. Errors

| Case | Behaviour |
|---|---|
| Bulk 400/404 | Sheet stays open; the server `detail` is shown inline |
| Bulk 409 | Re-preview, with the message |
| Undo 409 | Toast with the `detail`; the Undo button is removed |
| Undo with skips | "Restored N · M changed since, left as they are", with "Details" |
| Single edit 409/400 | 2a rollback and toast |

## 9. Testing

**Backend** (pytest, SQLite; Postgres 18 once). One test per R and U row, including these exact cases:
1. **R1:** a household-B id in A's request → 404, both unchanged. A filter never touches B's identical seed.
2. **R4–R7:** null bucket on {income, plain expense, transfer, bucketed bill-linked expense, bucket-less Fixed cost} → income applied, the Fixed cost `unchanged`, and 3 `needs_bucket` (plain expense, transfer, bucketed bill payment), no `IntegrityError`. A bucket-less Fixed cost moved into a monthly bucket applies. Income into a bucket with `show_income` off is skipped while the expenses move. A single PUT nulling a bucketed bill payment returns 400 (`update_transaction` is unchanged), and a PUT that keeps a bucket-less Fixed cost bucket-less succeeds.
3. **R8:** 3 rows into an event bucket, one dated before `start_date`: `spent_after − spent_before` = two amounts, `outside_period = 1`, and it equals `bucket_spent` after apply.
4. **R9–R11:** by bill + `move_bill` → `/recurring/entries` shows the new bucket. Event target, an `in` item, or `ids` → 400.
5. **R12/R18:** links unchanged; the entry's `paid_by` is the new payer, and the old one after undo.
6. **R13–R15:** a cash row with a take: payer → other member is skipped, method → card is skipped, and the take is still active and the same. Method → cash with no payer is skipped; with a payer in the batch it applies.
7. **R17/R19:** 33.33/66.66 of 100 → applied, and the splits sum to 100.00. Fuel → Groceries with litres → `fuel_data`.
8. **R20/R21:** a dry run leaves the row, batch and suggestion counts identical. Apply leaves an open suggestion open.
9. **Limits:** 1,001 ids, an empty filter or no changes → 400. An `expected_count` mismatch → 409 with no writes.
10. **Undo:**
    - U2 (a PUT on one row, then undo: `changed_since`, the others restored);
    - U4 (a Fixed cost moved into a bucket, then the item deleted, then undo);
    - a second undo → 409;
    - 24 h + 1 s (frozen clock) → 409;
    - another household → 404.
11. **Feed:** each `q` field hits; a non-member's name doesn't; `q=42.50`; `day_totals` across pages; a bad date → 400. Duplicates: a dismissed pair is hidden, but a 3-group with one dismissed pair still shows. Receipt: own → 200; foreign, deleted or missing → 404. `GET /transactions/counts`, `/duplicates` and `/bulk` return their payloads, not 404.
12. **Migration:** round-trip from `b8c9d0e1f2a3`, `test_single_head`, and the production-shaped upgrade test.

**Frontend** (Vitest, typed fake `fetch`):
- the `filters.ts` round-trip;
- the detail PUT keeps `splits`;
- swipe delete: Undo sends nothing, otherwise the DELETE goes after 5 s;
- All → filter → untick → hand-picked;
- `expected_count` is sent, and a 409 re-previews;
- the bar is disabled offline.

**Before handover:** typecheck, test, build and the full pytest suite. Then a manual pass at 390×844 in light and dark mode: move a bill's payments and the bill, then undo; clear No payer; resolve a duplicate.

## 10. Delivery

Subagent-driven, one worktree per stream. UI streams load `frontend-design`, `mobile-native` and `apple-design`. The final review runs on the most capable model.

| Stream | Content | Depends on | Weight |
|---|---|---|---|
| **B1** | migration, models, `services/bulk.py`, `api/bulk.py`, the R7 skip rule (no change to `update_transaction`), tests 1–10 and 12 | **Starts now**, branched from 2d stream M so `b8c9d0e1f2a3` exists; merges after M | 9 |
| **B2** | filter, response models, counts, duplicates, receipt, history (no bulk events until B1 merges), test 11 | **Starts now**, in parallel (different files) | 5 |
| **F1** | kit additions, keys, feed, chips, filters, swipe, detail, duplicates | 2a stream A; B2 (regenerate types); 2b's `usePendingTransactions` (stubbed `[]` until then) | 11 |
| **F2** | selection, bulk sheet, preview, undo, recent changes, 2a Item-sheet link | F1, B1 | 8 |
| **Review** | review and manual pass | all | 2 |

The last column is the relative weight of each stream, not an hour count.

**Estimate:** agent build time, with streams in parallel: about 3–4 hours.

**Merge order:** 2d M (`b8c9d0e1f2a3`) → B1/B2 (`c9d0e1f2a3b4`) → F1 → F2. 2d's mutes migration (`d0e1f2a3b4c5`) chains after `c9d0e1f2a3b4`, so it merges after B1. A migration runs, so take the usual `pg_dump` first. The user pushes to `main`.

## 11. Decisions made in this spec

1. One `TransactionFilter` drives the feed and bulk-by-filter, so "N match" is the list shown.
2. Search extends `GET /transactions`. `q` adds merchant, matches member names only, and is not accent-insensitive.
3. **R1/R2:** foreign or missing ids → 404 for the whole request; own deleted rows → skipped.
4. Rows are skipped whole, never half-changed. Unchanged rows aren't stored.
5. **R7:** `update_transaction` is not relaxed: a bucket-less Fixed cost stays bucket-less only if it already was. In bulk, a bill-linked expense that has a bucket is skipped (`needs_bucket`) when moved to `null`; a bucket-less one may stay bucket-less or move into a monthly bucket. The bill moves with `move_bill`, not with a null bucket.
6. **R4–R6:** income goes to "No bucket" or to a `require_takes_income` bucket. Transfers follow the expense rules.
7. **R3:** an archived target bucket → 400. Moving out of an archived bucket is allowed.
8. **R9–R11:** the bill move is *by bill* only, to a monthly bucket or none, with no entry regeneration.
9. **R13–R15:** cash takes are never dropped or reassigned. Method → cash needs a payer.
10. **R19:** fuel rows with litres are skipped when recategorised away from fuel.
11. **R12/R18/R20:** suggestions and links are untouched. Only the entry's `paid_by` follows the payer.
12. **R8:** the preview uses `bucket_spent` periods. Out-of-period rows are counted separately.
13. Preview→apply drift is caught by `expected_count` (409).
14. Limits: 1,000 rows per batch; page size 50 (max 200); duplicates over 90 days and ±3 days.
15. Undo: any member, 24 h, once per batch, only rows still holding the batch's values. The batch tables are never purged.
16. Change detection uses the stored new values; no `updated_at` column is added.
17. Undo re-checks existence, the CHECK, takes and splits, but not `require_takes_income`.
18. `duplicate_dismissals` shares the migration, so "Keep both" holds for both members.
19. History is derived (no audit log, no "Added by").
20. Receipts get an API-auth endpoint; 2b's View should use it.
21. Bulk, undo and dismiss are online-only. Swipe delete and field edits are queued.
22. Swipe delete is held for 5 s locally (no restore endpoint), and sent at once when the page is hidden.
23. Queued creates can't be swiped or selected.
24. Duplicates is an exclusive chip mode, not a route.
25. Copy, amount, date and shares go through 2b's composer.
26. "All" selects the server-side filter or bill, not just the loaded rows.
