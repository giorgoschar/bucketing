import { SETTINGS_PAGES } from './settingsIndex'
import type { SearchOption } from './types'

/** Lower case, accents off, so "Σεπτέμβριος" and "ΣΕΠΤΕΜΒΡΙΟΣ" or "café" and "CAFE" meet. */
export const fold = (s: string): string => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()

const MAX = 5
type Month = { month: string; label: string }

/** Statements on the device: the month's name ("September 2026", "sept") or its YYYY-MM. */
export function statementOptions(months: readonly Month[], q: string): SearchOption[] {
  const needle = fold(q.trim())
  if (needle.length < 2) return []
  return months
    .filter((m) => fold(m.label).includes(needle) || m.month.includes(needle))
    .slice(0, MAX)
    .map((m) => ({ id: '', group: 'statements', label: m.label, to: `/insights/statements/${encodeURIComponent(m.month)}` }))
}

/** Settings pages whose name or a keyword contains the query. */
export function settingsOptions(q: string): SearchOption[] {
  const needle = fold(q.trim())
  if (needle.length < 2) return []
  return SETTINGS_PAGES
    .filter((p) => fold(p.title).includes(needle) || p.keywords.some((k) => fold(k).includes(needle)))
    .slice(0, MAX)
    .map((p) => ({ id: '', group: 'settings', label: p.title, to: p.to }))
}
