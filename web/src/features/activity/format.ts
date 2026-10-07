import type { RefData, Txn } from './hooks'

export const METHOD_LABELS: Record<string, string> = {
  card: 'Card', cash: 'Cash', apple_pay: 'Apple Pay', transfer: 'Transfer', other: 'Other',
}
const DAY = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
const parse = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}
const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString()

export function dayLabel(iso: string, today = new Date()): string {
  const d = parse(iso)
  const text = DAY.format(d).replace(',', '')
  if (sameDay(d, today)) return `Today · ${text}`
  const y = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  if (sameDay(d, y)) return `Yesterday · ${text}`
  return d.getFullYear() === today.getFullYear() ? text : `${text} ${d.getFullYear()}`
}

export type DayGroup = { date: string; label: string; net: number; rows: Txn[] }

export function groupByDay(rows: Txn[], dayTotals: Record<string, number>, today = new Date()): DayGroup[] {
  const groups: DayGroup[] = []
  for (const t of rows) {
    const date = t.transaction_date ?? ''
    let g = groups.at(-1)
    if (!g || g.date !== date) {
      g = { date, label: dayLabel(date, today), net: dayTotals[date] ?? 0, rows: [] }
      groups.push(g)
    }
    g.rows.push(t)
  }
  return groups
}

export function gapLabel(a: Txn, b: Txn): string {
  const minutes = Math.abs(Date.parse(b.created_at ?? '') - Date.parse(a.created_at ?? '')) / 60000
  if (minutes <= 10) return `${Math.max(1, Math.round(minutes))} min apart`
  const days = Math.round(Math.abs(parse(b.transaction_date ?? '').getTime() - parse(a.transaction_date ?? '').getTime()) / 864e5)
  if (days === 0) return 'Same day'
  return days === 1 ? '1 day apart' : `${days} days apart`
}

export function rowTitle(t: Txn, ref?: RefData): string {
  return t.merchant || t.notes || ref?.categories.find((c) => c.id === t.category_id)?.name || 'Transaction'
}

export function rowSubtitle(t: Txn, ref?: RefData): string {
  const parts: string[] = []
  const category = ref?.categories.find((c) => c.id === t.category_id)?.name
  if (category) parts.push(category)
  if (t.payer_mode === 'own_share') parts.push('each their share')
  else if (t.missing_payer) parts.push('no payer')
  else if (t.paid_by) parts.push(ref?.members.find((m) => m.user_id === t.paid_by)?.display_name ?? '')
  if (t.splits.length > 0 && t.payer_mode !== 'own_share') parts.push('split')
  return parts.filter(Boolean).join(' · ')
}
