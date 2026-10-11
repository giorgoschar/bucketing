# Phase C: declutter, rules that learn, search everywhere, scan from Add — design

Approved by the user on 2026-10-11 (chat). Decisions:

- Declutter Home, Insights, Plan › Upcoming and Add. Activity, Cash, Pantry and Settings are left alone.
- Insights gets three tabs.
- A rule is offered the second time the same category is picked for the same merchant. Never created without a tap.
- Search opens with `/` or `⌘K` on desktop and from a top-bar icon on the phone.
- Add gets one scan button with two choices; "Cash from wallet" moves into the payment-method chip.
- No long-press actions.

The audit behind the declutter list is in `.superpowers/sdd/phase-c/audit/` (20 screenshots, `index.md`).

## 1. Goal

The app has grown a screen at a time. Home shows nine attention rows at once, Insights is 14 cards long, and pages use 11 to 14 different text sizes. Phase C makes the busy screens calmer and adds three time-savers.

Out of scope: long-press and right-click menus, changes to what any number means, the old Jinja app.

## 2. Declutter

### 2.1 Home

**Needs attention**

- **Order, most urgent first:** `failed` (a change that could not sync), `overdue`, `monthReview`, `match`, `missingAmount`, `cash`, `billChange`, `budget`, `pantry`, `category`. Within a kind, the existing order.
- **One row per recurring item.** `overdue`, `missingAmount` and `billChange` rows of the same item merge into one row: the most urgent kind is the row and keeps its action; each of the others is a line under it that is itself a link ("Needs an amount for 13 Oct", "Was €84, usually €61"). Dismissing a bill change (✕) removes only that line.
- **Three rows, then the rest.** The first 3 rows show. Under them, one button: "Show 6 more" (the number of hidden rows; singular "Show 1 more"). It expands in place and becomes "Show fewer". The choice lasts for the session (not stored). The count badge beside the heading stays the total.
- **Actions.** Only the first row's main action is a filled button. Every other action is a quiet text button. A second action ("Not this") is always quiet. Rows that had no action (`budget`, `category`) become links: to Plan › Budgets, and to the category screen for this month.
- Nothing is removed: every kind that shows today still shows, in the list or behind "Show more".

**Recent activity:** 5 rows (today 10). "See all" stays.

**Desktop:** the hero spans the width; under it two columns, Needs attention on the left (about 60 %) and Recent activity on the right. Home's content width on desktop becomes 1100 px.

### 2.2 Insights

**Tabs.** Under the lens and period controls, a segmented control: **Overview**, **Trends**, **Bills & statements**. It is kept in the query string (`?tab=trends`, `?tab=bills`; Overview is the default and writes nothing). Changing the lens or period keeps the tab. Phone and desktop.

| Tab | Cards, in order |
|---|---|
| Overview | identity and share (member lens only), **Summary**, Where it went, Categories vs usual, Budgets |
| Trends | **By month**, Biggest expense, How you paid, Fuel; desktop also: Last 12 months, Categories table |
| Bills & statements | Bills (the panel on desktop), Statements |

**Summary card** replaces four cards (headline, "This month · On track", "In / Out / Net", "Savings rate"):

- the spent figure and the change against the previous period, as today's headline;
- one line "On track for €3,720 by 31 Oct", only where the On track card shows today;
- In, Out and Net in one row;
- one line "You kept 57% of what came in", only where the Savings rate card shows today.

Every sentence and figure is the one its old card showed. The explanatory footnotes of the old cards go into a single "How these are counted" disclosure at the bottom of the card, closed by default.

**By month card** replaces "In and Out by month" and "Spend trend": one chart with a two-way switch, **In and out** (default) and **Spending**. Each view is the old card's chart, legend and footnote, unchanged.

**Empty period:** Overview shows the existing empty message; the other two tabs work as usual.

**Desktop:** each tab uses the two-column flow from Phase A; Summary, Bills, Statements and the tables span both columns.

### 2.3 Plan › Upcoming

- One list grouped by week (Monday to Sunday): "This week", "Next week", then "20–26 Oct". One card per week, one row per entry.
- A row: the weekday and day ("Tue 13"), the name, the amount (with "≈" and "No amount yet" as today). The "Out" label under the name goes; income rows keep "In" and the positive tone.
- "Net this month" appears once per week, in the week's header, as the figure after that week's last entry. A week that crosses into the next month shows it per month it touches.
- Tapping a row opens the entry sheet, as today. Overdue entries keep their place and their mark.

### 2.4 Add

