import { isEmpty, toQuery, type TransactionFilter } from './filters'

export type Selection =
  | { kind: 'off' }
  | { kind: 'picked'; ids: string[] }
  | { kind: 'filter'; filter: TransactionFilter; count: number }
  | { kind: 'bill'; billId: string; count: number }

export type SelectionAction =
  | { type: 'enter'; id?: string }
  | { type: 'toggle'; id: string; loadedIds: string[] }
  | { type: 'all'; filter: TransactionFilter; total: number }
  | { type: 'cancel' }

export type BulkSelect = { ids: string[] } | { filter: Record<string, string | boolean> } | { bill_id: string }

export const OFF: Selection = { kind: 'off' }

/** By bill only when the item is the whole filter; anything more could make
 * the two selections differ. */
function billOnly(f: TransactionFilter): string | null {
  const { recurring_bill_id, ...rest } = f
  return recurring_bill_id && isEmpty(rest) ? recurring_bill_id : null
}

export function reduce(s: Selection, a: SelectionAction): Selection {
  switch (a.type) {
    case 'cancel':
      return OFF
    case 'enter':
      return s.kind === 'off' ? { kind: 'picked', ids: a.id ? [a.id] : [] } : s
    case 'all': {
      const bill = billOnly(a.filter)
      return bill ? { kind: 'bill', billId: bill, count: a.total } : { kind: 'filter', filter: a.filter, count: a.total }
    }
    case 'toggle':
      // Unticking a row in an "All" selection returns to hand-picked: the loaded rows minus that one.
      if (s.kind === 'filter' || s.kind === 'bill') return { kind: 'picked', ids: a.loadedIds.filter((id) => id !== a.id) }
      if (s.kind === 'off') return { kind: 'picked', ids: [a.id] }
      return { kind: 'picked', ids: s.ids.includes(a.id) ? s.ids.filter((i) => i !== a.id) : [...s.ids, a.id] }
  }
}

export const isSelected = (s: Selection, id: string) =>
  s.kind === 'filter' || s.kind === 'bill' || (s.kind === 'picked' && s.ids.includes(id))

export const selectedCount = (s: Selection) =>
  s.kind === 'off' ? 0 : s.kind === 'picked' ? s.ids.length : s.count

export function toSelect(s: Selection): BulkSelect {
  if (s.kind === 'filter') return { filter: toQuery(s.filter) }
  if (s.kind === 'bill') return { bill_id: s.billId }
  return { ids: s.kind === 'picked' ? s.ids : [] }
}

/** Sent with apply for filter and bill selections: the server answers 409 on drift. */
export const expectedCount = (s: Selection) => (s.kind === 'filter' || s.kind === 'bill' ? s.count : null)
