# Plan › Pantry: design

Approved by the user in chat on 2026-10-08. The decisions:

- The barcode is scanned with a camera-scan library that loads only when the user taps Scan, and typing the digits always works as a fallback.
- The shopping list is still computed, and the user can add one-off extra lines.
- Ticking an item never touches stock or money. Ticked items go into the pantry only after the user confirms.
- Home gets one summary row for Pantry.

The old "Mark bought → log the expense" flow is **not** ported. The polish batch in `docs/redesign/backlog.md` waits until after Pantry.

## 1. Goal

This ports the stock / pantry feature (old UI `/stock`, `/stock/shopping`) to the React PWA as Plan › Pantry, following the Vault mocks (`docs/redesign/mocks/cash-pantry.html`, the Pantry section from about line 254). The existing services in `app/services/stock.py` are reused: low stock, restock quantity, price advice, run-out, the shopping list grouping and price snapshots.

Out of scope:

- A per-product price target ("tell me below €8.49"). The existing `track_price` flag and the automatic `price_drop` alert are kept.
- Sharing or exporting the list.
- Creating or changing expenses from Pantry, in any form.
- Desktop-specific layouts.
- Receipt-to-product matching.

## 2. Rules that do not change

- **Low:** an item is low when `quantity <= min_quantity`.
- **Shopping list:** it contains low items, plus items whose run-out estimate is 7 days or less. `restock_quantity` is `max(1, ceil(2*min − qty))`. Rows are grouped by the cheapest retailer, and unpriced items come last. `best_single_store` is kept as it is.
- **Adjusting stock:** `adjust_stock` clamps at 0 and logs the applied delta as `buy` or `use`.
- **Adding a product** by an existing household barcode revives that product instead of creating a duplicate.
- **PosoKanei failures:** prices-unavailable returns 503, a not-found barcode returns 404, and the app keeps working without prices.
- **Household scoping:** every id is household-scoped, and a foreign id is treated as missing (404).

## 3. Server

### 3.1 New table `shopping_lines` (migration `e1f2a3b4c5d6`, revises `d0e1f2a3b4c5`)

| column | type | notes |
|---|---|---|
| id | String(36) PK | uuid, as other tables use |
| household_id | FK households, CASCADE, indexed | |
| stock_item_id | FK stock_items, CASCADE, nullable | set means a **tick** on a computed item; null means a **one-off line** |
| name | String(200), nullable | required for a one-off line, null for a tick |
| quantity | Numeric(10,2), nullable | a one-off line's optional qty, or the ticked qty (default: that item's `need_qty` at tick time) |
| checked_at | DateTime(tz), nullable | ticked time; one-off lines can be unticked |
| created_by | FK users, SET NULL | |
| created_at | DateTime(tz) | |
| cleared_at | DateTime(tz), nullable | soft clear; active means `cleared_at IS NULL` |

- **Uniqueness:** a partial unique index allows only one active tick per `stock_item_id` (`WHERE cleared_at IS NULL AND stock_item_id IS NOT NULL`). Both SQLite and Postgres support this, using `sqlite_where` and `postgresql_where`.
- **Migration:** it is additive and its downgrade drops the table. Add it to `tests/test_migrations.py` and `tests/test_planning_upgrade.py`, following the existing style.

### 3.2 Endpoints, all under `/api/v1`, `require_api_auth`, with CSRF as the existing API does

**Stock list**

- `GET /stock` is extended. Every new field is optional to older clients.
  - New fields: `unit`, `unit_quantity`, `image_url`, `need_qty` (`restock_quantity`), `runout_days` (int or null, from `runout_bulk`) and `advice` (`buy_now|wait|neutral|unknown`, from `price_advice_bulk`).
  - It also returns `ticked` (bool) and `tick_id`.
- `POST /stock` is extended: it accepts `unit_quantity`, `image_url` and `min_quantity`. When a `posokanei_id` is given, it snapshots prices the same way the Jinja `POST /stock` does (`snapshot_now`, best effort, ignoring `PosokaneiUnavailable`). It returns the list item.

**Product detail and settings**

- `GET /stock/{id}` returns the product detail:
  - the list item fields;
  - `prices_today`: every latest snapshot as `{retailer, retailer_name, price, unit_price, is_discount}`, cheapest unit price first;
  - `history`: one point per day over the last 183 days, `{date, min_price}`, the lowest across retailers;
  - `advice_detail`: the `price_advice` dict with `current_min`, `median_30d`, `min_90d`, `trend_pct_30d`, `reason` and `as_of`;
  - `prices_as_of`: the latest snapshot date, or null.
- `PATCH /stock/{id}` with `{min_quantity?, track_price?}` calls `update_stock_settings` and returns the list item.
- `POST /stock/{id}/refresh` fetches today's prices, the same way the Jinja refresh does. It returns 503 when PosoKanei is unavailable, otherwise the detail.
- `POST /stock/{id}/archive` returns 204. It also clears that item's active tick.

**Shopping list**

