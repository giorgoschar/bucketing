# Plan › Cash: design

Approved by the user on 2026-10-08 (chat), together with these decisions:

- Year folds into Month.
- Home gets a "cash not logged" row.
- "Count now" is a real recount.

The backlog polish batch (`docs/redesign/backlog.md`) waits until Cash and Pantry ship.

## 1. Goal

The new app (`/app`) has no cash screen, so the user still goes to the old UI at `/cash`.

This change ports cash tracking to the React PWA and follows the Vault mocks (`docs/redesign/mocks/cash-pantry.html`, Cash section). It reuses the existing cash rules in `app/services/cash.py` unchanged, apart from the new recount kind in §3.1.

Out of scope:

- Pantry: the next phase.
- Notifying a stash owner when someone takes from their stash. No such notification exists today, and the UI must not promise one.
- Editing a movement: delete it and add it again.
- The legacy `out` kind: read-only, shown in history only.

## 2. Rules that do not change (`app/services/cash.py` docstring)

- **Stash:** private.
  - `stash = stash_in − takes from it + put_back`, over all time.
  - Only the owner sees the balance or its history.
  - A take from someone else's stash is never refused, so their stash can go negative.
  - A take from your own stash is refused if it doesn't cover the amount (`OWN_STASH_SHORT`).
- **Wallet:** per member and per month, visible to the household.
  - `spent = carried + taken − put_back − still_have_end`, floored at 0.
  - `not_yet_logged = spent − logged − outs`, floored at 0.
  - Others see `taken` net of put back. `put_back` is returned to the member only.
- **Currency:** the household currency only.
- **Spend in one step:** a take with `spend_bucket_id` logs the cash expense too, linked to the take. This is only allowed from your own stash or the bank.

## 3. Server

### 3.1 New movement kind `stash_count` (a recount)

- `CashKind.stash_count = "stash_count"`. `kind` is a `String(16)`, so there is **no migration**.
- **Request:** `POST /api/v1/cash/movements` with `{"kind":"stash_count","amount":<counted>, "movement_date"?, "note"?}`.
  - `amount` is what the owner physically counted. It must be ≥ 0, and 0 is allowed.
  - `stash_owner_id`, `spend_bucket_id` and `category_id` are rejected (422).
- **What the server stores:** one row with `user_id = actor`, `kind = stash_count` and `amount = counted − stash_balance(actor)`, computed at save time inside the same transaction.
  - The amount is the signed correction, and it may be negative or zero.
  - A zero correction is still stored, as a "counted, it matched" record.
- **`stash_balance`** includes the owner's `stash_count` rows, adding their signed amount.
  - `_stash_rows(owner)` gets a third branch: `user_id == owner AND kind == stash_count`.
- **What ignores `stash_count`:**
  - wallet maths (`_load_ledger` / `_breakdown`, `wallet_summaries`, `not_yet_logged`);
  - Insights (`cash_spending`, `cash_scope`);
  - `require_stash_covers`, which only reads the balance.
- **Each place that switches on kind must be checked:** a test must prove that a recount changes the stash but not the wallet or Insights.
- **Privacy:** a `stash_count` row belongs to the owner only. `list_movements` already returns only your own rows plus others' takes from your stash. Add a test that another member never receives it.
- **Delete:** `delete_own_movement` treats `stash_count` like `stash_in`.
  - Deleting it is refused with 400 if that would leave the stash below zero.
  - When the row's amount is negative, deleting it raises the balance, so it is always allowed.
- **Legacy Jinja `/cash` history** (`templates/cash/_list.html`): label the row "Recounted your stash (±€X)", and show nothing new in the forms.

### 3.2 `GET /api/v1/cash/wallets?month=YYYY-MM`

- Default: the current month. Auth: `require_api_auth`. A bad month returns 400, as `/summary` does.
- Response (`CashWalletsOut`):
  ```json
  {"month":"2026-10","stash":"380.00",
   "members":[{"member_id":"…","name":"Giorgos","is_me":true,
               "wallet":{"carried":"0.00","taken":"120.00","put_back":"0.00","still_have":null,
                         "spent":"120.00","logged":"75.00","outs":"0.00","not_yet_logged":"45.00"}}]}
  ```
  - `stash` is the viewer's own.
  - `members` covers every household member: the viewer first, then the others by name.
  - Use one `wallet_summaries(..., viewer_id=user.id)` call.
  - `put_back` is null for the other members.
  - Names come from the same source the existing member and payer lists use.
  - Amounts are serialised the way `/summary` serialises them today (`quantize`). Keep that wire format.

### 3.3 Typed responses

- Add Pydantic response models (`response_model=`) to the existing `/movements` GET/POST and `/summary` endpoints, plus `/wallets`. **Do not change the JSON shape.** The composer's `useStash` reads `GET /movements?limit=1` → `.stash`.
- The movement item has `kind` as a Literal that includes `out` and `stash_count`.
- Re-run `npm run gen:api` so `web/src/api/schema.d.ts` gets real types.

## 4. Web (`/app`)

### 4.1 Plan segments

- `VIEWS` is now Upcoming · Month · Budgets · Cash.
- Month gets an inline `Segmented` switch, Month | Year, held in the query string `?view=month&scale=year`. Year renders the existing `<Year/>` unchanged.
- Old links `?view=year` resolve to Month with the Year scale.
- `?view=cash` shows the Cash screen.

### 4.2 Cash screen (`web/src/features/plan/cash/`)

Top to bottom:

