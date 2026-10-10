import type { BillChange, HistoryPoint } from './types'

/** The arithmetic behind the history screen (spec §5.3). Pure; the server did the §3.4 comparison. */

export interface MonthCell {
  /** 1..12 */
  month: number
  /** The month's entries summed; null when there are none. */
  amount: number | null
  /** The same month a year earlier, when it has entries. */
  lastYear: number | null
  usage: number | null
  /** Month amount over month usage, from the entries that have a usage. */
  unitPrice: number | null
}

const ym = (iso: string) => iso.slice(0, 7)
const yearOf = (iso: string) => Number(iso.slice(0, 4))
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)
const cents = (n: number) => Math.round(n * 100) / 100

export function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b)
  const m = s.length >> 1
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

export function unitPriceOf(amount: number, usage: number | null): number | null {
  return usage === null || usage <= 0 ? null : Math.round((amount / usage) * 1e4) / 1e4
}

/** Entries grouped by YYYY-MM. */
function byMonth(points: HistoryPoint[]): Map<string, HistoryPoint[]> {
  const out = new Map<string, HistoryPoint[]>()
  for (const p of points) {
    const k = ym(p.due_date)
    out.set(k, [...(out.get(k) ?? []), p])
  }
  return out
}

export function yearsOf(points: HistoryPoint[]): number[] {
  return [...new Set(points.map((p) => yearOf(p.due_date)))].sort((a, b) => a - b)
}

/** Twelve cells for `year`: two entries in one month are summed. */
export function yearCells(points: HistoryPoint[], year: number): MonthCell[] {
  const groups = byMonth(points)
  const total = (y: number, m: number) => {
    const g = groups.get(`${y}-${String(m).padStart(2, '0')}`)
    return g ? cents(sum(g.map((p) => p.amount))) : null
  }
  return Array.from({ length: 12 }, (_, i) => {
    const month = i + 1
    const g = groups.get(`${year}-${String(month).padStart(2, '0')}`) ?? []
    const withUsage = g.filter((p) => p.usage !== null)
    const usage = withUsage.length ? sum(withUsage.map((p) => p.usage as number)) : null
    const priced = g.filter((p) => p.usage !== null && p.usage > 0)
    const unitPrice = priced.length ? unitPriceOf(sum(priced.map((p) => p.amount)), sum(priced.map((p) => p.usage as number))) : null
    return { month, amount: total(year, month), lastYear: total(year - 1, month), usage, unitPrice }
  })
}

/** This entry's month against the same month a year earlier, in € and whole % (half up); null when that month is empty. */
export function againstLastYear(points: HistoryPoint[], p: HistoryPoint): { delta: number; pct: number | null } | null {
  const groups = byMonth(points)
  const y = yearOf(p.due_date)
  const month = p.due_date.slice(5, 7)
  const now = groups.get(`${y}-${month}`)
  const before = groups.get(`${y - 1}-${month}`)
  if (!now || !before) return null
  const a = sum(now.map((x) => x.amount))
  const b = sum(before.map((x) => x.amount))
  const delta = cents(a - b)
  if (b === 0) return { delta, pct: null }
  const pct = (delta / b) * 100
  return { delta, pct: Math.sign(pct) * Math.round(Math.abs(pct)) }
}

/** The Usual tile: the server's figure when there is a change, else the median of the last 3 amounts. */
export function usualOf(points: HistoryPoint[], change: BillChange | null): number | null {
  if (change) return change.usual
  if (points.length === 0) return null
  return median(points.slice(-3).map((p) => p.amount))
}

/** Entries due in the 12 calendar months ending in `today`'s month; the average divides by their number. */
export function twelveMonth(points: HistoryPoint[], today: string): { total: number; average: number } | null {
  const [ty, tm] = [yearOf(today), Number(today.slice(5, 7))]
  const index = (iso: string) => yearOf(iso) * 12 + Number(iso.slice(5, 7)) - 1
  const end = ty * 12 + tm - 1
  const inside = points.filter((p) => index(p.due_date) > end - 12 && index(p.due_date) <= end)
  if (inside.length === 0) return null
  const total = cents(sum(inside.map((p) => p.amount)))
  return { total, average: cents(total / inside.length) }
}
