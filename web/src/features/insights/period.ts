import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

export type Preset = 'this_month' | 'last_month' | 'last_3m' | 'last_6m' | 'this_year' | 'custom'
export interface Period { preset: Preset; from?: string; to?: string }

export const DEFAULT_PERIOD: Period = { preset: 'this_month' }
export const PERIOD_STORAGE_KEY = 'tameio.insights.period'
export const PRESETS: { value: Preset; label: string }[] = [
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_3m', label: '3 months' },
  { value: 'last_6m', label: '6 months' },
  { value: 'this_year', label: 'This year' },
  { value: 'custom', label: 'Custom' },
]

const ISO = /^\d{4}-\d{2}-\d{2}$/

/** A real calendar date in YYYY-MM-DD (2026-02-30 is not). */
export function isIsoDate(s: string | null | undefined): s is string {
  if (!s || !ISO.test(s)) return false
  const d = new Date(`${s}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s
}

export function rangeError(from?: string, to?: string): string | null {
  if (!isIsoDate(from) || !isIsoDate(to)) return 'Pick both dates.'
  if (from > to) return 'From must be on or before To.'
  return null
}

export function normalisePeriod(p: Partial<Period> | null | undefined): Period | null {
  if (!p || !PRESETS.some((x) => x.value === p.preset)) return null
  if (p.preset === 'custom') return rangeError(p.from, p.to) ? null : { preset: 'custom', from: p.from, to: p.to }
  return { preset: p.preset as Preset }
}

export function parsePeriod(params: URLSearchParams): Period | null {
  return normalisePeriod({
    preset: (params.get('p') ?? undefined) as Preset | undefined,
    from: params.get('from') ?? undefined,
    to: params.get('to') ?? undefined,
  })
}

export function writePeriod(params: URLSearchParams, p: Period): URLSearchParams {
  const next = new URLSearchParams(params)
  next.set('p', p.preset)
  if (p.preset === 'custom' && p.from && p.to) {
    next.set('from', p.from)
    next.set('to', p.to)
  } else {
    next.delete('from')
    next.delete('to')
  }
  return next
}

/** The `GET /insights` (and drill-down) query for a period. */
export function periodQuery(p: Period): { preset: Preset; start_date?: string; end_date?: string } {
  return p.preset === 'custom' ? { preset: 'custom', start_date: p.from, end_date: p.to } : { preset: p.preset }
}

export function periodKey(p: Period): string {
  return p.preset === 'custom' ? `custom:${p.from}:${p.to}` : p.preset
}

/** Words for sentences: "this month", "last month", "in this period". */
export function periodPhrase(p: Period): string {
  if (p.preset === 'this_month') return 'this month'
  if (p.preset === 'last_month') return 'last month'
  return 'in this period'
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** The same-length window just before (the server's range_start/range_end), for "See the previous period". */
export function previousPeriod(p: Period, rangeStart: string | null, rangeEnd: string | null): Period | null {
  if (p.preset === 'this_month') return { preset: 'last_month' }
  if (!isIsoDate(rangeStart) || !isIsoDate(rangeEnd)) return null
  const span = Math.round((Date.parse(rangeEnd) - Date.parse(rangeStart)) / 86_400_000) + 1
  const to = addDays(rangeStart, -1)
  return { preset: 'custom', from: addDays(to, -(span - 1)), to }
}

function readStored(): Period | null {
  try {
    const raw = localStorage.getItem(PERIOD_STORAGE_KEY)
    return raw ? normalisePeriod(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

function store(p: Period): void {
  try {
    localStorage.setItem(PERIOD_STORAGE_KEY, JSON.stringify(p))
  } catch {
    // Private mode or storage full: the URL still carries it.
  }
}

/** The one reader of the period on Insights and every drill-down: URL, then storage, then this month. */
export function usePeriod(): [Period, (next: Period) => void] {
  const [params, setParams] = useSearchParams()
  const period = parsePeriod(params) ?? readStored() ?? DEFAULT_PERIOD
  const set = useCallback(
    (next: Period) => {
      setParams((prev) => writePeriod(prev, next), { replace: true })
      store(next)
    },
    [setParams],
  )
  return [period, set]
}
