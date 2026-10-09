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
  /** "All" while some matching rows are pending or mid-delete: these rows by id instead of the filter. */
  | { type: 'pick'; ids: string[] }
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
    case 'pick':
      return { kind: 'picked', ids: a.ids }
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

/** The server's cap on one bulk request (app/services/bulk.py BULK_MAX_ROWS), for ids and filter matches. */
export const BULK_MAX_ROWS = 1000

export type AllMode =
  | { kind: 'filter'; count: number }
  | { kind: 'ids'; count: number }
  | { kind: 'off'; reason: 'pending' | 'too-many' | null }

/**
 * What "Select › All" does. It is the filter on the server, unless a matching row is pending (a queued edit
 * or delete) or in its swipe-delete hold: the server would change that row too, and the queued write would
 * undo it later (P3 M1). Then, with every row loaded, All picks the selectable rows by id (up to the server's
 * cap); with more to load it is off until the sync, because an unloaded page may hold a pending row.
 * `pending` is global on purpose: a queued write on a row outside the loaded pages may still match.
 */
export function allMode(i: {
  total: number; selectable: number; excluded: number; complete: boolean; pending: boolean; emptyFilter: boolean
}): AllMode {
  if (i.pending && !i.complete) return { kind: 'off', reason: 'pending' }
  if (i.excluded > 0) {
    if (i.selectable > BULK_MAX_ROWS) return { kind: 'off', reason: 'too-many' }
    return i.selectable > 0 ? { kind: 'ids', count: i.selectable } : { kind: 'off', reason: null }
  }
  // Select by filter needs a filter: the server refuses an empty one (400), and so it does more matches than
  // the cap (400 "N transactions match. Narrow the filter").
  if (i.total > BULK_MAX_ROWS && !i.emptyFilter) return { kind: 'off', reason: 'too-many' }
  return i.total > 0 && !i.emptyFilter ? { kind: 'filter', count: i.total } : { kind: 'off', reason: null }
}
