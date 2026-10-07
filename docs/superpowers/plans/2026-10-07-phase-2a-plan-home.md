# Phase 2a: Plan and Home Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Plan tab (Upcoming, Month, Year, Budgets, Items) and the Home tab of the Tameio PWA, on a shared UI kit and an offline-first data layer, plus the one backend addition they need (the rule preview).

**Architecture:** `web/src/ui/` is a presentational kit with no data access. `web/src/data/` wraps TanStack Query with the Phase 1 encrypted Dexie cache (`useCachedQuery`) and the Phase 1 offline queue (`useAction`). `web/src/features/plan/` and `web/src/features/home/` hold the screens and their `hooks.ts`. Screens never call `api` directly. The backend gains `POST /api/v1/recurring/preview` in `app/api/recurring.py`. Work runs in five parallel streams (A kit and data, B backend, C Plan, D Items, E Home) merged in order.

**Tech Stack:** React 19, Vite 8, TypeScript 6 (`erasableSyntaxOnly`, `verbatimModuleSyntax`), Vitest 4 with Testing Library and jsdom, TanStack Query 5, Dexie 4 (+ `dexie-react-hooks`), openapi-fetch 0.17, react-router 7; FastAPI, pytest (xdist).

**Spec:** `docs/superpowers/specs/2026-10-07-phase-2a-plan-home-design.md` (the authority). Sibling specs that consume stream A: `2026-10-07-phase-2b-composer-design.md` §3.1, `2026-10-07-phase-2c-activity-bulk-design.md` §3, `2026-10-07-phase-2d-insights-settings-design.md` §3. Planning API spec: `2026-10-06-planning-redesign-design.md`.

## Global Constraints

- No new npm or Python dependencies. Tests use `fireEvent` from `@testing-library/react` (there is no `user-event`).
- TypeScript: `erasableSyntaxOnly` is on, so no `enum`, no namespaces and no constructor parameter properties. Use `as const` unions. `verbatimModuleSyntax` is on, so type-only imports use `import type`.
- Screens use the kit and their feature's `hooks.ts` only. They never import `api` (spec §3).
- `screens/Plan.tsx` and `screens/Home.tsx` become one-line re-exports of the feature screens.
- Money: EUR by default, formatted with `Intl.NumberFormat('en-IE')` ("€1,284.60"). Negatives use a real minus ("−€64.20"). "≈ " goes before estimates. Every figure uses tabular numerals.
- Dates: `YYYY-MM-DD` strings are parsed as local dates. They are formatted with `Intl.DateTimeFormat('en-GB')`: "Mon 26 Oct", "26 Oct", "Oct 2026", and "14:02" for times.
- Fonts: Sora for figures (`--font-display`), Plus Jakarta Sans for text (`--font-body`), JetBrains Mono for numbers in tables (`--font-num`). Use tokens from `web/src/styles/tokens.css` only. No hard-coded colours, except `#fff` on a solid tint.
- Tap targets are at least 44 px. Sheets and the tab bar respect the safe areas. Sheets slide in, and `prefers-reduced-motion` turns that off (the global rule in `index.css` already does this).
- Colour is never the only signal. Overdue also says "Overdue", over-pace also says "over pace", and flagged categories also say "above usual". Every interactive element has an accessible name.
- Width: 360–430 px is the target. On wider screens the content sits in a centred 480 px column.
- Copy is verbatim from the spec:
  - "Offline · updated HH:MM"
  - "No saved data yet. Connect once to load Plan."
  - "Nothing due in the next 30 days"
  - "Add a recurring item"
  - "All clear"
  - "Preview needs a connection"
  - "1 change couldn't be saved"
  - "Keep the expense"
  - "Delete the expense"
  - "Pause instead"
  - "Net (projected)"
  - "Trips & events: €X"
  - "Cash not yet logged: €X"
  - "Yearly and quarterly bills average €X/month"
- No database migration.
- Every new worktree runs `cd web && npm ci` before anything else (`web/node_modules` is not shared). Streams that run Python also need the venv link: `ln -s ../expenses-phase1/.venv-int .venv` from the worktree root.
- Speed mode: a task runs only its own test files (`cd web && npm test -- <files>`, or the single pytest file). The integration task runs everything.
- UI tasks begin with: load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.
- Don't rename any export listed under "Stream A exports" below. Sibling plans (2b, 2c, 2d) are written against these names. Adding to them is fine.

## Review Focus

1. **Amounts typed with a comma.** Greek iPhone keyboards type "86,40". Every amount field must send "86.40", and must never send NaN or reject the input. Pinned in A1 (`parseAmount`), C1 (Set amount), D2 (`formToBody`).
2. **FastAPI 422 errors.** A 422 `detail` is a list, not a string. The toast must read "Some values aren’t valid. Check them and try again." and never "[object Object]". Pinned in A6.
3. **Nulls and zeros from the API.** These must render without "€NaN" or a NaN-width bar: `budget: null`, `pct: null`, `pace: null`, `amount: null`, and a year whose figures are all 0. Pinned in C2 (amount null), C4 (all-zero year), C5 (budget null, pace null).
4. **Editing an item must not drop fields.** `PUT /recurring/{id}` replaces the whole row, including splits. A save must carry `splits`, `payer_mode`, `total_occurrences` and `contract_end_date` through unchanged. Pinned in D2 (`formToBody`), D4 (Item sheet PUT body).
5. **No false "All clear".** Home must not say "All clear" unless every attention source has data. Offline with nothing cached shows no attention section at all. Pinned in E2.

---

## Streams, branches and worktrees

| Stream | Branch | Starts from | Tasks |
|---|---|---|---|
| A: kit and data layer | `feat/2a-a` | `feat/phase2a-plan-home` | A1–A8 |
| B: backend rule preview | `feat/2a-b` | `feat/phase2a-plan-home` | B1 |
| C: Plan screens and the Entry sheet | `feat/2a-c` | `feat/2a-a` after A8 | C1–C6 (C1 is tagged `2a-c1`) |
| D: Items and the Item sheet | `feat/2a-d` | tag `2a-c1`, then `git merge feat/2a-b` | D1–D5 |
| E: Home | `feat/2a-e` | tag `2a-c1` | E1–E3 |
| Integration | `feat/phase2a-plan-home` | after all streams | INT |

Worktree setup, each from `/Users/giorgoscharitidis/expenses-p2`:

```bash
git worktree add ../expenses-2a-a -b feat/2a-a feat/phase2a-plan-home
git worktree add ../expenses-2a-b -b feat/2a-b feat/phase2a-plan-home
# after A8 is committed on feat/2a-a:
git worktree add ../expenses-2a-c -b feat/2a-c feat/2a-a
# after C1 is committed and tagged (git tag 2a-c1 in the C worktree) and B1 is committed:
git worktree add ../expenses-2a-d -b feat/2a-d 2a-c1 && (cd ../expenses-2a-d && git merge --no-edit feat/2a-b)
git worktree add ../expenses-2a-e -b feat/2a-e 2a-c1
```

**Why C1 gates D and E.** Upcoming (C), Home (E) and Items (D) all open the Entry sheet. Home also reads the plan hooks (month, upcoming, budgets, categories vs usual). C1 delivers `features/plan/hooks.ts`, `entryPatch.ts` and `EntrySheet.tsx`. D and E branch from that commit, so they import the real sheet and hooks rather than stubs. After C1, the folders are disjoint:
- C writes `features/plan/*` except `items/`.
- D writes `features/plan/items/*` and `router.tsx`.
- E writes `features/home/*` and `screens/Home.tsx`.

**Shared files and their single owner:**

| File | Owner task |
|---|---|
| `data/keys.ts` | A5 |
| `shell/AppShell.tsx`, `shell/AppShell.test.tsx` | A7 |
| `shell/TopBar.tsx`, `shell/shell.css` | A8 |
| `offline/queue.ts`, `offline/useQueue.ts` | A7 |
| `offline/db.ts` | A5 |
| `index.css` | A2 |
| `test/setup.ts` | unchanged |
| `screens/Plan.tsx` | C6 |
| `screens/Home.tsx` | E3 |
| `router.tsx` | D5 |
| `api/openapi.json`, `api/schema.d.ts` | B1 |

## File map

```
app/api/recurring.py                       B1  + RulePreviewIn, RulePreviewOut, POST /recurring/preview
tests/test_api_recurring_preview.py        B1
web/src/api/openapi.json, schema.d.ts      B1  regenerated
web/src/index.css                          A2  imports ui/ui.css
web/src/data/types.ts                      A1  schema aliases + narrowed types for untyped endpoints
web/src/ui/format.ts (+test)               A1  money, amount parsing, dates
web/src/ui/Money.tsx (+test)               A1
web/src/ui/ui.css                          A2  kit styles ported from mocks/components.css
web/src/ui/icons.tsx                       A2
web/src/ui/ListRow.tsx, Segmented.tsx, ProgressBar.tsx, Badge.tsx,
           OfflineBanner.tsx, EmptyState.tsx (+kit.test.tsx)   A2
web/src/ui/Sheet.tsx, Toast.tsx (+tests)   A3
web/src/data/http.ts, online.ts, pending.ts (+tests)          A4
web/src/test/fakeApi.ts (+test), fixtures.ts, render.tsx      A4
web/src/offline/db.ts                      A5  + cacheEntry()
web/src/data/keys.ts, cachedQuery.ts (+test)                  A5
web/src/ui/QueryView.tsx (+test)           A5
web/src/data/action.ts (+test)             A6
web/src/offline/queue.ts                   A7  + onQueueDrained()
web/src/offline/useQueue.ts (+test)        A7  + useFailedQueueRows(), dismissFailed()
web/src/data/queueBridge.ts (+test)        A7
web/src/shell/AppShell.tsx (+test)         A7  Toaster + queue bridge
web/src/data/reads.ts (+test)              A8  household, items, buckets, categories, transaction narrowing
web/src/shell/TopBar.tsx (+test), shell.css  A8  actions slot, 480 px column
web/src/features/plan/hooks.ts             C1  plan reads + useEntryActions
web/src/features/plan/entryPatch.ts (+test)  C1
web/src/features/plan/EntrySheet.tsx (+test), entry.css      C1
web/src/features/plan/plan.css             C2
web/src/features/plan/Upcoming.tsx (+test) C2
web/src/features/plan/Month.tsx (+test)    C3
web/src/features/plan/Year.tsx (+test)     C4
web/src/features/plan/Budgets.tsx (+test)  C5
web/src/features/plan/Plan.tsx (+test), web/src/screens/Plan.tsx   C6
web/src/features/plan/items/rule.ts (+test)                   D1
web/src/features/plan/items/form.ts, hooks.ts (+tests)        D2
web/src/features/plan/items/RulePicker.tsx (+test), items.css D3
web/src/features/plan/items/ItemSheet.tsx (+test)             D4
web/src/features/plan/items/Items.tsx (+test), web/src/router.tsx  D5
web/src/features/home/attention.ts (+test), hooks.ts          E1
web/src/features/home/NeedsAttention.tsx (+test), home.css    E2
web/src/features/home/Home.tsx, RecentActivity.tsx (+test), web/src/screens/Home.tsx   E3
```

## Stream A exports (the contract for C, D, E, 2b, 2c, 2d)

```ts
// ui/format.ts
formatMoney(amount: number, opts?: { currency?: string; signed?: boolean; whole?: boolean }): string
parseAmount(input: string): string | null | undefined        // "86,4" → "86.40"; "" → null; invalid → undefined
parseISODate(iso: string): Date; toISODate(d: Date): string; todayISO(now?: Date): string
addDays(iso: string, days: number): string; shiftMonth(month: string, by: number): string
monthsBetween(from: string, to: string): number
formatDayHeader(iso): string /* "Mon 26 Oct" */; formatShortDate(iso): string /* "26 Oct" */
formatMonthLabel(month: 'YYYY-MM'): string /* "Oct 2026" */; formatMonthShort(month): string /* "Oct" */
formatMonthName(month: number): string /* 12 → "December" */; formatTime(ms: number): string /* "14:02" */
ordinal(n: number): string /* 26 → "26th" */

// ui components (each in its own file under ui/)
<Money amount={number|null} currency? signed? whole? estimated? tone?: 'auto'|'none' nullText? className? />
<Sheet open onClose title closeOnBackdrop?=true footer? initialFocus?>{children}</Sheet>
<ListRow title subtitle? leading? trailing? badges? onClick? muted? ariaLabel? className? />; <List label?>{rows}</List>
<Segmented<T extends string> label options={readonly {value:T,label:string}[]} value onChange disabled? />
<ProgressBar value max label tone?: 'ok'|'warn'|'over' thin? />; progressTone(pct: number): ProgressTone
<Badge tone?: 'neutral'|'pos'|'neg'|'warn'|'acc' icon?>{text}</Badge>
<OfflineBanner updatedAt={ms} now? />; <EmptyState title body? icon? action?={label, to?|onClick?} />
<QueryView result={CachedQuery<T>} noDataText showBanner?=true loadingLabel?>{(data: T) => node}</QueryView>
toast(message: string, opts?: { action?: {label, onClick}; durationMs?: number; tone?: 'default'|'error' }): void
dismissToast(): void; useToast(): { show: typeof toast; dismiss: typeof dismissToast }; <Toaster />
icons: CheckIcon, ChevronLeftIcon, ChevronRightIcon, ChevronDownIcon, AlertIcon, ArrowInIcon, ArrowOutIcon,
       ClockIcon, CloudOffIcon, PauseIcon, PlusIcon, XIcon, LinkIcon

// data/
useCachedQuery<T>(key: QueryKey, fetcher: (signal: AbortSignal) => Promise<T>, opts?: { enabled?: boolean }): CachedQuery<T>
interface CachedQuery<T> { data: T | undefined; dataUpdatedAt: number; fromCache: boolean; isLoading: boolean;
  isError: boolean; offline: boolean; stale: boolean; noData: boolean; refetch(): void }
cacheKeyFor(householdId: string, key: QueryKey): string     // "q:<hh>:<JSON key>"
useAction<V = void, T = unknown>(spec: ActionSpec<V, T>): { run(vars: V): Promise<ActionResult<T>>; busy: boolean }
interface ActionSpec<V, T> { method: 'POST'|'PUT'|'PATCH'|'DELETE'; path: string | ((v: V) => string);
  body?: unknown | ((v: V) => unknown); optimistic?(qc: QueryClient, v: V): void; invalidates: readonly QueryKey[];
  pendingId?: string | ((v: V) => string | undefined); toastRejections?: boolean }
type ActionResult<T> = { status: 'done'; data: T } | { status: 'queued' } | { status: 'rejected'; code: number; detail: string }
keys, affects                                                // see A5 for the full tree
unwrap(p): Promise<data>; class ApiError { status; detail }; detailOf(error, status?): string
useOnline(): boolean; isOnline(): boolean
markPending(id); clearPending(); isPending(id): boolean; usePendingIds(): ReadonlySet<string>
installQueueBridge(qc: QueryClient): () => void
useHousehold(); useRecurringItems(); useBuckets(); useCategories(); memberName(m); toTransactionPage(raw)
types: EntryOut, UpcomingDayOut, MonthPictureOut, MonthRowOut, BucketMonthRowOut, YearOut, YearMonthOut,
       BudgetRowOut, PaceOut, RecurringItemOut, RecurringItemIn, EntryDoneIn, MatchOut, CategoryUsualOut,
       Member, Household, Bucket, Category, TransactionRow, TransactionPage, PaymentMethod, Direction, EntryStatus

// offline/
onQueueDrained(cb: (r: ReplayResult) => void): () => void          // queue.ts
useFailedQueueRows(): FailedQueueRow[]; dismissFailed(id: number): Promise<void>; interface FailedQueueRow { id; error; createdAt }
cacheEntry<T>(key: string): Promise<{ value: T; updatedAt: number } | undefined>   // db.ts

// test/ (tests only)
fakeApi(routes?: Routes): FakeApi   // typed from the OpenAPI schema; FakeApi { calls; callsTo(route); on(route, h); down(); up() }
reply(status, body?): Response; hang(): Promise<never>
renderWithProviders(ui, { route?, client? }): RenderResult & { client; router }
Providers({ client, children }); testQueryClient(); setOnline(online: boolean); resetTestEnv(): Promise<void>; TEST_IDENTITY
fixtures: entry, day, item, monthPicture, yearOut, yearMonth, budgetRow, pace, match, categoryUsual,
          member, household, txn, page, bucket, category, readRoutes()
```

---
## Stream A: UI kit and data layer

### Task A1: Types, formatting and `Money`

**Stream:** A. **Depends on:** nothing.

**Files:**
- Create: `web/src/data/types.ts`
- Create: `web/src/ui/format.ts`, `web/src/ui/format.test.ts`
- Create: `web/src/ui/Money.tsx`, `web/src/ui/Money.test.tsx`

**Interfaces:**
- Consumes: `components` from `web/src/api/schema.d.ts` (generated).
- Produces: every type in `data/types.ts`; every function in `ui/format.ts`; `Money` (see the "Stream A exports" block).

- [ ] **Step 0: Prepare the worktree**

Run: `cd /Users/giorgoscharitidis/expenses-2a-a/web && npm ci`
Expected: installs without errors.

- [ ] **Step 1: Write the failing tests**

`web/src/ui/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  addDays, formatDayHeader, formatMoney, formatMonthLabel, formatMonthName, formatMonthShort,
  formatShortDate, formatTime, monthsBetween, ordinal, parseAmount, shiftMonth, todayISO,
} from './format'

describe('formatMoney', () => {
  it('formats euros with a real minus and an optional plus', () => {
    expect(formatMoney(1284.6)).toBe('€1,284.60')
    expect(formatMoney(-64.2)).toBe('−€64.20')
    expect(formatMoney(1865, { signed: true })).toBe('+€1,865.00')
    expect(formatMoney(0, { signed: true })).toBe('€0.00')
    expect(formatMoney(1200, { whole: true })).toBe('€1,200')
    expect(formatMoney(-0.001)).toBe('€0.00')
  })
  it('handles other currencies and a bad code without throwing', () => {
    expect(formatMoney(12.5, { currency: 'USD' })).toBe('US$12.50')
    expect(formatMoney(12.5, { currency: 'eu' })).toBe('12.50 eu')
  })
})

describe('parseAmount', () => {
  it('accepts a comma or a dot and returns two decimals', () => {
    expect(parseAmount('86,40')).toBe('86.40')
    expect(parseAmount('86,4')).toBe('86.40')
    expect(parseAmount(' 1500 ')).toBe('1500.00')
    expect(parseAmount('€38.9')).toBe('38.90')
    expect(parseAmount('.5')).toBe('0.50')
  })
  it('blank is null; anything else is undefined', () => {
    expect(parseAmount('')).toBeNull()
    expect(parseAmount('   ')).toBeNull()
    expect(parseAmount('abc')).toBeUndefined()
    expect(parseAmount('1.234,50')).toBeUndefined()
    expect(parseAmount('-5')).toBeUndefined()
    expect(parseAmount('3.456')).toBeUndefined()
  })
})

describe('dates', () => {
  it('formats local dates the way the screens show them', () => {
    expect(formatDayHeader('2026-10-26')).toBe('Mon 26 Oct')
    expect(formatShortDate('2026-10-09')).toBe('9 Oct')
    expect(formatMonthLabel('2026-10')).toBe('Oct 2026')
    expect(formatMonthShort('2027-01')).toBe('Jan')
    expect(formatMonthName(12)).toBe('December')
    expect(formatTime(new Date(2026, 9, 7, 14, 2).getTime())).toBe('14:02')
  })
  it('does date arithmetic across month and year ends', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
    expect(monthsBetween('2026-10', '2027-09')).toBe(11)
    expect(monthsBetween('2026-10', '2025-11')).toBe(-11)
    expect(todayISO(new Date(2026, 9, 7, 23, 59))).toBe('2026-10-07')
  })
  it('ordinals', () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 26, 31].map(ordinal)).toEqual([
      '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '26th', '31st',
    ])
  })
})
```

`web/src/ui/Money.test.tsx`:

```tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { Money } from './Money'

afterEach(cleanup)

it('renders the amount with tabular numerals', () => {
  render(<Money amount={38.9} />)
  expect(screen.getByText('€38.90')).toHaveClass('ui-money')
})

it('marks estimates with ≈ and signs when asked', () => {
  render(<Money amount={1500} signed estimated />)
  expect(screen.getByText('≈ +€1,500.00')).toBeInTheDocument()
})

it('never shows NaN: null and non-finite amounts show the fallback text', () => {
  render(<><Money amount={null} /><Money amount={Number.NaN} nullText="variable" /></>)
  expect(screen.getByText('—')).toBeInTheDocument()
  expect(screen.getByText('variable')).toBeInTheDocument()
  expect(document.body.textContent).not.toContain('NaN')
})

it('tone auto tints positive amounts only', () => {
  render(<><Money amount={10} tone="auto" /><Money amount={-10} tone="auto" /></>)
  expect(screen.getByText('€10.00')).toHaveClass('ui-pos')
  expect(screen.getByText('−€10.00')).not.toHaveClass('ui-pos')
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/ui/format.test.ts src/ui/Money.test.tsx`
Expected: FAIL, "Failed to resolve import './format'" and "'./Money'".

- [ ] **Step 3: Write the implementation**

`web/src/data/types.ts`:

```ts
import type { components } from '../api/schema'

type S = components['schemas']

// Typed by the API's response models.
export type EntryOut = S['EntryOut']
export type UpcomingDayOut = S['UpcomingDayOut']
export type MonthPictureOut = S['MonthPictureOut']
export type MonthRowOut = S['MonthRowOut']
export type BucketMonthRowOut = S['BucketMonthRowOut']
export type YearOut = S['YearOut']
export type YearMonthOut = S['YearMonthOut']
export type BudgetRowOut = S['BudgetRowOut']
export type PaceOut = S['PaceOut']
export type RecurringItemOut = S['RecurringItemOut']
export type RecurringItemIn = S['RecurringItemIn']
export type EntryDoneIn = S['EntryDoneIn']
export type MatchOut = S['MatchOut']
export type CategoryUsualOut = S['CategoryUsualOut']

export type Direction = 'in' | 'out'
export type EntryStatus = 'expected' | 'done' | 'skipped'
export type PaymentMethod = 'card' | 'cash' | 'apple_pay' | 'transfer' | 'other'

// These endpoints return plain dicts (untyped in the schema); data/reads.ts narrows them to these shapes.
export interface Member {
  user_id: string
  role: string
  display_name: string | null
  username: string | null
  avatar_color: string | null
}
export interface Household { id: string; name: string; default_currency: string; members: Member[] }
export interface Bucket { id: string; name: string; kind: string; status: string; budget: number | null }
export interface Category { id: string; name: string; icon: string | null; color: string | null }
/** One row of GET /transactions. `keys.transactions.recent()` holds TransactionRow[] (newest first). */
export interface TransactionRow {
  id: string
  type: 'expense' | 'income'
  amount: number
  currency: string
  transaction_date: string
  merchant: string | null
  notes: string | null
  bucket_id: string | null
  category_id: string | null
  paid_by: string | null
  payment_method: string | null
  recurring_bill_id: string | null
}
export interface TransactionPage { total: number; page: number; page_size: number; items: TransactionRow[] }
```

`web/src/ui/format.ts`:

```ts
/** Money and date formatting shared by every screen. Pure: no data access. */

const MINUS = '−'
const moneyFormats = new Map<string, Intl.NumberFormat | null>()

function moneyFormat(currency: string, whole: boolean): Intl.NumberFormat | null {
  const id = `${currency}:${whole}`
  if (!moneyFormats.has(id)) {
    let f: Intl.NumberFormat | null = null
    try {
      f = new Intl.NumberFormat('en-IE', {
        style: 'currency',
        currency,
        minimumFractionDigits: whole ? 0 : 2,
        maximumFractionDigits: whole ? 0 : 2,
      })
    } catch {
      f = null // not an ISO 4217 code: fall back to "12.50 XYZ"
    }
    moneyFormats.set(id, f)
  }
  return moneyFormats.get(id) ?? null
}

export interface MoneyOptions { currency?: string; signed?: boolean; whole?: boolean }

/** "€1,284.60". Negatives get a real minus ("−€64.20"); `signed` adds "+" to positives. */
export function formatMoney(amount: number, { currency = 'EUR', signed = false, whole = false }: MoneyOptions = {}): string {
  const rounded = whole ? Math.round(amount) : Math.round(amount * 100) / 100
  const magnitude = Math.abs(rounded)
  const f = moneyFormat(currency, whole)
  const text = f ? f.format(magnitude) : `${magnitude.toFixed(whole ? 0 : 2)} ${currency}`
  if (rounded < 0) return `${MINUS}${text}`
  if (signed && rounded > 0) return `+${text}`
  return text
}

/**
 * Text typed into an amount field → the decimal string the API takes ("86,4" → "86.40").
 * Blank → null. Anything that isn't a non-negative amount with up to two decimals → undefined.
 */
export function parseAmount(input: string): string | null | undefined {
  const s = input.replace(/[\s€]/g, '').replace(',', '.')
  if (s === '') return null
  if (!/^(\d+(\.\d{0,2})?|\.\d{1,2})$/.test(s)) return undefined
  return Number(s).toFixed(2)
}

const pad = (n: number) => String(n).padStart(2, '0')

/** "2026-10-26" → local midnight (never UTC: a UTC parse shows the previous day west of Greenwich). */
export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}
export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
export function todayISO(now: Date = new Date()): string {
  return toISODate(now)
}
export function addDays(iso: string, days: number): string {
  const d = parseISODate(iso)
  d.setDate(d.getDate() + days)
  return toISODate(d)
}
/** "2026-12" + 1 → "2027-01". */
export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}
export function monthsBetween(from: string, to: string): number {
  const [fy, fm] = from.split('-').map(Number)
  const [ty, tm] = to.split('-').map(Number)
  return (ty - fy) * 12 + (tm - fm)
}

const dateFormat = (opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-GB', opts)
const DAY_HEADER = dateFormat({ weekday: 'short', day: 'numeric', month: 'short' })
const SHORT_DATE = dateFormat({ day: 'numeric', month: 'short' })
const MONTH_LABEL = dateFormat({ month: 'short', year: 'numeric' })
const MONTH_SHORT = dateFormat({ month: 'short' })
const MONTH_NAME = dateFormat({ month: 'long' })
const TIME = dateFormat({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

export const formatDayHeader = (iso: string): string => DAY_HEADER.format(parseISODate(iso))
export const formatShortDate = (iso: string): string => SHORT_DATE.format(parseISODate(iso))
export const formatMonthLabel = (month: string): string => MONTH_LABEL.format(parseISODate(`${month}-01`))
export const formatMonthShort = (month: string): string => MONTH_SHORT.format(parseISODate(`${month}-01`))
export const formatMonthName = (month: number): string => MONTH_NAME.format(new Date(2000, month - 1, 1))
export const formatTime = (ms: number): string => TIME.format(new Date(ms))

export function ordinal(n: number): string {
  const suffixes = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return `${n}${suffixes[(v - 20) % 10] ?? suffixes[v] ?? suffixes[0]}`
}
```

`web/src/ui/Money.tsx`:

```tsx
import { formatMoney } from './format'

export interface MoneyProps {
  amount: number | null
  currency?: string
  signed?: boolean
  whole?: boolean
  estimated?: boolean
  /** 'auto' tints positive amounts with --pos (income); the sign carries the meaning either way. */
  tone?: 'auto' | 'none'
  nullText?: string
  className?: string
}

export function Money({
  amount, currency = 'EUR', signed = false, whole = false, estimated = false, tone = 'none', nullText = '—', className,
}: MoneyProps) {
  if (amount === null || !Number.isFinite(amount)) {
    return <span className={['ui-money', className].filter(Boolean).join(' ')}>{nullText}</span>
  }
  const cls = ['ui-money', tone === 'auto' && amount > 0 ? 'ui-pos' : null, className].filter(Boolean).join(' ')
  return <span className={cls}>{`${estimated ? '≈ ' : ''}${formatMoney(amount, { currency, signed, whole })}`}</span>
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/ui/format.test.ts src/ui/Money.test.tsx && npm run typecheck`
Expected: PASS; typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/data/types.ts web/src/ui/format.ts web/src/ui/format.test.ts web/src/ui/Money.tsx web/src/ui/Money.test.tsx
git commit -m "feat(web): kit formatting (money, amounts, dates), Money and shared API types"
```

---

### Task A2: Kit styles and presentational components

**Stream:** A. **Depends on:** A1.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/ui/ui.css`, `web/src/ui/icons.tsx`
- Create: `web/src/ui/ListRow.tsx`, `web/src/ui/Segmented.tsx`, `web/src/ui/ProgressBar.tsx`, `web/src/ui/Badge.tsx`, `web/src/ui/OfflineBanner.tsx`, `web/src/ui/EmptyState.tsx`
- Create: `web/src/ui/kit.test.tsx`
- Modify: `web/src/index.css:1` (add the kit import)

**Interfaces:**
- Consumes: `formatShortDate`, `formatTime`, `toISODate` (A1).
- Produces: `ListRow`, `List`, `Segmented`, `SegmentedOption`, `ProgressBar`, `progressTone`, `ProgressTone`, `Badge`, `BadgeTone`, `OfflineBanner`, `EmptyState`, and the icons (exact props in the exports block). CSS classes for later tasks:
  - `ui-sec`, `ui-sec__title`
  - `ui-card`, `ui-hero`
  - `ui-list`, `ui-row`
  - `ui-ico ui-ico--{pos|neg|warn|acc|neutral}`
  - `ui-field`, `ui-field__label`, `ui-field__error`
  - `ui-input`, `ui-check`
  - `ui-figure`, `ui-num`, `ui-money`
  - `ui-pos`, `ui-neg`, `ui-warn`, `ui-muted`
  - `ui-eyebrow`, `ui-sr`
  - `ui-iconbtn`, `ui-iconbtn--bare`
  - `btn--sm`, `btn--ghost` (the base `.btn`, `.btn--primary`, `.btn--danger`, `.btn--block` and `.btn--lg` stay in `shell/shell.css`)

- [ ] **Step 1: Write the failing tests**

`web/src/ui/kit.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import { Badge } from './Badge'
import { EmptyState } from './EmptyState'
import { List, ListRow } from './ListRow'
import { OfflineBanner } from './OfflineBanner'
import { ProgressBar, progressTone } from './ProgressBar'
import { Segmented } from './Segmented'

afterEach(cleanup)

it('ListRow is a button only when it has onClick', () => {
  const onClick = vi.fn()
  render(
    <List label="Bills">
      <ListRow title="Cosmote" subtitle="Out" trailing="€38.90" onClick={onClick} />
      <ListRow title="Salary" />
    </List>,
  )
  fireEvent.click(screen.getByRole('button', { name: /Cosmote/ }))
  expect(onClick).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: /Salary/ })).toBeNull()
  expect(screen.getByRole('group', { name: 'Bills' })).toBeInTheDocument()
})

it('Segmented marks the current option and reports changes', () => {
  const onChange = vi.fn()
  const opts = [{ value: 'a', label: 'Upcoming' }, { value: 'b', label: 'Month' }] as const
  render(<Segmented label="View" options={opts} value="a" onChange={onChange} />)
  expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(screen.getByRole('button', { name: 'Month' }))
  expect(onChange).toHaveBeenCalledWith('b')
})

it('ProgressBar tone changes at 80% and 100%, and is safe with a zero max', () => {
  expect([0, 79.9, 80, 99.9, 100, 140].map(progressTone)).toEqual(['ok', 'ok', 'warn', 'warn', 'over', 'over'])
  render(<><ProgressBar value={1050} max={1200} label="Day to day" /><ProgressBar value={50} max={0} label="Empty" /></>)
  const bar = screen.getByRole('progressbar', { name: 'Day to day' })
  expect(bar).toHaveAttribute('data-tone', 'warn')
  expect(bar).toHaveAttribute('aria-valuenow', '88')
  const empty = screen.getByRole('progressbar', { name: 'Empty' })
  expect(empty).toHaveAttribute('aria-valuenow', '0')
  expect((empty.firstChild as HTMLElement).style.width).toBe('0%')
})

it('Badge renders its tone class', () => {
  render(<Badge tone="warn">over pace</Badge>)
  expect(screen.getByText('over pace')).toHaveClass('ui-badge', 'ui-badge--warn')
})

it('OfflineBanner shows the time today and the date otherwise', () => {
  const now = new Date(2026, 9, 7, 18, 0).getTime()
  const { rerender } = render(<OfflineBanner updatedAt={new Date(2026, 9, 7, 14, 2).getTime()} now={now} />)
  expect(screen.getByRole('status')).toHaveTextContent('Offline · updated 14:02')
  rerender(<OfflineBanner updatedAt={new Date(2026, 9, 5, 9, 30).getTime()} now={now} />)
  expect(screen.getByRole('status')).toHaveTextContent('Offline · updated 5 Oct 09:30')
})

it('EmptyState renders a link action or a button action', () => {
  const onClick = vi.fn()
  render(
    <MemoryRouter>
      <EmptyState title="Nothing due in the next 30 days" action={{ label: 'Add a recurring item', to: '/plan/items?new=1' }} />
      <EmptyState title="Couldn’t load this." action={{ label: 'Try again', onClick }} />
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: 'Add a recurring item' })).toHaveAttribute('href', '/plan/items?new=1')
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(onClick).toHaveBeenCalledOnce()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/ui/kit.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the implementation**

`web/src/ui/icons.tsx` (Lucide paths, inlined like `shell/icons.tsx`):

```tsx
import type { ReactNode } from 'react'

function Icon({ children, strokeWidth = 1.9 }: { children: ReactNode; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" focusable="false" className="ui-icon">
      {children}
    </svg>
  )
}

export const CheckIcon = () => <Icon strokeWidth={2.4}><path d="M20 6 9 17l-5-5" /></Icon>
export const ChevronLeftIcon = () => <Icon><path d="m15 18-6-6 6-6" /></Icon>
export const ChevronRightIcon = () => <Icon><path d="m9 18 6-6-6-6" /></Icon>
export const ChevronDownIcon = () => <Icon><path d="m6 9 6 6 6-6" /></Icon>
export const AlertIcon = () => (
  <Icon><circle cx="12" cy="12" r="10" /><line x1="12" x2="12" y1="8" y2="12" /><line x1="12" x2="12.01" y1="16" y2="16" /></Icon>
)
export const ArrowInIcon = () => <Icon><path d="M17 7 7 17" /><path d="M17 17H7V7" /></Icon>
export const ArrowOutIcon = () => <Icon><path d="M7 7h10v10" /><path d="M7 17 17 7" /></Icon>
export const ClockIcon = () => <Icon><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></Icon>
export const CloudOffIcon = () => (
  <Icon>
    <path d="m2 2 20 20" /><path d="M5.782 5.782A7 7 0 0 0 9 19h8.5a4.5 4.5 0 0 0 1.307-.193" />
    <path d="M21.532 16.5A4.5 4.5 0 0 0 17.5 10h-1.79A7.008 7.008 0 0 0 10 5.07" />
  </Icon>
)
export const PauseIcon = () => (
  <Icon><rect x="14" y="4" width="4" height="16" rx="1" /><rect x="6" y="4" width="4" height="16" rx="1" /></Icon>
)
export const PlusIcon = () => <Icon strokeWidth={2.2}><path d="M5 12h14" /><path d="M12 5v14" /></Icon>
export const XIcon = () => <Icon strokeWidth={2}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></Icon>
export const LinkIcon = () => (
  <Icon>
    <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
    <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
  </Icon>
)
```

`web/src/ui/ListRow.tsx` (the full code; the other presentational components follow the same pattern):

```tsx
import type { ReactNode } from 'react'

export interface ListRowProps {
  title: ReactNode
  subtitle?: ReactNode
  /** An icon tile or avatar on the left. */
  leading?: ReactNode
  /** Usually a <Money>; right-aligned. */
  trailing?: ReactNode
  badges?: ReactNode
  /** Makes the row a <button>; without it the row is static. */
  onClick?: () => void
  /** Greyed (paused items). Pair it with a text badge: colour is never the only signal. */
  muted?: boolean
  ariaLabel?: string
  className?: string
}

export function ListRow({ title, subtitle, leading, trailing, badges, onClick, muted, ariaLabel, className }: ListRowProps) {
  const cls = ['ui-row', muted ? 'ui-row--muted' : null, className].filter(Boolean).join(' ')
  const inner = (
    <>
      {leading && <span className="ui-row__lead">{leading}</span>}
      <span className="ui-row__main">
        <span className="ui-row__title">{title}</span>
        {subtitle && <span className="ui-row__sub">{subtitle}</span>}
        {badges && <span className="ui-row__badges">{badges}</span>}
      </span>
      {trailing !== undefined && trailing !== null && <span className="ui-row__end">{trailing}</span>}
    </>
  )
  return onClick ? (
    <button type="button" className={cls} onClick={onClick} aria-label={ariaLabel}>{inner}</button>
  ) : (
    <div className={cls}>{inner}</div>
  )
}

/** The grouped-list surface (mock `.list`). `label` names it for screen readers. */
export function List({ children, label }: { children: ReactNode; label?: string }) {
  return <div className="ui-list" role={label ? 'group' : undefined} aria-label={label}>{children}</div>
}
```

`web/src/ui/Segmented.tsx`:

```tsx
export interface SegmentedOption<T extends string> { value: T; label: string }
export interface SegmentedProps<T extends string> {
  /** Accessible name of the group, e.g. "Plan view". */
  label: string
  options: readonly SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  disabled?: boolean
}