1. **My stash card.**
   - The balance (`ui-num`), with the caption "Only you see this".
   - Buttons: **Add**, **Take** and **Count**.
   - When the stash is below 0 (by more than 0.005): the balance is shown as "Balance by the book". A warning reads "Your stash may be €20 short" with **Count now**, which opens the Count sheet.
2. **Wallets, "‹ October 2026 ›".**
   - Use a month stepper, the same component and format Month already uses. Caption: "Household sees these".
   - One card per member, the viewer first. Each card shows the sum "Took €120 − Logged €75 = €45 not yet logged".
     - "Took" is `carried + taken − put_back`, as returned.
     - "Logged" is `logged + outs`.
     - When there is a still-have, it is also subtracted and shown: `− In hand €15`.
     - When `not_yet_logged ≤ 0.005`, the card shows "All logged" instead.
   - The viewer's own card also has:
     - **Log it**, only when there is an amount not yet logged.
     - **Still have**, which opens the Cash sheet in Still have mode.
3. **Movements.**
   - The data is `GET /cash/movements?month=` for the shown month, newest first. Each row is worded as in the old `_list.html`, and a recount row reads "Recounted your stash (−€20)".
   - Others' deleted takes from your stash are struck through, with "(deleted)".
   - A row with `transaction_id` links to `/activity/:id`.
   - Tapping one of your own rows opens a small sheet with **Delete**. It confirms inside the sheet and shows the server's 400 detail inline.

### 4.3 Cash sheet: one sheet with three modes, Take / Put back / Still have

**Take**
- Amount, using the same amount input and comma-decimal parsing as the composer.
- **From:**
  - My stash, showing "€380 now → €340 after".
  - Each other member's stash, showing "Balance hidden".
  - Bank / ATM.
- Date (default today) and an optional note.
- **"I spent it on…"** toggle, only for My stash or the Bank.
  - When on, it shows bucket and category pickers (from the composer data) and sends `spend_bucket_id` and `category_id`.
- The button reads "Take €40", or "Take €40 and log it" when the spend toggle is on.
- A short own stash shows the server's `OWN_STASH_SHORT` message inline. The client also pre-checks it with the known stash.

**Put back**
- Amount, date and note. The button reads "Put back €X".

**Still have**
- Prompt: "How much cash is in your wallet right now?". Amount 0 is allowed; date and note are optional.
- It shows the not-yet-logged amount before and after: "€45 → €30". After = max(0, not_yet_logged − (still_have_new − (still_have_current ?? 0))), and the server is authoritative on refresh.
- The button reads "Save €15 in hand".

**Add to stash**
- The same sheet without the segment row: amount, date and note. Title: "Add to stash".

### 4.4 Count sheet

- Prompt: "How much is in your stash right now?". Amount 0 or more.
- It shows "By the book €-20 → Counted €0 · correction +€20" before saving. The button reads "Save count".

### 4.5 Log it

- It navigates to `/new?mode=cash&take=none&amount=45.00`.
- The composer must accept `amount`: a positive decimal pre-fills the keypad, and anything else is ignored.
- It must accept `take=none`: cash method, with the "Not tracked" take source. The cash is already out of the wallet, so this must not create a second take.
- Today, `?mode=cash` without `take` keeps its current behaviour.

### 4.6 Home › Needs attention

- New kind `cash`: the viewer's own current-month `not_yet_logged > 0.005`, taken from the wallets query.
- Text: "€45 cash not logged yet". Action: **Log it**, as in §4.5.
- Order: after `missingAmount` and before `budget`.
- When the wallets query has nothing cached, the row is not shown and no error appears.

### 4.7 Data, offline, invalidation

- Reads use `useCachedQuery`, and the new keys are added to `web/src/data/keys.ts` additively:
  - `cashWallets(month)`
  - `cashMovements(month)`
- Offline, the screen renders from cache with "Offline · showing saved cash".
- Writes are **online-only**, the same way Settings writes are (no queue, `role=alert` error toast). Offline, every write button is disabled with "Connect to change cash".
- After any cash write, and after a composer save or delete of a cash expense with a take, invalidate:
  - the cash keys;
  - `keys.cashStash()`;
  - Home dashboard and attention;
  - Plan month;
  - Insights.

### 4.8 Accessibility and layout

- 390×844 with no horizontal overflow, in light and dark.
- 44 px targets. Sheets use `focusTrap`.
- Amounts use `ui-num`, wrapped where they sit in running text (P3 lesson: the `.ui-num` nowrap overflow).

## 5. Tests (must exist)

**Server**
- Recount:
  - positive, negative and zero corrections;
  - the balance equals the counted amount afterwards;
  - a later take still subtracts;
  - deleting a count follows the §3.1 rule;
  - another member never sees the count;
  - the wallet and Insights are unchanged by a count.
- `/wallets`:
  - every member, the viewer first;
  - `put_back` is hidden for others;
  - a bad month returns 400;
  - household isolation.
- Typed models keep the old JSON shape: a snapshot of `/movements` and `/summary` keys.
- Legacy `/cash` page renders a recount row.
- Postgres run of the cash tests.

**Web**
- Plan segments, including the legacy `?view=year`.
- Cash screen states: stash positive or negative, all logged or not, offline.
- Each sheet mode's request body.
- The take source hides the spend toggle for another member's stash.
- Count preview arithmetic.
- `/new?mode=cash&take=none&amount=` pre-fills and creates no take.
- Home cash attention row and its order.
- Invalidation after writes.