- `GET /stock/shopping` is extended.
  - Each group item gains `name`, `unit`, `need_qty`, `ticked` and `tick_id`.
  - The response adds `unpriced`.
  - It adds `lines`: the active one-off lines `{id, name, quantity, checked}`.
  - It adds `ticked_count`: active ticks plus checked one-off lines.

**Ticks and one-off lines**

- `POST /stock/shopping/ticks` with `{stock_item_id, quantity?}` ticks a computed item and returns the tick.
  - Ticking an item that is already ticked is idempotent and returns the existing tick.
  - An archived or foreign item returns 404.
- `DELETE /stock/shopping/ticks/{id}` unticks: the tick is hard-deleted and the endpoint returns 204.
- `POST /stock/shopping/lines` with `{name, quantity?}` adds a one-off line and returns it.
- `PATCH /stock/shopping/lines/{id}` with `{checked: bool}` checks or unchecks the line.
- `DELETE /stock/shopping/lines/{id}` returns 204.

**Applying ticks**

- `POST /stock/shopping/apply-ticked` with `{}`, in **one transaction**:
  - For every active tick, run `adjust_stock(+quantity, reason=buy)` and set `cleared_at`. A tick whose item has been archived meanwhile is only cleared.
  - Every **checked** one-off line is cleared.
  - Unchecked one-off lines stay.
  - It returns `{applied: [{name, before, after}], cleared_lines: n}`.
  - It never touches transactions.
  - Calling it a second time with nothing ticked returns empty results, not an error.

**Product lookup**

- The existing `GET /products/search` and `GET /products/barcode/{code}` are unchanged.
- The barcode response gains `in_pantry`: `{stock_item_id, quantity}` or null, found by matching the household barcode.

**Typed responses**

- Pydantic `response_model`s for every stock and shopping endpoint.
- **Keep the existing JSON keys and number/string types.** Pin the current shape with a snapshot test before changing anything, as the Cash work did.
- Then run `npm run gen:api`.

### 3.3 Home summary

- `GET /stock/summary` returns `{low_count, ticked_count}`. It is cheap: count queries only, with no PosoKanei calls and no run-out maths.

## 4. Web (`/app`)

### 4.1 Plan segments

- Plan has five segments: Upcoming · Month · Budgets · Cash · **Pantry**, with `?view=pantry`.
- At 390 px the five must fit without scrolling. If they do not fit at the current padding, tighten the segment padding; never truncate a label.

### 4.2 Pantry list (`web/src/features/plan/pantry/`)

- **Header:**
  - a search box that filters by name and brand on the client;
  - a **＋** button that opens Add;
  - chips: All / Running low / Price tracked.
- **Each row:**
  - name, plus "· {unit_quantity} {unit}" when known;
  - "{qty} left", and when low "· need {need_qty}", with a warm tint;
  - the cheapest-price chip: "€1.19 · Sklavenitis", green when `advice === 'buy_now'`;
  - a 44 px **− n +** stepper using `POST /stock/{id}/adjust`;
  - tapping the row body opens the detail.
- **Floating button:** "Shopping list (N)", where N is the low and run-out count from the shopping list. It opens the list.
- **Empty state:** "Nothing in your pantry yet", with Add.

### 4.3 Add, search and scan

- **Add sheet:**
  - a search box that searches PosoKanei for queries of 2 or more characters, debounced at 300 ms;
  - a **Scan barcode** button and a **Type barcode** field;
  - a "Not listed? Add manually" form with name, brand, size, in stock and keep at least;
  - the footnote "Prices from PosoKanei", plus the date when known.
- **Search results** show brand, size, the best price and store, and **＋**, which adds the item with a default minimum of 1.
- **Scan:**
  - The camera reader is lazy-loaded only when Scan is tapped, and never ends up in the main chunk. Use a maintained library that reads EAN-13, EAN-8 and UPC-A on iOS Safari. Prefer a library that needs no CSP change; the CSP already allows `'wasm-unsafe-eval'` and `worker-src blob:`.
  - The scan box is wide and short, the rear camera is used, and the stream stops on close.
  - If the camera is unavailable or permission is denied, show "Type the barcode instead" with the field focused.
- **Barcode result sheet:**
  - name and barcode;
  - "In pantry: 3" when `in_pantry` is set;
  - the best price and the other stores;
  - **Scan another**, plus **Add to pantry** (or **Open** when it is already in the pantry).
  - Checking a price never adds the product.
  - 404 shows "Not on PosoKanei · Add manually", with the barcode prefilled. 503 shows "Prices unavailable right now", and manual add stays available.

### 4.4 Product detail (`/plan/pantry/:id`, lazy-loaded)

- A stock stepper, with "{n} below your minimum" when low.
- A **Keep at least** stepper (`PATCH min_quantity`).
- "Lasts about {runout_days} days", or nothing when null.
- **Prices today:** a bar per store, cheapest first, with a discount marker.
- **6-month lowest price:** a small line chart drawn to scale. When there are fewer than 2 points, show "Not enough price history yet".
- A **Track price** toggle (`PATCH track_price`), with the caption "Get a notification when it drops".
- **Refresh prices** (a 503 shows an inline message), and **Archive** with an in-sheet confirm.
- Back returns to the list.

