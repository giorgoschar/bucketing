/** Activity filters live in the URL under the API's names (spec §3), so 2a's
 * and 2d's "See all" links can deep-link. Plain /activity opens on this
 * month; a link with its own filter, or ?all=1, is all time. */

export type TxnType = 'expense' | 'income' | 'transfer'
export type TransactionFilter = {
  q?: string
  type?: TxnType
  category_id?: string
  bucket_id?: string
  no_bucket?: boolean
  paid_by?: string
  missing_payer?: boolean
  payment_method?: string
  recurring_bill_id?: string
  fixed?: boolean
  from_date?: string
  to_date?: string
  min_amount?: string
  max_amount?: string
}
export type FeedState = { filter: TransactionFilter; dups: boolean }

const TEXT_KEYS = [
  'q', 'type', 'category_id', 'bucket_id', 'paid_by', 'payment_method',
  'recurring_bill_id', 'from_date', 'to_date', 'min_amount', 'max_amount',
] as const
const FLAG_KEYS = ['missing_payer', 'no_bucket', 'fixed'] as const
const TYPES: readonly string[] = ['expense', 'income', 'transfer']
const METHODS: readonly string[] = ['card', 'cash', 'apple_pay', 'transfer', 'other']

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

function validDate(v: string): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v)
  if (!m) return false
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return d.getFullYear() === Number(m[1]) && d.getMonth() === Number(m[2]) - 1 && d.getDate() === Number(m[3])
}

export function monthRange(d: Date): { from_date: string; to_date: string } {
  return {
    from_date: iso(new Date(d.getFullYear(), d.getMonth(), 1)),
    to_date: iso(new Date(d.getFullYear(), d.getMonth() + 1, 0)),
  }
}

export function isEmpty(f: TransactionFilter): boolean {
  return Object.values(f).every((v) => v === undefined || v === false || v === '')
}

export function fromSearch(params: URLSearchParams, today = new Date()): FeedState {
  const filter: TransactionFilter = {}
  for (const k of TEXT_KEYS) {
    const v = params.get(k)?.trim()
    if (!v) continue
    if (k === 'type' && !TYPES.includes(v)) continue
    if (k === 'payment_method' && !METHODS.includes(v)) continue
    if ((k === 'from_date' || k === 'to_date') && !validDate(v)) continue
    if ((k === 'min_amount' || k === 'max_amount') && !/^\d+(?:[.,]\d+)?$/.test(v)) continue
    ;(filter as Record<string, string>)[k] = v
  }
  for (const k of FLAG_KEYS) if (params.get(k) === '1') filter[k] = true
  const dups = params.get('dups') === '1'
  if (!dups && params.get('all') !== '1' && isEmpty(filter)) Object.assign(filter, monthRange(today))
  return { filter, dups }
}

export function toSearch({ filter, dups }: FeedState): URLSearchParams {
  const p = new URLSearchParams()
  for (const k of TEXT_KEYS) {
    const v = filter[k]
    if (v) p.set(k, String(v))
  }
  for (const k of FLAG_KEYS) if (filter[k]) p.set(k, '1')
  if (dups) p.set('dups', '1')
  else if (isEmpty(filter)) p.set('all', '1') // "All time" with nothing else
  return p
}

/** The query object for GET /transactions and select.filter. */
export function toQuery(filter: TransactionFilter): Record<string, string | boolean> {
  const out: Record<string, string | boolean> = {}
  for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== '' && v !== false) out[k] = v
  return out
}

export function toggle(filter: TransactionFilter, patch: TransactionFilter): TransactionFilter {
  const next: TransactionFilter = { ...filter }
  for (const [k, v] of Object.entries(patch) as [keyof TransactionFilter, unknown][]) {
    if (next[k] === v) delete next[k]
    else (next as Record<string, unknown>)[k] = v
  }
  return next
}

function isWholeMonth(f: TransactionFilter): boolean {
  if (!f.from_date || !f.to_date) return false
  const [y, m] = f.from_date.split('-').map(Number)
  const r = monthRange(new Date(y, m - 1, 1))
  return r.from_date === f.from_date && r.to_date === f.to_date
}

export function monthLabel(f: TransactionFilter): string {
  if (isWholeMonth(f)) {
    const [y, m] = f.from_date!.split('-').map(Number)
    return new Intl.DateTimeFormat('en-GB', { month: 'short', year: 'numeric' }).format(new Date(y, m - 1, 1))
  }
  return f.from_date || f.to_date ? 'Custom dates' : 'All time'
}

/** The Filters chip's count: fields the Filters sheet sets (not q, not a whole month). */
export function activeFilterCount(f: TransactionFilter): number {
  let n = 0
  if (f.type) n++
  if (f.category_id) n++
  if (f.bucket_id || f.no_bucket) n++
  if (f.paid_by) n++
  if (f.payment_method) n++
  if (f.recurring_bill_id || f.fixed) n++
  if (f.min_amount || f.max_amount) n++
  if ((f.from_date || f.to_date) && !isWholeMonth(f)) n++
  return n
}