export function Segmented<T extends string>({ label, options, value, onChange, disabled }: SegmentedProps<T>) {
  return (
    <div className="ui-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className="ui-seg__opt" aria-pressed={o.value === value}
          disabled={disabled} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
```

`web/src/ui/ProgressBar.tsx`:

```tsx
export type ProgressTone = 'ok' | 'warn' | 'over'

/** Spec §4.4: the tint changes at 80% and at 100%. */
export function progressTone(pct: number): ProgressTone {
  return pct >= 100 ? 'over' : pct >= 80 ? 'warn' : 'ok'
}

export interface ProgressBarProps { value: number; max: number; label: string; tone?: ProgressTone; thin?: boolean }

export function ProgressBar({ value, max, label, tone, thin }: ProgressBarProps) {
  const pct = max > 0 && Number.isFinite(value) ? (value / max) * 100 : 0
  const width = Math.min(100, Math.max(0, pct))
  return (
    <div className={thin ? 'ui-bar ui-bar--thin' : 'ui-bar'} role="progressbar" aria-label={label}
      aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} data-tone={tone ?? progressTone(pct)}>
      <span className="ui-bar__fill" style={{ width: `${width}%` }} />
    </div>
  )
}
```

The remaining components, exactly:

- `web/src/ui/Badge.tsx`: `export type BadgeTone = 'neutral' | 'pos' | 'neg' | 'warn' | 'acc'`. `export function Badge({ tone = 'neutral', icon, children }: { tone?: BadgeTone; icon?: ReactNode; children: ReactNode })` renders `<span className={`ui-badge ui-badge--${tone}`}>{icon}{children}</span>`.
- `web/src/ui/OfflineBanner.tsx`: `export function OfflineBanner({ updatedAt, now = Date.now() }: { updatedAt: number; now?: number })`.
  - It renders `<p className="ui-banner" role="status"><CloudOffIcon />Offline · updated {when}</p>`.
  - `when` is `formatTime(updatedAt)` when `updatedAt` falls on the same local day as `now`.
  - Otherwise `when` is `` `${formatShortDate(toISODate(new Date(updatedAt)))} ${formatTime(updatedAt)}` ``.
  - When `updatedAt` is `0`, `when` is `"never"`.
- `web/src/ui/EmptyState.tsx`: `export interface EmptyStateProps { title: string; body?: string; icon?: ReactNode; action?: { label: string; to?: string; onClick?: () => void } }`.
  - It renders `<div className="ui-empty">`, which contains, in order:
    - `{icon}`;
    - `<p className="ui-empty__title">{title}</p>`;
    - the body as `<p className="ui-empty__body">`;
    - the action.
  - The action is a react-router `<Link className="btn btn--primary" to={to}>` when `to` is set. Otherwise it is `<button type="button" className="btn" onClick={onClick}>`.

`web/src/ui/ui.css`:

```css
/* Vault UI kit, ported from docs/redesign/mocks/components.css. Tokens from styles/tokens.css only.
   Base .btn/.btn--primary/.btn--danger/.btn--block/.btn--lg live in shell/shell.css. */

/* ---------------- Type ---------------- */
.ui-figure { font-family: var(--font-display); font-weight: var(--display-weight); font-variant-numeric: tabular-nums; letter-spacing: -.03em; line-height: 1.05; }
.ui-num, .ui-money { font-family: var(--font-num); font-variant-numeric: tabular-nums; font-weight: var(--num-weight); letter-spacing: -.01em; white-space: nowrap; }
.ui-figure.ui-money { font-family: var(--font-display); font-weight: var(--display-weight); }
.ui-eyebrow { margin: 0; font-size: 11.5px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.ui-pos { color: var(--pos); } .ui-neg { color: var(--neg); } .ui-warn { color: var(--warn); } .ui-muted { color: var(--muted); }
.ui-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
.ui-icon { width: 18px; height: 18px; flex: none; }

/* ---------------- Sections and surfaces ---------------- */
.ui-sec { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin: 20px 0 8px; }
.ui-sec__title { margin: 0; display: flex; align-items: center; gap: 8px; font-weight: 650; font-size: 17px; letter-spacing: -.01em; }
.ui-sec a { min-height: 44px; display: inline-flex; align-items: center; font-size: 13.5px; font-weight: 600; color: var(--accent); text-decoration: none; }
.ui-card { background: var(--surface); border: var(--card-border); border-radius: var(--r-lg); box-shadow: var(--shadow); padding: 16px; }
.ui-hero { background: var(--hero-bg); color: var(--hero-ink); border-radius: var(--r-lg); padding: 18px; }

/* ---------------- Buttons (additions to shell .btn) ---------------- */
.btn--sm { min-height: 44px; padding: 0 14px; font-size: 14px; border-radius: var(--r-sm); }
.btn--ghost { background: transparent; color: var(--accent); }
.btn:disabled { opacity: .5; cursor: default; }
.ui-iconbtn {
  width: 44px; height: 44px; flex: none; padding: 0; border: 0; border-radius: 50%;
  display: grid; place-items: center; background: var(--surface-2); color: var(--ink); cursor: pointer;
  -webkit-tap-highlight-color: transparent; touch-action: manipulation;
}
.ui-iconbtn .ui-icon { width: 20px; height: 20px; }
.ui-iconbtn--bare { background: transparent; }
.ui-iconbtn:disabled { opacity: .35; cursor: default; }

/* ---------------- Grouped list ---------------- */
.ui-list { background: var(--surface); border: var(--card-border); border-radius: var(--r-lg); box-shadow: var(--shadow); overflow: hidden; }
.ui-row {
  position: relative; display: flex; align-items: center; gap: 12px; width: 100%; min-height: 56px; padding: 11px 14px;
  border: 0; background: transparent; color: inherit; font: inherit; text-align: left;
}
button.ui-row { cursor: pointer; -webkit-tap-highlight-color: transparent; touch-action: manipulation; }
button.ui-row:active { background: var(--surface-2); }
.ui-list > .ui-row + .ui-row::before { content: ""; position: absolute; top: 0; left: 14px; right: 0; height: 1px; background: var(--line); }
.ui-row--muted { opacity: .55; }
.ui-row__lead { flex: none; display: grid; }
.ui-row__main { flex: 1; min-width: 0; display: block; }
.ui-row__title { display: block; font-weight: 600; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ui-row__sub { display: block; font-size: 12.5px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ui-row__badges { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.ui-row__end { flex: none; text-align: right; font-size: 15px; }

/* Icon tiles */
.ui-ico {
  width: 36px; height: 36px; flex: none; border-radius: var(--r-sm); display: grid; place-items: center;
  background: color-mix(in srgb, var(--tint, var(--c6)) 16%, var(--surface)); color: var(--tint, var(--c6));
}
.ui-ico .ui-icon { width: 19px; height: 19px; }
.ui-ico--pos { --tint: var(--pos); } .ui-ico--neg { --tint: var(--neg); } .ui-ico--warn { --tint: var(--warn); }
.ui-ico--acc { --tint: var(--accent); } .ui-ico--neutral { --tint: var(--c6); }

/* ---------------- Segmented ---------------- */
.ui-seg { display: flex; flex-wrap: wrap; padding: 3px; gap: 2px; background: var(--surface-2); border-radius: var(--r-md); }
.ui-seg__opt {
  flex: 1 1 auto; min-height: 38px; padding: 0 10px; border: 0; border-radius: calc(var(--r-md) - 3px);
  background: transparent; color: var(--muted); font-size: 13.5px; font-weight: 650; white-space: nowrap; cursor: pointer;
  -webkit-tap-highlight-color: transparent; touch-action: manipulation;
}
.ui-seg__opt[aria-pressed="true"] { background: var(--surface); color: var(--ink); box-shadow: 0 1px 3px rgba(0,0,0,.12); }
.ui-seg__opt:disabled { cursor: default; opacity: .6; }

/* ---------------- Progress ---------------- */
.ui-bar { height: 8px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
.ui-bar--thin { height: 5px; }
.ui-bar__fill { display: block; height: 100%; border-radius: inherit; background: var(--accent); transition: width .3s ease; }
.ui-bar[data-tone="warn"] .ui-bar__fill { background: var(--warn); }
.ui-bar[data-tone="over"] .ui-bar__fill { background: var(--neg); }

/* ---------------- Badges ---------------- */
.ui-badge {
  display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 8px; border-radius: var(--r-pill);
  font-size: 11.5px; font-weight: 700; white-space: nowrap; background: var(--surface-2); color: var(--ink-2);
}
.ui-badge .ui-icon { width: 12px; height: 12px; }
.ui-badge--pos { background: var(--pos-soft); color: var(--pos); }
.ui-badge--neg { background: var(--neg-soft); color: var(--neg); }
.ui-badge--warn { background: var(--warn-soft); color: var(--warn); }
.ui-badge--acc { background: var(--accent-soft); color: var(--accent); }

/* ---------------- Fields ---------------- */
.ui-field { display: flex; flex-direction: column; gap: 6px; }
.ui-field__label { font-size: 12.5px; font-weight: 600; color: var(--muted); }
.ui-field__error { margin: 0; font-size: 12.5px; font-weight: 600; color: var(--neg); }
/* 16px stops iOS zooming into the field on focus. */
.ui-input {
  width: 100%; min-height: 46px; padding: 0 14px; border: 1px solid var(--line); border-radius: var(--r-md);
  background: var(--surface); color: var(--ink); font: inherit; font-size: 16px;
}
.ui-input[aria-invalid="true"] { border-color: var(--neg); }
textarea.ui-input { min-height: 88px; padding: 10px 14px; resize: vertical; }
.ui-check { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; font-weight: 600; }
.ui-check input { width: 22px; height: 22px; flex: none; accent-color: var(--accent); }

/* ---------------- States ---------------- */
.ui-banner {
  margin: 0 0 12px; display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: var(--r-md);
  background: var(--warn-soft); color: var(--warn); font-size: 13px; font-weight: 650;
}
.ui-banner .ui-icon { width: 16px; height: 16px; }
.ui-empty { display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 40px 16px; text-align: center; color: var(--muted); }
.ui-empty__title { margin: 0; color: var(--ink-2); font-weight: 650; }
.ui-empty__body { margin: 0; font-size: 14px; }
.ui-skeleton {
  height: 120px; border-radius: var(--r-lg);
  background: linear-gradient(90deg, var(--surface) 0%, var(--surface-2) 50%, var(--surface) 100%);
  background-size: 200% 100%; animation: ui-shimmer 1.4s linear infinite;
}

/* ---------------- Sheet (ui/Sheet.tsx) ---------------- */
.ui-sheet-layer { position: fixed; inset: 0; z-index: 20; display: flex; align-items: flex-end; justify-content: center; }
.ui-sheet-scrim { position: absolute; inset: 0; background: var(--scrim); animation: ui-fade .2s ease; }
.ui-sheet {
  position: relative; width: 100%; max-width: 480px; max-height: 88dvh; display: flex; flex-direction: column;
  background: var(--surface); color: var(--ink); border-radius: 26px 26px 0 0; box-shadow: var(--shadow-sheet);
  padding: 8px calc(env(safe-area-inset-right) + 16px) calc(env(safe-area-inset-bottom) + 16px) calc(env(safe-area-inset-left) + 16px);
  outline: none; overscroll-behavior: contain; animation: ui-sheet-in .32s cubic-bezier(.32, .72, 0, 1);
}
.ui-sheet__grab { width: 38px; height: 5px; flex: none; border-radius: 3px; background: var(--line); margin: 0 auto 6px; }
.ui-sheet__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-bottom: 8px; }
.ui-sheet__title { margin: 0; min-width: 0; font-size: 20px; font-weight: 650; letter-spacing: -.01em; overflow-wrap: anywhere; }
.ui-sheet__body { min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; overscroll-behavior: contain; }
.ui-sheet__foot { flex: none; display: flex; flex-direction: column; gap: 8px; padding-top: 12px; }

/* ---------------- Toast (ui/Toast.tsx) ---------------- */
.ui-toast-region {
  position: fixed; left: 0; right: 0; z-index: 30; max-width: 480px; margin: 0 auto; padding: 0 16px;
  bottom: calc(env(safe-area-inset-bottom) + 96px); pointer-events: none;
}
.ui-toast {
  pointer-events: auto; display: flex; align-items: center; gap: 12px; padding: 8px 8px 8px 14px; min-height: 48px;
  border-radius: var(--r-lg); background: var(--ink); color: var(--bg); box-shadow: 0 10px 30px rgba(0,0,0,.25);
  font-size: 14px; font-weight: 550; animation: ui-toast-in .22s ease;
}
.ui-toast__text { flex: 1; min-width: 0; padding: 6px 0; }
.ui-toast__action {
  flex: none; min-height: 44px; padding: 0 10px; border: 0; background: transparent; color: inherit;
  font-weight: 750; text-decoration: underline; text-underline-offset: 3px; cursor: pointer;
}
.ui-toast--error .ui-icon { color: var(--neg); }

@keyframes ui-sheet-in { from { transform: translateY(100%); } to { transform: none; } }
@keyframes ui-fade { from { opacity: 0; } }
@keyframes ui-toast-in { from { opacity: 0; transform: translateY(8px); } }
@keyframes ui-shimmer { to { background-position: -200% 0; } }
```

`web/src/index.css`: add a second line after `@import './styles/tokens.css';`:

```css
@import './ui/ui.css';
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/ui/kit.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui web/src/index.css
git commit -m "feat(web): Vault kit styles, icons, ListRow, Segmented, ProgressBar, Badge, OfflineBanner, EmptyState"
```

---

### Task A3: `Sheet` and `Toast`

**Stream:** A. **Depends on:** A2.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/ui/Sheet.tsx`, `web/src/ui/Sheet.test.tsx`
- Create: `web/src/ui/Toast.tsx`, `web/src/ui/Toast.test.tsx`

**Interfaces:**
- Consumes: `XIcon`, `AlertIcon` (A2).
- Produces:
  - `Sheet(props: SheetProps)`, where `SheetProps = { open: boolean; onClose(): void; title: string; children: ReactNode; footer?: ReactNode; closeOnBackdrop?: boolean; initialFocus?: RefObject<HTMLElement | null> }`;
  - `toast(message, opts?)`, `dismissToast()`, `useToast()`, `Toaster`;
  - `ToastOptions = { action?: { label: string; onClick(): void }; durationMs?: number; tone?: 'default' | 'error' }`.
  - The default `durationMs` is 4000. A new toast replaces the one on screen. `toast()` works outside React, and `useAction` calls it.

The Sheet is a portal `<div role="dialog" aria-modal="true">`, not a `<dialog>`. jsdom (the test environment) has no `HTMLDialogElement.showModal`, and a custom layer lets us own the slide and the safe-area padding. Focus is trapped by hand. Only the topmost open sheet reacts to Esc and Tab.

- [ ] **Step 1: Write the failing tests**

`web/src/ui/Sheet.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { Sheet } from './Sheet'

afterEach(cleanup)

function Harness({ closeOnBackdrop, onClose = () => {} }: { closeOnBackdrop?: boolean; onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      <Sheet open={open} title="Cosmote" closeOnBackdrop={closeOnBackdrop}
        onClose={() => { onClose(); setOpen(false) }}>
        <button type="button">First</button>
        <button type="button">Last</button>
      </Sheet>
    </>
  )
}

it('opens as a named modal dialog and moves focus inside', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  const dialog = screen.getByRole('dialog', { name: 'Cosmote' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(dialog.contains(document.activeElement)).toBe(true)
})

it('Esc closes and focus returns to the opener', () => {
  render(<Harness />)
  const opener = screen.getByRole('button', { name: 'Open' })
  opener.focus()
  fireEvent.click(opener)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(document.activeElement).toBe(opener)
})

it('a backdrop tap closes unless closeOnBackdrop is false', () => {
  const onClose = vi.fn()
  const { unmount } = render(<Harness onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  fireEvent.click(screen.getByTestId('sheet-backdrop'))
  expect(onClose).toHaveBeenCalledOnce()
  unmount()
  render(<Harness closeOnBackdrop={false} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  fireEvent.click(screen.getByTestId('sheet-backdrop'))
  expect(onClose).toHaveBeenCalledOnce()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
})

it('traps Tab inside the sheet', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('button', { name: 'Open' }))
  const last = screen.getByRole('button', { name: 'Last' })
  last.focus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }))
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)
})
```

`web/src/ui/Toast.test.tsx`:

```tsx
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { dismissToast, toast, Toaster } from './Toast'

afterEach(() => { cleanup(); dismissToast(); vi.useRealTimers() })

it('shows a toast in a polite live region; a new one replaces it', () => {
  render(<Toaster />)
  act(() => toast('Saved'))
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  act(() => toast('Skipped'))
  expect(screen.getByRole('status')).toHaveTextContent('Skipped')
  expect(screen.getByRole('status')).not.toHaveTextContent('Saved')
})

it('runs the action and dismisses', () => {
  const onClick = vi.fn()
  render(<Toaster />)
  act(() => toast('Deleted', { action: { label: 'Undo', onClick } }))
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  expect(onClick).toHaveBeenCalledOnce()
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('dismisses itself after durationMs', () => {
  vi.useFakeTimers()
  render(<Toaster />)
  act(() => toast('Moved 3 payments', { durationMs: 10_000 }))
  act(() => { vi.advanceTimersByTime(9_999) })
  expect(screen.getByRole('status')).toHaveTextContent('Moved 3 payments')
  act(() => { vi.advanceTimersByTime(1) })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/ui/Sheet.test.tsx src/ui/Toast.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the implementation**

`web/src/ui/Sheet.tsx`:

```tsx
import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { XIcon } from './icons'

export interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** Pinned below the scrolling body (primary actions). */
  footer?: ReactNode
  /** false for sheets that show something the user must acknowledge (2d's backup codes). */
  closeOnBackdrop?: boolean
  /** Where focus lands on open; defaults to the first focusable element (the Close button). */
  initialFocus?: RefObject<HTMLElement | null>
}

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
const focusables = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))

/** Open sheets, innermost last: only the top one handles Esc and Tab. */
const stack: HTMLElement[] = []

export function Sheet({ open, onClose, title, children, footer, closeOnBackdrop = true, initialFocus }: SheetProps) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose })

  useEffect(() => {
    if (!open || !panel.current) return
    const node = panel.current
    const opener = document.activeElement as HTMLElement | null
    stack.push(node)
    ;(initialFocus?.current ?? focusables(node)[0] ?? node).focus()
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== node) return
      if (e.key === 'Escape') {
        e.preventDefault()
        onCloseRef.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = focusables(node)
      if (items.length === 0) {
        e.preventDefault()
        node.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && (document.activeElement === first || !node.contains(document.activeElement))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (document.activeElement === last || !node.contains(document.activeElement))) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden' // the page behind must not scroll under the sheet
    return () => {
      document.removeEventListener('keydown', onKey)
      stack.splice(stack.indexOf(node), 1)
      document.body.style.overflow = overflow
      opener?.focus?.()
    }
  }, [open, initialFocus])

  if (!open) return null
  return createPortal(
    <div className="ui-sheet-layer">
      <div className="ui-sheet-scrim" aria-hidden="true" data-testid="sheet-backdrop"
        onClick={closeOnBackdrop ? onClose : undefined} />
      <div ref={panel} className="ui-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="ui-sheet__grab" aria-hidden="true" />
        <div className="ui-sheet__head">
          <h2 id={titleId} className="ui-sheet__title">{title}</h2>
          <button type="button" className="ui-iconbtn" aria-label="Close" onClick={onClose}><XIcon /></button>
        </div>
        <div className="ui-sheet__body">{children}</div>
        {footer && <div className="ui-sheet__foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
```

`web/src/ui/Toast.tsx`:

```tsx
import { useSyncExternalStore } from 'react'
import { AlertIcon } from './icons'

export interface ToastAction { label: string; onClick: () => void }
export interface ToastOptions { action?: ToastAction; durationMs?: number; tone?: 'default' | 'error' }
interface Shown extends ToastOptions { id: number; message: string }

const DEFAULT_MS = 4000
let current: Shown | null = null
let seq = 0
let timer: ReturnType<typeof setTimeout> | undefined
const subs = new Set<() => void>()
const emit = () => subs.forEach((cb) => cb())
const subscribe = (cb: () => void) => {
  subs.add(cb)
  return () => { subs.delete(cb) }
}

/** Show a toast; it replaces the one on screen. Callable outside React (useAction uses it). */
export function toast(message: string, opts: ToastOptions = {}): void {
  clearTimeout(timer)
  current = { ...opts, id: ++seq, message }
  emit()
  timer = setTimeout(dismissToast, opts.durationMs ?? DEFAULT_MS)
}

export function dismissToast(): void {
  clearTimeout(timer)
  if (!current) return
  current = null
  emit()
}

const handle = { show: toast, dismiss: dismissToast }
/** For components that prefer a hook; the functions are module-level and stable. */
export function useToast(): typeof handle {
  return handle
}

/** Rendered once by AppShell (and by renderWithProviders in tests). */
export function Toaster() {
  const t = useSyncExternalStore(subscribe, () => current, () => null)
  return (
    <div className="ui-toast-region" role="status" aria-live="polite">
      {t && (
        <div key={t.id} className={t.tone === 'error' ? 'ui-toast ui-toast--error' : 'ui-toast'}>
          {t.tone === 'error' && <AlertIcon />}
          <span className="ui-toast__text">{t.message}</span>
          {t.action && (
            <button type="button" className="ui-toast__action"
              onClick={() => { t.action?.onClick(); dismissToast() }}>
              {t.action.label}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/ui/Sheet.test.tsx src/ui/Toast.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/ui/Sheet.tsx web/src/ui/Sheet.test.tsx web/src/ui/Toast.tsx web/src/ui/Toast.test.tsx
git commit -m "feat(web): bottom Sheet with focus trap and Toast store with actions"
```

---
### Task A4: Data primitives and the test kit (typed fake API, fixtures, render helpers)

**Stream:** A. **Depends on:** A3.

**Files:**
- Create: `web/src/data/http.ts`, `web/src/data/http.test.ts`
- Create: `web/src/data/online.ts`
- Create: `web/src/data/pending.ts`, `web/src/data/pending.test.ts`
- Create: `web/src/test/fakeApi.ts`, `web/src/test/fakeApi.test.ts`
- Create: `web/src/test/fixtures.ts`
- Create: `web/src/test/render.tsx`

**Interfaces:**
- Consumes: `api` (`api/client.ts`), `paths` (`api/schema.d.ts`), `wipe` (`offline/db.ts`), `setIdentity`/`Identity` (`offline/identity.ts`), `Toaster`/`dismissToast` (A3), the types (A1).
- Produces:
  - `ApiError`, `unwrap`, `detailOf`, `useOnline`, `isOnline`;
  - `markPending`, `clearPending`, `isPending`, `usePendingIds`;
  - `fakeApi`, `reply`, `hang`, `Route`, `Routes`, `Reply`, `FakeApi`, `FakeRequest`, `FakeCall`;
  - every fixture factory, plus `readRoutes()`;
  - `renderWithProviders`, `Providers`, `testQueryClient`, `setOnline`, `resetTestEnv`, `TEST_IDENTITY`.

`fakeApi` is the "typed fake fetch built from the OpenAPI types" that spec §9 and 2b §9 refer to. Each route key is `"METHOD /path/template"` as the schema spells it. A handler's return type is that route's success body, or a `Response` for errors.

- [ ] **Step 1: Write the failing tests**

`web/src/data/http.test.ts`:

```ts
import { afterEach, expect, it } from 'vitest'
import { api } from '../api/client'
import { fakeApi, reply } from '../test/fakeApi'
import { resetTestEnv } from '../test/render'
import { ApiError, detailOf, unwrap } from './http'

afterEach(resetTestEnv)

it('unwrap returns the data on 2xx', async () => {
  fakeApi({ 'GET /api/v1/plan/year': () => ({ months: [], infrequent_monthly_average: 0, estimated: false }) })
  await expect(unwrap(api.GET('/api/v1/plan/year'))).resolves.toEqual({ months: [], infrequent_monthly_average: 0, estimated: false })
})

it('unwrap throws ApiError with the server detail otherwise', async () => {
  fakeApi({ 'GET /api/v1/plan/month': () => reply(400, { detail: 'month must be YYYY-MM.' }) })
  const err = await unwrap(api.GET('/api/v1/plan/month', { params: { query: { month: 'x' } } })).catch((e: unknown) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect(err).toMatchObject({ status: 400, detail: 'month must be YYYY-MM.' })
})

it('detailOf reads strings, turns 422 lists into a readable message and falls back by status', () => {
  expect(detailOf({ detail: 'Already paid.' }, 409)).toBe('Already paid.')
  expect(detailOf({ detail: [{ loc: ['body', 'amount'], msg: 'Field required', type: 'missing' }] }, 422))
    .toBe('Some values aren’t valid. Check them and try again.')
  expect(detailOf(undefined, 401)).toBe('Your session has ended. Sign in again.')
  expect(detailOf('<html>', 418)).toBe('Something went wrong (HTTP 418). Try again.')
})
```

`web/src/data/pending.test.ts`:

```ts
import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { clearPending, isPending, markPending, usePendingIds } from './pending'

afterEach(() => clearPending())

it('tracks queued row ids and re-renders subscribers', () => {
  const { result } = renderHook(() => usePendingIds())
  expect(result.current.size).toBe(0)
  act(() => markPending('e1'))
  expect(result.current.has('e1')).toBe(true)
  expect(isPending('e1')).toBe(true)
  act(() => clearPending())
  expect(result.current.has('e1')).toBe(false)
})
```

`web/src/test/fakeApi.test.ts`:

```ts
import { afterEach, expect, it } from 'vitest'
import { api } from '../api/client'
import { fakeApi, reply } from './fakeApi'
import { entry } from './fixtures'
import { resetTestEnv } from './render'

afterEach(resetTestEnv)

it('answers typed routes, fills path params and records calls with their JSON bodies', async () => {
  const fake = fakeApi({
    'POST /api/v1/recurring/entries/{entry_id}/done': (req) => entry({ id: req.params.entry_id, status: 'done' }),
  })
  const { data } = await api.POST('/api/v1/recurring/entries/{entry_id}/done', {
    params: { path: { entry_id: 'e7' } },
    body: { amount: '12.00', payment_method: 'card' },
  })
  expect(data).toMatchObject({ id: 'e7', status: 'done' })
  expect(fake.callsTo('POST /api/v1/recurring/entries/{entry_id}/done')).toMatchObject([
    { path: '/api/v1/recurring/entries/e7/done', body: { amount: '12.00', payment_method: 'card' } },
  ])
})

it('literal routes win over templated ones; unknown routes are a 404 naming the request', async () => {
  fakeApi({
    'GET /api/v1/recurring/{item_id}': () => reply(500),
    'GET /api/v1/recurring/entries': () => [],
  })
  const ok = await api.GET('/api/v1/recurring/entries', { params: { query: { from: '2026-09-01', to: '2026-10-06' } } })
  expect(ok.response.status).toBe(200)
  const missing = await api.GET('/api/v1/plan/year')
  expect(missing.response.status).toBe(404)
  expect(missing.error).toEqual({ detail: 'fakeApi: no route for GET /api/v1/plan/year' })
})

it('down() makes every request fail at the network level; null replies are 204', async () => {
  const fake = fakeApi({ 'POST /api/v1/matches/{match_id}/dismiss': () => null })
  const res = await api.POST('/api/v1/matches/{match_id}/dismiss', { params: { path: { match_id: 'm1' } } })
  expect(res.response.status).toBe(204)
  fake.down()
  await expect(api.GET('/api/v1/matches')).rejects.toThrow(TypeError)
  fake.up()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/data/http.test.ts src/data/pending.test.ts src/test/fakeApi.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the implementation**

`web/src/data/http.ts`:

```ts
/** Errors and response unwrapping for openapi-fetch results (which never throw on HTTP errors). */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** The server's message for a failed request, made safe to show in a toast. */
export function detailOf(error: unknown, status?: number): string {
  const detail = typeof error === 'object' && error !== null ? (error as { detail?: unknown }).detail : undefined
  if (typeof detail === 'string' && detail.trim()) return detail
  // FastAPI's 422: a list of {loc, msg, type}. Never show "[object Object]".
  if (Array.isArray(detail)) return 'Some values aren’t valid. Check them and try again.'
  if (status === 401) return 'Your session has ended. Sign in again.'
  return status ? `Something went wrong (HTTP ${status}). Try again.` : 'Something went wrong. Try again.'
}

interface Raw { data?: unknown; error?: unknown; response: Response }

/** For useCachedQuery fetchers: the data on 2xx, an ApiError otherwise (so TanStack sees a failure). */
export async function unwrap<R extends Raw>(p: Promise<R>): Promise<NonNullable<R['data']>> {
  const { data, error, response } = await p
  if (!response.ok) throw new ApiError(response.status, detailOf(error, response.status))
  return data as NonNullable<R['data']>
}
```

`web/src/data/online.ts`:

```ts
import { useSyncExternalStore } from 'react'

export const isOnline = (): boolean => globalThis.navigator?.onLine !== false

const subscribe = (cb: () => void) => {
  window.addEventListener('online', cb)
  window.addEventListener('offline', cb)
  return () => {
    window.removeEventListener('online', cb)
    window.removeEventListener('offline', cb)
  }
}

/** The browser's online flag, live. Optimistic: a captive portal still counts as online. */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribe, isOnline, () => true)
}
```

`web/src/data/pending.ts`:

```ts
import { useSyncExternalStore } from 'react'

/**
 * Ids of rows whose change is waiting in the offline queue (spec §3.2: the "queued" marker).
 * In memory only: the queue bridge clears it when nothing is pending any more.
 */
let ids: ReadonlySet<string> = new Set()
const subs = new Set<() => void>()
const emit = () => subs.forEach((cb) => cb())
const subscribe = (cb: () => void) => {
  subs.add(cb)
  return () => { subs.delete(cb) }
}

export function markPending(id: string): void {
  if (ids.has(id)) return
  ids = new Set([...ids, id])
  emit()
}

export function clearPending(): void {
  if (ids.size === 0) return
  ids = new Set()
  emit()
}

export const isPending = (id: string): boolean => ids.has(id)

export function usePendingIds(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, () => ids, () => ids)
}
```

`web/src/test/fakeApi.ts`:

```ts
import { vi } from 'vitest'
import type { paths } from '../api/schema'

type Lower = 'get' | 'post' | 'put' | 'patch' | 'delete'
type Op<P extends keyof paths, M extends Lower> = paths[P][M]
type JsonOf<R> = R extends { content: { 'application/json': infer J } } ? J : null
type Success<O> = O extends { responses: infer R }
  ? 200 extends keyof R
    ? JsonOf<R[200 & keyof R]>
    : 201 extends keyof R
      ? JsonOf<R[201 & keyof R]>
      : null
  : never

/** Every "METHOD /path" the schema declares, e.g. "POST /api/v1/recurring/entries/{entry_id}/done". */
export type Route = {
  [P in keyof paths & string]: {
    [M in Lower]: [Op<P, M>] extends [undefined] ? never : `${Uppercase<M>} ${P}`
  }[Lower]
}[keyof paths & string]

type PathOf<R> = R extends `${string} ${infer P}` ? P : never
type MethodOf<R> = R extends `${infer M} ${string}` ? Lowercase<M> : never
/** The success body the schema declares for a route (null for a 204). */
export type Reply<R extends Route> = Success<Op<PathOf<R> & keyof paths, MethodOf<R> & Lower>>

export interface FakeRequest {
  method: string
  path: string
  params: Record<string, string>
  query: URLSearchParams
  body: unknown
  headers: Headers
}
export type Handler<R extends Route> = (req: FakeRequest) => Reply<R> | Response | Promise<Reply<R> | Response>
export type Routes = { [R in Route]?: Handler<R> }
export type FakeCall = Omit<FakeRequest, 'params'>

export interface FakeApi {
  calls: FakeCall[]
  /** Calls that matched one route template. */
  callsTo(route: Route): FakeCall[]
  /** Add or replace a handler mid-test. */
  on<R extends Route>(route: R, handler: Handler<R>): void
  /** From now on every request rejects with TypeError('Failed to fetch'), like no connection. */
  down(): void
  up(): void
}

/** An error (or any explicit) response for a handler to return. */
export const reply = (status: number, body?: unknown): Response =>
  body === undefined ? new Response(null, { status }) : Response.json(body, { status })

/** A request that never answers: for "still loading" states. */
export const hang = (): Promise<never> => new Promise<never>(() => {})

function compile(route: string) {
  const [method, pattern] = route.split(' ')
  const names: string[] = []
  const source = pattern.replace(/\{(\w+)\}/g, (_m, name: string) => {
    names.push(name)
    return '([^/]+)'
  })
  return { method, re: new RegExp(`^${source}$`), names, literal: names.length === 0 }
}

/**
 * Replaces globalThis.fetch for the test (restored by vi.restoreAllMocks / resetTestEnv).
 * Works for both the openapi-fetch client (Request objects) and the offline queue (string URLs).
 */
export function fakeApi(routes: Routes = {}): FakeApi {
  const table = new Map<string, (req: FakeRequest) => unknown>()
  for (const [route, handler] of Object.entries(routes)) table.set(route, handler as (req: FakeRequest) => unknown)
  const calls: FakeCall[] = []
  let offline = false

  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), globalThis.location.origin), init)
    const url = new URL(req.url)
    const text = req.method === 'GET' || req.method === 'HEAD' ? '' : await req.clone().text()
    const call: FakeCall = {
      method: req.method,
      path: url.pathname,
      query: url.searchParams,
      body: text ? (JSON.parse(text) as unknown) : undefined,
      headers: req.headers,
    }
    calls.push(call)
    if (offline) throw new TypeError('Failed to fetch')
    // Literal routes first, so /recurring/entries never lands on /recurring/{item_id}.
    const ordered = [...table.entries()]
      .map(([key, handler]) => ({ ...compile(key), handler }))
      .sort((a, b) => Number(b.literal) - Number(a.literal))
    for (const r of ordered) {
      if (r.method !== req.method) continue
      const m = r.re.exec(url.pathname)
      if (!m) continue
      const params = Object.fromEntries(r.names.map((n, i) => [n, decodeURIComponent(m[i + 1])]))
      const out = await r.handler({ ...call, params })
      if (out instanceof Response) return out
      return out === null || out === undefined ? new Response(null, { status: 204 }) : Response.json(out)
    }
    return reply(404, { detail: `fakeApi: no route for ${req.method} ${url.pathname}` })
  })

  return {
    calls,
    callsTo: (route) => {
      const c = compile(route)
      return calls.filter((x) => x.method === c.method && c.re.test(x.path))
    },
    on: (route, handler) => { table.set(route, handler as (req: FakeRequest) => unknown) },
    down: () => { offline = true },
    up: () => { offline = false },
  }
}
```

`web/src/test/fixtures.ts`:

```ts
import type {
  Bucket, BudgetRowOut, Category, CategoryUsualOut, EntryOut, Household, MatchOut, Member, MonthPictureOut,
  PaceOut, RecurringItemOut, TransactionPage, TransactionRow, UpcomingDayOut, YearMonthOut, YearOut,
} from '../data/types'
import type { Routes } from './fakeApi'

/** Cosmote, out, €38.90, due Fri 9 Oct 2026, expected. */
export function entry(over: Partial<EntryOut> = {}): EntryOut {
  return {
    id: 'e1', item_id: 'i1', name: 'Cosmote', direction: 'out', due_date: '2026-10-09', status: 'expected',
    amount: 38.9, estimated: false, currency: 'EUR', bucket_id: null, category_id: null, transaction_id: null,
    overdue: false, infrequent: false, ...over,
  }
}

export function day(date: string, entries: EntryOut[], net_this_month: number): UpcomingDayOut {
  return { date, entries, net_this_month }
}

export function item(over: Partial<RecurringItemOut> = {}): RecurringItemOut {
  return {
    id: 'i1', name: 'Cosmote', direction: 'out', amount: 38.9, currency: 'EUR', category_id: null, bucket_id: null,
    rule_kind: 'monthly_day', interval_months: 1, rule_day: 9, rule_month: null, rule_adjust: 'none', rule_days: null,
    rule_weekday: null, rule_interval_weeks: null, start_date: '2026-01-09', end_date: null, total_occurrences: null,
    contract_end_date: null, paid_by_default: 'u1', payer_mode: 'single', is_auto_pay: false, is_active: true,
    notes: null, splits: [], next_entry: entry(), ...over,
  }
}

/** October 2026: in 3,150 so far, net projected +2,311.10. */
export function monthPicture(over: Partial<MonthPictureOut> = {}): MonthPictureOut {
  return {
    month: '2026-10',
    income: { so_far: 3150, still_to_come: 1500, projected: 4650 },
    fixed: { so_far: 600, still_to_come: 238.9, projected: 838.9 },
    buckets: {
      so_far: 685, still_to_come: 815, projected: 1500,
      rows: [
        { bucket_id: 'b1', name: 'Day to day', budget: 1200, so_far: 685, still_to_come: 515, projected: 1200 },
        { bucket_id: 'b2', name: 'Kids', budget: null, so_far: 0, still_to_come: 300, projected: 300 },
      ],
    },
    net_projected: 2311.1, events_spent: 410, cash: 45, estimated: false, ...over,
  }
}

export function yearMonth(month: string, income: number, out: number, estimated = false): YearMonthOut {
  return { month, income, out, estimated }
}
export function yearOut(months: YearMonthOut[], over: Partial<YearOut> = {}): YearOut {
  return { months, infrequent_monthly_average: 42.5, estimated: false, ...over }
}

export function budgetRow(over: Partial<BudgetRowOut> = {}): BudgetRowOut {
  return {
    bucket_id: 'b1', name: 'Day to day', kind: 'monthly', budget: 1200, spent: 904, pct: 75.3,
    period_start: '2026-10-01', period_end: '2026-10-31', days_left: null, archive_suggested: false, ...over,
  }
}
export function pace(over: Partial<PaceOut> = {}): PaceOut {
  return { bucket_id: 'b1', name: 'Day to day', budget: 1200, spent: 904, pct: 75.3, pace: 1310, over_pace: true, ...over }
}

export function match(over: Partial<MatchOut> = {}): MatchOut {
  return {
    id: 'm1', label: 'Cosmote', transaction_id: 't1', transaction_date: '2026-10-03', transaction_amount: 38.9,
    merchant: 'Cosmote', notes: null, entry: entry({ due_date: '2026-10-05' }), ...over,
  }
}

export function categoryUsual(over: Partial<CategoryUsualOut> = {}): CategoryUsualOut {
  return { category_id: 'c1', name: 'Groceries', icon: '🛒', color: '#f59e0b', this_month: 412, usual: 300, flagged: true, ...over }
}

export function member(over: Partial<Member> = {}): Member {
  return { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'giorgos', avatar_color: null, ...over }
}
export function household(
  members: Member[] = [member(), member({ user_id: 'u2', role: 'member', display_name: 'Maria', username: 'maria' })],
): Household {
  return { id: 'h1', name: 'Home', default_currency: 'EUR', members }
}

export function txn(over: Partial<TransactionRow> = {}): TransactionRow {
  return {
    id: 't1', type: 'expense', amount: 64.2, currency: 'EUR', transaction_date: '2026-10-06', merchant: 'Sklavenitis',
    notes: null, bucket_id: 'b1', category_id: null, paid_by: 'u1', payment_method: 'card', recurring_bill_id: null, ...over,
  }
}
export function page(items: TransactionRow[]): TransactionPage {
  return { total: items.length, page: 1, page_size: 10, items }
}

export function bucket(over: Partial<Bucket> = {}): Bucket {
  return { id: 'b1', name: 'Day to day', kind: 'monthly', status: 'active', budget: 1200, ...over }
}
export function category(over: Partial<Category> = {}): Category {
  return { id: 'c1', name: 'Groceries', icon: '🛒', color: '#f59e0b', ...over }
}

/** Handlers for the shared reads in data/reads.ts (household, items, buckets, categories). */
export function readRoutes(): Routes {
  return {
    'GET /api/v1/settings/household': () => household(),
    'GET /api/v1/recurring': () => [item()],
    'GET /api/v1/buckets': () => [bucket()],
    'GET /api/v1/settings/categories': () => [category()],
  }
}
```

`web/src/test/render.tsx`:

```tsx
import { cleanup, render, type RenderResult } from '@testing-library/react'
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement, ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { clearPending } from '../data/pending'
import { wipe } from '../offline/db'
import { setIdentity, type Identity } from '../offline/identity'
import { dismissToast, Toaster } from '../ui/Toast'

export const TEST_IDENTITY: Identity = { user_id: 'u1', household_id: 'h1' }

/** No retries (a failure shows at once), nothing garbage-collected mid-test, offline-first like the app. */
export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 30_000, networkMode: 'offlineFirst' },
      mutations: { retry: false },
    },
  })
}

export function Providers({ client, children }: { client: QueryClient; children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

export type Rendered = RenderResult & { client: QueryClient; router: ReturnType<typeof createMemoryRouter> }

/**
 * Renders `ui` at `route` inside a fresh query client, a memory router (every path renders `ui`, so links
 * only change router.state.location) and the Toaster, signed in as TEST_IDENTITY.
 */
export function renderWithProviders(ui: ReactElement, opts: { route?: string; client?: QueryClient } = {}): Rendered {
  setIdentity(TEST_IDENTITY)
  const client = opts.client ?? testQueryClient()
  const router = createMemoryRouter([{ path: '*', element: <>{ui}<Toaster /></> }], {
    initialEntries: [opts.route ?? '/'],
  })
  const result = render(<Providers client={client}><RouterProvider router={router} /></Providers>)
  return { ...result, client, router }
}

/** Flip the online state for useOnline(), useAction and TanStack's onlineManager together. */
export function setOnline(online: boolean): void {
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online })
  onlineManager.setOnline(online)
  window.dispatchEvent(new Event(online ? 'online' : 'offline'))
}

/** afterEach: unmount, restore spies and timers, back online, and clear toasts, pending ids, identity and the store. */
export async function resetTestEnv(): Promise<void> {
  cleanup()
  vi.restoreAllMocks()
  vi.useRealTimers()
  Reflect.deleteProperty(navigator, 'onLine') // falls back to Navigator.prototype.onLine
  onlineManager.setOnline(true)
  dismissToast()
  clearPending()
  setIdentity(null)
  await wipe()
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/data/http.test.ts src/data/pending.test.ts src/test/fakeApi.test.ts && npm run typecheck`
Expected: PASS. If typecheck rejects a fixture field, the schema is the authority: match the field to `web/src/api/schema.d.ts` and don't change the schema.

- [ ] **Step 5: Commit**

```bash
git add web/src/data/http.ts web/src/data/http.test.ts web/src/data/online.ts web/src/data/pending.ts web/src/data/pending.test.ts web/src/test
git commit -m "feat(web): http/online/pending primitives and the typed fake API test kit"
```

---

### Task A5: Query keys, `useCachedQuery` and `QueryView`

**Stream:** A. **Depends on:** A4.

**Files:**
- Modify: `web/src/offline/db.ts` (add `cacheEntry` after `cacheGet`)
- Modify: `web/src/offline/db.test.ts` (add one test)
- Create: `web/src/data/keys.ts`
- Create: `web/src/data/cachedQuery.ts`, `web/src/data/cachedQuery.test.tsx`
- Create: `web/src/ui/QueryView.tsx`, `web/src/ui/QueryView.test.tsx`

**Interfaces:**
- Consumes: `cachePut` (db.ts), `getIdentity` (identity.ts), `useSession` (`session/SessionProvider.tsx`), `useOnline` (A4), `EmptyState`, `OfflineBanner` (A2).
- Produces:
  - `cacheEntry<T>(key): Promise<{ value: T; updatedAt: number } | undefined>`;
  - `keys`, `affects`;
  - `cacheKeyFor(householdId, key)`;
  - `useCachedQuery<T>(key, fetcher, opts?)`, which returns `CachedQuery<T>`;
  - `QueryView`, `QueryViewState<T>`.

**How household scoping works.** The household id is part of the device-cache key: `q:<household_id>:<JSON query key>`. The in-memory TanStack keys stay plain. SessionProvider already calls `queryClient.clear()` on sign-out, on session expiry and on an account switch from another tab. It wipes Dexie when `/me` returns a different user or household. So only the persisted copy needs the household in its key. Keeping the TanStack keys plain keeps optimistic patches and invalidation prefix-based and simple.

**How seeding works.** `initialData` must be synchronous, but the cache is async because it has to decrypt. On mount, the hook reads `cacheEntry` and calls `setQueryData(key, value, { updatedAt })`. It does this only when the query has no data yet, so a fetch that landed first is never overwritten by the older copy.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/offline/db.test.ts`:

```ts
it('cacheEntry returns the value with its updatedAt, and undefined when missing', async () => {
  const before = Date.now()
  await cachePut('k', { a: 1 })
  const row = await cacheEntry<{ a: number }>('k')
  expect(row?.value).toEqual({ a: 1 })
  expect(row!.updatedAt).toBeGreaterThanOrEqual(before)
  expect(await cacheEntry('missing')).toBeUndefined()
})
```

(and change its import line to `import { cacheEntry, cacheGet, cachePut, db, wipe } from './db'`).

`web/src/data/cachedQuery.test.tsx`:

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { api } from '../api/client'
import { cacheEntry, cachePut } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { fakeApi, hang, reply } from '../test/fakeApi'
import { day, entry } from '../test/fixtures'
import { Providers, resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../test/render'
import { cacheKeyFor, useCachedQuery } from './cachedQuery'
import { unwrap } from './http'
import { keys } from './keys'

const KEY = keys.plan.upcoming(30)
const fetchUpcoming = (signal: AbortSignal) =>
  unwrap(api.GET('/api/v1/plan/upcoming', { params: { query: { days: 30 } }, signal }))
const cached = [day('2026-10-09', [entry()], 1200)]
const fresh = [day('2026-10-09', [entry({ amount: 40 })], 1198.9)]

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

const mount = () =>
  renderHook(() => useCachedQuery(KEY, fetchUpcoming), {
    wrapper: ({ children }) => <Providers client={testQueryClient()}>{children}</Providers>,
  })

it('seeds from the device cache before the network answers', async () => {
  await cachePut(cacheKeyFor('h1', KEY), cached)
  const stored = await cacheEntry(cacheKeyFor('h1', KEY))
  fakeApi({ 'GET /api/v1/plan/upcoming': () => hang() })
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(cached))
  expect(result.current.fromCache).toBe(true)
  expect(result.current.dataUpdatedAt).toBe(stored!.updatedAt)
  expect(result.current.stale).toBe(false)
})

it('writes a successful fetch to the cache under this household only', async () => {
  fakeApi({ 'GET /api/v1/plan/upcoming': () => fresh })
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(fresh))
  expect(result.current.fromCache).toBe(false)
  await waitFor(async () => expect((await cacheEntry(cacheKeyFor('h1', KEY)))?.value).toEqual(fresh))
  expect(await cacheEntry(cacheKeyFor('h2', KEY))).toBeUndefined()
})

it('a fresh answer wins over the older device copy, whichever arrives first', async () => {
  await cachePut(cacheKeyFor('h1', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => fresh })
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(fresh))
  await new Promise((r) => setTimeout(r, 30))
  expect(result.current.data).toEqual(fresh)
})

it('offline with a cache: shows it and flags the stale banner', async () => {
  await cachePut(cacheKeyFor('h1', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => fresh }).down()
  setOnline(false)
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(cached))
  expect(result.current).toMatchObject({ offline: true, stale: true, noData: false })
})

it('offline without a cache: noData once the cache was checked, never before', async () => {
  fakeApi({}).down()
  setOnline(false)
  const { result } = mount()
  expect(result.current.noData).toBe(false)
  await waitFor(() => expect(result.current.noData).toBe(true))
  expect(result.current.isLoading).toBe(false)
})

it('online but the refetch failed: keeps the cached data and flags stale', async () => {
  await cachePut(cacheKeyFor('h1', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => reply(503, { detail: 'down' }) })
  const { result } = mount()
  await waitFor(() => expect(result.current.stale).toBe(true))
  expect(result.current.data).toEqual(cached)
})

it("never reads another household's copy", async () => {
  await cachePut(cacheKeyFor('h2', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => hang() })
  const { result } = mount()
  await new Promise((r) => setTimeout(r, 50))
  expect(result.current.data).toBeUndefined()
  expect(result.current.isLoading).toBe(true)
})
```

`web/src/ui/QueryView.test.tsx`:

```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { QueryView, type QueryViewState } from './QueryView'

afterEach(cleanup)

const base: QueryViewState<string> = {
  data: undefined, dataUpdatedAt: 0, isLoading: true, offline: false, stale: false, noData: false, refetch: () => {},
}
const show = (s: Partial<QueryViewState<string>>, showBanner?: boolean) =>
  render(
    <QueryView result={{ ...base, ...s }} noDataText="No saved data yet. Connect once to load Plan." showBanner={showBanner}>
      {(d) => <p>{d}</p>}
    </QueryView>,
  )

it('loading shows a busy skeleton', () => {
  show({})
  expect(screen.getByRole('status', { name: 'Loading' })).toHaveAttribute('aria-busy', 'true')
})

it('data renders children; stale data adds the offline banner unless suppressed', () => {
  const at = new Date(2026, 9, 7, 14, 2).getTime()
  const { unmount } = show({ data: 'plan', isLoading: false, stale: true, dataUpdatedAt: at })
  expect(screen.getByText('plan')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Offline · updated')
  unmount()
  show({ data: 'plan', isLoading: false, stale: true, dataUpdatedAt: at }, false)
  expect(screen.queryByRole('status')).toBeNull()
})

it('offline with nothing saved says so; online failure offers Try again', () => {
  const { unmount } = show({ isLoading: false, noData: true, offline: true })
  expect(screen.getByText('No saved data yet. Connect once to load Plan.')).toBeInTheDocument()
  unmount()
  const refetch = vi.fn()
  show({ isLoading: false, noData: true, offline: false, refetch })
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(refetch).toHaveBeenCalledOnce()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/offline/db.test.ts src/data/cachedQuery.test.tsx src/ui/QueryView.test.tsx`
Expected: FAIL (`cacheEntry` is not exported; the modules are not found).

- [ ] **Step 3: Write the implementation**

`web/src/offline/db.ts`, added after `cacheGet`:

```ts
/** Like cacheGet, plus when the value was stored (the "updated HH:MM" of the offline banner). */
export async function cacheEntry<T>(key: string): Promise<{ value: T; updatedAt: number } | undefined> {
  const row = await db.cache.get(key)
  if (!row) return undefined
  const { open } = await import('./crypto')
  return { value: await open<T>(row), updatedAt: row.updatedAt }
}
```

`web/src/data/keys.ts`:

```ts
import type { QueryKey } from '@tanstack/react-query'

/**
 * Every query key in the app. The plain prefixes (keys.plan.all, ...) are what invalidation and optimistic
 * patches match on. The household id is not in these keys: it is in the device-cache key (cacheKeyFor).
 */
export const keys = {
  plan: {
    all: ['plan'] as const,
    /** UpcomingDayOut[] */
    upcoming: (days: number) => ['plan', 'upcoming', days] as const,
    /** MonthPictureOut; month is 'YYYY-MM' */
    month: (month: string) => ['plan', 'month', month] as const,
    year: () => ['plan', 'year'] as const,
    budgets: () => ['plan', 'budgets'] as const,
    pace: () => ['plan', 'pace'] as const,
  },
  insights: {
    all: ['insights'] as const,
    /** CategoryUsualOut[] */
    categoriesVsUsual: (month: string) => ['insights', 'categories-vs-usual', month] as const,
  },
  recurring: {
    all: ['recurring'] as const,
    /** RecurringItemOut[] */
    list: () => ['recurring', 'list'] as const,
    one: (id: string) => ['recurring', 'one', id] as const,
    entries: (from: string, to: string) => ['recurring', 'entries', from, to] as const,
  },
  home: {
    all: ['home'] as const,
    /** EntryOut[]: GET /recurring/entries for the overdue window (spec §5.2) */
    overdue: (from: string, to: string) => ['home', 'overdue', from, to] as const,
  },
  /** MatchOut[] */
  matches: () => ['matches'] as const,
  transactions: {
    all: ['transactions'] as const,
    /** TransactionRow[]: the last 10, newest first (Home › Recent; 2b adds pending rows to it) */
    recent: () => ['transactions', 'recent'] as const,
    one: (id: string) => ['transactions', 'one', id] as const,
    /** number: how many transactions an item has (its "history"), from GET /transactions?recurring_bill_id */
    forItem: (itemId: string) => ['transactions', 'item', itemId] as const,
  },
  household: () => ['household'] as const,
  buckets: () => ['buckets'] as const,
  categories: () => ['categories'] as const,
  categoryRules: () => ['category-rules'] as const,
  cashStash: () => ['cash-stash'] as const,
}

/** What each kind of change makes stale (useAction `invalidates`; the queue bridge uses `sync`). */
export const affects = {
  entry: [keys.plan.all, keys.home.all, keys.recurring.all, keys.matches(), keys.transactions.all, keys.insights.all],
  item: [keys.plan.all, keys.home.all, keys.recurring.all],
  sync: [
    keys.plan.all, keys.home.all, keys.recurring.all, keys.matches(), keys.transactions.all, keys.insights.all,
    keys.buckets(),
  ],
} satisfies Record<string, readonly QueryKey[]>
```

`web/src/data/cachedQuery.ts`:

```ts
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { cacheEntry, cachePut } from '../offline/db'
import { getIdentity } from '../offline/identity'
import { useSession } from '../session/SessionProvider'
import { useOnline } from './online'

export interface CachedQuery<T> {
  data: T | undefined
  /** When the shown data was fetched (ms); 0 without data. */
  dataUpdatedAt: number
  /** The shown data came from the device cache, not from a fetch in this session. */
  fromCache: boolean
  /** Nothing to show yet, and it may still arrive. */
  isLoading: boolean
  isError: boolean
  offline: boolean
  /** Show "Offline · updated HH:MM": data is shown but we are offline or the last fetch failed. */
  stale: boolean
  /** Nothing to show and nothing coming: offline (or failing) with no saved copy. */
  noData: boolean
  refetch: () => void
}

/** The device-cache key: scoped to the household so a switch never shows another household's data. */
export function cacheKeyFor(householdId: string, key: QueryKey): string {
  return `q:${householdId}:${JSON.stringify(key)}`
}

/**
 * A TanStack query that renders the last saved copy at once (online or offline) and saves every
 * successful fetch to the encrypted device cache. `fetcher` must throw on failure (use `unwrap`).
 */
export function useCachedQuery<T>(
  key: QueryKey,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: { enabled?: boolean } = {},
): CachedQuery<T> {
  const qc = useQueryClient()
  const online = useOnline()
  const { me } = useSession()
  // The session's household; the queue identity covers the first render before SessionProvider's effect.
  const household = me?.household_id ?? getIdentity()?.household_id ?? null
  const hash = JSON.stringify(key)
  const storeKey = household ? cacheKeyFor(household, key) : null
  const [seed, setSeed] = useState<{ hash: string; at: number } | null>(null)
  const [checked, setChecked] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    const done = () => { if (live) setChecked(hash) }
    if (!storeKey) {
      done()
      return () => { live = false }
    }
    cacheEntry<T>(storeKey).then((row) => {
      if (!live) return
      const k = JSON.parse(hash) as QueryKey
      // Only fill an empty query: data that is already there (a fetch that landed first) is newer.
      if (row && !qc.getQueryState(k)?.dataUpdatedAt) {
        qc.setQueryData(k, row.value, { updatedAt: row.updatedAt })
        setSeed({ hash, at: row.updatedAt })
      }
      done()
    }, done)
    return () => { live = false }
  }, [qc, hash, storeKey])

  const q = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const data = await fetcher(signal)
      if (storeKey) void cachePut(storeKey, data).catch(() => {}) // a racing wipe wins; nothing to persist
      return data
    },
    networkMode: 'offlineFirst',
    enabled: opts.enabled ?? true,
  })

  const has = q.data !== undefined
  const cacheChecked = checked === hash
  // setQueryData clears `error` but not errorUpdatedAt: a failure newer than the shown data still counts.
  const lastFetchFailed = q.isError || q.errorUpdatedAt > q.dataUpdatedAt
  return {
    data: q.data,
    dataUpdatedAt: has ? q.dataUpdatedAt : 0,
    fromCache: has && seed?.hash === hash && q.dataUpdatedAt === seed.at,
    isLoading: !has && !(cacheChecked && (!online || q.isError)),
    isError: q.isError,
    offline: !online,
    stale: has && (!online || lastFetchFailed),
    noData: !has && cacheChecked && (!online || q.isError),
    refetch: () => { void q.refetch() },
  }
}
```

`web/src/ui/QueryView.tsx`:

```tsx
import type { ReactNode } from 'react'
import { EmptyState } from './EmptyState'
import { OfflineBanner } from './OfflineBanner'

/** The parts of a cached query (data/cachedQuery) that decide what a screen shows. */
export interface QueryViewState<T> {
  data: T | undefined
  dataUpdatedAt: number
  isLoading: boolean
  offline: boolean
  stale: boolean
  noData: boolean
  refetch: () => void
}

export interface QueryViewProps<T> {
  result: QueryViewState<T>
  /** Spec §8: "No saved data yet. Connect once to load Plan." */
  noDataText: string
  /** false for a secondary query on a screen that already shows the banner once. */
  showBanner?: boolean
  loadingLabel?: string
  children: (data: T) => ReactNode
}

export function QueryView<T>({ result, noDataText, showBanner = true, loadingLabel = 'Loading', children }: QueryViewProps<T>) {
  if (result.data !== undefined) {
    return (
      <>
        {showBanner && result.stale && <OfflineBanner updatedAt={result.dataUpdatedAt} />}
        {children(result.data)}
      </>
    )
  }
  if (result.noData) {
    return result.offline ? (
      <EmptyState title={noDataText} />
    ) : (
      <EmptyState title="Couldn’t load this." action={{ label: 'Try again', onClick: result.refetch }} />
    )
  }
  return <div className="ui-skeleton" role="status" aria-busy="true" aria-label={loadingLabel} />
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/offline/db.test.ts src/data/cachedQuery.test.tsx src/ui/QueryView.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/offline/db.ts web/src/offline/db.test.ts web/src/data/keys.ts web/src/data/cachedQuery.ts web/src/data/cachedQuery.test.tsx web/src/ui/QueryView.tsx web/src/ui/QueryView.test.tsx
git commit -m "feat(web): query keys, useCachedQuery over the encrypted cache, QueryView states"
```

---

### Task A6: `useAction` (optimistic writes, rollback, offline queue)

**Stream:** A. **Depends on:** A5.

**Files:**
- Create: `web/src/data/action.ts`, `web/src/data/action.test.tsx`

**Interfaces:**
- Consumes: `api` (client), `enqueue` (`offline/queue.ts`), `toast` (A3), `detailOf` (A4), `isOnline` (A4), `markPending` (A4).
- Produces: `useAction<V = void, T = unknown>(spec: ActionSpec<V, T>): { run(vars: V): Promise<ActionResult<T>>; busy: boolean }`, `ActionSpec`, `ActionResult`, `ActionMethod`.
  - `run` never throws.
  - `{ status: 'done', data }` means the server applied the change.
  - `{ status: 'queued' }` means the change is in the offline queue.
  - `{ status: 'rejected', code, detail }` means the change was refused and rolled back. A toast shows `detail` unless `toastRejections: false`.
  - This is 2b §3.1's union, plus `rejected`.

**Status rules** (spec §3.2, §8):

| Response | Behaviour |
|---|---|
| 2xx | Keep the patch, invalidate, resolve `done` |
| 408, 429, 5xx, network error, or `navigator.onLine === false` | Enqueue, keep the patch, `markPending(pendingId)`, resolve `queued` |
| 401 | Roll back, no toast, no queue. The client's 401 middleware signs the session out, and the user redoes the change after signing in. Resolve `rejected` |
| Any other 4xx (400, 403, 404, 409, 422) | Roll back, toast `detail`, invalidate, resolve `rejected` |

The rollback snapshot covers every query under the `invalidates` prefixes. An `optimistic` patch must stay inside them.

- [ ] **Step 1: Write the failing test**

`web/src/data/action.test.tsx`:

```tsx
import { act, render, renderHook, screen } from '@testing-library/react'
import type { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { fakeApi, reply } from '../test/fakeApi'
import { day, entry } from '../test/fixtures'
import { Providers, resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../test/render'
import { Toaster } from '../ui/Toast'
import { useAction, type ActionResult, type ActionSpec } from './action'
import { keys } from './keys'
import { isPending } from './pending'
import type { EntryOut, UpcomingDayOut } from './types'

const KEY = keys.plan.upcoming(30)
const SKIP = 'POST /api/v1/recurring/entries/{entry_id}/skip' as const

const markSkipped = (qc: QueryClient) =>
  qc.setQueryData<UpcomingDayOut[]>(KEY, (old) =>
    old?.map((d) => ({ ...d, entries: d.entries.map((e) => ({ ...e, status: 'skipped' })) })))

const spec = (over: Partial<ActionSpec<void, EntryOut>> = {}): ActionSpec<void, EntryOut> => ({
  method: 'POST', path: '/api/v1/recurring/entries/e1/skip', optimistic: markSkipped,
  invalidates: [keys.plan.all], pendingId: 'e1', ...over,
})

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

function setup(s = spec()) {
  const client = testQueryClient()
  client.setQueryData(KEY, [day('2026-10-09', [entry()], 1200)])
  render(<Toaster />)
  const hook = renderHook(() => useAction(s), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  })
  const run = async () => {
    let r: ActionResult<EntryOut> | undefined
    await act(async () => { r = await hook.result.current.run() })
    return r!
  }
  const status = () => client.getQueryData<UpcomingDayOut[]>(KEY)![0].entries[0].status
  return { client, run, status }
}

it('online 2xx: keeps the patch, resolves done with the data and invalidates', async () => {
  fakeApi({ [SKIP]: () => entry({ status: 'skipped' }) })
  const { client, run, status } = setup()
  const spy = vi.spyOn(client, 'invalidateQueries')
  expect(await run()).toEqual({ status: 'done', data: entry({ status: 'skipped' }) })
  expect(status()).toBe('skipped')
  expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] })
})

it('409: rolls back, toasts the server detail, invalidates and resolves rejected', async () => {
  fakeApi({ [SKIP]: () => reply(409, { detail: 'This entry is already done.' }) })
  const { client, run, status } = setup()
  const spy = vi.spyOn(client, 'invalidateQueries')
  expect(await run()).toEqual({ status: 'rejected', code: 409, detail: 'This entry is already done.' })
  expect(status()).toBe('expected')
  expect(screen.getByRole('status')).toHaveTextContent('This entry is already done.')
  expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] })
})

it('422 with a list detail toasts a readable message', async () => {
  fakeApi({ [SKIP]: () => reply(422, { detail: [{ loc: ['body'], msg: 'Field required', type: 'missing' }] }) })
  const { run } = setup()
  await run()
  expect(screen.getByRole('status')).toHaveTextContent('Some values aren’t valid. Check them and try again.')
  expect(screen.getByRole('status')).not.toHaveTextContent('[object Object]')
})

it('toastRejections false: no toast, but the detail is returned for the caller to show', async () => {
  fakeApi({ [SKIP]: () => reply(409, { detail: 'Delete it too.' }) })
  const { run } = setup(spec({ toastRejections: false }))
  expect(await run()).toEqual({ status: 'rejected', code: 409, detail: 'Delete it too.' })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('offline: queues without sending, keeps the patch and marks the row pending', async () => {
  const fake = fakeApi({})
  setOnline(false)
  const { run, status } = setup()
  expect(await run()).toEqual({ status: 'queued' })
  expect(status()).toBe('skipped')
  expect(await db.queue.count()).toBe(1)
  expect(isPending('e1')).toBe(true)
  expect(fake.calls).toHaveLength(0)
})

it('a network failure or a 5xx while online is queued too', async () => {
  const fake = fakeApi({ [SKIP]: () => reply(503) })
  const { run } = setup()
  expect(await run()).toEqual({ status: 'queued' })
  fake.down()
  expect(await run()).toEqual({ status: 'queued' })
  expect(await db.queue.count()).toBe(2)
})

it('401: rolls back, no toast and nothing queued', async () => {
  fakeApi({ [SKIP]: () => reply(401, { detail: 'Not authenticated' }) })
  const { run, status } = setup()
  expect(await run()).toMatchObject({ status: 'rejected', code: 401 })
  expect(status()).toBe('expected')
  expect(await db.queue.count()).toBe(0)
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/data/action.test.tsx`
Expected: FAIL (`./action` not found).

- [ ] **Step 3: Write the implementation**

`web/src/data/action.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { api } from '../api/client'
import { enqueue } from '../offline/queue'
import { toast } from '../ui/Toast'
import { detailOf } from './http'
import { isOnline } from './online'
import { markPending } from './pending'

export type ActionMethod = 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type ActionResult<T> =
  | { status: 'done'; data: T }
  | { status: 'queued' }
  | { status: 'rejected'; code: number; detail: string }

type OrFn<V, R> = R | ((vars: V) => R)

export interface ActionSpec<V, T> {
  method: ActionMethod
  /** A concrete path ("/api/v1/recurring/entries/e1/done"): the queue replays exactly this. */
  path: OrFn<V, string>
  body?: OrFn<V, unknown>
  /** Patch cached queries at once. Must stay inside `invalidates` (that is what rollback restores). */
  optimistic?: (qc: QueryClient, vars: V) => void
  invalidates: readonly QueryKey[]
  /** The row to mark "Waiting to sync" when the change is queued. */
  pendingId?: OrFn<V, string | undefined>
  /** false: the caller shows the rejection itself (Entry sheet's Fixed-cost undo). */
  toastRejections?: boolean
  /** Unused at runtime; carries the response type. */
  readonly _result?: T
}

interface Raw { data?: unknown; error?: unknown; response: Response }

const resolve = <V, R>(x: OrFn<V, R>, vars: V): R =>
  typeof x === 'function' ? (x as (v: V) => R)(vars) : x

function send(method: ActionMethod, path: string, body: unknown): Promise<Raw> {
  // A dynamic path goes through the typed client untyped, so the CSRF header and 401 handling still apply.
  const init = (body === undefined ? {} : { body }) as never
  const p =
    method === 'POST' ? api.POST(path as never, init)
    : method === 'PUT' ? api.PUT(path as never, init)
    : method === 'PATCH' ? api.PATCH(path as never, init)
    : api.DELETE(path as never, init)
  return p as unknown as Promise<Raw>
}

const queueable = (status: number) => status >= 500 || status === 408 || status === 429

/** One write: optimistic patch, then the API, the offline queue, or a rollback (spec §3.2). Exported for tests. */
export async function perform<V, T>(qc: QueryClient, s: ActionSpec<V, T>, vars: V): Promise<ActionResult<T>> {
  const path = resolve(s.path, vars)
  const body = s.body === undefined ? undefined : resolve(s.body, vars)
  const pendingId = s.pendingId === undefined ? undefined : resolve(s.pendingId, vars)

  await Promise.all(s.invalidates.map((queryKey) => qc.cancelQueries({ queryKey })))
  const snapshot = s.invalidates.flatMap((queryKey) => qc.getQueriesData({ queryKey }))
  s.optimistic?.(qc, vars)
  const rollback = () => { for (const [k, data] of snapshot) qc.setQueryData(k, data) }
  const invalidate = () => { for (const queryKey of s.invalidates) void qc.invalidateQueries({ queryKey }) }

  const queue = async (): Promise<ActionResult<T>> => {
    try {
      await enqueue({ method: s.method, path, body })
    } catch {
      rollback()
      const detail = 'Couldn’t save this change on the phone. Try again.'
      toast(detail, { tone: 'error' })
      return { status: 'rejected', code: 0, detail }
    }
    if (pendingId) markPending(pendingId)
    return { status: 'queued' }
  }

  if (!isOnline()) return queue()
  let res: Raw
  try {
    res = await send(s.method, path, body)
  } catch {
    return queue() // failed at the network level
  }
  if (res.response.ok) {
    invalidate()
    return { status: 'done', data: res.data as T }
  }
  const code = res.response.status
  if (queueable(code)) return queue()
  rollback()
  const detail = detailOf(res.error, code)
  if (code === 401) return { status: 'rejected', code, detail }
  if (s.toastRejections !== false) toast(detail, { tone: 'error' })
  invalidate()
  return { status: 'rejected', code, detail }
}

export function useAction<V = void, T = unknown>(spec: ActionSpec<V, T>): { run: (vars: V) => Promise<ActionResult<T>>; busy: boolean } {
  const qc = useQueryClient()
  const ref = useRef(spec)
  useEffect(() => { ref.current = spec })
  const [busy, setBusy] = useState(false)
  const run = useCallback(async (vars: V) => {
    setBusy(true)
    try {
      return await perform(qc, ref.current, vars)
    } finally {
      setBusy(false)
    }
  }, [qc])
  return { run, busy }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/data/action.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/data/action.ts web/src/data/action.test.tsx
git commit -m "feat(web): useAction with optimistic patch, rollback and offline queueing"
```

---
### Task A7: Queue drain bridge, failed rows and the shell wiring

**Stream:** A. **Depends on:** A6.

**Files:**
- Modify: `web/src/offline/queue.ts` (export the result type, add `onQueueDrained`, notify in `replay`)
- Modify: `web/src/offline/queue.test.ts` (one test)
- Modify: `web/src/offline/useQueue.ts` (add `useFailedQueueRows`, `dismissFailed`)
- Create: `web/src/offline/useQueue.test.tsx`
- Create: `web/src/data/queueBridge.ts`, `web/src/data/queueBridge.test.ts`
- Modify: `web/src/shell/AppShell.tsx` (install the bridge, render `<Toaster />`)
- Modify: `web/src/shell/AppShell.test.tsx:7` (the queue mock gains `onQueueDrained`) and add one test

**Interfaces:**
- Consumes: `affects` (A5), `clearPending` (A4), `Toaster` (A3), `queryClient` (`web/src/queryClient.ts`).
- Produces:
  - `onQueueDrained(cb: (r: ReplayResult) => void): () => void`;
  - `type ReplayResult = { sent: number; failed: number; stoppedOnAuth: boolean }`;
  - `useFailedQueueRows(): FailedQueueRow[]`;
  - `dismissFailed(id: number): Promise<void>`;
  - `interface FailedQueueRow { id: number; error: string; createdAt: number }`;
  - `installQueueBridge(qc: QueryClient): () => void`.

Spec §3.2 says "when the queue drains, invalidate the plan and home keys", but `replay()` had no listeners. The bridge does three things after any replay that sent or failed a row:
- it invalidates `affects.sync`;
- it clears the pending markers once no row is pending;
- it covers failed rows too, because their optimistic patch is now wrong.

Failed rows keep their `error` in plain text (the body stays sealed). Home › Needs attention lists them (E2).

- [ ] **Step 1: Write the failing tests**

Append to `web/src/offline/queue.test.ts` (and add `onQueueDrained` to its import from `./queue`):

```ts
it('tells drain listeners what a replay sent, and stays quiet when nothing happened', async () => {
  serve(ok)
  const seen: unknown[] = []
  const off = onQueueDrained((r) => seen.push(r))
  await replay()
  expect(seen).toEqual([])
  await post()
  await replay()
  expect(seen).toEqual([{ sent: 1, failed: 0, stoppedOnAuth: false }])
  off()
  await post()
  await replay()
  expect(seen).toHaveLength(1)
})
```

`web/src/offline/useQueue.test.tsx`:

```tsx
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { resetTestEnv, TEST_IDENTITY } from '../test/render'
import { db } from './db'
import { setIdentity } from './identity'
import { enqueue } from './queue'
import { dismissFailed, useFailedQueueRows } from './useQueue'

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('lists failed rows with their server message, oldest first, and dismisses them', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'b' } })
  const [first, second] = await db.queue.toArray() // primary-key (queue) order
  await db.queue.put({ ...first, status: 'failed', error: 'Your wallet has less cash' })
  const { result } = renderHook(() => useFailedQueueRows())
  await waitFor(() =>
    expect(result.current).toEqual([{ id: first.id, error: 'Your wallet has less cash', createdAt: first.createdAt }]))
  expect(result.current.map((r) => r.id)).not.toContain(second.id)
  await act(() => dismissFailed(first.id!))
  await waitFor(() => expect(result.current).toEqual([]))
  expect(await db.queue.count()).toBe(1)
})
```

`web/src/data/queueBridge.test.ts`:

```ts
import { waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setIdentity } from '../offline/identity'
import { enqueue, replay } from '../offline/queue'
import { fakeApi, reply } from '../test/fakeApi'
import { entry } from '../test/fixtures'
import { resetTestEnv, TEST_IDENTITY, testQueryClient } from '../test/render'
import { isPending, markPending } from './pending'
import { installQueueBridge } from './queueBridge'

const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('after a replay: invalidates plan, home and the rest, and clears pending markers once nothing is pending', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => entry({ status: 'skipped' }),
  })
  const client = testQueryClient()
  const spy = vi.spyOn(client, 'invalidateQueries')
  const stop = installQueueBridge(client)
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })
  markPending('e1')
  await replay()
  await waitFor(() => expect(isPending('e1')).toBe(false))
  expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] })
  expect(spy).toHaveBeenCalledWith({ queryKey: ['home'] })
  stop()
})

it('a row that is still pending (backed off) keeps the markers', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => entry({ status: 'skipped' }),
    'POST /api/v1/recurring/entries/{entry_id}/amount': () => reply(503),
  })
  const stop = installQueueBridge(testQueryClient())
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e2/amount', body: { amount: '10.00' } })
  markPending('e2')
  await replay()
  await new Promise((r) => setTimeout(r, 30))
  expect(isPending('e2')).toBe(true)
  stop()
})
```

Append to `web/src/shell/AppShell.test.tsx`:

```tsx
it('renders the toast region while signed in', () => {
  at('/', 'signedIn')
  act(() => toast('Saved'))
  expect(screen.getByText('Saved')).toBeInTheDocument()
  act(() => dismissToast())
})
```

with `import { dismissToast, toast } from '../ui/Toast'` added, and the mock on line 7 changed to:

```tsx
vi.mock('../offline/queue', () => ({ startReplayTriggers: () => start(), onQueueDrained: () => () => {} }))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/offline/queue.test.ts src/offline/useQueue.test.tsx src/data/queueBridge.test.ts src/shell/AppShell.test.tsx`
Expected: FAIL (`onQueueDrained`, `useFailedQueueRows`, `./queueBridge` missing; no toast region in AppShell).

- [ ] **Step 3: Write the implementation**

`web/src/offline/queue.ts`:
1. Change `interface Result { sent: number; failed: number; stoppedOnAuth: boolean }` to `export interface ReplayResult { sent: number; failed: number; stoppedOnAuth: boolean }` and add `type Result = ReplayResult` below it.
2. Add, after the `let rerunForced = false` line:

```ts
const drainListeners = new Set<(r: ReplayResult) => void>()

/** Called after every replay that sent or failed at least one row (2a: invalidate, clear pending markers). */
export function onQueueDrained(cb: (r: ReplayResult) => void): () => void {
  drainListeners.add(cb)
  return () => { drainListeners.delete(cb) }
}
```

3. In `replay()`, inside the `running = (async () => { try { ... } })()` block, replace the final `return r` with:

```ts
      if (r.sent > 0 || r.failed > 0) {
        for (const cb of drainListeners) {
          try { cb(r) } catch { /* a listener must never break the drain */ }
        }
      }
      return r
```

`web/src/offline/useQueue.ts`, appended:

```ts
export interface FailedQueueRow { id: number; error: string; createdAt: number }
const NO_ROWS: FailedQueueRow[] = []

/** Queued changes the server refused on replay (spec §3.2 step 4), oldest first. Only `error` is plaintext. */
export function useFailedQueueRows(): FailedQueueRow[] {
  const rows = useLiveQuery(async () =>
    (await db.queue.where('status').equals('failed').sortBy('id')).map((r) => ({
      id: r.id!,
      error: r.error || 'The server refused this change.',
      createdAt: r.createdAt,
    })))
  return rows ?? NO_ROWS
}

export function dismissFailed(id: number): Promise<void> {
  return db.queue.delete(id)
}
```

`web/src/data/queueBridge.ts`:

```ts
import type { QueryClient } from '@tanstack/react-query'
import { db } from '../offline/db'
import { onQueueDrained } from '../offline/queue'
import { affects } from './keys'
import { clearPending } from './pending'

/**
 * After the offline queue sends (or fails) rows, the server's view has changed: refetch what writes touch,
 * and drop the "Waiting to sync" markers once no row is pending. Installed by AppShell while signed in.
 */
export function installQueueBridge(qc: QueryClient): () => void {
  return onQueueDrained(() => {
    for (const queryKey of affects.sync) void qc.invalidateQueries({ queryKey })
    void db.queue.where('status').equals('pending').count().then(
      (n) => { if (n === 0) clearPending() },
      () => {},
    )
  })
}
```

`web/src/shell/AppShell.tsx`:
- Add the imports `import { installQueueBridge } from '../data/queueBridge'`, `import { queryClient } from '../queryClient'` and `import { Toaster } from '../ui/Toast'`.
- Replace the replay effect with:

```tsx
  // Replay queued offline writes on open, `online` and returning to the tab (iOS has no Background Sync).
  // The bridge first, so the first drain already refreshes the screens and clears the pending markers.
  useEffect(() => {
    if (status !== 'signedIn') return
    const stopBridge = installQueueBridge(queryClient)
    const stopReplay = startReplayTriggers()
    return () => {
      stopReplay()
      stopBridge()
    }
  }, [status])
```

- Render `<Toaster />` after `<TabBar />` inside `.shell`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/offline/queue.test.ts src/offline/useQueue.test.tsx src/data/queueBridge.test.ts src/shell/AppShell.test.tsx && npm run typecheck`
Expected: PASS, including the existing queue and AppShell tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/offline/queue.ts web/src/offline/queue.test.ts web/src/offline/useQueue.ts web/src/offline/useQueue.test.tsx web/src/data/queueBridge.ts web/src/data/queueBridge.test.ts web/src/shell/AppShell.tsx web/src/shell/AppShell.test.tsx
git commit -m "feat(web): queue drain listeners, failed-row list, queue bridge and the shell Toaster"
```

---

### Task A8: Shared reads, the top-bar actions slot and the 480 px column

**Stream:** A. **Depends on:** A7. **Tag after commit:** none (C branches from `feat/2a-a`).

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/data/reads.ts`, `web/src/data/reads.test.tsx`
- Modify: `web/src/shell/TopBar.tsx` (add an `actions` prop)
- Create: `web/src/shell/TopBar.test.tsx`
- Modify: `web/src/shell/shell.css` (centred 480 px column; `.topbar__end`)

**Interfaces:**
- Consumes: `useCachedQuery` and `keys` (A5), `unwrap` (A4), the types (A1).
- Produces:
  - `useHousehold(): CachedQuery<Household>`;
  - `useRecurringItems(): CachedQuery<RecurringItemOut[]>`;
  - `useBuckets(): CachedQuery<Bucket[]>`;
  - `useCategories(): CachedQuery<Category[]>`;
  - `memberName(m: Member): string`;
  - `toHousehold(raw: unknown): Household`, `toBuckets(raw: unknown): Bucket[]`, `toCategories(raw: unknown): Category[]`, `toTransactionPage(raw: unknown): TransactionPage`;
  - `TopBar({ title, actions? })`, where `actions` renders before the account button.

These reads live in A because C, D, E, 2b and 2d all need them. `GET /settings/household`, `/buckets`, `/settings/categories` and `/transactions` are untyped dicts in the schema. Spec §4.6 asks for these to be narrowed locally.

- [ ] **Step 1: Write the failing tests**

`web/src/data/reads.test.tsx`:

```tsx
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { setIdentity } from '../offline/identity'
import { fakeApi } from '../test/fakeApi'
import { bucket, household, item, member } from '../test/fixtures'
import { Providers, resetTestEnv, TEST_IDENTITY, testQueryClient } from '../test/render'
import { memberName, toTransactionPage, useBuckets, useHousehold, useRecurringItems } from './reads'

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

const wrapper = ({ children }: { children: ReactNode }) => <Providers client={testQueryClient()}>{children}</Providers>

it('useHousehold narrows the untyped dict; missing members become []', async () => {
  fakeApi({ 'GET /api/v1/settings/household': () => ({ id: 'h1', name: 'Home', default_currency: 'EUR' }) })
  const { result } = renderHook(() => useHousehold(), { wrapper })
  await waitFor(() => expect(result.current.data).toEqual({ id: 'h1', name: 'Home', default_currency: 'EUR', members: [] }))
})

it('useRecurringItems and useBuckets return the lists', async () => {
  fakeApi({ 'GET /api/v1/recurring': () => [item()], 'GET /api/v1/buckets': () => [{ ...bucket(), balance: {} }] })
  const items = renderHook(() => useRecurringItems(), { wrapper })
  const buckets = renderHook(() => useBuckets(), { wrapper })
  await waitFor(() => expect(items.result.current.data).toEqual([item()]))
  await waitFor(() => expect(buckets.result.current.data).toEqual([bucket()]))
})

it('memberName falls back from display name to username', () => {
  expect(memberName(member())).toBe('Giorgos')
  expect(memberName(member({ display_name: null }))).toBe('giorgos')
  expect(memberName(member({ display_name: null, username: null }))).toBe('Member')
  expect(household().members).toHaveLength(2)
})

it('toTransactionPage coerces numeric strings and drops nothing', () => {
  const p = toTransactionPage({ total: '2', page: 1, page_size: 10, items: [{ id: 't1', type: 'income', amount: '2450.00', currency: 'EUR', transaction_date: '2026-10-01' }] })
  expect(p.total).toBe(2)
  expect(p.items[0]).toMatchObject({ id: 't1', type: 'income', amount: 2450, merchant: null, bucket_id: null })
})
```

`web/src/shell/TopBar.test.tsx`:

```tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { TopBar } from './TopBar'

afterEach(cleanup)

it('renders actions before the account button', () => {
  render(<TopBar title="Plan" actions={<button type="button">Items</button>} />)
  const buttons = screen.getAllByRole('button')
  expect(buttons.map((b) => b.getAttribute('aria-label') ?? b.textContent)).toEqual(['Items', 'Account'])
  expect(screen.getByRole('heading', { name: 'Plan' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/data/reads.test.tsx src/shell/TopBar.test.tsx`
Expected: FAIL (`./reads` missing; TopBar ignores `actions`).

- [ ] **Step 3: Write the implementation**

`web/src/data/reads.ts`:

```ts
import { api } from '../api/client'
import { useCachedQuery, type CachedQuery } from './cachedQuery'
import { unwrap } from './http'
import { keys } from './keys'
import type { Bucket, Category, Household, Member, RecurringItemOut, TransactionPage, TransactionRow } from './types'

type Dict = Record<string, unknown>
const asDict = (x: unknown): Dict => (typeof x === 'object' && x !== null ? (x as Dict) : {})
const str = (x: unknown, fallback = ''): string => (typeof x === 'string' ? x : x == null ? fallback : String(x))
const strOrNull = (x: unknown): string | null => (x == null || x === '' ? null : String(x))
const num = (x: unknown): number => (typeof x === 'number' ? x : Number(x ?? 0))
const numOrNull = (x: unknown): number | null => (x == null || x === '' ? null : Number(x))
const list = (x: unknown): unknown[] => (Array.isArray(x) ? x : [])

export function toMember(raw: unknown): Member {
  const d = asDict(raw)
  return {
    user_id: str(d.user_id), role: str(d.role, 'member'), display_name: strOrNull(d.display_name),
    username: strOrNull(d.username), avatar_color: strOrNull(d.avatar_color),
  }
}

export function toHousehold(raw: unknown): Household {
  const d = asDict(raw)
  return { id: str(d.id), name: str(d.name), default_currency: str(d.default_currency, 'EUR'), members: list(d.members).map(toMember) }
}

export function toBuckets(raw: unknown): Bucket[] {
  return list(raw).map((b) => {
    const d = asDict(b)
    return { id: str(d.id), name: str(d.name), kind: str(d.kind, 'monthly'), status: str(d.status, 'active'), budget: numOrNull(d.budget) }
  })
}

export function toCategories(raw: unknown): Category[] {
  return list(raw).map((c) => {
    const d = asDict(c)
    return { id: str(d.id), name: str(d.name), icon: strOrNull(d.icon), color: strOrNull(d.color) }
  })
}

export function toTransactionRow(raw: unknown): TransactionRow {
  const d = asDict(raw)
  return {
    id: str(d.id), type: d.type === 'income' ? 'income' : 'expense', amount: num(d.amount), currency: str(d.currency, 'EUR'),
    transaction_date: str(d.transaction_date), merchant: strOrNull(d.merchant), notes: strOrNull(d.notes),
    bucket_id: strOrNull(d.bucket_id), category_id: strOrNull(d.category_id), paid_by: strOrNull(d.paid_by),
    payment_method: strOrNull(d.payment_method), recurring_bill_id: strOrNull(d.recurring_bill_id),
  }
}

export function toTransactionPage(raw: unknown): TransactionPage {
  const d = asDict(raw)
  return { total: num(d.total), page: num(d.page ?? 1), page_size: num(d.page_size ?? 50), items: list(d.items).map(toTransactionRow) }
}

export const memberName = (m: Member): string => m.display_name || m.username || 'Member'

export function useHousehold(): CachedQuery<Household> {
  return useCachedQuery(keys.household(), async (signal) =>
    toHousehold(await unwrap(api.GET('/api/v1/settings/household', { signal }))))
}

export function useRecurringItems(): CachedQuery<RecurringItemOut[]> {
  return useCachedQuery(keys.recurring.list(), (signal) => unwrap(api.GET('/api/v1/recurring', { signal })))
}

export function useBuckets(): CachedQuery<Bucket[]> {
  return useCachedQuery(keys.buckets(), async (signal) => toBuckets(await unwrap(api.GET('/api/v1/buckets', { signal }))))
}

export function useCategories(): CachedQuery<Category[]> {
  return useCachedQuery(keys.categories(), async (signal) =>
    toCategories(await unwrap(api.GET('/api/v1/settings/categories', { signal }))))
}
```

`web/src/shell/TopBar.tsx`:
- The signature becomes `export function TopBar({ title, actions }: { title: string; actions?: ReactNode })`.
- Import `type ReactNode` from `react`.
- Wrap the account button in `<div className="topbar__end">{actions}<button … className="topbar__account" …>…</button></div>`. The `<dialog>` stays a sibling after that div.

`web/src/shell/shell.css`:
- Add these lines in the Shell and Top bar sections:

```css
/* Phones fill the width; wider screens get a centred 480px column (spec §7). */
.shell__main { max-width: 480px; margin: 0 auto; }
.tabbar { max-width: 480px; margin: 0 auto; }
.topbar__end { display: flex; align-items: center; gap: 6px; flex: none; }
```

- Keep `.tabbar`'s existing `left: 0; right: 0;`, because with `margin: 0 auto` they centre the fixed bar.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/data/reads.test.tsx src/shell/TopBar.test.tsx src/shell/shell.test.tsx && npm run typecheck && npm run lint`
Expected: PASS; lint reports no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/data/reads.ts web/src/data/reads.test.tsx web/src/shell/TopBar.tsx web/src/shell/TopBar.test.tsx web/src/shell/shell.css
git commit -m "feat(web): shared household/items/buckets/categories reads, TopBar actions, 480px column"
```

Stream A is done. Stream C now branches from `feat/2a-a`.

---

## Stream B: Backend rule preview

### Task B1: `POST /api/v1/recurring/preview` and regenerated types

**Stream:** B. **Depends on:** nothing (runs beside A).

**Files:**
- Modify: `app/api/recurring.py` (imports; models after `EntryAmountIn`; route in the entries section, before `/{item_id}` routes)
- Create: `tests/test_api_recurring_preview.py`
- Modify (generated): `web/src/api/openapi.json`, `web/src/api/schema.d.ts`

**Interfaces:**
- Consumes: from `app/core/schedule.py`:
  - `Rule(kind, interval_months, day, month, adjust, days, weekday, interval_weeks)`;
  - `validate_rule(rule) -> Rule`, which raises `RuleError` (a `ValueError` whose message is user-facing);
  - `iter_dates(rule, start, *, end=None, total=None, until) -> Iterator[date]`;
  - `MAX_INTERVAL_MONTHS = 120`.
  - Also `local_today()` from `app/core/clock.py`, and `require_api_auth` (cookie or Bearer).
- Produces:
  - `POST /api/v1/recurring/preview`.
  - The body is `RulePreviewIn`: `rule_kind`, `interval_months`, `rule_day`, `rule_month`, `rule_adjust`, `rule_days`, `rule_weekday`, `rule_interval_weeks`, `start_date`, `end_date`, and `count` (1–12, default 3).
  - The response is `RulePreviewOut {dates: list[date]}`.
  - In TS after `gen:api`, the path is `'/api/v1/recurring/preview'`, the body is `components['schemas']['RulePreviewIn']`, and the response is `{ dates: string[] }`.

**Behaviour.**
- The dates come from `start_date`, not from today, so the anchors of `monthly_interval` and `weekly` don't move. Only dates on or after `max(today, start_date)` are kept, up to `count`.
- `until` caps the generator at `first + MAX_INTERVAL_MONTHS * count` months, or at `date.max` on overflow. The worst case it has to cover is 12 dates 120 months apart.
- An invalid rule returns 400 with the `RuleError` message. An `end_date` before `start_date` returns 400. A `count` outside 1–12 returns 422 (pydantic).
- Nothing is written.

- [ ] **Step 0: Prepare the worktree**

Run: `cd /Users/giorgoscharitidis/expenses-2a-b && ln -s ../expenses-phase1/.venv-int .venv && (cd web && npm ci)`
Expected: `.venv/bin/python -c "import app"` works; `web/node_modules` exists.

- [ ] **Step 1: Write the failing test**

`tests/test_api_recurring_preview.py`:

```python
"""POST /api/v1/recurring/preview (2a spec §6): the next dates of a schedule rule. Writes nothing."""

from datetime import date, timedelta

from app.core.calendar_gr import last_business_day, orthodox_easter
from app.core.clock import local_today
from app.models import RecurringBill
from tests.test_api import api  # noqa: F401  (fixture)

URL = "/api/v1/recurring/preview"
FUTURE = "2097-01-01"  # later than any run's today, so the expected dates are fixed


def _dates(r):
    assert r.status_code == 200, r.text
    return [date.fromisoformat(d) for d in r.json()["dates"]]


def test_salary_rule_moves_to_the_business_day_before(client, api):  # noqa: F811
    headers, _ = api
    body = {"rule_kind": "monthly_day", "rule_day": 26, "rule_adjust": "previous_business_day", "start_date": FUTURE}
    r = client.post(URL, headers=headers, json=body)
    # 26 Jan 2097 is a Saturday: the salary comes on Friday the 25th.
    assert r.json() == {"dates": ["2097-01-25", "2097-02-26", "2097-03-26"]}


def test_last_business_day(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(URL, headers=headers, json={"rule_kind": "last_business_day", "start_date": FUTURE, "count": 6})
    dates = _dates(r)
    assert [d.isoformat() for d in dates[:3]] == ["2097-01-31", "2097-02-28", "2097-03-29"]
    assert len(dates) == 6
    assert all(d == last_business_day(d.year, d.month) for d in dates)


def test_easter_offset_counts_from_orthodox_easter(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(URL, headers=headers, json={"rule_kind": "easter_offset", "rule_days": -2, "start_date": FUTURE})
    dates = _dates(r)
    assert [d.isoformat() for d in dates] == ["2097-05-03", "2098-04-25", "2099-04-10"]
    assert all(d == orthodox_easter(d.year) - timedelta(days=2) for d in dates)


def test_count_and_end_date_limit_the_dates(client, api):  # noqa: F811
    headers, _ = api
    rule = {"rule_kind": "monthly_day", "rule_day": 5, "start_date": FUTURE}
    assert len(_dates(client.post(URL, headers=headers, json={**rule, "count": 12}))) == 12
    ended = _dates(client.post(URL, headers=headers, json={**rule, "count": 5, "end_date": "2097-02-28"}))
    assert [d.isoformat() for d in ended] == ["2097-01-05", "2097-02-05"]


def test_a_past_start_previews_from_today_and_keeps_its_anchor(client, api):  # noqa: F811
    headers, _ = api
    today = local_today()
    start = date(today.year - 2, today.month, 15)
    body = {"rule_kind": "monthly_interval", "interval_months": 3, "start_date": start.isoformat()}
    dates = _dates(client.post(URL, headers=headers, json=body))
    assert len(dates) == 3 and dates == sorted(dates)
    assert all(d >= today and d.day == 15 for d in dates)
    assert all(((d.year - start.year) * 12 + d.month - start.month) % 3 == 0 for d in dates)


def test_weekly_from_a_past_start_stays_on_its_weekday(client, api):  # noqa: F811
    headers, _ = api
    today = local_today()
    body = {"rule_kind": "weekly", "rule_weekday": 0, "rule_interval_weeks": 2,
            "start_date": (today - timedelta(days=100)).isoformat()}
    dates = _dates(client.post(URL, headers=headers, json=body))
    assert len(dates) == 3 and all(d.weekday() == 0 and d >= today for d in dates)
    assert dates[1] - dates[0] == timedelta(weeks=2)


def test_an_invalid_rule_is_400_with_the_message(client, api):  # noqa: F811
    headers, _ = api
    r = client.post(URL, headers=headers, json={"rule_kind": "monthly_day", "start_date": FUTURE})
    assert r.status_code == 400 and r.json()["detail"] == "The day must be 1 to 31."
    r = client.post(URL, headers=headers, json={"rule_kind": "fortnightly", "start_date": FUTURE})
    assert r.status_code == 400 and "Unknown schedule" in r.json()["detail"]
    r = client.post(URL, headers=headers,
                    json={"rule_kind": "last_business_day", "start_date": FUTURE, "end_date": "2096-01-01"})
    assert r.status_code == 400
    r = client.post(URL, headers=headers, json={"rule_kind": "last_business_day", "start_date": FUTURE, "count": 13})
    assert r.status_code == 422


def test_needs_auth_and_writes_nothing(client, db, api):  # noqa: F811
    headers, _ = api
    body = {"rule_kind": "last_business_day", "start_date": FUTURE}
    assert client.post(URL, json=body).status_code == 401
    assert client.post(URL, headers=headers, json=body).status_code == 200
    assert db.query(RecurringBill).count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_recurring_preview.py -o addopts="" -p no:cacheprovider -q`
Expected: FAIL. Without the route, the POST is answered with 405 (only GET/PUT/DELETE exist on `/{item_id}`) or 404.

- [ ] **Step 3: Write the implementation**

`app/api/recurring.py`:
- Imports:

```python
from itertools import islice

from dateutil.relativedelta import relativedelta

from app.core.schedule import (
    MAX_INTERVAL_MONTHS,
    MAX_INTERVAL_WEEKS,
    Rule,
    RuleError,
    iter_dates,
    validate_rule,
)
```

- The existing `from app.core.schedule import MAX_INTERVAL_MONTHS, MAX_INTERVAL_WEEKS, RuleError, validate_rule` is replaced by the block above.
- Models, after `class EntryAmountIn`:

```python
class RulePreviewIn(BaseModel):
    """The schedule fields of RecurringItemIn, plus how many dates to return."""

    rule_kind: str = "monthly_day"
    interval_months: int = 1
    rule_day: int | None = None
    rule_month: int | None = None
    rule_adjust: str = "none"
    rule_days: int | None = None
    rule_weekday: int | None = None
    rule_interval_weeks: int | None = None
    start_date: date
    end_date: date | None = None
    count: int = Field(default=3, ge=1, le=12)


class RulePreviewOut(BaseModel):
    dates: list[date]


def _preview_until(first: date, count: int) -> date:
    """Far enough for ``count`` dates of the sparsest rule (MAX_INTERVAL_MONTHS apart)."""
    try:
        return first + relativedelta(months=MAX_INTERVAL_MONTHS * count)
    except (OverflowError, ValueError):
        return date.max
```

- The route, placed after `entry_amount` and before the `# ---- items` comment, so that it precedes the `/{item_id}` routes:

```python
@router.post("/preview", response_model=RulePreviewOut)
def preview(body: RulePreviewIn, auth=Depends(require_api_auth)):
    """The next ``count`` dates of a rule (2a spec §6), from today or the start date, whichever is
    later. Dates are generated from the start date, so monthly_interval and weekly keep their anchor.
    Writes nothing."""
    rule = Rule(
        kind=body.rule_kind,
        interval_months=body.interval_months,
        day=body.rule_day,
        month=body.rule_month,
        adjust=body.rule_adjust,
        days=body.rule_days,
        weekday=body.rule_weekday,
        interval_weeks=body.rule_interval_weeks or 1,
    )
    try:
        validate_rule(rule)
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="The end date is before the start date.")
    first = max(body.start_date, local_today())
    dates = iter_dates(
        rule, body.start_date, end=body.end_date, until=_preview_until(first, body.count)
    )
    return RulePreviewOut(dates=list(islice((d for d in dates if d >= first), body.count)))
```

- [ ] **Step 4: Run the test to verify it passes, then regenerate the web types**

Run: `.venv/bin/python -m pytest tests/test_api_recurring_preview.py tests/test_api_recurring.py -o addopts="" -p no:cacheprovider -q`
Expected: PASS.

Run: `.venv/bin/ruff format app/api/recurring.py tests/test_api_recurring_preview.py && .venv/bin/ruff check app/api/recurring.py tests/test_api_recurring_preview.py`
Expected: clean.

Run: `cd web && npm run gen:api && grep -n "/api/v1/recurring/preview" src/api/schema.d.ts && npm run typecheck`
Expected: the path is present in `schema.d.ts`; typecheck passes.

- [ ] **Step 5: Commit**

```bash
git add app/api/recurring.py tests/test_api_recurring_preview.py web/src/api/openapi.json web/src/api/schema.d.ts
git commit -m "feat(api): POST /recurring/preview returns a rule's next dates; regenerate web types"
```

---
## Stream C: Plan screens and the Entry sheet

### Task C1: Plan hooks, the entry patch and the Entry sheet

**Stream:** C. **Depends on:** A1–A8. **After commit:** `git tag 2a-c1` (D and E branch from it).

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/hooks.ts`
- Create: `web/src/features/plan/entryPatch.ts`, `web/src/features/plan/entryPatch.test.ts`
- Create: `web/src/features/plan/EntrySheet.tsx`, `web/src/features/plan/EntrySheet.test.tsx`
- Create: `web/src/features/plan/entry.css`

**Interfaces:**
- Consumes: `useCachedQuery`, `useAction`, `ActionResult`, `keys`, `affects`, `unwrap`, `usePendingIds`, `useHousehold`, `useRecurringItems`, `memberName`, `Sheet`, `Money`, `Badge`, `Segmented`, the icons, `formatDayHeader`, `formatMoney`, `parseAmount`, `todayISO`, the types; `useSession`.
- Produces:
  - `UPCOMING_DAYS = 30`;
  - `usePlanUpcoming(days?: number): CachedQuery<UpcomingDayOut[]>`;
  - `usePlanMonth(month: string): CachedQuery<MonthPictureOut>`;
  - `useCategoriesVsUsual(month: string): CachedQuery<CategoryUsualOut[]>`;
  - `usePlanYear(): CachedQuery<YearOut>`;
  - `useBudgets(): CachedQuery<BudgetRowOut[]>`;
  - `usePace(): CachedQuery<PaceOut[]>`;
  - `useEntryActions(entry): EntryActions`, where `EntryActions = { markDone(body: EntryDoneIn); skip(); setAmount(amount: string); undo(deleteTransaction: boolean); busy: boolean }` and each action returns `Promise<ActionResult<EntryOut>>`;
  - `EntryChange`, `applyChange`, `netDelta`, `patchUpcoming`, `patchEntryEverywhere(qc, target, change)`;
  - `EntrySheet({ entry: EntryOut | null; intent?: 'default' | 'amount'; onClose })`, `EntryIntent`.

**Behaviour (spec §4.6):**
- Header: the amount (with "≈"), "Due Fri 9 Oct" ("Expected" for in entries), a status badge (Overdue / Expected / Paid / Received / Skipped) and "Waiting to sync" when the row is pending.
- Expected entries offer **Paid** (or **Received**), **Set amount** and **Skip**.
  - The Paid form has the amount (prefilled), who and method.
  - Who defaults to the item's `paid_by_default`, then the signed-in user, then the first member. It is hidden when the household has one member.
  - Method defaults to card for out entries and transfer for in entries.
  - `intent: 'amount'` opens straight on Set amount (from Home).
- Done or skipped entries offer **Undo**. Undo of a paid **out** entry asks "Keep the expense" or "Delete the expense".
  - A rejection of Keep (the Fixed-cost 409) is shown inline with the server's text, and only "Delete the expense" stays.
- Any rejection keeps the sheet open with the message. A done or queued result closes it.

- [ ] **Step 1: Write the failing tests**

`web/src/features/plan/entryPatch.test.ts`:

```ts
import { expect, it } from 'vitest'
import { day, entry } from '../../test/fixtures'
import type { UpcomingDayOut } from '../../data/types'
import { applyChange, patchUpcoming } from './entryPatch'

const cosmote = entry() // out, €38.90, due 2026-10-09
const days = [
  day('2026-10-08', [], 1000),
  day('2026-10-09', [cosmote], 961.1),
  day('2026-11-02', [entry({ id: 'e2', due_date: '2026-11-02', amount: 50 })], -50),
]
const nets = (d: UpcomingDayOut[]) => d.map((x) => x.net_this_month)

it('skip gives the expected amount back from the due day to the end of its month', () => {
  const out = patchUpcoming(days, cosmote, { kind: 'skip' })
  expect(nets(out)).toEqual([1000, 1000, -50])
  expect(out[1].entries[0].status).toBe('skipped')
})

it('paid today with another amount: the paid amount counts from today, the expected one goes', () => {
  const out = patchUpcoming(days, cosmote, { kind: 'done', amount: 40, today: '2026-10-08' })
  expect(nets(out)).toEqual([960, 960, -50])
  expect(out[1].entries[0]).toMatchObject({ status: 'done', amount: 40, estimated: false })
})

it('a new amount moves only its own month, from the due day', () => {
  expect(nets(patchUpcoming(days, cosmote, { kind: 'amount', amount: 50 }))).toEqual([1000, 950, -50])
})

it('in entries add instead of subtract, and the next month restarts', () => {
  const salary = entry({ id: 's', direction: 'in', amount: 1500, due_date: '2026-10-26' })
  const d = [day('2026-10-26', [salary], 2500), day('2026-10-30', [], 2400), day('2026-11-01', [], 0)]
  expect(nets(patchUpcoming(d, salary, { kind: 'skip' }))).toEqual([1000, 900, 0])
})

it('a confirmed match is done without counting the money twice', () => {
  expect(nets(patchUpcoming(days, cosmote, { kind: 'linked' }))).toEqual([1000, 1000, -50])
  expect(applyChange(cosmote, { kind: 'linked' }).status).toBe('done')
})

it('a variable entry (amount null) counts as zero, never NaN', () => {
  const variable = entry({ amount: null })
  const out = patchUpcoming([day('2026-10-09', [variable], 100)], variable, { kind: 'amount', amount: 80 })
  expect(out[0].net_this_month).toBe(20)
})
```

`web/src/features/plan/EntrySheet.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { fakeApi, reply, type Routes } from '../../test/fakeApi'
import { entry, household, item, member, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { EntrySheet } from './EntrySheet'

afterEach(resetTestEnv)

const DONE = 'POST /api/v1/recurring/entries/{entry_id}/done' as const
const AMOUNT = 'POST /api/v1/recurring/entries/{entry_id}/amount' as const
const SKIP = 'POST /api/v1/recurring/entries/{entry_id}/skip' as const
const UNDO = 'POST /api/v1/recurring/entries/{entry_id}/undo' as const
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/recurring': () => [item({ paid_by_default: 'u2' })],
  ...over,
})

it('expected out entry: Paid prefills amount, the item payer and card, then posts done and closes', async () => {
  const fake = fakeApi(routes({ [DONE]: () => entry({ status: 'done' }) }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry()} onClose={onClose} />)
  const sheet = screen.getByRole('dialog', { name: 'Cosmote' })
  expect(sheet).toHaveTextContent('Due Fri 9 Oct')
  expect(sheet).toHaveTextContent('€38.90')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Paid' }))
  expect(screen.getByLabelText('Amount')).toHaveValue('38.90')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Maria' })).toHaveAttribute('aria-pressed', 'true'))
  expect(screen.getByRole('button', { name: 'Card' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(DONE)).toMatchObject([
    { path: '/api/v1/recurring/entries/e1/done', body: { amount: '38.90', person: 'u2', payment_method: 'card' } },
  ])
})

it('expected in entry: Received, "Received by" and transfer by default', async () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ direction: 'in', name: 'Salary', amount: 1500 })} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Received' }))
  expect(screen.getByRole('button', { name: 'Transfer' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByRole('group', { name: 'Received by' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Mark received €1,500.00' })).toBeEnabled()
})

it('Set amount accepts a comma and sends a dot; garbage is refused before sending', async () => {
  const fake = fakeApi(routes({ [AMOUNT]: () => entry({ amount: 86.4 }) }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry({ name: 'Electricity', estimated: true, amount: 83.5 })} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Set amount' }))
  const input = screen.getByLabelText('Amount')
  expect(input).toHaveAttribute('placeholder', 'Usually ≈ €83.50')
  fireEvent.change(input, { target: { value: 'abc' } })
  expect(screen.getByText('Enter an amount like 86.40')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save amount' })).toBeDisabled()
  fireEvent.change(input, { target: { value: '86,40' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save amount' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(AMOUNT)[0].body).toEqual({ amount: '86.40' })
})

it('intent amount opens straight on Set amount', () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ estimated: true })} intent="amount" onClose={() => {}} />)
  expect(screen.getByLabelText('Amount')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Paid' })).toBeNull()
})

it('undo of a paid out entry asks; a Fixed-cost 409 is shown inline and only Delete the expense remains', async () => {
  const fixed = "This expense has no bucket, so it can't stay without its bill. Delete it too, or give it a bucket first."
  const fake = fakeApi(routes({
    [UNDO]: (req) => ((req.body as { delete_transaction: boolean }).delete_transaction ? entry() : reply(409, { detail: fixed })),
  }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry({ status: 'done', transaction_id: 't1' })} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  fireEvent.click(screen.getByRole('button', { name: 'Keep the expense' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(fixed)
  expect(screen.queryByRole('button', { name: 'Keep the expense' })).toBeNull()
  expect(onClose).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete the expense' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(UNDO).map((c) => c.body)).toEqual([{ delete_transaction: false }, { delete_transaction: true }])
})

it('undo of a skipped entry is direct', async () => {
  const fake = fakeApi(routes({ [UNDO]: () => entry() }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry({ status: 'skipped' })} onClose={onClose} />)
  expect(screen.getByRole('dialog')).toHaveTextContent('Skipped')
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(UNDO)[0].body).toEqual({ delete_transaction: false })
})

it('a one-member household gets no "Paid by" choice and sends that member', async () => {
  const fake = fakeApi(routes({
    'GET /api/v1/settings/household': () => household([member()]),
    'GET /api/v1/recurring': () => [item({ paid_by_default: null })],
    [DONE]: () => entry({ status: 'done' }),
  }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  await waitFor(() => expect(fake.callsTo('GET /api/v1/settings/household')).toHaveLength(1))
  await new Promise((r) => setTimeout(r, 20))
  expect(screen.queryByRole('group', { name: 'Paid by' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(DONE)[0].body).toMatchObject({ person: 'u1' })
})

it('offline: Skip is queued and the sheet closes', async () => {
  const fake = fakeApi(routes())
  setOnline(false)
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(await db.queue.count()).toBe(1)
  expect(fake.callsTo(SKIP)).toHaveLength(0)
})

it('an overdue entry says so in words', () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ overdue: true })} onClose={() => {}} />)
  expect(screen.getByRole('dialog')).toHaveTextContent('Overdue')
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/plan/entryPatch.test.ts src/features/plan/EntrySheet.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/entryPatch.ts`:

```ts
import type { QueryClient } from '@tanstack/react-query'
import { keys } from '../../data/keys'
import type { EntryOut, RecurringItemOut, UpcomingDayOut } from '../../data/types'

export type EntryChange =
  /** Paid / Received: creates a transaction dated today. */
  | { kind: 'done'; amount: number | null; today: string }
  /** A confirmed match: done, and its transaction already counts. */
  | { kind: 'linked' }
  | { kind: 'skip' }
  | { kind: 'amount'; amount: number }
  | { kind: 'undo' }

const signed = (e: EntryOut, amount: number | null) => (amount ?? 0) * (e.direction === 'in' ? 1 : -1)
const cents = (n: number) => Math.round(n * 100) / 100
const monthOf = (iso: string) => iso.slice(0, 7)

export function applyChange(e: EntryOut, change: EntryChange): EntryOut {
  switch (change.kind) {
    case 'done': return { ...e, status: 'done', amount: change.amount ?? e.amount, estimated: false, overdue: false }
    case 'linked': return { ...e, status: 'done', overdue: false }
    case 'skip': return { ...e, status: 'skipped', overdue: false }
    case 'amount': return { ...e, amount: change.amount, estimated: false }
    case 'undo': return { ...e, status: 'expected' }
  }
}

/** How a change moves the running "net this month" shown on `day` (planning spec §5.2). */
export function netDelta(day: string, target: EntryOut, change: EntryChange): number {
  const expected = signed(target, target.amount)
  // An expected entry counts from its due day to the end of its own month.
  const counted = monthOf(day) === monthOf(target.due_date) && day >= target.due_date
  switch (change.kind) {
    case 'skip':
    case 'linked':
      return counted ? -expected : 0
    case 'amount':
      return counted ? signed(target, change.amount) - expected : 0
    case 'done': {
      // The new transaction is dated today, so it counts on every listed day of today's month.
      const paid = monthOf(day) === monthOf(change.today) ? signed(target, change.amount ?? target.amount) : 0
      return paid - (counted ? expected : 0)
    }
    case 'undo':
      return 0 // the refetch after the action settles the figures
  }
}

export function patchUpcoming(days: UpcomingDayOut[], target: EntryOut, change: EntryChange): UpcomingDayOut[] {
  return days.map((d) => ({
    ...d,
    net_this_month: cents(d.net_this_month + netDelta(d.date, target, change)),
    entries: d.entries.map((e) => (e.id === target.id ? applyChange(e, change) : e)),
  }))
}

/** The optimistic patch for an entry action, on every cached list that shows the entry (all under affects.entry). */
export function patchEntryEverywhere(qc: QueryClient, target: EntryOut, change: EntryChange): void {
  qc.setQueriesData<UpcomingDayOut[]>({ queryKey: [...keys.plan.all, 'upcoming'] }, (old) =>
    old && patchUpcoming(old, target, change))
  qc.setQueriesData<EntryOut[]>({ queryKey: [...keys.home.all, 'overdue'] }, (old) =>
    old?.map((e) => (e.id === target.id ? applyChange(e, change) : e)))
  qc.setQueryData<RecurringItemOut[]>(keys.recurring.list(), (old) =>
    old?.map((i) => (i.next_entry && i.next_entry.id === target.id ? { ...i, next_entry: applyChange(i.next_entry, change) } : i)))
}
```

`web/src/features/plan/hooks.ts`:

```ts
import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAction, type ActionResult } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import type { EntryDoneIn, EntryOut } from '../../data/types'
import { todayISO } from '../../ui/format'
import { patchEntryEverywhere, type EntryChange } from './entryPatch'

export const UPCOMING_DAYS = 30

export function usePlanUpcoming(days: number = UPCOMING_DAYS) {
  return useCachedQuery(keys.plan.upcoming(days), (signal) =>
    unwrap(api.GET('/api/v1/plan/upcoming', { params: { query: { days } }, signal })))
}

export function usePlanMonth(month: string) {
  return useCachedQuery(keys.plan.month(month), (signal) =>
    unwrap(api.GET('/api/v1/plan/month', { params: { query: { month } }, signal })))
}

export function useCategoriesVsUsual(month: string) {
  return useCachedQuery(keys.insights.categoriesVsUsual(month), (signal) =>
    unwrap(api.GET('/api/v1/insights/categories-vs-usual', { params: { query: { month } }, signal })))
}

export function usePlanYear() {
  return useCachedQuery(keys.plan.year(), (signal) => unwrap(api.GET('/api/v1/plan/year', { signal })))
}

export function useBudgets() {
  return useCachedQuery(keys.plan.budgets(), (signal) => unwrap(api.GET('/api/v1/plan/budgets', { signal })))
}

export function usePace() {
  return useCachedQuery(keys.plan.pace(), (signal) => unwrap(api.GET('/api/v1/plan/pace', { signal })))
}

export interface EntryActions {
  markDone: (body: EntryDoneIn) => Promise<ActionResult<EntryOut>>
  skip: () => Promise<ActionResult<EntryOut>>
  setAmount: (amount: string) => Promise<ActionResult<EntryOut>>
  undo: (deleteTransaction: boolean) => Promise<ActionResult<EntryOut>>
  busy: boolean
}

/** Spec §4.6: POST /recurring/entries/{id}/done|skip|amount|undo, optimistic and queueable. */
export function useEntryActions(entry: EntryOut): EntryActions {
  const base = `/api/v1/recurring/entries/${entry.id}`
  const shared = { method: 'POST' as const, invalidates: affects.entry, pendingId: entry.id }
  const patch = (change: EntryChange) => (qc: QueryClient) => patchEntryEverywhere(qc, entry, change)

  const done = useAction<EntryDoneIn, EntryOut>({
    ...shared,
    path: `${base}/done`,
    body: (b: EntryDoneIn) => b,
    optimistic: (qc, b) =>
      patchEntryEverywhere(qc, entry, { kind: 'done', amount: b.amount == null ? null : Number(b.amount), today: todayISO() }),
  })
  const skip = useAction<void, EntryOut>({ ...shared, path: `${base}/skip`, optimistic: patch({ kind: 'skip' }) })
  const amount = useAction<string, EntryOut>({
    ...shared,
    path: `${base}/amount`,
    body: (a: string) => ({ amount: a }),
    optimistic: (qc, a) => patchEntryEverywhere(qc, entry, { kind: 'amount', amount: Number(a) }),
  })
  // Quiet rejections: the sheet shows a Fixed-cost 409 inline next to "Delete the expense".
  const undoKeep = useAction<void, EntryOut>({
    ...shared, path: `${base}/undo`, body: { delete_transaction: false }, toastRejections: false, optimistic: patch({ kind: 'undo' }),
  })
  const undoDelete = useAction<void, EntryOut>({
    ...shared, path: `${base}/undo`, body: { delete_transaction: true }, toastRejections: false, optimistic: patch({ kind: 'undo' }),
  })

  return {
    markDone: done.run,
    skip: () => skip.run(),
    setAmount: amount.run,
    undo: (deleteTransaction) => (deleteTransaction ? undoDelete : undoKeep).run(),
    busy: done.busy || skip.busy || amount.busy || undoKeep.busy || undoDelete.busy,
  }
}
```

`web/src/features/plan/EntrySheet.tsx`:

```tsx
import { useState } from 'react'
import type { ActionResult } from '../../data/action'
import { usePendingIds } from '../../data/pending'
import { memberName, useHousehold, useRecurringItems } from '../../data/reads'
import type { EntryDoneIn, EntryOut, PaymentMethod } from '../../data/types'
import { useSession } from '../../session/SessionProvider'
import { Badge } from '../../ui/Badge'
import { AlertIcon, CheckIcon, ClockIcon } from '../../ui/icons'
import { Money } from '../../ui/Money'
import { Segmented } from '../../ui/Segmented'
import { Sheet } from '../../ui/Sheet'
import { formatDayHeader, formatMoney, parseAmount } from '../../ui/format'
import { useEntryActions, type EntryActions } from './hooks'
import './entry.css'

export type EntryIntent = 'default' | 'amount'
export interface EntrySheetProps { entry: EntryOut | null; intent?: EntryIntent; onClose: () => void }

const METHODS: readonly { value: PaymentMethod; label: string }[] = [
  { value: 'card', label: 'Card' },
  { value: 'cash', label: 'Cash' },
  { value: 'apple_pay', label: 'Apple Pay' },
  { value: 'transfer', label: 'Transfer' },
  { value: 'other', label: 'Other' },
]

export function EntrySheet({ entry, intent = 'default', onClose }: EntrySheetProps) {
  return (
    <Sheet open={entry !== null} onClose={onClose} title={entry?.name ?? ''}>
      {entry && <EntryBody key={`${entry.id}:${intent}`} entry={entry} intent={intent} onClose={onClose} />}
    </Sheet>
  )
}

type Mode = 'menu' | 'pay' | 'amount' | 'undo'

function EntryBody({ entry, intent, onClose }: { entry: EntryOut; intent: EntryIntent; onClose: () => void }) {
  const expected = entry.status === 'expected'
  const isIn = entry.direction === 'in'
  const [mode, setMode] = useState<Mode>(intent === 'amount' && expected ? 'amount' : 'menu')
  const [problem, setProblem] = useState<string | null>(null)
  const actions = useEntryActions(entry)
  const pending = usePendingIds().has(entry.id)
  const after = (r: ActionResult<unknown>) => {
    if (r.status === 'rejected') setProblem(r.detail)
    else onClose()
  }

  return (
    <div className="entry">
      <div className="entry__summary">
        <Money className="entry__amount ui-figure" amount={entry.amount} currency={entry.currency}
          estimated={entry.estimated} nullText="No amount yet" />
        <p className="entry__due">{isIn ? 'Expected' : 'Due'} {formatDayHeader(entry.due_date)}</p>
        <div className="entry__badges">
          <StatusBadge entry={entry} />
          {pending && <Badge icon={<ClockIcon />}>Waiting to sync</Badge>}
        </div>
      </div>

      {problem && <p className="entry__problem" role="alert">{problem}</p>}

      {expected && mode === 'menu' && (
        <div className="entry__actions">
          <button type="button" className="btn btn--primary btn--block btn--lg" onClick={() => setMode('pay')}>
            {isIn ? 'Received' : 'Paid'}
          </button>
          <button type="button" className="btn btn--block" onClick={() => setMode('amount')}>Set amount</button>
          <button type="button" className="btn btn--ghost btn--block" disabled={actions.busy}
            onClick={async () => after(await actions.skip())}>Skip</button>
        </div>
      )}
      {expected && mode === 'pay' && <PayForm entry={entry} actions={actions} onResult={after} />}
      {expected && mode === 'amount' && <AmountForm entry={entry} actions={actions} onResult={after} />}

      {!expected && mode === 'menu' && (
        <div className="entry__actions">
          <button type="button" className="btn btn--block" disabled={actions.busy}
            onClick={async () => {
              if (entry.status === 'done' && !isIn) setMode('undo')
              else after(await actions.undo(false))
            }}>
            Undo
          </button>
        </div>
      )}
      {mode === 'undo' && (
        <div className="entry__actions">
          <p className="entry__question">Undo this payment. What should happen to the expense?</p>
          {!problem && (
            <button type="button" className="btn btn--block" disabled={actions.busy}
              onClick={async () => after(await actions.undo(false))}>Keep the expense</button>
          )}
          <button type="button" className="btn btn--danger btn--block" disabled={actions.busy}
            onClick={async () => after(await actions.undo(true))}>Delete the expense</button>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ entry }: { entry: EntryOut }) {
  if (entry.status === 'done') return <Badge tone="pos" icon={<CheckIcon />}>{entry.direction === 'in' ? 'Received' : 'Paid'}</Badge>
  if (entry.status === 'skipped') return <Badge>Skipped</Badge>
  if (entry.overdue) return <Badge tone="neg" icon={<AlertIcon />}>Overdue</Badge>
  return <Badge>Expected</Badge>
}

interface FormProps { entry: EntryOut; actions: EntryActions; onResult: (r: ActionResult<unknown>) => void }

function PayForm({ entry, actions, onResult }: FormProps) {
  const isIn = entry.direction === 'in'
  const { me } = useSession()
  const members = useHousehold().data?.members ?? []
  const item = useRecurringItems().data?.find((i) => i.id === entry.item_id)
  const fallbackWho = item?.paid_by_default ?? me?.id ?? members[0]?.user_id ?? null
  const [picked, setPicked] = useState<string | null>(null)
  const who = picked ?? fallbackWho
  const [method, setMethod] = useState<PaymentMethod>(isIn ? 'transfer' : 'card')
  const [text, setText] = useState(entry.amount === null ? '' : entry.amount.toFixed(2))
  const parsed = parseAmount(text)
  const amount = parsed ?? (entry.amount === null ? null : entry.amount.toFixed(2))
  const valid = parsed !== undefined && amount !== null
  const whoLabel = isIn ? 'Received by' : 'Paid by'

  const submit = async () => {
    if (!valid) return
    const body: EntryDoneIn = { amount: parsed ?? null, person: who, payment_method: method }
    onResult(await actions.markDone(body))
  }

  return (
    <form className="entry__form" onSubmit={(e) => { e.preventDefault(); void submit() }}>
      <label className="ui-field">
        <span className="ui-field__label">Amount</span>
        <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" value={text}
          aria-invalid={parsed === undefined} onChange={(e) => setText(e.target.value)} />
      </label>
      {parsed === undefined && <p className="ui-field__error">Enter an amount like 38.90</p>}
      {members.length > 1 && (
        <div className="ui-field">
          <span className="ui-field__label" aria-hidden="true">{whoLabel}</span>
          <Segmented label={whoLabel} value={who ?? ''} onChange={setPicked}
            options={members.map((m) => ({ value: m.user_id, label: memberName(m) }))} />
        </div>
      )}
      <div className="ui-field">
        <span className="ui-field__label" aria-hidden="true">Method</span>
        <Segmented label="Method" options={METHODS} value={method} onChange={setMethod} />
      </div>
      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={!valid || actions.busy}>
        {`${isIn ? 'Mark received' : 'Mark paid'}${amount !== null ? ` ${formatMoney(Number(amount), { currency: entry.currency })}` : ''}`}
      </button>
    </form>
  )
}

function AmountForm({ entry, actions, onResult }: FormProps) {
  const [text, setText] = useState(entry.amount !== null && !entry.estimated ? entry.amount.toFixed(2) : '')
  const parsed = parseAmount(text)
  const hint = entry.amount !== null && entry.estimated ? `Usually ≈ ${formatMoney(entry.amount, { currency: entry.currency })}` : undefined
  return (
    <form className="entry__form"
      onSubmit={async (e) => { e.preventDefault(); if (parsed) onResult(await actions.setAmount(parsed)) }}>
      <label className="ui-field">
        <span className="ui-field__label">Amount</span>
        <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" value={text} placeholder={hint}
          aria-invalid={parsed === undefined} onChange={(e) => setText(e.target.value)} />
      </label>
      {parsed === undefined && <p className="ui-field__error">Enter an amount like 86.40</p>}
      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={!parsed || actions.busy}>Save amount</button>
    </form>
  )
}
```

`web/src/features/plan/entry.css`:

```css
/* Entry sheet (spec §4.6). */
.entry { display: flex; flex-direction: column; gap: 16px; }
.entry__summary { display: flex; flex-direction: column; gap: 6px; }
.entry__amount { font-size: 36px; }
.entry__due { margin: 0; font-size: 14px; color: var(--muted); }
.entry__badges { display: flex; flex-wrap: wrap; gap: 6px; }
.entry__actions, .entry__form { display: flex; flex-direction: column; gap: 10px; }
.entry__question { margin: 0; color: var(--ink-2); }
.entry__problem {
  margin: 0; padding: 10px 12px; border-radius: var(--r-md);
  background: var(--neg-soft); color: var(--neg); font-size: 14px; font-weight: 550;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/plan/entryPatch.test.ts src/features/plan/EntrySheet.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit and tag**

```bash
git add web/src/features/plan/hooks.ts web/src/features/plan/entryPatch.ts web/src/features/plan/entryPatch.test.ts web/src/features/plan/EntrySheet.tsx web/src/features/plan/EntrySheet.test.tsx web/src/features/plan/entry.css
git commit -m "feat(web): plan hooks, optimistic entry patch and the Entry sheet"
git tag 2a-c1
```

---

### Task C2: Upcoming

**Stream:** C. **Depends on:** C1.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/plan.css` (every Plan view's styles: Upcoming, Month, Year, Budgets and the screen)
- Create: `web/src/features/plan/Upcoming.tsx`, `web/src/features/plan/Upcoming.test.tsx`

**Interfaces:**
- Consumes: `usePlanUpcoming` (C1), `EntrySheet` (C1), `usePendingIds`, `QueryView`, `EmptyState`, `List`, `ListRow`, `Money`, `Badge`, the icons, `formatDayHeader`.
- Produces: `Upcoming()` (no props).

**Behaviour (spec §4.1):**
- Days come from `GET /plan/upcoming?days=30`. Days with no entries are skipped. Each day is a `<section>` labelled by its "Mon 26 Oct" heading, and the header shows "Net this month" with the signed running net.
- Each row is a button and shows:
  - the direction tile (in: `ui-ico--pos` with the arrow-in icon; out: `ui-ico--neutral`);
  - the name;
  - "In" or "Out" as text;
  - the amount (in rows signed with `tone="auto"`, plus "≈" when estimated; "No amount yet" when null);
  - badges: "Waiting to sync" when pending, and Paid/Received/Skipped while an optimistic status is showing.
- Tapping a row opens the Entry sheet.
- Empty: "Nothing due in the next 30 days" with an "Add a recurring item" link to `/plan/items?new=1`.

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/Upcoming.test.tsx`:

```tsx
import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { markPending } from '../../data/pending'
import { fakeApi } from '../../test/fakeApi'
import { day, entry, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { Upcoming } from './Upcoming'

afterEach(resetTestEnv)

const days = [
  day('2026-10-09', [entry()], 1161.1),
  day('2026-10-20', [], 1161.1),
  day('2026-10-26', [entry({ id: 'e2', item_id: 'i2', name: 'Salary', direction: 'in', due_date: '2026-10-26', amount: 1500, estimated: true })], 2661.1),
  day('2026-11-02', [entry({ id: 'e3', item_id: 'i3', name: 'Electricity', due_date: '2026-11-02', amount: null })], 0),
]

it('groups entries under day headings with the running net, marking estimates and missing amounts', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  const oct26 = await screen.findByRole('region', { name: 'Mon 26 Oct' })
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Fri 9 Oct', 'Mon 26 Oct', 'Mon 2 Nov'])
  expect(oct26).toHaveTextContent('Net this month +€2,661.10')
  expect(within(oct26).getByRole('button', { name: /Salary/ })).toHaveTextContent('≈ +€1,500.00')
  expect(screen.getByRole('region', { name: 'Mon 2 Nov' })).toHaveTextContent('No amount yet')
  expect(document.body.textContent).not.toContain('NaN')
})

it('tapping a row opens the Entry sheet', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  fireEvent.click(await screen.findByRole('button', { name: /Cosmote/ }))
  expect(screen.getByRole('dialog', { name: 'Cosmote' })).toBeInTheDocument()
})

it('marks rows whose change is waiting to sync', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  act(() => markPending('e1'))
  expect(await screen.findByRole('button', { name: /Cosmote/ })).toHaveTextContent('Waiting to sync')
})

it('empty: says nothing is due and links to a new item', async () => {
  fakeApi({ 'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [], 0)] })
  renderWithProviders(<Upcoming />)
  expect(await screen.findByText('Nothing due in the next 30 days')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Add a recurring item' })).toHaveAttribute('href', '/plan/items?new=1')
})

it('offline with nothing saved', async () => {
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<Upcoming />)
  expect(await screen.findByText('No saved data yet. Connect once to load Plan.')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/Upcoming.test.tsx`
Expected: FAIL (`./Upcoming` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/Upcoming.tsx`:

```tsx
import { useState } from 'react'
import { usePendingIds } from '../../data/pending'
import type { EntryOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatDayHeader } from '../../ui/format'
import { ArrowInIcon, ArrowOutIcon, CheckIcon, ClockIcon } from '../../ui/icons'
import { List, ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { EntrySheet } from './EntrySheet'
import { usePlanUpcoming } from './hooks'
import './plan.css'

export function Upcoming() {
  const upcoming = usePlanUpcoming()
  const pending = usePendingIds()
  const [open, setOpen] = useState<EntryOut | null>(null)

  return (
    <>
      <QueryView result={upcoming} noDataText="No saved data yet. Connect once to load Plan.">
        {(all) => {
          const days = all.filter((d) => d.entries.length > 0)
          if (days.length === 0) {
            return (
              <EmptyState title="Nothing due in the next 30 days"
                action={{ label: 'Add a recurring item', to: '/plan/items?new=1' }} />
            )
          }
          return (
            <div className="plan-days">
              {days.map((d) => (
                <section key={d.date} className="plan-day" aria-labelledby={`day-${d.date}`}>
                  <header className="plan-day__head">
                    <h3 id={`day-${d.date}`} className="plan-day__title">{formatDayHeader(d.date)}</h3>
                    <span className="plan-day__net">Net this month <Money amount={d.net_this_month} signed /></span>
                  </header>
                  <List>
                    {d.entries.map((e) => (
                      <EntryRow key={e.id} entry={e} pending={pending.has(e.id)} onOpen={() => setOpen(e)} />
                    ))}
                  </List>
                </section>
              ))}
            </div>
          )
        }}
      </QueryView>
      <EntrySheet entry={open} onClose={() => setOpen(null)} />
    </>
  )
}

function EntryRow({ entry, pending, onOpen }: { entry: EntryOut; pending: boolean; onOpen: () => void }) {
  const isIn = entry.direction === 'in'
  const badges = [
    pending && <Badge key="sync" icon={<ClockIcon />}>Waiting to sync</Badge>,
    entry.status === 'done' && <Badge key="done" tone="pos" icon={<CheckIcon />}>{isIn ? 'Received' : 'Paid'}</Badge>,
    entry.status === 'skipped' && <Badge key="skip">Skipped</Badge>,
  ].filter(Boolean)
  return (
    <ListRow
      onClick={onOpen}
      leading={<span className={isIn ? 'ui-ico ui-ico--pos' : 'ui-ico ui-ico--neutral'}>{isIn ? <ArrowInIcon /> : <ArrowOutIcon />}</span>}
      title={entry.name}
      subtitle={isIn ? 'In' : 'Out'}
      badges={badges.length ? badges : undefined}
      trailing={
        <Money amount={entry.amount} currency={entry.currency} estimated={entry.estimated}
          signed={isIn} tone={isIn ? 'auto' : 'none'} nullText="No amount yet" />
      }
    />
  )
}
```

`web/src/features/plan/plan.css`:

```css
/* Plan tab: the screen, Upcoming, Month, Year, Budgets. Kit classes come from ui/ui.css. */
.plan { display: flex; flex-direction: column; gap: 16px; }
.plan__seg { position: sticky; top: calc(env(safe-area-inset-top) + 60px); z-index: 3; }

/* Upcoming */
.plan-days { display: flex; flex-direction: column; gap: 18px; }
.plan-day__head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding: 0 2px 6px; }
.plan-day__title { margin: 0; font-size: 13px; font-weight: 650; color: var(--ink-2); }
.plan-day__net { font-size: 12.5px; color: var(--muted); white-space: nowrap; }
.plan-day__net .ui-money { color: var(--ink-2); }

/* Month */
.plan-month { display: flex; flex-direction: column; gap: 14px; }
.plan-switch { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.plan-switch__label { margin: 0; font-size: 16px; font-weight: 650; }
.plan-net { display: flex; flex-direction: column; gap: 4px; }
.plan-net__figure { font-size: 40px; }
.plan-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.plan-table th, .plan-table td { padding: 9px 4px; text-align: right; border-bottom: 1px solid var(--line); }
.plan-table thead th { font-size: 11.5px; font-weight: 600; color: var(--muted); }
.plan-table th[scope="row"] { text-align: left; font-weight: 600; color: var(--ink-2); white-space: nowrap; }
.plan-table .ui-money { font-size: 13px; }
.plan-bucket__chev { display: grid; color: var(--muted); transition: transform .2s ease; }
.plan-bucket button[aria-expanded="true"] .plan-bucket__chev { transform: rotate(180deg); }
.plan-bucket__detail { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0; padding: 0 14px 12px; }
.plan-bucket__detail dt { font-size: 11.5px; font-weight: 600; color: var(--muted); }
.plan-bucket__detail dd { margin: 2px 0 0; font-size: 14px; }
.plan-aside { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--ink-2); }
.plan-aside__note { margin: 0; font-size: 12px; color: var(--muted); }
.plan-usual__row--flagged { background: var(--warn-soft); }
.plan-usual__icon { width: 36px; height: 36px; display: grid; place-items: center; border-radius: var(--r-sm); background: var(--surface-2); font-size: 18px; }

/* Year */
.plan-year__rows { list-style: none; margin: 0; padding: 0; }
.plan-year__row { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--line); }
.plan-year__month { font-size: 13px; font-weight: 650; color: var(--ink-2); }
.plan-year__bars { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.plan-year__bar { display: block; height: 6px; border-radius: 3px; }
.plan-year__bar--in { background: var(--pos); }
.plan-year__bar--out { background: var(--c6); }
.plan-year__vals { display: flex; flex-direction: column; align-items: flex-end; font-size: 11.5px; line-height: 1.35; color: var(--muted); }
.plan-year__vals .ui-money { font-size: 12px; color: var(--ink-2); }
.plan-year__foot { margin: 12px 0 0; font-size: 13px; color: var(--muted); }

/* Budgets */
.plan-budget { display: flex; flex-direction: column; gap: 10px; padding: 14px; }
.plan-budget + .plan-budget { border-top: 1px solid var(--line); }
.plan-budget__top { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.plan-budget__name { min-width: 0; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plan-budget__fig { font-size: 13.5px; color: var(--ink-2); white-space: nowrap; }
.plan-budget__foot { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; font-size: 12.5px; color: var(--muted); }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/Upcoming.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/plan.css web/src/features/plan/Upcoming.tsx web/src/features/plan/Upcoming.test.tsx
git commit -m "feat(web): Plan › Upcoming grouped by day with running net"
```

---
### Task C3: Month

**Stream:** C. **Depends on:** C2.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/Month.tsx`, `web/src/features/plan/Month.test.tsx`

**Interfaces:**
- Consumes: `usePlanMonth`, `useCategoriesVsUsual` (C1), `QueryView`, `ListRow`, `Money`, `Badge`, the icons, `formatMonthLabel`, `monthsBetween`, `shiftMonth`, `todayISO`; `useSearchParams` (react-router).
- Produces: `Month()`, `MAX_MONTH_SHIFT = 11`.

**Behaviour (spec §4.2):**
- The month comes from the URL `?month=YYYY-MM`. It defaults to the current month and falls back to it when the value is malformed or more than 11 months away.
- The switcher has "Previous month" and "Next month" buttons, disabled at ±11. Moving writes `month` to the URL with `replace`.
- **Net (projected)** is the big figure: signed, with "≈" when `estimated`.
- The table has the rows In, Out · Fixed and Out · Buckets, and the columns So far, To come and Projected. Figures are whole euros so the table fits at 360 px. "≈" goes on To come and Projected when `estimated`.
- Bucket rows expand (`aria-expanded`) to show budget ("No budget" when null), so far and projected.
- The separate lines read "Trips & events: €X" and "Cash not yet logged: €X", with the note "Not counted in Net."
- Categories vs usual is a list:
  - the subtitle is "Usual €300", or "Usual —" when there is no usual;
  - flagged rows get the warn tint plus an "above usual" badge.

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/Month.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { categoryUsual, monthPicture } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Month } from './Month'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12)) // Wed 7 Oct 2026
})
afterEach(resetTestEnv)

const routes = () => ({
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/insights/categories-vs-usual': () => [
    categoryUsual(),
    categoryUsual({ category_id: 'c2', name: 'Fuel', this_month: 80, usual: null, flagged: false }),
  ],
})

it('shows Net (projected), the in/out table and the lines kept out of Net', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />, { route: '/plan?view=month' })
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 3, name: 'Oct 2026' })).toBeInTheDocument()
  const fixed = screen.getByRole('rowheader', { name: 'Out · Fixed' }).closest('tr')!
  expect(fixed).toHaveTextContent('Out · Fixed€600€239€839')
  expect(screen.getByRole('rowheader', { name: 'In' }).closest('tr')).toHaveTextContent('In€3,150€1,500€4,650')
  expect(screen.getByText(/Trips & events/)).toHaveTextContent('Trips & events: €410.00')
  expect(screen.getByText(/Cash not yet logged/)).toHaveTextContent('Cash not yet logged: €45.00')
})

it('bucket rows expand to budget, so far and projected; a missing budget says so', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />)
  const kids = await screen.findByRole('button', { name: /Kids/ })
  expect(kids).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(kids)
  expect(kids).toHaveAttribute('aria-expanded', 'true')
  expect(kids.parentElement).toHaveTextContent('No budget')
  fireEvent.click(screen.getByRole('button', { name: /Day to day/ }))
  expect(screen.getByRole('button', { name: /Day to day/ }).parentElement).toHaveTextContent('Budget€1,200')
})

it('categories vs usual: flagged rows say "above usual"; no usual shows —', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />)
  const list = await screen.findByRole('region', { name: 'Categories vs usual' })
  expect(within(list).getByText('Groceries').closest('.ui-row')).toHaveTextContent('above usual')
  expect(within(list).getByText('Fuel').closest('.ui-row')).toHaveTextContent('Usual —')
  expect(within(list).getByText('Fuel').closest('.ui-row')).not.toHaveTextContent('above usual')
})

it('estimates show ≈', async () => {
  fakeApi({ ...routes(), 'GET /api/v1/plan/month': () => monthPicture({ estimated: true }) })
  renderWithProviders(<Month />)
  expect(await screen.findByText('≈ +€2,311.10')).toBeInTheDocument()
})

it('the switcher crosses the year end and asks for the new month', async () => {
  const fake = fakeApi(routes())
  const { router } = renderWithProviders(<Month />, { route: '/plan?view=month&month=2026-12' })
  expect(await screen.findByRole('heading', { level: 3, name: 'Dec 2026' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
  expect(screen.getByRole('heading', { level: 3, name: 'Jan 2027' })).toBeInTheDocument()
  expect(router.state.location.search).toBe('?view=month&month=2027-01')
  await waitFor(() =>
    expect(fake.callsTo('GET /api/v1/plan/month').map((c) => c.query.get('month'))).toContain('2027-01'))
})

it('stops 11 months either side and ignores an out-of-range month in the URL', async () => {
  fakeApi(routes())
  const { unmount } = renderWithProviders(<Month />, { route: '/plan?month=2027-09' })
  expect(await screen.findByRole('button', { name: 'Next month' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Previous month' })).toBeEnabled()
  unmount()
  const second = renderWithProviders(<Month />, { route: '/plan?month=2025-11' })
  expect(await screen.findByRole('button', { name: 'Previous month' })).toBeDisabled()
  second.unmount()
  renderWithProviders(<Month />, { route: '/plan?month=2030-01' })
  expect(await screen.findByRole('heading', { level: 3, name: 'Oct 2026' })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/Month.test.tsx`
Expected: FAIL (`./Month` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/Month.tsx`:

```tsx
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import type { BucketMonthRowOut, CategoryUsualOut, MonthPictureOut, MonthRowOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { formatMonthLabel, monthsBetween, shiftMonth, todayISO } from '../../ui/format'
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { useCategoriesVsUsual, usePlanMonth } from './hooks'
import './plan.css'

export const MAX_MONTH_SHIFT = 11
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/

export function Month() {
  const [params, setParams] = useSearchParams()
  const current = todayISO().slice(0, 7)
  const asked = params.get('month')
  const month = asked && MONTH.test(asked) && Math.abs(monthsBetween(current, asked)) <= MAX_MONTH_SHIFT ? asked : current
  const offset = monthsBetween(current, month)
  const go = (by: number) => {
    const next = new URLSearchParams(params)
    next.set('month', shiftMonth(month, by))
    setParams(next, { replace: true })
  }
  const picture = usePlanMonth(month)
  const usual = useCategoriesVsUsual(month)

  return (
    <div className="plan-month">
      <div className="plan-switch">
        <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Previous month"
          disabled={offset <= -MAX_MONTH_SHIFT} onClick={() => go(-1)}><ChevronLeftIcon /></button>
        <h3 className="plan-switch__label" aria-live="polite">{formatMonthLabel(month)}</h3>
        <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Next month"
          disabled={offset >= MAX_MONTH_SHIFT} onClick={() => go(1)}><ChevronRightIcon /></button>
      </div>
      <QueryView result={picture} noDataText="No saved data yet. Connect once to load Plan.">
        {(p) => <MonthPicture picture={p} />}
      </QueryView>
      {usual.data && usual.data.length > 0 && <CategoriesVsUsual rows={usual.data} />}
    </div>
  )
}

function MonthPicture({ picture: p }: { picture: MonthPictureOut }) {
  const est = p.estimated
  const rows: [string, MonthRowOut][] = [['In', p.income], ['Out · Fixed', p.fixed], ['Out · Buckets', p.buckets]]
  return (
    <>
      <div className="ui-card plan-net">
        <p className="ui-eyebrow">Net (projected)</p>
        <Money className="ui-figure plan-net__figure" amount={p.net_projected} signed estimated={est} />
      </div>
      <table className="plan-table">
        <caption className="ui-sr">In and out this month</caption>
        <thead>
          <tr><td /><th scope="col">So far</th><th scope="col">To come</th><th scope="col">Projected</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, r]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td><Money amount={r.so_far} whole /></td>
              <td><Money amount={r.still_to_come} whole estimated={est} /></td>
              <td><Money amount={r.projected} whole estimated={est} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <BucketRows rows={p.buckets.rows} estimated={est} />
      <ul className="plan-aside">
        <li>Trips & events: <Money amount={p.events_spent} /></li>
        <li>Cash not yet logged: <Money amount={p.cash} /></li>
      </ul>
      <p className="plan-aside__note">Not counted in Net.</p>
    </>
  )
}

function BucketRows({ rows, estimated }: { rows: BucketMonthRowOut[]; estimated: boolean }) {
  const [open, setOpen] = useState<string | null>(null)
  if (rows.length === 0) return null
  return (
    <div className="ui-list">
      {rows.map((b) => {
        const expanded = open === b.bucket_id
        return (
          <div key={b.bucket_id} className="plan-bucket">
            <button type="button" className="ui-row" aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : b.bucket_id)}>
              <span className="ui-row__main"><span className="ui-row__title">{b.name}</span></span>
              <span className="ui-row__end"><Money amount={b.projected} whole estimated={estimated} /></span>
              <span className="plan-bucket__chev" aria-hidden="true"><ChevronDownIcon /></span>
            </button>
            {expanded && (
              <dl className="plan-bucket__detail">
                <div><dt>Budget</dt><dd>{b.budget === null ? 'No budget' : <Money amount={b.budget} whole />}</dd></div>
                <div><dt>So far</dt><dd><Money amount={b.so_far} whole /></dd></div>
                <div><dt>Projected</dt><dd><Money amount={b.projected} whole estimated={estimated} /></dd></div>
              </dl>
            )}
          </div>
        )
      })}
    </div>
  )
}

function CategoriesVsUsual({ rows }: { rows: CategoryUsualOut[] }) {
  return (
    <section aria-labelledby="usual-title">
      <div className="ui-sec"><h3 id="usual-title" className="ui-sec__title">Categories vs usual</h3></div>
      <div className="ui-list">
        {rows.map((c) => (
          <ListRow key={c.category_id ?? c.name}
            className={c.flagged ? 'plan-usual__row--flagged' : undefined}
            leading={<span className="plan-usual__icon" aria-hidden="true">{c.icon}</span>}
            title={c.name}
            subtitle={c.usual === null ? 'Usual —' : <>Usual <Money amount={c.usual} whole /></>}
            badges={c.flagged ? <Badge tone="warn">above usual</Badge> : undefined}
            trailing={<Money amount={c.this_month} whole />} />
        ))}
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/Month.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/Month.tsx web/src/features/plan/Month.test.tsx
git commit -m "feat(web): Plan › Month with switcher, table, buckets and categories vs usual"
```

---

### Task C4: Year

**Stream:** C. **Depends on:** C3.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/Year.tsx`, `web/src/features/plan/Year.test.tsx`

**Interfaces:**
- Consumes: `usePlanYear` (C1), `QueryView`, `Money`, `formatMonthShort`.
- Produces: `Year()`.

**Behaviour (spec §4.3):**
- There are 12 rows. Each row shows the month, an in bar (`--pos`) and an out bar (`--c6`), and the labels "In €X", "Out €Y" and "Net ±€Z" with `tone="auto"`.
- Both bars are scaled to the year's largest in or out value. When that maximum is 0, every bar is 0% wide (never NaN).
- Rows with `estimated` show "≈" on their values.
- The footer reads "Yearly and quarterly bills average €X/month".

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/Year.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { yearMonth, yearOut } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Year } from './Year'

afterEach(resetTestEnv)

const widths = (cls: string) =>
  Array.from(document.querySelectorAll<HTMLElement>(`.${cls}`)).map((el) => el.style.width)

it('scales both bars to the largest value of the year and writes the values out', async () => {
  fakeApi({
    'GET /api/v1/plan/year': () =>
      yearOut([yearMonth('2026-10', 3000, 1500), yearMonth('2026-11', 1500, 3000, true), yearMonth('2026-12', 0, 0)]),
  })
  renderWithProviders(<Year />)
  const oct = (await screen.findByText('Oct')).closest('li')!
  expect(oct).toHaveTextContent('In €3,000')
  expect(oct).toHaveTextContent('Out €1,500')
  expect(oct).toHaveTextContent('Net +€1,500')
  expect(widths('plan-year__bar--in')).toEqual(['100%', '50%', '0%'])
  expect(widths('plan-year__bar--out')).toEqual(['50%', '100%', '0%'])
  expect(screen.getByText('Nov').closest('li')).toHaveTextContent('Net ≈ −€1,500')
  expect(screen.getByText(/Yearly and quarterly bills average/)).toHaveTextContent('Yearly and quarterly bills average €42.50/month')
})

it('an all-zero year draws empty bars, not NaN', async () => {
  fakeApi({ 'GET /api/v1/plan/year': () => yearOut([yearMonth('2026-10', 0, 0), yearMonth('2026-11', 0, 0)]) })
  renderWithProviders(<Year />)
  await screen.findByText('Oct')
  expect(widths('plan-year__bar--in')).toEqual(['0%', '0%'])
  expect(document.body.textContent).not.toContain('NaN')
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/Year.test.tsx`
Expected: FAIL (`./Year` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/Year.tsx`:

```tsx
import type { YearOut } from '../../data/types'
import { formatMonthShort } from '../../ui/format'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { usePlanYear } from './hooks'
import './plan.css'

export function Year() {
  const year = usePlanYear()
  return (
    <QueryView result={year} noDataText="No saved data yet. Connect once to load Plan.">
      {(y) => <YearBars year={y} />}
    </QueryView>
  )
}

function YearBars({ year }: { year: YearOut }) {
  const max = Math.max(0, ...year.months.flatMap((m) => [m.income, m.out]))
  const width = (v: number) => `${max > 0 ? Math.min(100, Math.max(0, (v / max) * 100)) : 0}%`
  return (
    <div className="plan-year">
      <ul className="plan-year__rows">
        {year.months.map((m) => (
          <li key={m.month} className="plan-year__row">
            <span className="plan-year__month">{formatMonthShort(m.month)}</span>
            <div className="plan-year__bars" aria-hidden="true">
              <span className="plan-year__bar plan-year__bar--in" style={{ width: width(m.income) }} />
              <span className="plan-year__bar plan-year__bar--out" style={{ width: width(m.out) }} />
            </div>
            <span className="plan-year__vals">
              <span>In <Money amount={m.income} whole estimated={m.estimated} /></span>
              <span>Out <Money amount={m.out} whole estimated={m.estimated} /></span>
              <span>Net <Money amount={m.income - m.out} whole signed tone="auto" estimated={m.estimated} /></span>
            </span>
          </li>
        ))}
      </ul>
      <p className="plan-year__foot">
        Yearly and quarterly bills average <Money amount={year.infrequent_monthly_average} />/month
      </p>
    </div>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/Year.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/Year.tsx web/src/features/plan/Year.test.tsx
git commit -m "feat(web): Plan › Year with CSS bars scaled to the year"
```

---

### Task C5: Budgets

**Stream:** C. **Depends on:** C4.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/Budgets.tsx`, `web/src/features/plan/Budgets.test.tsx`

**Interfaces:**
- Consumes: `useBudgets`, `usePace` (C1), `QueryView`, `EmptyState`, `ProgressBar`, `Badge`, `Money`, `formatShortDate`.
- Produces: `Budgets()`.

**Behaviour (spec §4.4):**
- Each bucket has a row: the name and "€904 of €1,200" in whole euros.
  - Without a budget it shows "€120 spent" and no bar.
  - With a budget there is a `ProgressBar`, labelled with the bucket name, whose tone changes at 80% and 100%.
- When the pace row has a non-null `pace` (the server sends null before the 7th), the row adds "on pace for €1,310". When `over_pace` is set it also adds an "over pace" badge.
- At or over 100% the row adds an "over budget" badge.
- Event buckets show "1 Oct – 12 Oct", then "N days left" ("1 day left" for one), then an "Archive?" badge when `archive_suggested`. The badge is a label only; 2d adds the button.
- With no rows the screen shows "No budgets yet".

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/Budgets.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { budgetRow, pace } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Budgets } from './Budgets'

afterEach(resetTestEnv)

const rows = [
  budgetRow(),
  budgetRow({ bucket_id: 'b2', name: 'Kids', budget: 300, spent: 255, pct: 85 }),
  budgetRow({ bucket_id: 'b3', name: 'Fun', budget: 200, spent: 208, pct: 104 }),
  budgetRow({ bucket_id: 'b4', name: 'Gifts', budget: null, spent: 120, pct: null }),
  budgetRow({
    bucket_id: 'b5', name: 'Naxos trip', kind: 'event', budget: 900, spent: 610, pct: 67.8,
    period_start: '2026-10-01', period_end: '2026-10-12', days_left: 5, archive_suggested: true,
  }),
]

it('tints bars at 80% and 100%, with words as well as colour', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => rows, 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  expect(await screen.findByRole('progressbar', { name: 'Day to day' })).toHaveAttribute('data-tone', 'ok')
  expect(screen.getByRole('progressbar', { name: 'Kids' })).toHaveAttribute('data-tone', 'warn')
  expect(screen.getByRole('progressbar', { name: 'Fun' })).toHaveAttribute('data-tone', 'over')
  expect(screen.getByText('Fun').closest('.plan-budget')).toHaveTextContent('over budget')
  expect(screen.getByText('Day to day').closest('.plan-budget')).toHaveTextContent('€904 of €1,200')
})

it('a bucket without a budget shows its spend and no bar', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => rows, 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  const gifts = (await screen.findByText('Gifts')).closest('.plan-budget')!
  expect(gifts).toHaveTextContent('€120 spent')
  expect(screen.queryByRole('progressbar', { name: 'Gifts' })).toBeNull()
  expect(document.body.textContent).not.toContain('NaN')
})

it('pace: "on pace for" and the over-pace marker; nothing before day 7 (pace null)', async () => {
  fakeApi({
    'GET /api/v1/plan/budgets': () => rows,
    'GET /api/v1/plan/pace': () => [pace(), pace({ bucket_id: 'b2', name: 'Kids', pace: null, over_pace: false })],
  })
  renderWithProviders(<Budgets />)
  const day2day = (await screen.findByText('Day to day')).closest('.plan-budget')!
  await screen.findByText(/on pace for/)
  expect(day2day).toHaveTextContent('on pace for €1,310')
  expect(day2day).toHaveTextContent('over pace')
  expect(screen.getByText('Kids').closest('.plan-budget')).not.toHaveTextContent('on pace')
})

it('event buckets show their dates, days left and the Archive? label', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => rows, 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  const trip = (await screen.findByText('Naxos trip')).closest('.plan-budget')!
  expect(trip).toHaveTextContent('1 Oct – 12 Oct')
  expect(trip).toHaveTextContent('5 days left')
  expect(trip).toHaveTextContent('Archive?')
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/Budgets.test.tsx`
Expected: FAIL (`./Budgets` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/Budgets.tsx`:

```tsx
import type { BudgetRowOut, PaceOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatShortDate } from '../../ui/format'
import { Money } from '../../ui/Money'
import { ProgressBar } from '../../ui/ProgressBar'
import { QueryView } from '../../ui/QueryView'
import { useBudgets, usePace } from './hooks'
import './plan.css'

export function Budgets() {
  const budgets = useBudgets()
  const pace = usePace()
  return (
    <QueryView result={budgets} noDataText="No saved data yet. Connect once to load Plan.">
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState title="No budgets yet" body="Budgets are set on buckets." />
        ) : (
          <div className="ui-list">
            {rows.map((b) => (
              <BudgetRow key={b.bucket_id} row={b} pace={pace.data?.find((p) => p.bucket_id === b.bucket_id)} />
            ))}
          </div>
        )
      }
    </QueryView>
  )
}

function BudgetRow({ row, pace }: { row: BudgetRowOut; pace?: PaceOut }) {
  const event = row.kind === 'event'
  const days = row.days_left
  return (
    <div className="plan-budget">
      <div className="plan-budget__top">
        <span className="plan-budget__name">{row.name}</span>
        <span className="plan-budget__fig">
          {row.budget === null
            ? <><Money amount={row.spent} whole /> spent</>
            : <><Money amount={row.spent} whole /> of <Money amount={row.budget} whole /></>}
        </span>
      </div>
      {row.budget !== null && row.budget > 0 && <ProgressBar value={row.spent} max={row.budget} label={row.name} />}
      <div className="plan-budget__foot">
        {event && row.period_start && row.period_end && (
          <span>{formatShortDate(row.period_start)} – {formatShortDate(row.period_end)}</span>
        )}
        {event && days !== null && <span>{days === 1 ? '1 day left' : `${days} days left`}</span>}
        {pace && pace.pace !== null && <span>on pace for <Money amount={pace.pace} whole /></span>}
        {pace && pace.pace !== null && pace.over_pace && <Badge tone="warn">over pace</Badge>}
        {row.pct !== null && row.pct >= 100 && <Badge tone="neg">over budget</Badge>}
        {event && row.archive_suggested && <Badge>Archive?</Badge>}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/Budgets.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/Budgets.tsx web/src/features/plan/Budgets.test.tsx
git commit -m "feat(web): Plan › Budgets with thresholds, pace and event buckets"
```

---

### Task C6: The Plan screen

**Stream:** C. **Depends on:** C5.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/Plan.tsx`, `web/src/features/plan/Plan.test.tsx`
- Modify: `web/src/screens/Plan.tsx` (becomes a one-line re-export)

**Interfaces:**
- Consumes: `Upcoming`, `Month`, `Year`, `Budgets` (C2–C5), `TopBar` (with `actions`, A8), `Segmented`.
- Produces: `Plan()`, re-exported by `screens/Plan.tsx`, so `router.tsx` is unchanged here.

**Behaviour (spec §4):**
- The segmented control **Upcoming · Month · Year · Budgets** is backed by `?view=`. Upcoming is the default and has no parameter.
- Switching views drops `month`. Switching uses `replace`, so Back leaves the tab rather than walking through the views.
- The top bar has an **Items** link to `/plan/items` (D5 adds that route; until D merges, the catch-all redirects).

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/Plan.test.tsx`:

```tsx
import { fireEvent, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { budgetRow, categoryUsual, day, entry, monthPicture, readRoutes, yearMonth, yearOut } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Plan } from './Plan'

afterEach(resetTestEnv)

const routes = () => ({
  ...readRoutes(),
  'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry()], 961.1)],
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/insights/categories-vs-usual': () => [categoryUsual()],
  'GET /api/v1/plan/year': () => yearOut([yearMonth('2026-10', 3000, 1500)]),
  'GET /api/v1/plan/budgets': () => [budgetRow()],
  'GET /api/v1/plan/pace': () => [],
})

it('opens on Upcoming and switches views through the URL', async () => {
  fakeApi(routes())
  const { router } = renderWithProviders(<Plan />, { route: '/plan' })
  expect(screen.getByRole('heading', { level: 1, name: 'Plan' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByRole('region', { name: 'Fri 9 Oct' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Budgets' }))
  expect(router.state.location.search).toBe('?view=budgets')
  expect(await screen.findByRole('progressbar', { name: 'Day to day' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Year' }))
  expect(await screen.findByText(/Yearly and quarterly bills average/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Upcoming' }))
  expect(router.state.location.search).toBe('')
})

it('has an Items link in the top bar', () => {
  fakeApi(routes())
  renderWithProviders(<Plan />, { route: '/plan?view=month' })
  expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('link', { name: 'Items' })).toHaveAttribute('href', '/plan/items')
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/Plan.test.tsx`
Expected: FAIL (`./Plan` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/Plan.tsx`:

```tsx
import { Link, useSearchParams } from 'react-router'
import { TopBar } from '../../shell/TopBar'
import { Segmented } from '../../ui/Segmented'
import { Budgets } from './Budgets'
import { Month } from './Month'
import { Upcoming } from './Upcoming'
import { Year } from './Year'
import './plan.css'

const VIEWS = [
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
  { value: 'budgets', label: 'Budgets' },
] as const
type View = (typeof VIEWS)[number]['value']

export function Plan() {
  const [params, setParams] = useSearchParams()
  const view: View = VIEWS.find((v) => v.value === params.get('view'))?.value ?? 'upcoming'
  const choose = (v: View) => setParams(v === 'upcoming' ? {} : { view: v }, { replace: true })
  return (
    <>
      <TopBar title="Plan" actions={<Link to="/plan/items" className="btn btn--sm">Items</Link>} />
      <section className="screen plan">
        <div className="plan__seg">
          <Segmented label="Plan view" options={VIEWS} value={view} onChange={choose} />
        </div>
        {view === 'upcoming' && <Upcoming />}
        {view === 'month' && <Month />}
        {view === 'year' && <Year />}
        {view === 'budgets' && <Budgets />}
      </section>
    </>
  )
}
```

`web/src/screens/Plan.tsx` (the whole file):

```tsx
export { Plan } from '../features/plan/Plan'
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/plan && npm run typecheck && npm run lint`
Expected: PASS (every Plan test, C1–C6); lint reports no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/Plan.tsx web/src/features/plan/Plan.test.tsx web/src/screens/Plan.tsx
git commit -m "feat(web): Plan tab with Upcoming, Month, Year and Budgets segments"
```

---
## Stream D: Items and the Item sheet

All D files live in `web/src/features/plan/items/`, plus `web/src/router.tsx` (D5). D never edits a C file.

### Task D1: Schedule rules: choices, fields and summaries

**Stream:** D. **Depends on:** C1 (tag `2a-c1`), B1 merged into the branch.

**Worktree prep:** `cd /Users/giorgoscharitidis/expenses-2a-d/web && npm ci && grep -c "/api/v1/recurring/preview" src/api/schema.d.ts`. The count must be at least 1 (B1 is merged).

**Files:**
- Create: `web/src/features/plan/items/rule.ts`, `web/src/features/plan/items/rule.test.ts`

**Interfaces:**
- Consumes: `formatMonthName`, `formatShortDate`, `ordinal`, `parseISODate` (A1); `RecurringItemOut` (A1).
- Produces:
  - `RULE_KINDS`, `RuleKind`, `RULE_ADJUSTS`, `RuleAdjust`, `RuleChoice`, `RuleFields`;
  - `RULE_LABELS`, `ADJUST_LABELS`, `WEEKDAYS`;
  - `toRuleFields(c: RuleChoice): RuleFields`;
  - `fromRuleFields(r: StoredRule, startDate: string): RuleChoice`;
  - `defaultChoice(kind: RuleKind, startDate: string): RuleChoice`;
  - `ruleSummary(c: RuleChoice, startDate: string): string`.

**Mapping (spec §4.7, planning spec §3.2):**

| Choice | `rule_*` fields; every field not listed is `null` (`rule_adjust` `none`, `interval_months` 1) |
|---|---|
| On a day of the month | `rule_kind: monthly_day`, `rule_day`, `rule_adjust`, `interval_months` (kept from the item; not editable) |
| Last business day of the month | `rule_kind: last_business_day`, `interval_months` (kept) |
| Every year on a date | `rule_kind: yearly`, `rule_day`, `rule_month`, `rule_adjust` |
| Easter ± days (Orthodox) | `rule_kind: easter_offset`, `rule_days` (negative = before), `rule_adjust` |
| Every few weeks on a weekday | `rule_kind: weekly`, `rule_weekday` (0 = Monday), `rule_interval_weeks` |
| Every few months from the start date | `rule_kind: monthly_interval`, `interval_months` (also the legacy rule of every old bill) |

The yearly and Easter rules get the business-day adjustment too, because the Christmas bonus is "21 Dec, previous business day" (planning spec §3.2). The spec table names the adjustment only for the monthly day. The planning spec gives it to both, so the picker offers it for both.

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/items/rule.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { item } from '../../../test/fixtures'
import { defaultChoice, fromRuleFields, ruleSummary, toRuleFields, type RuleChoice, type RuleFields } from './rule'

const none: Omit<RuleFields, 'rule_kind'> = {
  interval_months: 1, rule_day: null, rule_month: null, rule_adjust: 'none', rule_days: null, rule_weekday: null, rule_interval_weeks: null,
}

const cases: [RuleChoice, RuleFields][] = [
  [{ kind: 'monthly_day', day: 26, adjust: 'previous_business_day', everyMonths: 1 },
    { ...none, rule_kind: 'monthly_day', rule_day: 26, rule_adjust: 'previous_business_day' }],
  [{ kind: 'last_business_day', everyMonths: 1 }, { ...none, rule_kind: 'last_business_day' }],
  [{ kind: 'yearly', day: 21, month: 12, adjust: 'previous_business_day' },
    { ...none, rule_kind: 'yearly', rule_day: 21, rule_month: 12, rule_adjust: 'previous_business_day' }],
  [{ kind: 'easter_offset', days: -4, adjust: 'none' }, { ...none, rule_kind: 'easter_offset', rule_days: -4 }],
  [{ kind: 'weekly', weekday: 4, everyWeeks: 2 }, { ...none, rule_kind: 'weekly', rule_weekday: 4, rule_interval_weeks: 2 }],
  [{ kind: 'monthly_interval', everyMonths: 3 }, { ...none, rule_kind: 'monthly_interval', interval_months: 3 }],
]

describe('toRuleFields / fromRuleFields', () => {
  it.each(cases)('%o maps to its rule_* fields and back', (choice, fields) => {
    expect(toRuleFields(choice)).toEqual(fields)
    expect(fromRuleFields(fields, '2026-10-01')).toEqual(choice)
  })

  it('keeps an item’s interval on the monthly kinds', () => {
    const c = fromRuleFields({ ...none, rule_kind: 'monthly_day', rule_day: 5, interval_months: 2 }, '2026-01-05')
    expect(toRuleFields(c).interval_months).toBe(2)
  })

  it('unknown or legacy kinds read as "every N months from the start date"', () => {
    expect(fromRuleFields({ ...none, rule_kind: 'something_old', interval_months: 1 }, '2026-01-09'))
      .toEqual({ kind: 'monthly_interval', everyMonths: 1 })
  })

  it('a fresh choice takes its numbers from the start date', () => {
    expect(defaultChoice('monthly_day', '2026-10-07')).toEqual({ kind: 'monthly_day', day: 7, adjust: 'none', everyMonths: 1 })
    expect(defaultChoice('yearly', '2026-10-07')).toEqual({ kind: 'yearly', day: 7, month: 10, adjust: 'none' })
    expect(defaultChoice('weekly', '2026-10-07')).toEqual({ kind: 'weekly', weekday: 2, everyWeeks: 1 }) // a Wednesday
    expect(defaultChoice('easter_offset', '2026-10-07')).toEqual({ kind: 'easter_offset', days: 0, adjust: 'none' })
  })
})

describe('ruleSummary', () => {
  it('reads like the spec', () => {
    const s = (c: RuleChoice, start = '2026-12-03') => ruleSummary(c, start)
    expect(s({ kind: 'monthly_day', day: 26, adjust: 'previous_business_day', everyMonths: 1 })).toBe('26th, or the business day before')
    expect(s({ kind: 'monthly_day', day: 1, adjust: 'none', everyMonths: 1 })).toBe('1st of the month')
    expect(s({ kind: 'monthly_day', day: 15, adjust: 'next_business_day', everyMonths: 2 }))
      .toBe('15th, or the business day after · every 2 months')
    expect(s({ kind: 'last_business_day', everyMonths: 1 })).toBe('Last business day')
    expect(s({ kind: 'yearly', day: 21, month: 12, adjust: 'previous_business_day' }))
      .toBe('Every year on 21 December, or the business day before')
    expect(s({ kind: 'easter_offset', days: -4, adjust: 'none' })).toBe('4 days before Easter')
    expect(s({ kind: 'easter_offset', days: 1, adjust: 'none' })).toBe('1 day after Easter')
    expect(s({ kind: 'easter_offset', days: 0, adjust: 'none' })).toBe('Easter Sunday')
    expect(s({ kind: 'weekly', weekday: 0, everyWeeks: 1 })).toBe('Every Monday')
    expect(s({ kind: 'weekly', weekday: 4, everyWeeks: 2 })).toBe('Every 2 weeks on Friday')
    expect(s({ kind: 'monthly_interval', everyMonths: 3 })).toBe('Every 3 months from 3 Dec')
    expect(s({ kind: 'monthly_interval', everyMonths: 1 })).toBe('Every month from 3 Dec')
  })

  it('works on stored items', () => {
    const cosmote = item()
    expect(ruleSummary(fromRuleFields(cosmote, cosmote.start_date), cosmote.start_date)).toBe('9th of the month')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/items/rule.test.ts`
Expected: FAIL (`./rule` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/items/rule.ts`:

```ts
import type { RecurringItemOut } from '../../../data/types'
import { formatMonthName, formatShortDate, ordinal, parseISODate } from '../../../ui/format'

export const RULE_KINDS = ['monthly_day', 'last_business_day', 'yearly', 'easter_offset', 'weekly', 'monthly_interval'] as const
export type RuleKind = (typeof RULE_KINDS)[number]
export const RULE_ADJUSTS = ['none', 'previous_business_day', 'next_business_day'] as const
export type RuleAdjust = (typeof RULE_ADJUSTS)[number]

/** What the picker edits: one shape per schedule choice (spec §4.7). */
export type RuleChoice =
  | { kind: 'monthly_day'; day: number; adjust: RuleAdjust; everyMonths: number }
  | { kind: 'last_business_day'; everyMonths: number }
  | { kind: 'yearly'; day: number; month: number; adjust: RuleAdjust }
  | { kind: 'easter_offset'; days: number; adjust: RuleAdjust }
  | { kind: 'weekly'; weekday: number; everyWeeks: number }
  | { kind: 'monthly_interval'; everyMonths: number }

/** What the API stores (RecurringItemIn / RulePreviewIn). */
export interface RuleFields {
  rule_kind: RuleKind
  interval_months: number
  rule_day: number | null
  rule_month: number | null
  rule_adjust: RuleAdjust
  rule_days: number | null
  rule_weekday: number | null
  rule_interval_weeks: number | null
}

type StoredRule = Pick<RecurringItemOut,
  'rule_kind' | 'interval_months' | 'rule_day' | 'rule_month' | 'rule_adjust' | 'rule_days' | 'rule_weekday' | 'rule_interval_weeks'>

export const RULE_LABELS: Record<RuleKind, string> = {
  monthly_day: 'On a day of the month',
  last_business_day: 'Last business day of the month',
  yearly: 'Every year on a date',
  easter_offset: 'Easter ± days (Orthodox)',
  weekly: 'Every few weeks on a weekday',
  monthly_interval: 'Every few months from the start date',
}

export const ADJUST_LABELS: Record<RuleAdjust, string> = {
  none: 'Exact day',
  previous_business_day: 'Business day before',
  next_business_day: 'Business day after',
}

export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const

const BLANK: RuleFields = {
  rule_kind: 'monthly_day', interval_months: 1, rule_day: null, rule_month: null, rule_adjust: 'none',
  rule_days: null, rule_weekday: null, rule_interval_weeks: null,
}

export function toRuleFields(c: RuleChoice): RuleFields {
  switch (c.kind) {
    case 'monthly_day':
      return { ...BLANK, rule_kind: c.kind, interval_months: c.everyMonths, rule_day: c.day, rule_adjust: c.adjust }
    case 'last_business_day':
      return { ...BLANK, rule_kind: c.kind, interval_months: c.everyMonths }
    case 'yearly':
      return { ...BLANK, rule_kind: c.kind, rule_day: c.day, rule_month: c.month, rule_adjust: c.adjust }
    case 'easter_offset':
      return { ...BLANK, rule_kind: c.kind, rule_days: c.days, rule_adjust: c.adjust }
    case 'weekly':
      return { ...BLANK, rule_kind: c.kind, rule_weekday: c.weekday, rule_interval_weeks: c.everyWeeks }
    case 'monthly_interval':
      return { ...BLANK, rule_kind: c.kind, interval_months: c.everyMonths }
  }
}

const asAdjust = (v: string): RuleAdjust => ((RULE_ADJUSTS as readonly string[]).includes(v) ? (v as RuleAdjust) : 'none')

/** A stored rule as a picker choice; missing numbers come from the start date. */
export function fromRuleFields(r: StoredRule, startDate: string): RuleChoice {
  const start = parseISODate(startDate)
  const every = r.interval_months > 0 ? r.interval_months : 1
  switch (r.rule_kind) {
    case 'monthly_day':
      return { kind: 'monthly_day', day: r.rule_day ?? start.getDate(), adjust: asAdjust(r.rule_adjust), everyMonths: every }
    case 'last_business_day':
      return { kind: 'last_business_day', everyMonths: every }
    case 'yearly':
      return { kind: 'yearly', day: r.rule_day ?? start.getDate(), month: r.rule_month ?? start.getMonth() + 1, adjust: asAdjust(r.rule_adjust) }
    case 'easter_offset':
      return { kind: 'easter_offset', days: r.rule_days ?? 0, adjust: asAdjust(r.rule_adjust) }
    case 'weekly':
      // JS: Sunday = 0; the API: Monday = 0.
      return { kind: 'weekly', weekday: r.rule_weekday ?? (start.getDay() + 6) % 7, everyWeeks: r.rule_interval_weeks ?? 1 }
    default:
      return { kind: 'monthly_interval', everyMonths: every }
  }
}

/** The choice the picker switches to when the user picks another kind. */
export function defaultChoice(kind: RuleKind, startDate: string): RuleChoice {
  return fromRuleFields({ ...BLANK, rule_kind: kind }, startDate)
}

const adjustText = (a: RuleAdjust) =>
  a === 'previous_business_day' ? ', or the business day before' : a === 'next_business_day' ? ', or the business day after' : ''
const everyText = (n: number) => (n > 1 ? ` · every ${n} months` : '')

/** Plain language: "26th, or the business day before", "Last business day". */
export function ruleSummary(c: RuleChoice, startDate: string): string {
  switch (c.kind) {
    case 'monthly_day':
      return `${ordinal(c.day)}${c.adjust === 'none' ? ' of the month' : adjustText(c.adjust)}${everyText(c.everyMonths)}`
    case 'last_business_day':
      return `Last business day${everyText(c.everyMonths)}`
    case 'yearly':
      return `Every year on ${c.day} ${formatMonthName(c.month)}${adjustText(c.adjust)}`
    case 'easter_offset': {
      const n = Math.abs(c.days)
      const base = c.days === 0 ? 'Easter Sunday' : `${n} day${n === 1 ? '' : 's'} ${c.days < 0 ? 'before' : 'after'} Easter`
      return base + adjustText(c.adjust)
    }
    case 'weekly':
      return c.everyWeeks === 1 ? `Every ${WEEKDAYS[c.weekday]}` : `Every ${c.everyWeeks} weeks on ${WEEKDAYS[c.weekday]}`
    case 'monthly_interval':
      return c.everyMonths === 1
        ? `Every month from ${formatShortDate(startDate)}`
        : `Every ${c.everyMonths} months from ${formatShortDate(startDate)}`
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/items/rule.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/items/rule.ts web/src/features/plan/items/rule.test.ts
git commit -m "feat(web): schedule rule choices, rule_* mapping and plain-language summaries"
```

---

### Task D2: Item form model, rule preview and item actions

**Stream:** D. **Depends on:** D1.

**Files:**
- Create: `web/src/features/plan/items/form.ts`, `web/src/features/plan/items/form.test.ts`
- Create: `web/src/features/plan/items/hooks.ts`, `web/src/features/plan/items/hooks.test.tsx`

**Interfaces:**
- Consumes: `toRuleFields`, `fromRuleFields`, `defaultChoice`, `RuleChoice` (D1); `useAction`, `useCachedQuery`, `unwrap`, `ApiError`, `keys`, `affects`, `useOnline`, `toTransactionPage`, `parseAmount` (A).
- Produces:
  - `ItemForm`, `emptyItemForm(today, me)`, `itemToForm(item)`, `validateItemForm(f): string | null`, `formToBody(f): RecurringItemIn`, `pendingItem(body, id): RecurringItemOut`;
  - `PREVIEW_DEBOUNCE_MS = 300`, `useDebouncedValue<T>(value, ms): T`;
  - `PreviewState = { state: 'loading' } | { state: 'ready'; dates: string[] } | { state: 'offline' } | { state: 'error'; message: string }`;
  - `useRulePreview(rule, startDate, endDate): PreviewState`;
  - `useItemHasHistory(itemId: string | null): boolean | undefined`;
  - `useItemActions(): { create, update, remove, busy }`, with:
    - `create({ body, tempId })`;
    - `update({ id, body })`;
    - `remove({ id })`, which is quiet on rejection.

**Notes:**
- `PUT /recurring/{id}` replaces the whole row, splits included. `ItemForm.keep` carries the fields the sheet doesn't edit (`payer_mode`, `splits`, `total_occurrences`, `contract_end_date`), so they survive every save (Review Focus 4).
- An In item never sends a bucket, auto-pay or shares (the server answers 400).
- "History" is `GET /transactions?recurring_bill_id=<id>&page_size=1` with `total > 0`. It locks the direction and hides Delete.
- `ActionSpec.body`'s type includes `unknown`, so a `body` function gets no contextual parameter type. Annotate its parameter.

- [ ] **Step 1: Write the failing tests**

`web/src/features/plan/items/form.test.ts`:

```ts
import { expect, it } from 'vitest'
import { item } from '../../../test/fixtures'
import { emptyItemForm, formToBody, itemToForm, pendingItem, validateItemForm } from './form'

it('editing keeps the fields this sheet does not show (a PUT replaces the row)', () => {
  const existing = item({
    payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24, contract_end_date: '2027-12-31',
    splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
  })
  expect(formToBody({ ...itemToForm(existing), name: 'Cosmote fibre' })).toMatchObject({
    name: 'Cosmote fibre', payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24,
    contract_end_date: '2027-12-31', splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
    rule_kind: 'monthly_day', rule_day: 9, amount: '38.90', start_date: '2026-01-09',
  })
})

it('an In item never sends a bucket, auto-pay or shares', () => {
  const f = { ...itemToForm(item({ bucket_id: 'b1', is_auto_pay: true, splits: [{ user_id: 'u1', amount: 38.9 }] })), direction: 'in' as const }
  expect(formToBody(f)).toMatchObject({ direction: 'in', bucket_id: null, is_auto_pay: false, splits: [], payer_mode: 'single' })
})

it('amounts: a comma becomes a dot, blank means variable', () => {
  const base = { ...emptyItemForm('2026-10-07', 'u1'), name: 'Electricity' }
  expect(formToBody({ ...base, amount: '86,4' }).amount).toBe('86.40')
  expect(formToBody({ ...base, amount: '' }).amount).toBeNull()
  expect(formToBody({ ...base, currency: ' usd ' }).currency).toBe('USD')
})

it('validation explains the first problem', () => {
  const ok = { ...emptyItemForm('2026-10-07', 'u1'), name: 'Rent' }
  expect(validateItemForm(ok)).toBeNull()
  expect(validateItemForm({ ...ok, name: '  ' })).toBe('Give the item a name.')
  expect(validateItemForm({ ...ok, amount: '12,345' })).toBe('Enter the amount like 38.90, or leave it blank for a variable amount.')
  expect(validateItemForm({ ...ok, currency: 'EU' })).toBe('Use a 3-letter currency code, like EUR.')
  expect(validateItemForm({ ...ok, end_date: '2026-01-01' })).toBe('The end date is before the start date.')
})

it('a new form starts today, on the monthly day of today, paid by me', () => {
  expect(emptyItemForm('2026-10-07', 'u1')).toMatchObject({
    id: null, direction: 'out', currency: 'EUR', start_date: '2026-10-07', paid_by_default: 'u1', is_active: true,
    rule: { kind: 'monthly_day', day: 7, adjust: 'none', everyMonths: 1 },
  })
})

it('pendingItem builds a complete row from a queued body', () => {
  const body = formToBody({ ...emptyItemForm('2026-10-07', 'u1'), name: 'Salary', direction: 'in', amount: '1500' })
  expect(pendingItem(body, 'pending-1')).toMatchObject({
    id: 'pending-1', name: 'Salary', direction: 'in', amount: 1500, next_entry: null, is_active: true, splits: [],
  })
})
```

`web/src/features/plan/items/hooks.test.tsx`:

```tsx
import { act, renderHook, waitFor } from '@testing-library/react'
import type { QueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { keys } from '../../../data/keys'
import { isPending } from '../../../data/pending'
import type { RecurringItemOut } from '../../../data/types'
import { setIdentity } from '../../../offline/identity'
import { fakeApi, reply } from '../../../test/fakeApi'
import { item } from '../../../test/fixtures'
import { Providers, resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../../../test/render'
import { emptyItemForm, formToBody } from './form'
import { useDebouncedValue, useItemActions, useRulePreview } from './hooks'
import type { RuleChoice } from './rule'

const PREVIEW = 'POST /api/v1/recurring/preview' as const
const wrap = (client: QueryClient = testQueryClient()) =>
  ({ children }: { children: ReactNode }) => <Providers client={client}>{children}</Providers>
const salary = (day: number): RuleChoice => ({ kind: 'monthly_day', day, adjust: 'previous_business_day', everyMonths: 1 })

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('useDebouncedValue settles 300 ms after the last change', () => {
  vi.useFakeTimers()
  const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), { initialProps: { v: 1 } })
  rerender({ v: 2 })
  act(() => { vi.advanceTimersByTime(200) })
  rerender({ v: 3 })
  act(() => { vi.advanceTimersByTime(299) })
  expect(result.current).toBe(1)
  act(() => { vi.advanceTimersByTime(1) })
  expect(result.current).toBe(3)
})

it('previews the first rule at once, then only the last of a quick series of edits', async () => {
  const fake = fakeApi({ [PREVIEW]: () => ({ dates: ['2026-10-26', '2026-11-25', '2026-12-23'] }) })
  const { result, rerender } = renderHook(({ day }) => useRulePreview(salary(day), '2026-10-01', ''), {
    initialProps: { day: 26 }, wrapper: wrap(),
  })
  await waitFor(() => expect(result.current).toEqual({ state: 'ready', dates: ['2026-10-26', '2026-11-25', '2026-12-23'] }))
  expect(fake.callsTo(PREVIEW)[0].body).toEqual({
    rule_kind: 'monthly_day', interval_months: 1, rule_day: 26, rule_month: null, rule_adjust: 'previous_business_day',
    rule_days: null, rule_weekday: null, rule_interval_weeks: null, start_date: '2026-10-01', end_date: null, count: 3,
  })
  rerender({ day: 2 })
  rerender({ day: 25 })
  await waitFor(() => expect(fake.callsTo(PREVIEW)).toHaveLength(2))
  expect(fake.callsTo(PREVIEW)[1].body).toMatchObject({ rule_day: 25 })
  await new Promise((r) => setTimeout(r, 350))
  expect(fake.callsTo(PREVIEW)).toHaveLength(2) // day 2 was never sent
})

it('offline: "needs a connection" and no request', () => {
  const fake = fakeApi({})
  setOnline(false)
  const { result } = renderHook(() => useRulePreview(salary(26), '2026-10-01', ''), { wrapper: wrap() })
  expect(result.current).toEqual({ state: 'offline' })
  expect(fake.calls).toHaveLength(0)
})

it("a rule the server refuses shows the server's message", async () => {
  fakeApi({ [PREVIEW]: () => reply(400, { detail: 'The day must be 1 to 31.' }) })
  const { result } = renderHook(() => useRulePreview(salary(26), '2026-10-01', ''), { wrapper: wrap() })
  await waitFor(() => expect(result.current).toEqual({ state: 'error', message: 'The day must be 1 to 31.' }))
})

it('creating offline shows the item at once, marked pending', async () => {
  fakeApi({})
  setOnline(false)
  const client = testQueryClient()
  client.setQueryData(keys.recurring.list(), [item()])
  const { result } = renderHook(() => useItemActions(), { wrapper: wrap(client) })
  const body = formToBody({ ...emptyItemForm('2026-10-07', 'u1'), name: 'Salary', direction: 'in', amount: '1500' })
  let status = ''
  await act(async () => { status = (await result.current.create({ body, tempId: 'pending-1' })).status })
  expect(status).toBe('queued')
  expect(client.getQueryData<RecurringItemOut[]>(keys.recurring.list())!.map((i) => i.name)).toEqual(['Cosmote', 'Salary'])
  expect(isPending('pending-1')).toBe(true)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npm test -- src/features/plan/items/form.test.ts src/features/plan/items/hooks.test.tsx`
Expected: FAIL (modules not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/items/form.ts`:

```ts
import type { RecurringItemIn, RecurringItemOut } from '../../../data/types'
import { parseAmount } from '../../../ui/format'
import { defaultChoice, fromRuleFields, toRuleFields, type RuleChoice } from './rule'

export interface ItemForm {
  id: string | null
  name: string
  direction: 'in' | 'out'
  /** As typed; blank = variable. */
  amount: string
  currency: string
  rule: RuleChoice
  start_date: string
  /** '' = no end. */
  end_date: string
  bucket_id: string
  category_id: string
  paid_by_default: string
  is_auto_pay: boolean
  is_active: boolean
  notes: string
  /** Not edited in this sheet; carried through so a PUT (which replaces the row) never drops them. */
  keep: Required<Pick<RecurringItemIn, 'payer_mode' | 'splits'>> & Pick<RecurringItemIn, 'total_occurrences' | 'contract_end_date'>
}

export function emptyItemForm(today: string, me: string | null): ItemForm {
  return {
    id: null, name: '', direction: 'out', amount: '', currency: 'EUR', rule: defaultChoice('monthly_day', today),
    start_date: today, end_date: '', bucket_id: '', category_id: '', paid_by_default: me ?? '', is_auto_pay: false,
    is_active: true, notes: '', keep: { payer_mode: 'single', splits: [], total_occurrences: null, contract_end_date: null },
  }
}

export function itemToForm(item: RecurringItemOut): ItemForm {
  return {
    id: item.id,
    name: item.name,
    direction: item.direction === 'in' ? 'in' : 'out',
    amount: item.amount === null ? '' : item.amount.toFixed(2),
    currency: item.currency,
    rule: fromRuleFields(item, item.start_date),
    start_date: item.start_date,
    end_date: item.end_date ?? '',
    bucket_id: item.bucket_id ?? '',
    category_id: item.category_id ?? '',
    paid_by_default: item.paid_by_default ?? '',
    is_auto_pay: item.is_auto_pay,
    is_active: item.is_active,
    notes: item.notes ?? '',
    keep: {
      payer_mode: item.payer_mode,
      splits: item.splits.map((s) => ({ user_id: s.user_id, amount: s.amount })),
      total_occurrences: item.total_occurrences,
      contract_end_date: item.contract_end_date,
    },
  }
}

/** The first problem as a sentence, or null when the form can be saved. */
export function validateItemForm(f: ItemForm): string | null {
  if (!f.name.trim()) return 'Give the item a name.'
  if (f.name.trim().length > 100) return 'Keep the name under 100 characters.'
  if (parseAmount(f.amount) === undefined) return 'Enter the amount like 38.90, or leave it blank for a variable amount.'
  if (!/^[A-Za-z]{3}$/.test(f.currency.trim())) return 'Use a 3-letter currency code, like EUR.'
  if (!f.start_date) return 'Pick a start date.'
  if (f.end_date && f.end_date < f.start_date) return 'The end date is before the start date.'
  return null
}

/** The full RecurringItemIn (POST and PUT). Call validateItemForm first. */
export function formToBody(f: ItemForm): RecurringItemIn {
  const out = f.direction === 'out'
  return {
    name: f.name.trim(),
    direction: f.direction,
    amount: parseAmount(f.amount) ?? null,
    currency: f.currency.trim().toUpperCase(),
    ...toRuleFields(f.rule),
    start_date: f.start_date,
    end_date: f.end_date || null,
    bucket_id: out ? f.bucket_id || null : null,
    category_id: f.category_id || null,
    paid_by_default: f.keep.payer_mode === 'own_share' ? null : f.paid_by_default || null,
    is_auto_pay: out && f.is_auto_pay,
    is_active: f.is_active,
    notes: f.notes.trim() || null,
    payer_mode: out ? f.keep.payer_mode : 'single',
    splits: out ? f.keep.splits : [],
    total_occurrences: f.keep.total_occurrences ?? null,
    contract_end_date: f.keep.contract_end_date ?? null,
  }
}

/** The row Items shows while a create or edit waits in the queue. */
export function pendingItem(body: RecurringItemIn, id: string): RecurringItemOut {
  return {
    id,
    name: body.name,
    direction: body.direction ?? 'out',
    amount: body.amount == null ? null : Number(body.amount),
    currency: body.currency ?? 'EUR',
    category_id: body.category_id ?? null,
    bucket_id: body.bucket_id ?? null,
    rule_kind: body.rule_kind ?? 'monthly_day',
    interval_months: body.interval_months ?? 1,
    rule_day: body.rule_day ?? null,
    rule_month: body.rule_month ?? null,
    rule_adjust: body.rule_adjust ?? 'none',
    rule_days: body.rule_days ?? null,
    rule_weekday: body.rule_weekday ?? null,
    rule_interval_weeks: body.rule_interval_weeks ?? null,
    start_date: body.start_date,
    end_date: body.end_date ?? null,
    total_occurrences: body.total_occurrences ?? null,
    contract_end_date: body.contract_end_date ?? null,
    paid_by_default: body.paid_by_default ?? null,
    payer_mode: body.payer_mode ?? 'single',
    is_auto_pay: body.is_auto_pay ?? false,
    is_active: body.is_active ?? true,
    notes: body.notes ?? null,
    splits: (body.splits ?? []).map((s) => ({ user_id: s.user_id, amount: Number(s.amount) })),
    next_entry: null,
  }
}
```

`web/src/features/plan/items/hooks.ts`:

```ts
import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery, type QueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import { useAction } from '../../../data/action'
import { useCachedQuery } from '../../../data/cachedQuery'
import { ApiError, unwrap } from '../../../data/http'
import { affects, keys } from '../../../data/keys'
import { useOnline } from '../../../data/online'
import { toTransactionPage } from '../../../data/reads'
import type { RecurringItemIn, RecurringItemOut } from '../../../data/types'
import { pendingItem } from './form'
import { toRuleFields, type RuleChoice } from './rule'

export const PREVIEW_DEBOUNCE_MS = 300

/** `value` once it has stopped changing for `ms` (compared by JSON, so fresh objects don't restart it). */
export function useDebouncedValue<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  const json = JSON.stringify(value)
  useEffect(() => {
    const t = setTimeout(() => setSettled(JSON.parse(json) as T), ms)
    return () => clearTimeout(t)
  }, [json, ms])
  return settled
}

export type PreviewState =
  | { state: 'loading' }
  | { state: 'ready'; dates: string[] }
  | { state: 'offline' }
  | { state: 'error'; message: string }

/** "Next: 26 Oct, 25 Nov, 23 Dec" from POST /recurring/preview, debounced 300 ms (spec §4.7). Online only. */
export function useRulePreview(rule: RuleChoice, startDate: string, endDate: string): PreviewState {
  const online = useOnline()
  const body = useDebouncedValue(
    { ...toRuleFields(rule), start_date: startDate, end_date: endDate || null, count: 3 },
    PREVIEW_DEBOUNCE_MS,
  )
  const q = useQuery({
    queryKey: ['rule-preview', body],
    queryFn: ({ signal }) => unwrap(api.POST('/api/v1/recurring/preview', { body, signal })),
    enabled: online && body.start_date !== '',
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 5 * 60_000,
  })
  if (!online) return { state: 'offline' }
  if (q.error) return { state: 'error', message: q.error instanceof ApiError ? q.error.detail : 'Couldn’t check the dates.' }
  if (q.data) return { state: 'ready', dates: q.data.dates }
  return { state: 'loading' }
}

/** Whether an item has payments (locks its direction, hides Delete). undefined until known. */
export function useItemHasHistory(itemId: string | null): boolean | undefined {
  const q = useCachedQuery(
    keys.transactions.forItem(itemId ?? ''),
    async (signal) =>
      toTransactionPage(await unwrap(api.GET('/api/v1/transactions', {
        params: { query: { recurring_bill_id: itemId ?? '', page_size: 1 } },
        signal,
      }))).total,
    { enabled: itemId !== null },
  )
  return q.data === undefined ? undefined : q.data > 0
}

const editList = (qc: QueryClient, fn: (items: RecurringItemOut[]) => RecurringItemOut[]) =>
  qc.setQueryData<RecurringItemOut[]>(keys.recurring.list(), (old) => (old ? fn(old) : old))

type CreateVars = { body: RecurringItemIn; tempId: string }
type UpdateVars = { id: string; body: RecurringItemIn }
type RemoveVars = { id: string }

export function useItemActions() {
  const create = useAction<CreateVars, RecurringItemOut>({
    method: 'POST',
    path: '/api/v1/recurring',
    body: (v: CreateVars) => v.body,
    optimistic: (qc, v) => editList(qc, (items) => [...items, pendingItem(v.body, v.tempId)]),
    invalidates: affects.item,
    pendingId: (v) => v.tempId,
  })
  const update = useAction<UpdateVars, RecurringItemOut>({
    method: 'PUT',
    path: (v) => `/api/v1/recurring/${v.id}`,
    body: (v: UpdateVars) => v.body,
    optimistic: (qc, v) =>
      editList(qc, (items) => items.map((i) => (i.id === v.id ? { ...pendingItem(v.body, v.id), next_entry: i.next_entry } : i))),
    invalidates: affects.item,
    pendingId: (v) => v.id,
  })
  // Quiet: the sheet shows a 409 ("has payment history") next to "Pause instead".
  const remove = useAction<RemoveVars, null>({
    method: 'DELETE',
    path: (v) => `/api/v1/recurring/${v.id}`,
    optimistic: (qc, v) => editList(qc, (items) => items.filter((i) => i.id !== v.id)),
    invalidates: affects.item,
    pendingId: (v) => v.id,
    toastRejections: false,
  })
  return { create: create.run, update: update.run, remove: remove.run, busy: create.busy || update.busy || remove.busy }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/plan/items/form.test.ts src/features/plan/items/hooks.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/items/form.ts web/src/features/plan/items/form.test.ts web/src/features/plan/items/hooks.ts web/src/features/plan/items/hooks.test.tsx
git commit -m "feat(web): item form model, debounced rule preview and item actions"
```

---
### Task D3: The rule picker

**Stream:** D. **Depends on:** D2.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/items/items.css` (all Items styles: picker, sheet form and list)
- Create: `web/src/features/plan/items/RulePicker.tsx`, `web/src/features/plan/items/RulePicker.test.tsx`

**Interfaces:**
- Consumes: `RULE_KINDS`, `RULE_LABELS`, `RULE_ADJUSTS`, `ADJUST_LABELS`, `WEEKDAYS`, `defaultChoice`, `ruleSummary`, `RuleChoice`, `RuleKind`, `RuleAdjust` (D1); `useRulePreview`, `PreviewState` (D2); `Segmented`, `formatMonthName`, `formatShortDate`.
- Produces: `RulePicker({ value: RuleChoice; startDate: string; endDate: string; onChange(next: RuleChoice) })` and `previewText(p: PreviewState): string`.

**Behaviour:**
- A **Repeats** `<select>` lists the six choices. Picking one resets the fields with `defaultChoice(kind, startDate)`. Then come the fields for that kind:
  - **monthly_day:** "Day of the month" (1–31), plus the adjust control "If it falls on a weekend or holiday" (Exact day / Business day before / Business day after).
  - **last_business_day:** no fields.
  - **yearly:** "Day" (1–31), "Month" (a select of the month names), plus the adjust control.
  - **easter_offset:** "Days" (0–120), "Before or after Easter" (Before / After), plus the adjust control. The minus sign is a toggle because the iOS numeric keypad has no minus key.
  - **weekly:** "Weekday" (a select, Monday–Sunday) and "Every how many weeks" (1–52).
  - **monthly_interval:** "Every how many months" (1–120).
- Number fields use `inputMode="numeric"`. They report a change only when the text is a whole number in range. Otherwise they show "Enter 1 to 31" under the field and keep the last valid value.
- Under the fields come the plain-language summary (`ruleSummary`) and the preview line:
  - "Next: 26 Oct, 25 Nov, 23 Dec";
  - "Preview needs a connection";
  - "Checking the dates…";
  - the server's message;
  - "No dates after today" when the list is empty.

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/items/RulePicker.test.tsx`:

```tsx
import { fireEvent, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { toRuleFields, type RuleChoice } from './rule'
import { RulePicker } from './RulePicker'

afterEach(resetTestEnv)

function Harness({ initial }: { initial: RuleChoice }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <RulePicker value={value} startDate="2026-10-01" endDate="" onChange={setValue} />
      <output data-testid="fields">{JSON.stringify(toRuleFields(value))}</output>
    </>
  )
}
const fields = () => JSON.parse(screen.getByTestId('fields').textContent!) as Record<string, unknown>
const start = (): RuleChoice => ({ kind: 'monthly_day', day: 1, adjust: 'none', everyMonths: 1 })
const preview = () => fakeApi({ 'POST /api/v1/recurring/preview': () => ({ dates: ['2026-10-26', '2026-11-25', '2026-12-23'] }) })
const repeats = (kind: string) => fireEvent.change(screen.getByLabelText('Repeats'), { target: { value: kind } })

it('day of the month with the business day before (the salary rule)', async () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  fireEvent.change(screen.getByLabelText('Day of the month'), { target: { value: '26' } })
  fireEvent.click(screen.getByRole('button', { name: 'Business day before' }))
  expect(fields()).toMatchObject({ rule_kind: 'monthly_day', rule_day: 26, rule_adjust: 'previous_business_day', interval_months: 1 })
  expect(screen.getByText('26th, or the business day before')).toBeInTheDocument()
  expect(await screen.findByText('Next: 26 Oct, 25 Nov, 23 Dec')).toBeInTheDocument()
})

it('last business day of the month has no fields', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('last_business_day')
  expect(fields()).toEqual({
    rule_kind: 'last_business_day', interval_months: 1, rule_day: null, rule_month: null, rule_adjust: 'none',
    rule_days: null, rule_weekday: null, rule_interval_weeks: null,
  })
  expect(screen.queryByLabelText('Day of the month')).toBeNull()
})

it('every year on a date (the Christmas bonus)', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('yearly')
  fireEvent.change(screen.getByLabelText('Day'), { target: { value: '21' } })
  fireEvent.change(screen.getByLabelText('Month'), { target: { value: '12' } })
  fireEvent.click(screen.getByRole('button', { name: 'Business day before' }))
  expect(fields()).toMatchObject({ rule_kind: 'yearly', rule_day: 21, rule_month: 12, rule_adjust: 'previous_business_day' })
})

it('Easter offset: before is a toggle, the days stay positive', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('easter_offset')
  fireEvent.click(screen.getByRole('button', { name: 'Before' }))
  fireEvent.change(screen.getByLabelText('Days'), { target: { value: '4' } })
  expect(fields()).toMatchObject({ rule_kind: 'easter_offset', rule_days: -4 })
  fireEvent.click(screen.getByRole('button', { name: 'After' }))
  expect(fields()).toMatchObject({ rule_days: 4 })
})

it('every N weeks on a weekday, and every N months from the start date', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('weekly')
  fireEvent.change(screen.getByLabelText('Weekday'), { target: { value: '4' } })
  fireEvent.change(screen.getByLabelText('Every how many weeks'), { target: { value: '2' } })
  expect(fields()).toMatchObject({ rule_kind: 'weekly', rule_weekday: 4, rule_interval_weeks: 2 })
  repeats('monthly_interval')
  fireEvent.change(screen.getByLabelText('Every how many months'), { target: { value: '3' } })
  expect(fields()).toMatchObject({ rule_kind: 'monthly_interval', interval_months: 3, rule_weekday: null })
})

it('an out-of-range number is refused with a hint and the last good value is kept', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  fireEvent.change(screen.getByLabelText('Day of the month'), { target: { value: '32' } })
  expect(screen.getByText('Enter 1 to 31')).toBeInTheDocument()
  expect(fields()).toMatchObject({ rule_day: 1 })
})

it('offline: the preview says it needs a connection', () => {
  fakeApi({})
  setOnline(false)
  renderWithProviders(<Harness initial={start()} />)
  expect(screen.getByText('Preview needs a connection')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/items/RulePicker.test.tsx`
Expected: FAIL (`./RulePicker` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/items/RulePicker.tsx`:

```tsx
import { useId, useState } from 'react'
import { formatMonthName, formatShortDate } from '../../../ui/format'
import { Segmented } from '../../../ui/Segmented'
import { useRulePreview, type PreviewState } from './hooks'
import {
  ADJUST_LABELS, defaultChoice, RULE_ADJUSTS, RULE_KINDS, RULE_LABELS, ruleSummary, WEEKDAYS,
  type RuleAdjust, type RuleChoice, type RuleKind,
} from './rule'
import './items.css'

export interface RulePickerProps {
  value: RuleChoice
  startDate: string
  endDate: string
  onChange: (next: RuleChoice) => void
}

const ADJUST_OPTIONS = RULE_ADJUSTS.map((a) => ({ value: a, label: ADJUST_LABELS[a] }))
const SIDES = [{ value: 'before', label: 'Before' }, { value: 'after', label: 'After' }] as const

export function previewText(p: PreviewState): string {
  switch (p.state) {
    case 'offline': return 'Preview needs a connection'
    case 'loading': return 'Checking the dates…'
    case 'error': return p.message
    case 'ready': return p.dates.length ? `Next: ${p.dates.map(formatShortDate).join(', ')}` : 'No dates after today'
  }
}

export function RulePicker({ value, startDate, endDate, onChange }: RulePickerProps) {
  const preview = useRulePreview(value, startDate, endDate)
  return (
    <div className="items-rule">
      <label className="ui-field">
        <span className="ui-field__label">Repeats</span>
        <select className="ui-input" value={value.kind}
          onChange={(e) => onChange(defaultChoice(e.target.value as RuleKind, startDate))}>
          {RULE_KINDS.map((k) => <option key={k} value={k}>{RULE_LABELS[k]}</option>)}
        </select>
      </label>
      <KindFields value={value} onChange={onChange} />
      <p className="items-rule__summary">{ruleSummary(value, startDate)}</p>
      <p className="items-rule__preview" aria-live="polite">{previewText(preview)}</p>
    </div>
  )
}

function KindFields({ value: v, onChange }: { value: RuleChoice; onChange: (c: RuleChoice) => void }) {
  switch (v.kind) {
    case 'monthly_day':
      return (
        <>
          <NumberField label="Day of the month" value={v.day} min={1} max={31} onChange={(day) => onChange({ ...v, day })} />
          <AdjustField value={v.adjust} onChange={(adjust) => onChange({ ...v, adjust })} />
        </>
      )
    case 'last_business_day':
      return null
    case 'yearly':
      return (
        <>
          <div className="items-rule__row">
            <NumberField label="Day" value={v.day} min={1} max={31} onChange={(day) => onChange({ ...v, day })} />
            <label className="ui-field">
              <span className="ui-field__label">Month</span>
              <select className="ui-input" value={v.month} onChange={(e) => onChange({ ...v, month: Number(e.target.value) })}>
                {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{formatMonthName(i + 1)}</option>)}
              </select>
            </label>
          </div>
          <AdjustField value={v.adjust} onChange={(adjust) => onChange({ ...v, adjust })} />
        </>
      )
    case 'easter_offset':
      return <EasterFields value={v} onChange={onChange} />
    case 'weekly':
      return (
        <div className="items-rule__row">
          <label className="ui-field">
            <span className="ui-field__label">Weekday</span>
            <select className="ui-input" value={v.weekday} onChange={(e) => onChange({ ...v, weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </label>
          <NumberField label="Every how many weeks" value={v.everyWeeks} min={1} max={52}
            onChange={(everyWeeks) => onChange({ ...v, everyWeeks })} />
        </div>
      )
    case 'monthly_interval':
      return (
        <NumberField label="Every how many months" value={v.everyMonths} min={1} max={120}
          onChange={(everyMonths) => onChange({ ...v, everyMonths })} />
      )
  }
}

function EasterFields({ value: v, onChange }: { value: Extract<RuleChoice, { kind: 'easter_offset' }>; onChange: (c: RuleChoice) => void }) {
  // Kept apart from `days` so "Before" sticks while days is still 0.
  const [before, setBefore] = useState(v.days < 0)
  const days = Math.abs(v.days)
  return (
    <>
      <div className="items-rule__row">
        <NumberField label="Days" value={days} min={0} max={120} onChange={(n) => onChange({ ...v, days: before ? -n : n })} />
        <div className="ui-field">
          <span className="ui-field__label" aria-hidden="true">Before or after Easter</span>
          <Segmented label="Before or after Easter" options={SIDES} value={before ? 'before' : 'after'}
            onChange={(side) => {
              const b = side === 'before'
              setBefore(b)
              onChange({ ...v, days: b ? -days : days })
            }} />
        </div>
      </div>
      <AdjustField value={v.adjust} onChange={(adjust) => onChange({ ...v, adjust })} />
    </>
  )
}

function AdjustField({ value, onChange }: { value: RuleAdjust; onChange: (a: RuleAdjust) => void }) {
  return (
    <div className="ui-field">
      <span className="ui-field__label" aria-hidden="true">If it falls on a weekend or holiday</span>
      <Segmented label="If it falls on a weekend or holiday" options={ADJUST_OPTIONS} value={value} onChange={onChange} />
    </div>
  )
}

function NumberField({ label, value, min, max, onChange }: {
  label: string; value: number; min: number; max: number; onChange: (n: number) => void
}) {
  const id = useId()
  const [text, setText] = useState(String(value))
  const [synced, setSynced] = useState(value)
  if (value !== synced) {
    // The value changed from outside (another kind picked): show it.
    setSynced(value)
    setText(String(value))
  }
  const n = Number(text)
  const valid = text.trim() !== '' && Number.isInteger(n) && n >= min && n <= max
  return (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={id}>{label}</label>
      <input id={id} className="ui-input ui-num" inputMode="numeric" pattern="[0-9]*" autoComplete="off"
        value={text} aria-invalid={!valid}
        onChange={(e) => {
          const t = e.target.value
          setText(t)
          const k = Number(t)
          if (t.trim() !== '' && Number.isInteger(k) && k >= min && k <= max) {
            setSynced(k)
            onChange(k)
          }
        }} />
      {!valid && <p className="ui-field__error">{`Enter ${min} to ${max}`}</p>}
    </div>
  )
}
```

`web/src/features/plan/items/items.css`:

```css
/* Plan › Items: list, Item sheet and rule picker. Kit classes come from ui/ui.css. */
.items { display: flex; flex-direction: column; gap: 4px; }
.items-group + .items-group { margin-top: 4px; }

/* Rule picker */
.items-rule { display: flex; flex-direction: column; gap: 12px; }
.items-rule__row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; align-items: start; }
.items-rule__summary { margin: 0; font-size: 13.5px; font-weight: 600; color: var(--ink-2); }
.items-rule__preview {
  margin: 0; padding: 10px 12px; border-radius: var(--r-md); background: var(--surface-2);
  font-size: 13.5px; color: var(--ink-2); font-variant-numeric: tabular-nums;
}

/* Item sheet */
.items-form { display: flex; flex-direction: column; gap: 14px; }
.items-form__row { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 10px; }
.items-form__row--even { grid-template-columns: 1fr 1fr; }
.items-form__hint { margin: -6px 0 0; font-size: 12.5px; color: var(--muted); }
.items-form__problem {
  margin: 0; padding: 10px 12px; border-radius: var(--r-md);
  background: var(--neg-soft); color: var(--neg); font-size: 14px; font-weight: 550;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/items/RulePicker.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/items/RulePicker.tsx web/src/features/plan/items/RulePicker.test.tsx web/src/features/plan/items/items.css
git commit -m "feat(web): rule picker with plain-language choices and a live date preview"
```

---

### Task D4: The Item sheet

**Stream:** D. **Depends on:** D3.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/items/ItemSheet.tsx`, `web/src/features/plan/items/ItemSheet.test.tsx`

**Interfaces:**
- Consumes: `ItemForm`, `emptyItemForm`, `itemToForm`, `validateItemForm`, `formToBody` (D2); `useItemActions`, `useItemHasHistory` (D2); `RulePicker` (D3); `useBuckets`, `useCategories`, `useHousehold`, `memberName` (A8); `Sheet`, `Segmented`, `List`, `ListRow`, `Money`, `PauseIcon`, `formatShortDate`, `todayISO`; `useSession`.
- Produces: `ItemSheet({ open: boolean; item: RecurringItemOut | null; onClose(): void; onOpenEntry?(entry: EntryOut): void })`. A null `item` means a new item.

**Behaviour (spec §4.7):**
- The title is "New item" or "Edit item". The fields come in this order:
  1. Name.
  2. Direction (Out/In). On an existing item with history it is disabled, with the hint "This item has payments, so its direction can't change."
  3. Amount (the placeholder "Variable"; the hint "Leave the amount blank if it changes every time.") and Currency.
  4. The rule picker.
  5. Starts and "Ends (optional)" (`type="date"`).
  6. **Budget**, out only: "No budget (a Fixed cost)" plus the active monthly buckets. Event and archived buckets are left out.
  7. Category.
  8. "Paid by" or "Received by": "Not set" plus the members. It is hidden when `payer_mode` is `own_share`.
  9. "Pay automatically on the due date", out only.
  10. Notes.
  11. "Active".
- An existing item with a `next_entry` shows a "Next: 9 Oct" row. Tapping it calls `onOpenEntry`, so the Entry sheet opens from Items (spec §4.6).
- The **Add item** / **Save** submit runs `validateItemForm` first. A problem shows as an alert and nothing is sent. A rejection shows the server's `detail`. A done or queued result closes the sheet.
- **Delete item** is shown for an existing item unless it is known to have history. A 409 shows the server message plus **Pause instead**, which PUTs the saved item with `is_active: false`.

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/items/ItemSheet.test.tsx`:

```tsx
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi, reply, type Routes } from '../../../test/fakeApi'
import { bucket, entry, item, page, readRoutes, txn } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import { ItemSheet } from './ItemSheet'

afterEach(resetTestEnv)

const HISTORY_409 = "This bill has payment history, so it can't be deleted — deleting it would erase those payments. Deactivate it instead (the pause toggle on the bill)."
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/buckets': () => [bucket(), bucket({ id: 'b9', name: 'Naxos trip', kind: 'event' }), bucket({ id: 'b8', name: 'Old', status: 'archived' })],
  'GET /api/v1/transactions': () => page([]),
  'POST /api/v1/recurring/preview': () => ({ dates: ['2026-10-26'] }),
  ...over,
})

it('a new In item posts its rule fields and no bucket, auto-pay or shares', async () => {
  const fake = fakeApi(routes({ 'POST /api/v1/recurring': () => item({ id: 'i9', name: 'Salary', direction: 'in' }) }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={null} onClose={onClose} />)
  expect(screen.getByRole('dialog', { name: 'New item' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Salary' } })
  fireEvent.click(screen.getByRole('button', { name: 'In' }))
  expect(screen.queryByLabelText('Budget')).toBeNull()
  expect(screen.queryByRole('checkbox', { name: 'Pay automatically on the due date' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '1500' } })
  fireEvent.change(screen.getByLabelText('Starts'), { target: { value: '2026-10-01' } })
  fireEvent.change(screen.getByLabelText('Day of the month'), { target: { value: '26' } })
  fireEvent.click(screen.getByRole('button', { name: 'Business day before' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo('POST /api/v1/recurring')[0].body).toMatchObject({
    name: 'Salary', direction: 'in', amount: '1500.00', currency: 'EUR', rule_kind: 'monthly_day', rule_day: 26,
    rule_adjust: 'previous_business_day', start_date: '2026-10-01', bucket_id: null, is_auto_pay: false,
    splits: [], payer_mode: 'single',
  })
})

it('out items choose among active monthly budgets only', async () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={null} onClose={() => {}} />)
  await waitFor(() => expect(within(screen.getByLabelText('Budget')).getAllByRole('option')).toHaveLength(2))
  expect(within(screen.getByLabelText('Budget')).getAllByRole('option').map((o) => o.textContent))
    .toEqual(['No budget (a Fixed cost)', 'Day to day'])
})

it('saving an edit keeps shares, payer mode, contract end and occurrence count', async () => {
  const shared = item({
    payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24, contract_end_date: '2027-12-31',
    splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
  })
  const fake = fakeApi(routes({ 'PUT /api/v1/recurring/{item_id}': () => shared }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={shared} onClose={onClose} />)
  expect(screen.getByRole('dialog', { name: 'Edit item' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Paid by')).toBeNull()
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Cosmote fibre' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo('PUT /api/v1/recurring/{item_id}')[0]).toMatchObject({
    path: '/api/v1/recurring/i1',
    body: {
      name: 'Cosmote fibre', payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24,
      contract_end_date: '2027-12-31', splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
    },
  })
})

it('an item with payments locks its direction and offers no Delete', async () => {
  fakeApi(routes({ 'GET /api/v1/transactions': () => page([txn({ recurring_bill_id: 'i1' })]) }))
  renderWithProviders(<ItemSheet open item={item()} onClose={() => {}} />)
  expect(await screen.findByText("This item has payments, so its direction can't change.")).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'In' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Delete item' })).toBeNull()
})

it('Delete without history deletes; a 409 offers Pause instead, which pauses the saved item', async () => {
  const fake = fakeApi(routes({
    'DELETE /api/v1/recurring/{item_id}': () => reply(409, { detail: HISTORY_409 }),
    'PUT /api/v1/recurring/{item_id}': () => item({ is_active: false }),
  }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={item()} onClose={onClose} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Delete item' }))
  expect(await screen.findByText(HISTORY_409)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Pause instead' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo('PUT /api/v1/recurring/{item_id}')[0].body).toMatchObject({ is_active: false, name: 'Cosmote' })
})

it('nothing is sent while the form has a problem', () => {
  const fake = fakeApi(routes())
  renderWithProviders(<ItemSheet open item={null} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Give the item a name.')
  expect(fake.callsTo('POST /api/v1/recurring')).toHaveLength(0)
})

it('the next entry opens the Entry sheet', () => {
  fakeApi(routes())
  const onOpenEntry = vi.fn()
  renderWithProviders(<ItemSheet open item={item()} onClose={() => {}} onOpenEntry={onOpenEntry} />)
  fireEvent.click(screen.getByRole('button', { name: /Next: 9 Oct/ }))
  expect(onOpenEntry).toHaveBeenCalledWith(entry())
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/items/ItemSheet.test.tsx`
Expected: FAIL (`./ItemSheet` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/items/ItemSheet.tsx`:

```tsx
import { useState } from 'react'
import { memberName, useBuckets, useCategories, useHousehold } from '../../../data/reads'
import type { EntryOut, RecurringItemOut } from '../../../data/types'
import { useSession } from '../../../session/SessionProvider'
import { formatShortDate, todayISO } from '../../../ui/format'
import { PauseIcon } from '../../../ui/icons'
import { List, ListRow } from '../../../ui/ListRow'
import { Money } from '../../../ui/Money'
import { Segmented } from '../../../ui/Segmented'
import { Sheet } from '../../../ui/Sheet'
import { emptyItemForm, formToBody, itemToForm, validateItemForm, type ItemForm } from './form'
import { useItemActions, useItemHasHistory } from './hooks'
import { RulePicker } from './RulePicker'
import './items.css'

export interface ItemSheetProps {
  open: boolean
  /** null: a new item. */
  item: RecurringItemOut | null
  onClose: () => void
  onOpenEntry?: (entry: EntryOut) => void
}

const DIRECTIONS = [{ value: 'out', label: 'Out' }, { value: 'in', label: 'In' }] as const

export function ItemSheet({ open, item, onClose, onOpenEntry }: ItemSheetProps) {
  return (
    <Sheet open={open} onClose={onClose} title={item ? 'Edit item' : 'New item'}>
      {open && <ItemBody key={item?.id ?? 'new'} item={item} onClose={onClose} onOpenEntry={onOpenEntry} />}
    </Sheet>
  )
}

function ItemBody({ item, onClose, onOpenEntry }: Omit<ItemSheetProps, 'open'>) {
  const { me } = useSession()
  const [form, setForm] = useState<ItemForm>(() => (item ? itemToForm(item) : emptyItemForm(todayISO(), me?.id ?? null)))
  const set = <K extends keyof ItemForm>(key: K, value: ItemForm[K]) => setForm((f) => ({ ...f, [key]: value }))
  const [problem, setProblem] = useState<string | null>(null)
  const [deleteBlocked, setDeleteBlocked] = useState<string | null>(null)
  const history = useItemHasHistory(item?.id ?? null)
  const buckets = (useBuckets().data ?? []).filter((b) => b.kind === 'monthly' && b.status === 'active')
  const categories = useCategories().data ?? []
  const members = useHousehold().data?.members ?? []
  const actions = useItemActions()
  const out = form.direction === 'out'
  const directionLocked = item !== null && history === true
  const next = item?.next_entry ?? null

  const save = async () => {
    const msg = validateItemForm(form)
    if (msg) {
      setProblem(msg)
      return
    }
    setProblem(null)
    const body = formToBody(form)
    const r = item
      ? await actions.update({ id: item.id, body })
      : await actions.create({ body, tempId: `pending-${crypto.randomUUID()}` })
    if (r.status === 'rejected') setProblem(r.detail)
    else onClose()
  }

  const remove = async () => {
    if (!item) return
    const r = await actions.remove({ id: item.id })
    if (r.status === 'rejected') setDeleteBlocked(r.detail)
    else onClose()
  }

  const pause = async () => {
    if (!item) return
    const r = await actions.update({ id: item.id, body: formToBody({ ...itemToForm(item), is_active: false }) })
    if (r.status !== 'rejected') onClose()
  }

  return (
    <form className="items-form" noValidate onSubmit={(e) => { e.preventDefault(); void save() }}>
      {problem && <p className="items-form__problem" role="alert">{problem}</p>}

      <label className="ui-field">
        <span className="ui-field__label">Name</span>
        <input className="ui-input" value={form.name} maxLength={100} autoComplete="off"
          onChange={(e) => set('name', e.target.value)} />
      </label>

      <div className="ui-field">
        <span className="ui-field__label" aria-hidden="true">Direction</span>
        <Segmented label="Direction" options={DIRECTIONS} value={form.direction} disabled={directionLocked}
          onChange={(d) => set('direction', d)} />
        {directionLocked && <p className="items-form__hint">This item has payments, so its direction can't change.</p>}
      </div>

      <div className="items-form__row">
        <label className="ui-field">
          <span className="ui-field__label">Amount</span>
          <input className="ui-input ui-num" inputMode="decimal" autoComplete="off" placeholder="Variable"
            value={form.amount} onChange={(e) => set('amount', e.target.value)} />
        </label>
        <label className="ui-field">
          <span className="ui-field__label">Currency</span>
          <input className="ui-input" value={form.currency} maxLength={3} autoCapitalize="characters" autoComplete="off"
            onChange={(e) => set('currency', e.target.value.toUpperCase())} />
        </label>
      </div>
      <p className="items-form__hint">Leave the amount blank if it changes every time.</p>

      <RulePicker value={form.rule} startDate={form.start_date} endDate={form.end_date} onChange={(rule) => set('rule', rule)} />

      <div className="items-form__row items-form__row--even">
        <label className="ui-field">
          <span className="ui-field__label">Starts</span>
          <input type="date" className="ui-input" value={form.start_date} onChange={(e) => set('start_date', e.target.value)} />
        </label>
        <label className="ui-field">
          <span className="ui-field__label">Ends (optional)</span>
          <input type="date" className="ui-input" value={form.end_date} onChange={(e) => set('end_date', e.target.value)} />
        </label>
      </div>

      {out && (
        <label className="ui-field">
          <span className="ui-field__label">Budget</span>
          <select className="ui-input" value={form.bucket_id} onChange={(e) => set('bucket_id', e.target.value)}>
            <option value="">No budget (a Fixed cost)</option>
            {buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
      )}

      <label className="ui-field">
        <span className="ui-field__label">Category</span>
        <select className="ui-input" value={form.category_id} onChange={(e) => set('category_id', e.target.value)}>
          <option value="">No category</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </label>

      {form.keep.payer_mode !== 'own_share' && (
        <label className="ui-field">
          <span className="ui-field__label">{out ? 'Paid by' : 'Received by'}</span>
          <select className="ui-input" value={form.paid_by_default} onChange={(e) => set('paid_by_default', e.target.value)}>
            <option value="">Not set</option>
            {members.map((m) => <option key={m.user_id} value={m.user_id}>{memberName(m)}</option>)}
          </select>
        </label>
      )}

      {out && (
        <label className="ui-check">
          <span>Pay automatically on the due date</span>
          <input type="checkbox" checked={form.is_auto_pay} onChange={(e) => set('is_auto_pay', e.target.checked)} />
        </label>
      )}

      <label className="ui-field">
        <span className="ui-field__label">Notes</span>
        <textarea className="ui-input" value={form.notes} onChange={(e) => set('notes', e.target.value)} />
      </label>

      <label className="ui-check">
        <span>Active</span>
        <input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} />
      </label>
      {!form.is_active && <p className="items-form__hint">Paused items create no new entries.</p>}

      {next && onOpenEntry && (
        <List>
          <ListRow onClick={() => onOpenEntry(next)} title={`Next: ${formatShortDate(next.due_date)}`}
            subtitle="Pay, skip or set the amount"
            trailing={<Money amount={next.amount} currency={next.currency} estimated={next.estimated} nullText="variable" />} />
        </List>
      )}

      <button type="submit" className="btn btn--primary btn--block btn--lg" disabled={actions.busy}>
        {item ? 'Save' : 'Add item'}
      </button>
      {item && history !== true && !deleteBlocked && (
        <button type="button" className="btn btn--danger btn--block" disabled={actions.busy} onClick={() => void remove()}>
          Delete item
        </button>
      )}
      {deleteBlocked && (
        <>
          <p className="items-form__problem" role="alert">{deleteBlocked}</p>
          <button type="button" className="btn btn--block" disabled={actions.busy} onClick={() => void pause()}>
            <PauseIcon />Pause instead
          </button>
        </>
      )}
    </form>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/plan/items/ItemSheet.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/items/ItemSheet.tsx web/src/features/plan/items/ItemSheet.test.tsx
git commit -m "feat(web): Item sheet with rule picker, direction lock, delete or pause"
```

---

### Task D5: The Items list and its route

**Stream:** D. **Depends on:** D4.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/plan/items/Items.tsx`, `web/src/features/plan/items/Items.test.tsx`
- Modify: `web/src/router.tsx` (add `plan/items`)

**Interfaces:**
- Consumes: `useRecurringItems` (A8), `usePendingIds`, `ItemSheet` (D4), `EntrySheet` (C1), `fromRuleFields`, `ruleSummary` (D1), `TopBar` (with `actions`), `QueryView`, `EmptyState`, `ListRow`, `Badge`, `Money`, the icons, `formatShortDate`.
- Produces: `Items()` at `/plan/items`; `?new=1` opens an empty Item sheet. Plan's **Items** link (C6) and Upcoming's "Add a recurring item" (C2) point here.

**Behaviour (spec §4.5):**
- The list has two groups, **In** and **Out**. Within each group active items come in server order and paused items go last, greyed (`muted`) with a "Paused" badge.
- Each row shows the name; a subtitle of the rule summary plus " · next 26 Oct" when active with a `next_entry`; and the amount, or "variable" when null.
- Rows created offline (ids starting `pending-`) show "Waiting to sync" and are not tappable, because their id isn't real yet.
- The top bar has a "Plan" back link (accessible name "Back to Plan") and a **＋** button ("New item").
- Choosing the next entry inside the Item sheet closes it and opens the Entry sheet.

- [ ] **Step 1: Write the failing test**

`web/src/features/plan/items/Items.test.tsx`:

```tsx
import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../../data/keys'
import { markPending } from '../../../data/pending'
import { fakeApi, type Routes } from '../../../test/fakeApi'
import { entry, item, page, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, testQueryClient } from '../../../test/render'
import { emptyItemForm, formToBody, pendingItem } from './form'
import { Items } from './Items'

afterEach(resetTestEnv)

const list = [
  item(),
  item({
    id: 'i2', name: 'Salary', direction: 'in', amount: 1500, rule_day: 26, rule_adjust: 'previous_business_day',
    next_entry: entry({ id: 'e2', item_id: 'i2', name: 'Salary', direction: 'in', due_date: '2026-10-26', amount: 1500 }),
  }),
  item({ id: 'i3', name: 'Gym', is_active: false, next_entry: null }),
  item({ id: 'i4', name: 'Electricity', amount: null, rule_kind: 'last_business_day', rule_day: null,
    next_entry: entry({ id: 'e4', item_id: 'i4', name: 'Electricity', due_date: '2026-10-30', amount: null }) }),
]
const routes = (): Routes => ({
  ...readRoutes(),
  'GET /api/v1/recurring': () => list,
  'GET /api/v1/transactions': () => page([]),
  'POST /api/v1/recurring/preview': () => ({ dates: [] }),
})
const titles = (group: HTMLElement) =>
  Array.from(group.querySelectorAll('.ui-row__title')).map((t) => t.textContent)

it('groups In and Out, with the schedule, next date and amount; paused items last', async () => {
  fakeApi(routes())
  renderWithProviders(<Items />, { route: '/plan/items' })
  const inGroup = await screen.findByRole('region', { name: 'In' })
  const outGroup = screen.getByRole('region', { name: 'Out' })
  expect(titles(inGroup)).toEqual(['Salary'])
  expect(titles(outGroup)).toEqual(['Cosmote', 'Electricity', 'Gym'])
  expect(within(inGroup).getByRole('button', { name: /Salary/ })).toHaveTextContent('26th, or the business day before · next 26 Oct')
  expect(within(outGroup).getByRole('button', { name: /Electricity/ })).toHaveTextContent('Last business day · next 30 Oct')
  expect(within(outGroup).getByRole('button', { name: /Electricity/ })).toHaveTextContent('variable')
  expect(within(outGroup).getByRole('button', { name: /Gym/ })).toHaveTextContent('Paused')
})

it('tapping a row opens the Item sheet for it; ＋ and ?new=1 open a new one', async () => {
  fakeApi(routes())
  const { router } = renderWithProviders(<Items />, { route: '/plan/items' })
  fireEvent.click(await screen.findByRole('button', { name: /Cosmote/ }))
  expect(screen.getByRole('dialog', { name: 'Edit item' })).toBeInTheDocument()
  expect(screen.getByLabelText('Name')).toHaveValue('Cosmote')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: 'New item' }))
  expect(screen.getByRole('dialog', { name: 'New item' })).toBeInTheDocument()
  expect(router.state.location.search).toBe('?new=1')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(router.state.location.search).toBe('')
})

it('opens a new item straight from /plan/items?new=1', () => {
  fakeApi(routes())
  renderWithProviders(<Items />, { route: '/plan/items?new=1' })
  expect(screen.getByRole('dialog', { name: 'New item' })).toBeInTheDocument()
})

it('an item created offline shows as waiting to sync and cannot be opened yet', async () => {
  fakeApi(routes())
  const client = testQueryClient()
  const queued = pendingItem(formToBody({ ...emptyItemForm('2026-10-07', 'u1'), name: 'Cleaner' }), 'pending-1')
  client.setQueryData(keys.recurring.list(), [item(), queued])
  act(() => markPending('pending-1'))
  renderWithProviders(<Items />, { route: '/plan/items', client })
  const row = (await screen.findByText('Cleaner')).closest('.ui-row')!
  expect(row).toHaveTextContent('Waiting to sync')
  expect(row.tagName).toBe('DIV')
})

it('the next entry in the Item sheet opens the Entry sheet', async () => {
  fakeApi(routes())
  renderWithProviders(<Items />, { route: '/plan/items' })
  fireEvent.click(await screen.findByRole('button', { name: /Cosmote/ }))
  fireEvent.click(screen.getByRole('button', { name: /Next: 9 Oct/ }))
  expect(screen.getByRole('dialog', { name: 'Cosmote' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Edit item' })).toBeNull()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/plan/items/Items.test.tsx`
Expected: FAIL (`./Items` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/plan/items/Items.tsx`:

```tsx
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { usePendingIds } from '../../../data/pending'
import { useRecurringItems } from '../../../data/reads'
import type { EntryOut, RecurringItemOut } from '../../../data/types'
import { TopBar } from '../../../shell/TopBar'
import { Badge } from '../../../ui/Badge'
import { EmptyState } from '../../../ui/EmptyState'
import { formatShortDate } from '../../../ui/format'
import { ChevronLeftIcon, ClockIcon, PauseIcon, PlusIcon } from '../../../ui/icons'
import { ListRow } from '../../../ui/ListRow'
import { Money } from '../../../ui/Money'
import { QueryView } from '../../../ui/QueryView'
import { EntrySheet } from '../EntrySheet'
import { ItemSheet } from './ItemSheet'
import { fromRuleFields, ruleSummary } from './rule'
import './items.css'

export function Items() {
  const items = useRecurringItems()
  const pending = usePendingIds()
  const [params, setParams] = useSearchParams()
  const creating = params.get('new') === '1'
  const [editing, setEditing] = useState<RecurringItemOut | null>(null)
  const [entry, setEntry] = useState<EntryOut | null>(null)
  const closeSheet = () => {
    setEditing(null)
    if (creating) setParams({}, { replace: true })
  }

  return (
    <>
      <TopBar title="Items" actions={
        <>
          <Link to="/plan" className="btn btn--sm btn--ghost" aria-label="Back to Plan"><ChevronLeftIcon />Plan</Link>
          <button type="button" className="ui-iconbtn" aria-label="New item" onClick={() => setParams({ new: '1' })}>
            <PlusIcon />
          </button>
        </>
      } />
      <section className="screen items">
        <QueryView result={items} noDataText="No saved data yet. Connect once to load Plan.">
          {(all) =>
            all.length === 0 ? (
              <EmptyState title="No recurring items yet" body="Add salaries, rent and bills to see what’s coming."
                action={{ label: 'Add a recurring item', onClick: () => setParams({ new: '1' }) }} />
            ) : (
              <>
                <ItemGroup title="In" items={all.filter((i) => i.direction === 'in')} pending={pending} onOpen={setEditing} />
                <ItemGroup title="Out" items={all.filter((i) => i.direction !== 'in')} pending={pending} onOpen={setEditing} />
              </>
            )
          }
        </QueryView>
      </section>
      <ItemSheet open={creating || editing !== null} item={creating ? null : editing} onClose={closeSheet}
        onOpenEntry={(e) => { closeSheet(); setEntry(e) }} />
      <EntrySheet entry={entry} onClose={() => setEntry(null)} />
    </>
  )
}

function ItemGroup({ title, items, pending, onOpen }: {
  title: string; items: RecurringItemOut[]; pending: ReadonlySet<string>; onOpen: (i: RecurringItemOut) => void
}) {
  if (items.length === 0) return null
  const ordered = [...items.filter((i) => i.is_active), ...items.filter((i) => !i.is_active)]
  const id = `items-${title}`
  return (
    <section className="items-group" aria-labelledby={id}>
      <div className="ui-sec"><h2 id={id} className="ui-sec__title">{title}</h2></div>
      <div className="ui-list">
        {ordered.map((i) => {
          const queuedCreate = i.id.startsWith('pending-')
          const next = i.is_active && i.next_entry ? ` · next ${formatShortDate(i.next_entry.due_date)}` : ''
          const badges = [
            !i.is_active && <Badge key="paused" icon={<PauseIcon />}>Paused</Badge>,
            pending.has(i.id) && <Badge key="sync" icon={<ClockIcon />}>Waiting to sync</Badge>,
          ].filter(Boolean)
          return (
            <ListRow key={i.id}
              onClick={queuedCreate ? undefined : () => onOpen(i)}
              muted={!i.is_active}
              title={i.name}
              subtitle={`${ruleSummary(fromRuleFields(i, i.start_date), i.start_date)}${next}`}
              badges={badges.length ? badges : undefined}
              trailing={i.amount === null
                ? <span className="ui-muted">variable</span>
                : <Money amount={i.amount} currency={i.currency} />} />
          )
        })}
      </div>
    </section>
  )
}
```

`web/src/router.tsx`:
- Add the import `import { Items } from './features/plan/items/Items'`.
- Add the child route `{ path: 'plan/items', element: <Items /> },` after `{ path: 'plan', element: <Plan /> },`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/plan/items && npm run typecheck && npm run lint`
Expected: PASS (D1–D5); lint reports no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/plan/items/Items.tsx web/src/features/plan/items/Items.test.tsx web/src/router.tsx
git commit -m "feat(web): Plan › Items list with In/Out groups and the /plan/items route"
```

---
## Stream E: Home

All E files live in `web/src/features/home/`, plus `web/src/screens/Home.tsx` (E3).

### Task E1: The attention model and Home hooks

**Stream:** E. **Depends on:** C1 (tag `2a-c1`).

**Worktree prep:** `cd /Users/giorgoscharitidis/expenses-2a-e/web && npm ci`.

**Files:**
- Create: `web/src/features/home/attention.ts`, `web/src/features/home/attention.test.ts`
- Create: `web/src/features/home/hooks.ts`

**Interfaces:**
- Consumes:
  - `usePlanUpcoming`, `useBudgets`, `useCategoriesVsUsual`, `patchEntryEverywhere` (C1);
  - `useCachedQuery`, `useAction`, `keys`, `affects`, `unwrap`, `toTransactionPage` (A);
  - `useFailedQueueRows`, `FailedQueueRow` (A7);
  - `addDays`, `shiftMonth`, `todayISO`.
- Produces:
  - `AttentionItem` (union by `kind`: `'match' | 'overdue' | 'missingAmount' | 'budget' | 'category' | 'failed'`) and `AttentionInput`;
  - `buildAttention(input): AttentionItem[]`, `attentionReady(input): boolean`;
  - `BUDGET_WARN_PCT = 80`, `MAX_CATEGORIES = 3`, `MISSING_AMOUNT_DAYS = 7`;
  - `overdueWindow(today): { from: string; to: string }`;
  - `useOverdueEntries(today?)`, `useMatches()`, `useMatchActions(match): { link(), dismiss(), busy }`;
  - `useRecentTransactions(): CachedQuery<TransactionRow[]>` (key `keys.transactions.recent()`, which 2b extends with pending rows);
  - `useAttention(): { items: AttentionItem[]; ready: boolean }`.

**Rules (spec §5.2, in this order):**
1. Match suggestions.
2. Overdue entries: `GET /recurring/entries?from=<first of last month>&to=<yesterday>`, filtered to `overdue && status === 'expected'`, oldest first.
3. Missing amounts: expected entries due within 7 days that are estimated or have no amount.
4. Budgets at 80% or more (`pct` non-null).
5. Flagged categories, at most 3.
6. Failed queued changes.

`attentionReady` is true only when every server source has data, fresh or cached. Home uses it to avoid a false "All clear" (Review Focus 5).

**Matches.**
- **Link** removes the suggestion at once. It also marks the entry done with `EntryChange` `linked`, which leaves the running net alone because the transaction already counts.
- **Not this** removes the suggestion.
- Both queue offline (spec §3.2).

- [ ] **Step 1: Write the failing test**

`web/src/features/home/attention.test.ts`:

```ts
import { expect, it } from 'vitest'
import { budgetRow, categoryUsual, day, entry, match } from '../../test/fixtures'
import { attentionReady, buildAttention, overdueWindow, type AttentionInput } from './attention'

const TODAY = '2026-10-07'
const full = (over: Partial<AttentionInput> = {}): AttentionInput => ({
  today: TODAY,
  matches: [match()],
  overdue: [
    entry({ id: 'late2', name: 'Water', overdue: true, due_date: '2026-10-03' }),
    entry({ id: 'late1', name: 'Rent', overdue: true, due_date: '2026-09-30' }),
    entry({ id: 'paid', overdue: false, status: 'done', due_date: '2026-10-01' }),
  ],
  upcoming: [
    day('2026-10-09', [entry({ id: 'est', name: 'Electricity', estimated: true, amount: 83.5 }), entry({ id: 'fixed' })], 900),
    day('2026-10-14', [entry({ id: 'novalue', name: 'Water', amount: null, due_date: '2026-10-14' })], 850),
    day('2026-10-20', [entry({ id: 'far', estimated: true, due_date: '2026-10-20' })], 800),
  ],
  budgets: [budgetRow({ pct: 75 }), budgetRow({ bucket_id: 'b2', name: 'Kids', spent: 255, budget: 300, pct: 85 }), budgetRow({ bucket_id: 'b3', budget: null, pct: null })],
  categories: [
    categoryUsual({ category_id: 'c1', name: 'A' }), categoryUsual({ category_id: 'c2', name: 'B' }),
    categoryUsual({ category_id: 'c3', name: 'C' }), categoryUsual({ category_id: 'c4', name: 'D' }),
    categoryUsual({ category_id: 'c5', name: 'E', flagged: false }),
  ],
  failed: [{ id: 7, error: 'Your wallet has less cash', createdAt: 1 }],
  ...over,
})

it('orders the attention items as the spec lists them', () => {
  expect(buildAttention(full()).map((i) => i.key)).toEqual([
    'match:m1',
    'overdue:late1', 'overdue:late2',
    'amount:est', 'amount:novalue',
    'budget:b2',
    'category:c1', 'category:c2', 'category:c3',
    'failed:7',
  ])
})

it('nothing to do is an empty list', () => {
  expect(buildAttention(full({ matches: [], overdue: [], upcoming: [], budgets: [], categories: [], failed: [] }))).toEqual([])
})

it('is ready only when every server source has data', () => {
  expect(attentionReady(full())).toBe(true)
  expect(attentionReady(full({ matches: undefined }))).toBe(false)
  expect(attentionReady(full({ categories: undefined }))).toBe(false)
})

it('the overdue window runs from the first of last month to yesterday', () => {
  expect(overdueWindow('2026-10-07')).toEqual({ from: '2026-09-01', to: '2026-10-06' })
  expect(overdueWindow('2026-01-01')).toEqual({ from: '2025-12-01', to: '2025-12-31' })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/home/attention.test.ts`
Expected: FAIL (`./attention` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/home/attention.ts`:

```ts
import type { BudgetRowOut, CategoryUsualOut, EntryOut, MatchOut, UpcomingDayOut } from '../../data/types'
import type { FailedQueueRow } from '../../offline/useQueue'
import { addDays, shiftMonth } from '../../ui/format'

export type AttentionItem =
  | { kind: 'match'; key: string; match: MatchOut }
  | { kind: 'overdue'; key: string; entry: EntryOut }
  | { kind: 'missingAmount'; key: string; entry: EntryOut }
  | { kind: 'budget'; key: string; row: BudgetRowOut }
  | { kind: 'category'; key: string; row: CategoryUsualOut }
  | { kind: 'failed'; key: string; change: FailedQueueRow }

/** undefined = not loaded (no cache, no answer yet). */
export interface AttentionInput {
  today: string
  matches?: MatchOut[]
  overdue?: EntryOut[]
  upcoming?: UpcomingDayOut[]
  budgets?: BudgetRowOut[]
  categories?: CategoryUsualOut[]
  failed: FailedQueueRow[]
}

export const BUDGET_WARN_PCT = 80
export const MAX_CATEGORIES = 3
export const MISSING_AMOUNT_DAYS = 7

/** Spec §5.2: from the first of last month to yesterday. */
export function overdueWindow(today: string): { from: string; to: string } {
  return { from: `${shiftMonth(today.slice(0, 7), -1)}-01`, to: addDays(today, -1) }
}

/** Home › Needs attention, in the spec's order. */
export function buildAttention(i: AttentionInput): AttentionItem[] {
  const horizon = addDays(i.today, MISSING_AMOUNT_DAYS)
  const overdue = (i.overdue ?? [])
    .filter((e) => e.overdue && e.status === 'expected')
    .sort((a, b) => a.due_date.localeCompare(b.due_date))
  const missing = (i.upcoming ?? [])
    .flatMap((d) => d.entries)
    .filter((e) => e.status === 'expected' && (e.estimated || e.amount === null) && e.due_date <= horizon)
  return [
    ...(i.matches ?? []).map((match): AttentionItem => ({ kind: 'match', key: `match:${match.id}`, match })),
    ...overdue.map((entry): AttentionItem => ({ kind: 'overdue', key: `overdue:${entry.id}`, entry })),
    ...missing.map((entry): AttentionItem => ({ kind: 'missingAmount', key: `amount:${entry.id}`, entry })),
    ...(i.budgets ?? [])
      .filter((b) => b.pct !== null && b.pct >= BUDGET_WARN_PCT)
      .map((row): AttentionItem => ({ kind: 'budget', key: `budget:${row.bucket_id}`, row })),
    ...(i.categories ?? [])
      .filter((c) => c.flagged)
      .slice(0, MAX_CATEGORIES)
      .map((row): AttentionItem => ({ kind: 'category', key: `category:${row.category_id ?? row.name}`, row })),
    ...i.failed.map((change): AttentionItem => ({ kind: 'failed', key: `failed:${change.id}`, change })),
  ]
}

/** True once every server source has data: only then does an empty list mean "All clear". */
export function attentionReady(i: AttentionInput): boolean {
  return [i.matches, i.overdue, i.upcoming, i.budgets, i.categories].every((x) => x !== undefined)
}
```

`web/src/features/home/hooks.ts`:

```ts
import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAction } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import { toTransactionPage } from '../../data/reads'
import type { EntryOut, MatchOut } from '../../data/types'
import { useFailedQueueRows } from '../../offline/useQueue'
import { todayISO } from '../../ui/format'
import { patchEntryEverywhere } from '../plan/entryPatch'
import { useBudgets, useCategoriesVsUsual, usePlanUpcoming } from '../plan/hooks'
import { attentionReady, buildAttention, overdueWindow, type AttentionInput, type AttentionItem } from './attention'

export const RECENT_COUNT = 10

export function useOverdueEntries(today: string = todayISO()) {
  const { from, to } = overdueWindow(today)
  return useCachedQuery(keys.home.overdue(from, to), (signal) =>
    unwrap(api.GET('/api/v1/recurring/entries', { params: { query: { from, to } }, signal })))
}

export function useMatches() {
  return useCachedQuery(keys.matches(), (signal) => unwrap(api.GET('/api/v1/matches', { signal })))
}

/** The last 10 transactions, newest first (spec §5.3). 2b merges its pending rows into this key. */
export function useRecentTransactions() {
  return useCachedQuery(keys.transactions.recent(), async (signal) =>
    toTransactionPage(await unwrap(api.GET('/api/v1/transactions', { params: { query: { page_size: RECENT_COUNT } }, signal }))).items)
}

const dropMatch = (qc: QueryClient, id: string) =>
  qc.setQueryData<MatchOut[]>(keys.matches(), (old) => old?.filter((m) => m.id !== id))

/** Link and Not this (spec §5.2.1); both optimistic and queueable. */
export function useMatchActions(match: MatchOut) {
  const link = useAction<void, EntryOut>({
    method: 'POST',
    path: `/api/v1/matches/${match.id}/link`,
    optimistic: (qc) => {
      dropMatch(qc, match.id)
      patchEntryEverywhere(qc, match.entry, { kind: 'linked' })
    },
    invalidates: affects.entry,
    pendingId: match.id,
  })
  const dismiss = useAction<void, null>({
    method: 'POST',
    path: `/api/v1/matches/${match.id}/dismiss`,
    optimistic: (qc) => dropMatch(qc, match.id),
    invalidates: [keys.matches()],
    pendingId: match.id,
  })
  return { link: () => link.run(), dismiss: () => dismiss.run(), busy: link.busy || dismiss.busy }
}

export function useAttention(): { items: AttentionItem[]; ready: boolean } {
  const today = todayISO()
  const matches = useMatches().data
  const overdue = useOverdueEntries(today).data
  const upcoming = usePlanUpcoming().data
  const budgets = useBudgets().data
  const categories = useCategoriesVsUsual(today.slice(0, 7)).data
  const failed = useFailedQueueRows()
  const input: AttentionInput = { today, matches, overdue, upcoming, budgets, categories, failed }
  return { items: buildAttention(input), ready: attentionReady(input) }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/home/attention.test.ts && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/home/attention.ts web/src/features/home/attention.test.ts web/src/features/home/hooks.ts
git commit -m "feat(web): Home attention model and hooks (matches, overdue, recent)"
```

---

### Task E2: Needs attention

**Stream:** E. **Depends on:** E1.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/home/home.css` (all Home styles)
- Create: `web/src/features/home/NeedsAttention.tsx`, `web/src/features/home/NeedsAttention.test.tsx`

**Interfaces:**
- Consumes: `useAttention`, `useMatchActions`, `AttentionItem` (E1); `EntrySheet`, `EntryIntent` (C1); `dismissFailed` (A7); `Badge`, `ListRow`, `Money`, the icons, `formatShortDate`; `useNavigate`.
- Produces: `NeedsAttention()`.

**Behaviour (spec §5.2):**
- The section is titled "Needs attention" with a count badge.
- When `ready` is false and there are no items, it renders nothing.
- When ready and empty, it shows "All clear" with a check.
- Each row carries `data-attn={kind}`:
  - **match:** "Payment €38.90 at Cosmote on 3 Oct looks like **Cosmote** due 5 Oct", with **Link** and **Not this** buttons. `MatchOut` has no payment method, so "Card payment" becomes "Payment".
  - **overdue:** the name, the subtitle "€650.00 · was due 1 Oct" and an "Overdue" badge. Tapping it opens the Entry sheet.
  - **missingAmount:** "Electricity needs an amount" and the subtitle "Due 9 Oct · usually ≈ €83.50". Tapping it opens the Entry sheet on Set amount.
  - **budget:** the name, the subtitle "€1,050 of €1,200" and a "N% used" badge. Tapping it goes to `/plan?view=budgets`.
  - **category:** "Groceries above usual", the subtitle "€412 this month · usually €300" and an "above usual" badge. Tapping it goes to `/plan?view=month`.
  - **failed:** "1 change couldn't be saved", with the server message as the subtitle and a **Dismiss** button that deletes the queue row.

- [ ] **Step 1: Write the failing test**

`web/src/features/home/NeedsAttention.test.tsx`:

```tsx
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { enqueue } from '../../offline/queue'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { budgetRow, categoryUsual, day, entry, match, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline, TEST_IDENTITY } from '../../test/render'
import { setIdentity } from '../../offline/identity'
import { NeedsAttention } from './NeedsAttention'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const LINK = 'POST /api/v1/matches/{match_id}/link' as const
const DISMISS = 'POST /api/v1/matches/{match_id}/dismiss' as const
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/matches': () => [match()],
  'GET /api/v1/recurring/entries': () => [entry({ id: 'e9', item_id: 'i9', name: 'Rent', overdue: true, due_date: '2026-10-01', amount: 650 })],
  'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry({ id: 'e5', name: 'Electricity', estimated: true, amount: 83.5 })], 900)],
  'GET /api/v1/plan/budgets': () => [budgetRow({ spent: 1050, pct: 87.5 })],
  'GET /api/v1/insights/categories-vs-usual': () => [categoryUsual()],
  [LINK]: () => entry({ status: 'done' }),
  [DISMISS]: () => null,
  ...over,
})
const kinds = () => Array.from(document.querySelectorAll('[data-attn]')).map((n) => n.getAttribute('data-attn'))

it('lists what needs a tap in the spec order, with words for each state', async () => {
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'budget', 'category']))
  expect(screen.getByRole('heading', { name: /Needs attention/ })).toHaveTextContent('Needs attention5')
  expect(document.querySelector('[data-attn="match"]')).toHaveTextContent('Payment €38.90 at Cosmote on 3 Oct looks like Cosmote due 5 Oct')
  expect(document.querySelector('[data-attn="overdue"]')).toHaveTextContent('Overdue')
  expect(document.querySelector('[data-attn="missingAmount"]')).toHaveTextContent('Electricity needs an amount')
  expect(document.querySelector('[data-attn="budget"]')).toHaveTextContent('€1,050 of €1,200')
  expect(document.querySelector('[data-attn="category"]')).toHaveTextContent('Groceries above usual')
})

it('Link and Not this remove the suggestion at once and call the API', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: 'Link' }))
  await waitFor(() => expect(kinds()).not.toContain('match'))
  expect(fake.callsTo(LINK)[0].path).toBe('/api/v1/matches/m1/link')
})

it('Not this dismisses', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: 'Not this' }))
  await waitFor(() => expect(fake.callsTo(DISMISS)).toHaveLength(1))
  expect(kinds()).not.toContain('match')
})

it('an overdue row opens the Entry sheet; a missing amount opens it on Set amount', async () => {
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: /Rent/ }))
  expect(screen.getByRole('dialog', { name: 'Rent' })).toHaveTextContent('Overdue')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: /Electricity needs an amount/ }))
  expect(screen.getByRole('dialog', { name: 'Electricity' })).toBeInTheDocument()
  expect(screen.getByLabelText('Amount')).toBeInTheDocument()
})

it('a queued change that failed is listed with the server message and can be dismissed', async () => {
  setIdentity(TEST_IDENTITY)
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: {} })
  const [row] = await db.queue.toArray()
  await db.queue.put({ ...row, status: 'failed', error: 'Your wallet has less cash' })
  fakeApi(routes({ 'GET /api/v1/matches': () => [], 'GET /api/v1/recurring/entries': () => [] }))
  renderWithProviders(<NeedsAttention />)
  const failed = await screen.findByText("1 change couldn't be saved")
  expect(failed.closest('[data-attn]')).toHaveTextContent('Your wallet has less cash')
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  await waitFor(() => expect(kinds()).not.toContain('failed'))
  expect(await db.queue.count()).toBe(0)
})

it('All clear when everything loaded and nothing needs attention', async () => {
  fakeApi(routes({
    'GET /api/v1/matches': () => [], 'GET /api/v1/recurring/entries': () => [], 'GET /api/v1/plan/upcoming': () => [],
    'GET /api/v1/plan/budgets': () => [], 'GET /api/v1/insights/categories-vs-usual': () => [],
  }))
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByText('All clear')).toBeInTheDocument()
})

it('offline with nothing saved: no false "All clear"', async () => {
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<NeedsAttention />)
  await new Promise((r) => setTimeout(r, 50))
  expect(screen.queryByText('All clear')).toBeNull()
  expect(screen.queryByRole('heading', { name: /Needs attention/ })).toBeNull()
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/home/NeedsAttention.test.tsx`
Expected: FAIL (`./NeedsAttention` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/home/NeedsAttention.tsx`:

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router'
import type { EntryOut, MatchOut } from '../../data/types'
import { dismissFailed } from '../../offline/useQueue'
import { Badge } from '../../ui/Badge'
import { formatShortDate } from '../../ui/format'
import { AlertIcon, CheckIcon, LinkIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { EntrySheet, type EntryIntent } from '../plan/EntrySheet'
import type { AttentionItem } from './attention'
import { useAttention, useMatchActions } from './hooks'
import './home.css'

export function NeedsAttention() {
  const { items, ready } = useAttention()
  const [open, setOpen] = useState<{ entry: EntryOut; intent: EntryIntent } | null>(null)
  if (!ready && items.length === 0) return null
  return (
    <section className="home-attn" aria-labelledby="attn-title">
      <div className="ui-sec">
        <h2 id="attn-title" className="ui-sec__title">
          Needs attention{items.length > 0 && <Badge tone="neg">{items.length}</Badge>}
        </h2>
      </div>
      {items.length === 0 ? (
        <div className="ui-card home-clear"><CheckIcon /> All clear</div>
      ) : (
        <div className="ui-list">
          {items.map((it) => (
            <div key={it.key} className="home-attn__wrap" data-attn={it.kind}>
              <AttentionRow item={it} onOpen={(entry, intent) => setOpen({ entry, intent })} />
            </div>
          ))}
        </div>
      )}
      <EntrySheet entry={open?.entry ?? null} intent={open?.intent} onClose={() => setOpen(null)} />
    </section>
  )
}

function AttentionRow({ item, onOpen }: { item: AttentionItem; onOpen: (e: EntryOut, intent: EntryIntent) => void }) {
  const navigate = useNavigate()
  switch (item.kind) {
    case 'match':
      return <MatchRow match={item.match} />
    case 'overdue': {
      const e = item.entry
      return (
        <ListRow onClick={() => onOpen(e, 'default')}
          leading={<span className="ui-ico ui-ico--neg"><AlertIcon /></span>}
          title={e.name}
          subtitle={<><Money amount={e.amount} currency={e.currency} nullText="No amount yet" /> · was due {formatShortDate(e.due_date)}</>}
          badges={<Badge tone="neg">Overdue</Badge>} />
      )
    }
    case 'missingAmount': {
      const e = item.entry
      return (
        <ListRow onClick={() => onOpen(e, 'amount')}
          leading={<span className="ui-ico ui-ico--warn"><AlertIcon /></span>}
          title={`${e.name} needs an amount`}
          subtitle={<>Due {formatShortDate(e.due_date)}{e.amount !== null && <> · usually <Money amount={e.amount} estimated currency={e.currency} /></>}</>}
          trailing={<span className="home-attn__cta">Set</span>} />
      )
    }
    case 'budget': {
      const b = item.row
      return (
        <ListRow onClick={() => navigate('/plan?view=budgets')}
          title={b.name}
          subtitle={b.budget === null ? undefined : <><Money amount={b.spent} whole /> of <Money amount={b.budget} whole /></>}
          badges={<Badge tone={b.pct !== null && b.pct >= 100 ? 'neg' : 'warn'}>{`${Math.round(b.pct ?? 0)}% used`}</Badge>} />
      )
    }
    case 'category': {
      const c = item.row
      return (
        <ListRow onClick={() => navigate('/plan?view=month')}
          leading={<span className="home-attn__emoji" aria-hidden="true">{c.icon}</span>}
          title={`${c.name} above usual`}
          subtitle={<><Money amount={c.this_month} whole /> this month{c.usual !== null && <> · usually <Money amount={c.usual} whole /></>}</>}
          badges={<Badge tone="warn">above usual</Badge>} />
      )
    }
    case 'failed':
      return (
        <div className="home-attn__item">
          <span className="ui-ico ui-ico--neg"><AlertIcon /></span>
          <div className="home-attn__text">
            <div className="ui-row__title">1 change couldn't be saved</div>
            <div className="home-attn__sub">{item.change.error}</div>
          </div>
          <button type="button" className="btn btn--sm" onClick={() => void dismissFailed(item.change.id)}>Dismiss</button>
        </div>
      )
  }
}

function MatchRow({ match }: { match: MatchOut }) {
  const actions = useMatchActions(match)
  return (
    <div className="home-attn__item">
      <span className="ui-ico ui-ico--acc"><LinkIcon /></span>
      <p className="home-attn__text">
        Payment <Money amount={match.transaction_amount} /> at {match.merchant ?? match.label} on{' '}
        {formatShortDate(match.transaction_date)} looks like <strong>{match.entry.name}</strong> due{' '}
        {formatShortDate(match.entry.due_date)}
      </p>
      <div className="home-attn__acts">
        <button type="button" className="btn btn--sm btn--primary" disabled={actions.busy} onClick={() => void actions.link()}>Link</button>
        <button type="button" className="btn btn--sm" disabled={actions.busy} onClick={() => void actions.dismiss()}>Not this</button>
      </div>
    </div>
  )
}
```

`web/src/features/home/home.css`:

```css
/* Home: hero, Needs attention, Recent activity. Kit classes come from ui/ui.css. */
.home { display: flex; flex-direction: column; gap: 4px; }

.home-hero { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
.home-hero__eyebrow { color: inherit; opacity: .75; }
.home-hero__figure { font-size: 44px; }
.home-hero__sub { margin: 0; font-size: 13.5px; opacity: .85; }
.home-hero .ui-money { color: inherit; }

.ui-list > .home-attn__wrap + .home-attn__wrap { border-top: 1px solid var(--line); }
.home-attn__item { display: flex; align-items: center; gap: 12px; padding: 12px 14px; }
.home-attn__text { flex: 1; min-width: 0; margin: 0; font-size: 14px; line-height: 1.4; }
.home-attn__sub { font-size: 12.5px; color: var(--muted); overflow-wrap: anywhere; }
.home-attn__acts { display: flex; flex-direction: column; gap: 6px; flex: none; }
.home-attn__cta { font-size: 14px; font-weight: 650; color: var(--accent); }
.home-attn__emoji { width: 36px; height: 36px; display: grid; place-items: center; border-radius: var(--r-sm); background: var(--surface-2); font-size: 18px; }
.home-clear { display: flex; align-items: center; gap: 10px; color: var(--pos); font-weight: 650; }
.home-clear .ui-icon { width: 20px; height: 20px; }

.home-recent { margin-top: 4px; }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm test -- src/features/home/NeedsAttention.test.tsx && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/home/NeedsAttention.tsx web/src/features/home/NeedsAttention.test.tsx web/src/features/home/home.css
git commit -m "feat(web): Home › Needs attention with match links, overdue, amounts and failed changes"
```

---
### Task E3: The Home screen and Recent activity

**Stream:** E. **Depends on:** E2.

Load skills `frontend-design`, `mobile-native` and `apple-design` before writing UI code.

**Files:**
- Create: `web/src/features/home/RecentActivity.tsx`
- Create: `web/src/features/home/Home.tsx`, `web/src/features/home/Home.test.tsx`
- Modify: `web/src/screens/Home.tsx` (becomes a one-line re-export)

**Interfaces:**
- Consumes: `usePlanMonth` (C1), `NeedsAttention` (E2), `useRecentTransactions` (E1), `useBuckets` (A8), `TopBar`, `QueryView`, `EmptyState`, `ListRow`, `Money`, `formatMonthName`, `formatShortDate`, `todayISO`; `Link`.
- Produces: `Home()`, re-exported by `screens/Home.tsx`; `RecentActivity()`.

**Behaviour (spec §5):**
- **Header (hero card):**
  - the eyebrow is "October · projected" (month name · projected);
  - the big figure is this month's **Net (projected)**: signed, with "≈" when `estimated`;
  - under it, "In €3,150.00 so far · Out €1,285.00 so far", where Out so far is `fixed.so_far + buckets.so_far`.
  - Offline with nothing saved, it shows "No saved data yet. Connect once to load Home."
- **Needs attention** comes next (E2).
- **Recent activity** has the heading and a "See all" link to `/activity`. It shows the last 10 transactions, read-only:
  - the label is the merchant, else the notes, else "Income" or "Expense";
  - the subtitle is the date ("6 Oct") plus " · " and the bucket name when there is one;
  - the amount is signed (income +, expense −) with `tone="auto"`;
  - its `QueryView` sets `showBanner={false}`, so the offline banner appears once per screen;
  - with no transactions it shows "No payments yet".

- [ ] **Step 1: Write the failing test**

`web/src/features/home/Home.test.tsx`:

```tsx
import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cachePut } from '../../offline/db'
import { cacheKeyFor } from '../../data/cachedQuery'
import { keys } from '../../data/keys'
import { setIdentity } from '../../offline/identity'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { monthPicture, page, readRoutes, txn } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline, TEST_IDENTITY } from '../../test/render'
import { Home } from './Home'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const recent = [
  txn(),
  txn({ id: 't2', type: 'income', amount: 2450, merchant: null, notes: 'Salary', bucket_id: null, transaction_date: '2026-10-01' }),
]
const routes = (): Routes => ({
  ...readRoutes(),
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/transactions': () => page(recent),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
})

it('leads with the projected net and what came in and went out so far', async () => {
  fakeApi(routes())
  renderWithProviders(<Home />)
  expect(screen.getByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
  expect(screen.getByText(/October · projected/)).toBeInTheDocument()
  expect(screen.getByText(/so far ·/).closest('p')).toHaveTextContent('In €3,150.00 so far · Out €1,285.00 so far')
})

it('lists recent activity read-only, signed, with the bucket, and links to Activity', async () => {
  fakeApi(routes())
  renderWithProviders(<Home />)
  const recentSection = await screen.findByRole('region', { name: 'Recent activity' })
  const sklav = (await within(recentSection).findByText('Sklavenitis')).closest('.ui-row')!
  expect(sklav.tagName).toBe('DIV')
  expect(sklav).toHaveTextContent('6 Oct · Day to day')
  expect(sklav).toHaveTextContent('−€64.20')
  expect(within(recentSection).getByText('Salary').closest('.ui-row')).toHaveTextContent('+€2,450.00')
  expect(within(recentSection).getByRole('link', { name: 'See all' })).toHaveAttribute('href', '/activity')
  expect(await screen.findByText('All clear')).toBeInTheDocument()
})

it('offline with a saved month: shows it once with the banner', async () => {
  setIdentity(TEST_IDENTITY)
  await cachePut(cacheKeyFor('h1', keys.plan.month('2026-10')), monthPicture())
  await cachePut(cacheKeyFor('h1', keys.transactions.recent()), recent)
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<Home />)
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
  expect(await screen.findByText('Sklavenitis')).toBeInTheDocument()
  expect(screen.getAllByText(/Offline · updated/)).toHaveLength(1)
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm test -- src/features/home/Home.test.tsx`
Expected: FAIL (`./Home` not found).

- [ ] **Step 3: Write the implementation**

`web/src/features/home/RecentActivity.tsx`:

```tsx
import { Link } from 'react-router'
import { useBuckets } from '../../data/reads'
import type { TransactionRow } from '../../data/types'
import { EmptyState } from '../../ui/EmptyState'
import { formatShortDate } from '../../ui/format'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { useRecentTransactions } from './hooks'
import './home.css'

const label = (t: TransactionRow) => t.merchant || t.notes || (t.type === 'income' ? 'Income' : 'Expense')

export function RecentActivity() {
  const recent = useRecentTransactions()
  const buckets = useBuckets().data
  const bucketName = (id: string | null) => (id ? buckets?.find((b) => b.id === id)?.name : undefined)
  return (
    <section className="home-recent" aria-labelledby="recent-title">
      <div className="ui-sec">
        <h2 id="recent-title" className="ui-sec__title">Recent activity</h2>
        <Link to="/activity">See all</Link>
      </div>
      <QueryView result={recent} noDataText="No saved activity yet." showBanner={false}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title="No payments yet" />
          ) : (
            <div className="ui-list">
              {rows.map((t) => (
                <ListRow key={t.id}
                  title={label(t)}
                  subtitle={[formatShortDate(t.transaction_date), bucketName(t.bucket_id)].filter(Boolean).join(' · ')}
                  trailing={<Money amount={t.type === 'income' ? t.amount : -t.amount} currency={t.currency} signed tone="auto" />} />
              ))}
            </div>
          )
        }
      </QueryView>
    </section>
  )
}
```

`web/src/features/home/Home.tsx`:

```tsx
import type { MonthPictureOut } from '../../data/types'
import { TopBar } from '../../shell/TopBar'
import { formatMonthName, todayISO } from '../../ui/format'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { usePlanMonth } from '../plan/hooks'
import { NeedsAttention } from './NeedsAttention'
import { RecentActivity } from './RecentActivity'
import './home.css'

export function Home() {
  const picture = usePlanMonth(todayISO().slice(0, 7))
  return (
    <>
      <TopBar title="Home" />
      <section className="screen home">
        <QueryView result={picture} noDataText="No saved data yet. Connect once to load Home.">
          {(p) => <HomeFigure picture={p} />}
        </QueryView>
        <NeedsAttention />
        <RecentActivity />
      </section>
    </>
  )
}

function HomeFigure({ picture: p }: { picture: MonthPictureOut }) {
  const outSoFar = p.fixed.so_far + p.buckets.so_far
  return (
    <div className="ui-hero home-hero">
      <p className="ui-eyebrow home-hero__eyebrow">{formatMonthName(Number(p.month.slice(5, 7)))} · projected</p>
      <Money className="ui-figure home-hero__figure" amount={p.net_projected} signed estimated={p.estimated} />
      <p className="home-hero__sub">
        In <Money amount={p.income.so_far} /> so far · Out <Money amount={outSoFar} /> so far
      </p>
    </div>
  )
}
```

`web/src/screens/Home.tsx` (the whole file):

```tsx
export { Home } from '../features/home/Home'
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npm test -- src/features/home && npm run typecheck && npm run lint`
Expected: PASS (E1–E3); lint reports no errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/home/RecentActivity.tsx web/src/features/home/Home.tsx web/src/features/home/Home.test.tsx web/src/screens/Home.tsx
git commit -m "feat(web): Home with projected net, Needs attention and recent activity"
```

---

## Integration

### Task INT: Merge the streams, run everything, check by hand in Chrome

**Stream:** none (it runs on `feat/phase2a-plan-home` in `/Users/giorgoscharitidis/expenses-p2`). **Depends on:** A8, B1, C6, D5, E3.

Load skills `frontend-design`, `mobile-native` and `apple-design` before fixing any UI found in the manual pass.

**Files:**
- Modify: only what a failing check points to. Each fix gets its own commit naming the check it fixes.

- [ ] **Step 1: Merge in order**

```bash
cd /Users/giorgoscharitidis/expenses-p2
git checkout feat/phase2a-plan-home
git merge --no-ff feat/2a-a -m "Merge stream A: UI kit and data layer"
git merge --no-ff feat/2a-b -m "Merge stream B: rule preview endpoint"
git merge --no-ff feat/2a-c -m "Merge stream C: Plan screens and the Entry sheet"
git merge --no-ff feat/2a-d -m "Merge stream D: Items and the Item sheet"
git merge --no-ff feat/2a-e -m "Merge stream E: Home"
```

Expected: no conflicts. Each shared file has one owner, D already contains B, and D and E share the `2a-c1` commit with C. If `schema.d.ts` conflicts, take B's version and re-run `npm run gen:api` in Step 2.

- [ ] **Step 2: Run every check**

```bash
cd /Users/giorgoscharitidis/expenses-p2/web && npm ci
npm run gen:api && git diff --exit-code src/api   # the checked-in types match the backend
npm test
npm run typecheck
npm run lint
npm run build
cd .. && .venv/bin/python -m pytest -n 8 -o addopts="" -p no:cacheprovider
.venv/bin/ruff format --check . && .venv/bin/ruff check .
```

Expected: every command exits 0. Investigate any failure with superpowers:systematic-debugging before changing code. Fix it in the owning stream's files and re-run that check.

- [ ] **Step 3: Start the app with real data**

```bash
cd /Users/giorgoscharitidis/expenses-p2
NEW_APP_ENABLED=true DEBUG=true APP_SECRET_KEY=dev-only-secret .venv/bin/uvicorn app.main:app --port 8000
# in a second terminal:
cd /Users/giorgoscharitidis/expenses-p2/web && npm run dev
```

Seed a household:
1. Open `http://localhost:8000/` and finish the setup wizard (first run).
2. In the old UI, add a monthly bucket "Day to day" with a €1,200 budget. Add three expenses this month in it, and one €38.90 card expense with the merchant "Cosmote", dated two days ago.
3. Open `http://localhost:5173/app/`. Cookies are per host, not per port, so the session carries over.
4. In Plan › Items, create:
   - "Salary": In, €1,500, day 26, business day before;
   - "Partner salary": In, variable, last business day;
   - "Cosmote": Out, €38.90, day 9, in Day to day;
   - "Christmas bonus": In, €800, every year on 21 December, business day before.

- [ ] **Step 4: Manual pass in Chrome at 390×844, dark then light**

Use the chrome-devtools MCP tools:
- set the viewport to 390×844 (`resize_page` or `emulate`);
- switch modes with `emulate` and `colorScheme` set to `dark`, then `light`;
- take a `take_screenshot` of each screen in both modes.

Check each item:
- [ ] Item sheet: the preview line shows three dates for each rule, and "Preview needs a connection" with the network set to Offline.
- [ ] Items: In and Out groups, schedule summaries, "variable", next dates. Pausing an item greys it with "Paused".
- [ ] Upcoming: day headers, running net, "≈" on estimates. A row opens the Entry sheet. Paid closes it and the net moves at once. Undo of a paid Fixed cost shows the server message and "Delete the expense".
- [ ] Month: the table fits at 390 px without horizontal scroll. Bucket rows expand. Dec → Jan works. The switcher stops at ±11.
- [ ] Year: bars to scale, values readable, footer present.
- [ ] Budgets: tints at 80% and 100% plus the words. "on pace for" appears from the 7th.
- [ ] Home: projected net, "In … so far · Out … so far". Needs attention lists the Cosmote match: **Link** clears it, and the Cosmote entry turns done. Recent activity shows the expenses.
- [ ] Offline (DevTools Network → Offline):
  - reload: Plan and Home render from the cache with "Offline · updated HH:MM";
  - mark an entry paid: the row shows "Waiting to sync";
  - go back online: the queue replays, the badge clears, and the figures refresh.
- [ ] A failed replay: queue a Skip offline, then Skip the same entry from the old UI. Back online, Home shows "1 change couldn't be saved" with Dismiss.
- [ ] Every screenshot, both modes:
  - no horizontal overflow;
  - text and badges readable (contrast);
  - tap targets at least 44 px;
  - sheets clear the home indicator;
  - nothing hidden under the tab bar.

- [ ] **Step 5: Commit any fixes and report**

```bash
git status   # only intended fixes
git add <fixed files> && git commit -m "fix(web): <what the manual pass found>"
```

Report:
- each check's result, with its command output summary;
- the screenshots' paths;
- anything deferred.

The final review runs on the most capable model (spec §10). The user merges to `main`.

---

## Decisions this plan makes where the spec is open

1. **The Entry sheet and plan hooks are task C1, and D and E branch from it (tag `2a-c1`).** The spec says C, D and E start after A. But Upcoming, Home and Items all open the Entry sheet, and Home reads the plan hooks, so C1 has to come first.
2. **Items is a route, `/plan/items`, owned by D** (D5 edits `router.tsx`). Plan's **Items** button is a link, so C never imports D's code. D's files live in `features/plan/items/`.
3. **The household id is in the device-cache key** (`q:<hh>:<JSON key>`) but not in the TanStack keys. SessionProvider already clears the query client on every account or household change. This keeps optimistic patches and invalidation prefix-based.
4. **`initialData` can't be synchronous.** The cache needs an async decrypt. `useCachedQuery` instead seeds an empty query with `setQueryData(value, { updatedAt })` from the new `cacheEntry()`, and never overwrites data that has already arrived.
5. **`useAction` never throws.** It resolves `done | queued | rejected`: 2b's union plus `rejected`, so the sheets can stay open.
   - 401 is not queued. The session middleware signs out, and the user redoes the change.
   - 408, 429, 5xx and network errors are queued.
   - 4xx errors are rolled back and toasted.
   - FastAPI's list-shaped 422 `detail` gets a readable message.
6. **Queue drain and failures.** `onQueueDrained` is added to `offline/queue.ts`, and `installQueueBridge` invalidates `affects.sync` and clears the pending markers. Failed rows come from `useFailedQueueRows` / `dismissFailed` in `offline/useQueue.ts`.
7. **The toast is a module store** (`toast()`), so `useAction` can call it outside React. It has `action` and `durationMs`, which 2c needs.
8. **The Sheet is a portal with `role="dialog"`**, not a `<dialog>`, because jsdom lacks `showModal`. It has its own focus trap, Esc handling, backdrop close (with an opt-out for 2d) and safe-area padding.
9. **Shared reads live in `data/reads.ts`:** household, items, buckets, categories and the transaction narrowing. C, D, E, 2b and 2d all use them. `keys.transactions.recent()` holds `TransactionRow[]`.
10. **Rule picker:**
    - Yearly and Easter rules also get the business-day adjustment (the planning spec allows it, and the Christmas bonus needs it).
    - The monthly kinds keep an item's `interval_months`.
    - Easter is entered as days plus Before/After, because the iOS numeric keypad has no minus.
11. **Rule preview semantics.** Dates are generated from `start_date` and filtered to `≥ max(today, start)`, so `monthly_interval` and `weekly` keep their anchor. `until` covers 12 dates 120 months apart. An end date before the start date returns 400.
12. **Item history** is `GET /transactions?recurring_bill_id&page_size=1`. It locks the direction and hides Delete. "Pause instead" pauses the saved item, not unsaved edits.
13. **Match row copy.** It says "Payment …", not "Card payment …", because `MatchOut` has no payment method. Link uses an `EntryChange` `linked`, so the running net doesn't count the money twice.
14. **"Missing an amount"** also covers entries whose amount is null.
15. **The Month table** uses whole euros so four columns fit at 360 px. Net and the lines outside Net keep their cents.
