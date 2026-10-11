import type { BudgetRowOut, CategoryUsualOut, EntryOut, MatchOut, UpcomingDayOut } from '../../data/types'
import type { FailedQueueRow } from '../../offline/useQueue'
import { addDays, shiftMonth } from '../../ui/format'
import type { BillRow } from '../insights/bills/types'
import type { StatementReview } from '../insights/statements/types'

type AttentionVariant =
  | { kind: 'monthReview'; key: string; review: StatementReview }
  | { kind: 'match'; key: string; match: MatchOut }
  | { kind: 'overdue'; key: string; entry: EntryOut }
  | { kind: 'missingAmount'; key: string; entry: EntryOut }
  | { kind: 'billChange'; key: string; bill: BillRow }
  | { kind: 'cash'; key: string; amount: number }
  | { kind: 'pantry'; key: string; count: number }
  | { kind: 'budget'; key: string; row: BudgetRowOut }
  | { kind: 'category'; key: string; row: CategoryUsualOut }
  | { kind: 'failed'; key: string; change: FailedQueueRow }

/** `also`: lines of other kinds about the same recurring item, merged under this row (spec §2.1). */
export type AttentionItem = AttentionVariant & { also?: AttentionVariant[] }

/** Spec §2.1: most urgent first. */
export const ATTENTION_ORDER: AttentionVariant['kind'][] = [
  'failed', 'overdue', 'monthReview', 'match', 'missingAmount', 'cash', 'billChange', 'budget', 'pantry', 'category',
]
export const ATTENTION_VISIBLE = 3

const itemIdOf = (it: AttentionVariant): string | null =>
  it.kind === 'overdue' || it.kind === 'missingAmount' ? it.entry.item_id : it.kind === 'billChange' ? it.bill.item_id : null

/** One row per recurring item: a later kind about the same item becomes a line under the first (most urgent) row. */
function mergeByItem(sorted: AttentionVariant[]): AttentionItem[] {
  const primary = new Map<string, AttentionItem>()
  const out: AttentionItem[] = []
  for (const it of sorted) {
    const id = itemIdOf(it)
    const head = id === null ? undefined : primary.get(id)
    if (head && head.kind !== it.kind) {
      head.also = [...(head.also ?? []), it]
      continue
    }
    const row: AttentionItem = { ...it }
    if (id !== null && !head) primary.set(id, row)
    out.push(row)
  }
  return out
}

/** The rows that show, and how many wait behind "Show N more". */
export function visibleAttention<T>(rows: T[], expanded: boolean): { shown: T[]; hidden: number } {
  const hidden = Math.max(0, rows.length - ATTENTION_VISIBLE)
  return { shown: expanded ? rows : rows.slice(0, ATTENTION_VISIBLE), hidden }
}

/** undefined = not loaded (no cache, no answer yet). */
export interface AttentionInput {
  today: string
  matches?: MatchOut[]
  overdue?: EntryOut[]
  upcoming?: UpcomingDayOut[]
  budgets?: BudgetRowOut[]
  categories?: CategoryUsualOut[]
  /** The viewer's own not-yet-logged cash this month (GET /cash/wallets); undefined when not cached. */
  cashNotLogged?: number
  /** Pantry items running low (GET /stock/summary); undefined when not cached. Never holds back "All clear". */
  pantryLow?: number
  /** GET /insights/bills (spec §5.5); undefined when not cached, which hides the row without an error. */
  bills?: BillRow[]
  /** Entry ids of bill changes the user dismissed on this device. */
  dismissedBills?: ReadonlySet<string>
  /** GET /insights/statements `review` (Phase B §4.5): undefined when the list is not cached, null when there is nothing to review. */
  review?: StatementReview | null
  failed: FailedQueueRow[]
}

/** Below half a cent is nothing to log (cash spec §4.6). */
export const CASH_EPS = 0.005

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
  const flat: AttentionVariant[] = [
    // The one row about the past month; it expires by itself (the server stops sending `review` after day 5).
    // Saved while the window was open and read after it closed (offline): the server would send null by now.
    ...(i.review && i.today <= `${shiftMonth(i.review.month, 1)}-05`
      ? [{ kind: 'monthReview', key: `review:${i.review.month}`, review: i.review } satisfies AttentionVariant]
      : []),
    ...(i.matches ?? []).map((match): AttentionVariant => ({ kind: 'match', key: `match:${match.id}`, match })),
    ...overdue.map((entry): AttentionVariant => ({ kind: 'overdue', key: `overdue:${entry.id}`, entry })),
    ...missing.map((entry): AttentionVariant => ({ kind: 'missingAmount', key: `amount:${entry.id}`, entry })),
    ...(i.bills ?? [])
      .filter((b) => b.change !== null && !i.dismissedBills?.has(b.change.entry_id))
      .map((bill): AttentionVariant => ({ kind: 'billChange', key: `bill:${bill.item_id}:${bill.change?.entry_id}`, bill })),
    ...(i.cashNotLogged !== undefined && i.cashNotLogged > CASH_EPS
      ? [{ kind: 'cash', key: 'cash', amount: i.cashNotLogged } satisfies AttentionVariant]
      : []),
    ...(i.pantryLow !== undefined && i.pantryLow > 0
      ? [{ kind: 'pantry', key: 'pantry', count: i.pantryLow } satisfies AttentionVariant]
      : []),
    ...(i.budgets ?? [])
      .filter((b) => b.pct !== null && b.pct >= BUDGET_WARN_PCT)
      .map((row): AttentionVariant => ({ kind: 'budget', key: `budget:${row.bucket_id}`, row })),
    ...(i.categories ?? [])
      .filter((c) => c.flagged)
      .slice(0, MAX_CATEGORIES)
      .map((row): AttentionVariant => ({ kind: 'category', key: `category:${row.category_id ?? row.name}`, row })),
    ...i.failed.map((change): AttentionVariant => ({ kind: 'failed', key: `failed:${change.id}`, change })),
  ]
  return mergeByItem(ATTENTION_ORDER.flatMap((k) => flat.filter((x) => x.kind === k)))
}

/** True once every server source has data: only then does an empty list mean "All clear". */
export function attentionReady(i: AttentionInput): boolean {
  return [i.matches, i.overdue, i.upcoming, i.budgets, i.categories].every((x) => x !== undefined)
}