### 4.5 Shopping list (`/plan/pantry/list`, lazy-loaded)

- **Header:**
  - "{items} items · {stores} stores", plus the total;
  - when `best_single_store` exists and splitting saves more than €0.50, a badge "saves €X vs one store".
- **Store sections:**
  - each section has its subtotal;
  - each row has a check, "name × need_qty", a reason line ("Low · 1 left" or "Runs out in ~5 d") and the line price;
  - unpriced items go in a last section, "No price".
- **One-off lines section:**
  - **＋ Add item** takes a name and an optional quantity;
  - each line has a check and a swipe or button to delete.
- **Ticking:**
  - Ticking calls the tick endpoints, optimistic and **queued offline**, because people shop with poor signal. Use `useAction` with the queue, the same way plan entries do.
  - A tick never changes stock.
- **Footer**, when `ticked_count > 0`: "{n} ticked · **Add to pantry**". It calls `apply-ticked` (online-only), then shows a toast listing "Milk 0 → 2 · Olive oil 1 → 2".
- **Copy:** "Ticked items go into your pantry when you confirm. Nothing here changes your expenses."

### 4.6 Prompt after saving an expense

- After the composer successfully saves a **new expense** (not an edit, not income), check `GET /stock/summary` (cached).
- If `ticked_count > 0`, show a one-time sheet: "{n} ticked pantry items · Add them to the pantry?" with [Not now] [Add to pantry].
  - **Add** calls `apply-ticked`.
  - **Not now** dismisses it until the next new expense.
- It never blocks or alters the save.
- It does nothing when offline or when the summary call fails.

### 4.7 Home › Needs attention

- New kind `pantry`: "{low_count} pantry items running low · List", which opens `/plan/pantry/list`.
- It shows only when `low_count > 0`.
- Order: after `cash`, before `budget`.
- With no cache, there is no row and no error.

### 4.8 Data, offline, invalidation

- **Reads** use `useCachedQuery`. Add new keys to `data/keys.ts` (additive only):
  - `stockList`
  - `stockItem(id)`
  - `shopping`
  - `stockSummary`
- **Online-only writes**, which are disabled offline with "Connect to change the pantry":
  - adding a product
  - settings
  - refresh
  - archive
  - apply-ticked
- **The ± stepper** is queued offline, optimistic, with a pending marker. The adjust is a relative delta, so a replay is not idempotent: give each queued adjust a `client_id`, and the server dedupes on it. Add an optional `client_id` to `StockAdjust`, deduped per household within 24 h, the same way the composer's `client_id` works. Reuse that mechanism if it is generic.
- **Ticks and one-off lines** are queued.
- **After any pantry write, invalidate:** `stockList`, `shopping`, `stockSummary`, the item, and Home attention.

### 4.9 Notifications and old links

- `stock_low` currently links to `/stock/shopping` and `price_drop` to `/stock`. When the new app is in use, map them to `/app/plan/pantry/list` and `/app/plan?view=pantry` in `web/src/pwa/appRoute.ts`, keeping the old routes working.

### 4.10 Accessibility and layout

- 390×844 with no horizontal overflow, in light and dark.
- 44 px targets, and the steppers have labels ("Increase Milk").
- `.ui-num` in running text wraps.
- Sheets use `focusTrap`.
- The camera view has a Close button and handles Esc.

## 5. Tests that must exist

**Server**

- The migration: upgrade and downgrade, and the partial unique index.
- The ticks:
  - ticking is idempotent;
  - a foreign or archived item returns 404;
  - unticking.
- The one-off lines CRUD.
- apply-ticked:
  - the stock deltas and the before/after values;
  - checked lines are cleared and unchecked lines stay;
  - archived items are cleared without an adjust;
  - a second call returns empty results;
  - **no Transaction rows are created**.
- The adjust `client_id` dedupe.
- The detail history aggregation (the per-day minimum).
- PATCH settings, refresh returning 503, archive clearing the tick.
- The barcode `in_pantry`.
- `/stock/summary` counts.
- Snapshot tests of the existing JSON shapes.
- Household isolation on every new endpoint.
- A Postgres run of the stock, migration and upgrade tests.

**Web**

- The segments, including five fitting at 390.
- The list:
  - the chips and search;
  - the stepper sends the delta and is queued offline;
  - low tint and need text.
- The Add flows: search add, manual add, and the scan fallback when the camera is denied. The scanner module must not be in the main chunk; assert it via the build output or a dynamic-import test.
- The barcode sheet states (in pantry, 404, 503).
- The detail: the steppers PATCH, the chart draws to scale and its empty state, refresh 503, archive confirm.
- The shopping list:
  - grouping, totals and the saves badge;
  - the tick is queued offline;
  - one-off lines;
  - "Add to pantry" calls apply-ticked and shows the toast.
- The post-save prompt appears only for a new expense with ticks, and never blocks the save.
- The Home row: its order and threshold.
- Invalidation after writes.