- **One scan button,** top right of the form (an icon button labelled "Scan"). It opens a small sheet with two choices: **Receipt QR** (the existing receipt scan) and **Pantry barcode** (§5). The "Scan receipt" chip goes.
- **Cash from wallet** moves into the payment-method chip. The method list is Card, Cash, then the other existing methods. Choosing Cash shows the existing "taken from" control (My stash, another member, Bank / ATM, Not tracked) directly under the chips, with today's default. The "Cash from wallet" chip goes. Links with `?mode=cash…` keep working and land in this state.
- **One budget prompt.** The amber "Choose a budget" line above the keypad goes. The budget chip itself turns amber when a budget is required and missing, and Save stays disabled with its existing reason available to screen readers (`aria-describedby`).
- **Currency** moves into More, as its first field. It stays on the main form only when the entry being edited is not in the household currency, or when one of the household's last 20 entries was in another currency.
- The desktop Add panel gets the same four changes.

### 2.5 Type scale

One scale of six sizes as tokens (`--fs-xs` 12, `--fs-sm` 13.5, `--fs-md` 15, `--fs-lg` 17, `--fs-xl` 22, `--fs-hero` 34 px) and three weights (400, 500, 600). Every `font-size` and `font-weight` in `web/src` uses a token, except the amount in the composer and inside SVG charts. Sizes move to the nearest token; a size that would change by more than 1.5 px is listed in the report with before and after, and checked in a screenshot. This is done as one pass after the other streams are merged.

### 2.6 Barcode sheet wording

When a scanned barcode is one of the household's own and no store lists it, the sheet's heading is the item's name and the line reads "Your own item · no store lists this barcode", not "Not on PosoKanei".

## 3. Rules that learn

Existing: `category_rules` ("merchant contains X → category Y"), applied when the server categorises an entry, and managed in Settings › Categories.

### 3.1 When a rule is offered

After an entry is saved (created, or edited with a different category), the app asks the server whether to offer a rule:

`GET /api/v1/category-rules/suggestion?transaction_id=…` → `{"pattern": "lidl", "label": "Lidl", "category_id": "…", "category_name": "Groceries"}` or `null`.

It returns a suggestion only when all of these hold:

- the entry is an expense with a merchant ("Where?") that normalises to a usable pattern, and a category;
- no existing rule already gives that category for that merchant;
- at least 2 of the household's entries (not deleted, this one included) have the same normalised merchant **and** this category;
- the household has not said "Not now" twice for this pattern.

`label` is the merchant as the user typed it on this entry. Household-scoped: another household's entry is 404.

### 3.2 The prompt

- In the "Saved" message (the toast on the phone, the "Saved ·" line in the desktop panel): "Always use Groceries for Lidl?" with **Always** and **Not now**.
- **Always** calls the existing `POST /api/v1/category-rules` with the pattern and category. If a rule for that pattern exists with another category, it is re-pointed (the existing upsert). Then: "Rule saved. Change it in Settings › Categories."
- **Not now** calls `POST /api/v1/category-rules/suggestion/dismiss` with `{"pattern": "lidl"}`.
- The prompt never blocks: it goes away with the message, and ignoring it counts as nothing.
- Online only. Offline, or when the entry was queued, no prompt.
- Entries from Apple Pay: the prompt shows when such an entry's category is changed in the app. The Shortcut itself never creates rules (unchanged).

### 3.3 Storage

Migration `e7f8a9b0c1d2` (revises `d6e7f8a9b0c1`): table `category_rule_dismissals` — `id`, `household_id` (fk, cascade), `pattern` (`String(200)`), `times` (int, default 1), `updated_at`; unique on (`household_id`, `pattern`). Dismiss increments `times`. Creating a rule for a pattern deletes its dismissal row. Downgrade drops the table.

### 3.4 The composer uses rules

When "Where?" is filled and the category has not been touched by the user, the composer pre-selects the category the household's rules give for that text (an existing or new read of `GET /api/v1/category-rules`, matched on the device with the same normalisation as the server; test both sides against one shared list of cases). A category the user picked is never overwritten.

## 4. Search everywhere

### 4.1 Server

`GET /api/v1/search?q=…` → 

```json
{"entries": [{"id": "…", "date": "2026-10-07", "label": "Lidl", "category": "Groceries", "amount": -29.90, "currency": "EUR"}],
 "entries_more": true,
 "items": [{"id": "…", "name": "Nova internet", "direction": "out", "is_active": true}],
 "pantry": [{"id": "…", "name": "Barilla spaghetti", "brand": "Barilla", "quantity": 3}]}
```

