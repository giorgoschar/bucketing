// Hand-typed from spec §3 (docs/superpowers/specs/2026-10-09-phase-a-desktop-bills-design.md) until the
// server stream's `npm run gen:api` lands. Integration replaces these with aliases of the generated schema.
import type { EntryDoneIn, EntryOut, RecurringItemIn, RecurringItemOut } from '../../../data/types'

/** §3.4: the change of the latest done entry against its baseline. */
export interface BillChange {
  entry_id: string
  amount: number
  usual: number
  basis: 'last_year' | 'recent'
  delta: number
  pct: number
  direction: 'up' | 'down'
  reason: 'usage' | 'price' | null
  reason_pct: number | null
}

/** §3.5 */
export interface HistoryPoint {
  entry_id: string
  due_date: string
  amount: number
  usage: number | null
  unit_price: number | null
  transaction_id: string | null
}

export interface HistoryItem {
  id: string
  name: string
  direction: 'in' | 'out'
  currency: string
  usage_unit: string | null
  category_id: string | null
  is_active: boolean
}

export interface ItemHistoryOut {
  item: HistoryItem
  points: HistoryPoint[]
  change: BillChange | null
}

/** §3.6 */
export interface BillRow {
  item_id: string
  name: string
  category_id: string | null
  usage_unit: string | null
  is_active: boolean
  last: { entry_id: string; due_date: string; amount: number } | null
  recent: number[]
  total_12m: number | null
  average_12m: number | null
  change: BillChange | null
}

/** §3.2: the entry and the item carry usage until the generated types do. */
export type EntryWithUsage = EntryOut & { usage?: number | null; usage_unit?: string | null }
export type ItemWithUsage = RecurringItemOut & { usage_unit?: string | null }
export type ItemInWithUsage = RecurringItemIn & { usage_unit?: string | null }
export type EntryDoneWithUsage = EntryDoneIn & { usage?: number }
