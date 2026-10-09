# Tameio roadmap (agreed with the user, 2026-10-09)

The user works on the **desktop** a lot, both to add expenses and above all for statistics and insights. Desktop gets richer views than mobile.

Each phase gets its own design (spec), plan, build, review and push.

## Phase 0: Open Food Facts barcode lookup (small, first)

A barcode scan fills in the product's name, brand and size from Open Food Facts.

- **Lookup order:** own pantry → PosoKanei (only if it is enabled) → Open Food Facts → add manually.
- **Scope:** barcode lookups only. No name search, no photos, no prices.
- **Client behaviour:** polite. An honest User-Agent with a contact address, a 24 h cache, and well under 100 requests a minute.
- **Credit:** show "Product data: Open Food Facts" (ODbL).
- **Switch:** `OPENFOODFACTS_ENABLED`, default true.
- **Migration:** none.

## Phase A: Desktop and bill history

- **A real desktop layout:** sidebar navigation and wide screens, for adding expenses as well as viewing them.
- **Desktop Insights, richer than mobile:** per-bill and per-recurring-item history, in the style of the fuel view. For example electricity month by month, as a graph and a table, with patterns across years.
- **Price-change alerts on bills:** "Electricity was €84, usually €61".

## Phase B: Month-end review and statements

A review on the 1st of the month, covering:

- planned vs actual;
- budgets that ran over;
- bills that changed;
- unlogged cash;
- carrying budgets forward.

Each month is kept as a statement that can be reopened later, like a bank statement. Desktop first.

## Phase C: Everyday speed

- Rules that learn ("Always use Groceries for Lidl?"), for all entries.
- Search everywhere: entries, bills, pantry items, settings.
- A calmer Home: rank "Needs attention" by urgency and collapse the rest.
- Long-press quick actions on rows. No haptics, because they are unreliable in iOS Safari.

## Phase D: Receipts → pantry and prices

- Read receipt line items into pantry stock and the price history.
- Optional on-device route: an iOS Shortcut ("Extract Text from Image", or the Apple Intelligence "Use Model" action) that sends the text through a token. Test it on Greek receipts first.

## Prices

- **PosoKanei:** the polite client is built, but the service answers 403 to non-browser clients. We do not impersonate a browser. Next step: email the Ministry asking for access (draft offered to the user).
- **bigle.gr and My Market:** their terms forbid automated access.
- **Until then:** manual "Log a price", shipped in the polish round, plus Phase D receipts.
- See `docs/redesign/price-sources.md`.

## Not planned

- An iPhone widget: impossible in a PWA.
- Back Tap, or a home-screen shortcut: the user can add these any time.

Smaller follow-ups are in `docs/redesign/backlog.md`.