- `q` is trimmed; fewer than 2 characters or more than 100 is 400.
- **entries:** the same match as Activity's search (the `q` of the transaction filter), newest first, at most 5; `entries_more` when there are more. Soft-deleted rows never match.
- **items:** recurring items whose name contains `q`, case-insensitively, active first, at most 5.
- **pantry:** non-archived stock items whose name or brand contains `q`, or whose barcode equals `q`, at most 5.
- `LIKE` wildcards in `q` are escaped. Household-scoped. At most 4 queries. A per-user limit of 60 requests a minute (429 beyond), keyed after authentication.

### 4.2 The search box

- **Desktop:** a search field in the sidebar under Add; `/` or `⌘K` / `Ctrl K` focuses it from anywhere (`/` only when no field has focus and no dialog is open). Results open in a panel under the field.
- **Phone:** a search icon in the top bar of Home, Activity, Plan and Insights. It opens a full-screen search with the field focused.
- Typing waits 200 ms, cancels the previous request, and needs 2 characters.
- **Groups, in this order, each shown only when it has results:** Entries, Bills and income (recurring items), Pantry, Statements, Settings.
  - Statements are matched on the device against the saved statements list (month name or "2026-09").
  - Settings pages are matched on the device against a fixed list of page names and keywords (for example "dark" finds Appearance, "token" finds Automations).
- A result opens its place: the entry, the bill's history, the pantry item, the statement, the settings page. Entries end with "See all in Activity", which opens Activity with the same search.
- Keyboard: Up and Down move through results across groups, Enter opens, Esc clears then closes. The list is a `listbox` with `aria-activedescendant`; the number of results is announced.
- No results: "Nothing found for “lidl”."
- Offline: device-side groups still work; the server groups show "Connect to search entries, bills and pantry."

## 5. Scan a pantry item from Add

- **Pantry barcode** (§2.4) opens the existing barcode scanner, then the existing barcode sheet: an unknown product can be added to the pantry; one already in the pantry shows its − / + stepper.
- "Scan another" and closing work as in Pantry. Closing returns to the Add form with whatever was typed still there.
- The scanner code stays lazy-loaded; it must not enter the main chunk or the composer chunk.
- On desktop the same choice appears in the Add panel and uses the computer's camera; "type the digits" is available as in Pantry.

## 6. Accessibility and layout

- 390 × 844 and 1440 × 900, light and dark, no horizontal page scroll.
- 44 px targets on the phone, including quiet text buttons and the "Show more" button.
- The Insights tabs are a `tablist`; the By month switch and the Home expander announce their state (`aria-selected`, `aria-expanded`).
- Every desktop rule inside `@media (min-width: 1024px)`.
- Reduced motion: expanding and tab changes do not animate.

## 7. Tests (must exist)

**Server**

- Suggestion: each condition failing alone gives `null`; the 2nd matching entry gives a suggestion; a rule that already gives the category gives `null`; a rule giving another category still gives a suggestion; two dismissals stop it; creating a rule clears the dismissal; income and merchant-less entries; normalisation (case, accents, spaces); household isolation.
- Migration up and down on Postgres, one head.
- Search: each group; limits and `entries_more`; wildcard characters in `q`; length limits; barcode exact match; archived and soft-deleted rows left out; isolation; the rate limit; a bounded query count.

**Web**

- Home: the order; merged rows for one item and their links; ✕ on a merged bill-change line; 3 rows and the expander with its counts; one filled button; `budget` and `category` rows as links; 5 recent rows; the desktop two columns.
- Insights: the three tabs and their card lists per lens; the tab in the URL and kept across lens and period changes; the Summary card's lines present and absent exactly where the old cards were; the By month switch; the empty period; no existing figure or sentence changed (assert the old strings).
- Plan › Upcoming: week grouping including a week crossing a month and the turn of the year; the per-week net; no "Out" label; the entry sheet still opens.
- Add: the scan sheet and both choices; Cash in the method chip with the take source and its default; `?mode=cash&take=none&amount=` still pre-fills and creates no take; the amber chip and no second line; the currency rule, both ways; the same in the desktop panel.
- Rules: the prompt after the server suggests one; Always and Not now and their requests; no prompt offline or for a queued entry; the composer pre-selecting from a rule and never overwriting a picked category; the shared normalisation cases.
- Search: the shortcut keys and their exclusions; debounce and cancel; groups and their order; device-side groups offline; keyboard movement; each result's destination; "See all in Activity".
- Scan from Add: the lazy chunk boundaries; typed input kept after closing the scanner.
- Type scale: a test that no `font-size` or `font-weight` literal remains outside the allowed files.
- Bundle guard; phone suites for untouched screens unchanged.
