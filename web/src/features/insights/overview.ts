import { eur } from './format'
import { HOUSEHOLD, type Lens } from './lens'
import type { Period } from './period'
import type { InsightsData } from './types'

export type WidgetId =
  | 'identity' | 'share' | 'summary' | 'empty' | 'where' | 'vsUsual' | 'budgets'
  | 'byMonth' | 'biggest' | 'method' | 'fuel' | 'monthsTable' | 'categoriesTable'
  | 'bills' | 'billsPanel' | 'statements'

/** The three Insights tabs (spec §2.2). Overview is the default and writes nothing to the URL. */
export type InsightsTab = 'overview' | 'trends' | 'bills'
export const TABS: readonly { value: InsightsTab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'trends', label: 'Trends' },
  { value: 'bills', label: 'Bills & statements' },
]

export const isEmptyPeriod = (d: InsightsData) => d.kpis.count === 0 && d.total_spent === 0 && d.in_out.in === 0

/** YYYY-MM when the period is one calendar month (Categories vs usual compares a month). */
export function singleMonth(p: Period, d: InsightsData): string | null {
  return (p.preset === 'this_month' || p.preset === 'last_month') && d.start_date ? d.start_date.slice(0, 7) : null
}

/** Which lines of the Summary card show: each is the condition its old card had (spec §2.2). */
export function summaryParts(
  d: InsightsData,
  { lens, period }: { lens: Lens; period: Period },
): { onTrack: boolean; inOut: boolean; savings: boolean } {
  const empty = isEmptyPeriod(d)
  return {
    onTrack: !empty && lens === HOUSEHOLD && period.preset === 'this_month',
    inOut: !empty,
    savings: !empty && d.kpis.savings_rate != null,
  }
}

/** The cards of one tab, in order (spec §2.2), minus what this lens, period or data hides. */
export function visibleWidgets(
  d: InsightsData,
  { tab = 'overview', lens, period, bills = false, statements = false, desktop = false }: {
    tab?: InsightsTab; lens: Lens; period: Period; bills?: boolean; statements?: boolean; desktop?: boolean
  },
): WidgetId[] {
  const member = lens !== HOUSEHOLD
  const empty = isEmptyPeriod(d)
  if (tab === 'bills') {
    // A bill's history and a past month's statement are the household's, for all time: they stay in an empty period.
    return [...(bills ? [desktop ? 'billsPanel' : 'bills'] as const : []), ...(statements ? (['statements'] as const) : [])]
  }
  if (tab === 'trends') {
    const ids: WidgetId[] = ['byMonth']
    if (d.kpis.largest) ids.push('biggest')
    if (d.by_method.length) ids.push('method')
    if (d.fuel) ids.push('fuel')
    // Desktop only (spec §5.4): the last 12 months as a table, and every category.
    if (desktop) ids.push('monthsTable', ...(d.categories.length ? (['categoriesTable'] as const) : []))
    return ids
  }
  const ids: WidgetId[] = member ? ['identity', 'share', 'summary'] : ['summary']
  if (empty) return [...ids, 'empty']
  if (d.categories.length) ids.push('where')
  if (!member && singleMonth(period, d)) ids.push('vsUsual')
  if (d.budget_status.length) ids.push('budgets')
  return ids
}

export function deltaText(changePct: number | null): string | null {
  if (changePct == null) return null
  if (changePct === 0) return 'Same as the previous period'
  return `${changePct < 0 ? '−' : '+'}${Math.abs(changePct)}% vs the previous period`
}

/** "You paid €141.20 more than your share this month" (less, or about the same under €1). */
export function paidOutSentence(balance: number, who: { me: boolean; name: string }, phrase: string): string {
  const subject = who.me ? 'You' : who.name
  const their = who.me ? 'your' : 'their'
  if (Math.abs(balance) < 1) return `${subject} paid about the same as ${their} share ${phrase}`
  return `${subject} paid ${eur(Math.abs(balance))} ${balance > 0 ? 'more' : 'less'} than ${their} share ${phrase}`
}
