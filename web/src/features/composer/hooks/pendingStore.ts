/**
 * In-memory rows for saves in flight, ids hidden by a delete, and the id to highlight on Home
 * (spec §4.12, §5.3). Queued writes that survive a reload come from the queue itself (C5-2).
 */
export interface PendingRow {
  /** client_id for a create, the transaction id for an edit. */
  key: string
  id: string | null
  client_id: string | null
  type: 'expense' | 'income'
  /** Decimal string as sent, e.g. "3.00". */
  amount: string
  currency: string
  bucket_id: string | null
  category_id: string | null
  merchant: string | null
  transaction_date: string
  state: 'sending' | 'waiting'
}

interface Snapshot { inFlight: readonly PendingRow[]; hidden: ReadonlySet<string>; justSaved: string | null }

const HIGHLIGHT_MS = 2000
const EMPTY: Snapshot = { inFlight: [], hidden: new Set(), justSaved: null }
let snap: Snapshot = EMPTY
const listeners = new Set<() => void>()
const set = (next: Partial<Snapshot>) => {
  snap = { ...snap, ...next }
  listeners.forEach((l) => l())
}

export const pendingStore = {
  subscribe(l: () => void): () => void {
    listeners.add(l)
    return () => { listeners.delete(l) }
  },
  snapshot: (): Snapshot => snap,
  addInFlight(row: PendingRow) { set({ inFlight: [row, ...snap.inFlight.filter((r) => r.key !== row.key)] }) },
  removeInFlight(key: string) { set({ inFlight: snap.inFlight.filter((r) => r.key !== key) }) },
  hide(id: string) { set({ hidden: new Set([...snap.hidden, id]) }) },
  unhide(id: string) {
    const h = new Set(snap.hidden)
    h.delete(id)
    set({ hidden: h })
  },
  markJustSaved(id: string) {
    set({ justSaved: id })
    setTimeout(() => { if (snap.justSaved === id) set({ justSaved: null }) }, HIGHLIGHT_MS)
  },
  reset() { set(EMPTY) },
}

export interface BodyLike {
  client_id?: string | null
  type?: string
  amount: string | number
  currency: string
  bucket_id?: string | null
  category_id?: string | null
  merchant?: string | null
  transaction_date?: string | null
}

export function rowFromBody(body: BodyLike, state: PendingRow['state'], id: string | null = null): PendingRow {
  return {
    key: id ?? body.client_id ?? '',
    id,
    client_id: body.client_id ?? null,
    type: body.type === 'income' ? 'income' : 'expense',
    amount: String(body.amount),
    currency: body.currency,
    bucket_id: body.bucket_id ?? null,
    category_id: body.category_id ?? null,
    merchant: body.merchant ?? null,
    transaction_date: body.transaction_date ?? '',
    state,
  }
}
