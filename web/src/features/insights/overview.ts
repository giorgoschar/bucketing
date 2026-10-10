import { eur } from './format'
import { HOUSEHOLD, type Lens } from './lens'
import type { Period } from './period'
import type { InsightsData } from './types'

export type WidgetId =
  | 'identity' | 'headline' | 'share' | 'empty' | 'onTrack' | 'inOut' | 'where' | 'inOutMonths'
  | 'trend' | 'biggest' | 'method' | 'budgets' | 'savings' | 'vsUsual' | 'bills' | 'fuel'
  | 'billsPanel' | 'monthsTable' | 'categoriesTable'

export const isEmptyPeriod = (d: InsightsData) => d.kpis.count === 0 && d.total_spent === 0 && d.in_out.in === 0

/** YYYY-MM when the period is one calendar month (Categories vs usual compares a month). */
export function singleMonth(p: Period, d: InsightsData): string | null {
  return (p.preset === 'this_month' || p.preset === 'last_month') && d.start_date ? d.start_date.slice(0, 7) : null
}

/** The spec's fixed order (§4), minus what this lens, period or data hides. */
export function visibleWidgets(
  d: InsightsData,
  { lens, period, bills = false, desktop = false }: { lens: Lens; period: Period; bills?: boolean; desktop?: boolean },
): WidgetId[] {
  const member = lens !== HOUSEHOLD
  const ids: WidgetId[] = member ? ['identity', 'headline', 'share'] : ['headline']
  // A bill's history is the household's, for all time: the Bills card stays when the period has no spending.
  const billsId = bills ? ([desktop ? 'billsPanel' : 'bills'] as const) : []
  if (isEmptyPeriod(d)) return [...ids, 'empty', ...billsId]
  if (!member && period.preset === 'this_month') ids.push('onTrack')
  ids.push('inOut')
  if (d.categories.length) ids.push('where')
  ids.push('inOutMonths', 'trend')
  if (d.kpis.largest) ids.push('biggest')
  if (d.by_method.length) ids.push('method')
  if (d.budget_status.length) ids.push('budgets')
  if (d.kpis.savings_rate != null) ids.push('savings')
  if (!member && singleMonth(period, d)) ids.push('vsUsual')
  ids.push(...billsId)
  if (d.fuel) ids.push('fuel')
  // Desktop only (spec §5.4): the last 12 months as a table, and every category.
  if (desktop) ids.push('monthsTable', ...(d.categories.length ? (['categoriesTable'] as const) : []))
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
