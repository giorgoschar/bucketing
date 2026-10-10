import { formatMonthName, shiftMonth } from '../../../ui/format'
import type { StatementOut } from './types'

// The statement's wording as pure functions (spec §4). Money in a sentence is whole when it is whole.

const group = new Intl.NumberFormat('en-IE', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
const cents = new Intl.NumberFormat('en-IE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const MINUS = '−'

/** "€1,310" for a whole amount, "€84.50" otherwise: the alert money format. */
export function short(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  const rounded = Math.round(abs * 100) / 100
  const body = Number.isInteger(rounded) ? group.format(rounded) : cents.format(rounded)
  return `${n < 0 && rounded !== 0 ? MINUS : ''}€${body}`
}

/** "3 days left", "1 day left". */
export function daysLeftText(n: number): string {
  return `${n} ${n === 1 ? 'day' : 'days'} left`
}

const monthName = (month: string) => formatMonthName(Number(month.slice(5, 7)))
const MONTH_RE = /^(\d{4})-(\d{2})$/

/** "September 2026" for a YYYY-MM the server has not labelled yet (the page title while it loads). */
export function monthTitle(month: string): string {
  return MONTH_RE.test(month) ? `${monthName(month)} ${month.slice(0, 4)}` : 'Statement'
}

/** "2 October": a YYYY-MM-DD date's day and month name. */
export function dayAndMonth(iso: string): string {
  return `${Number(iso.slice(8, 10))} ${monthName(iso.slice(0, 7))}`
}

/** The last day of the review window, in the month after `month`: "5 October" for 2026-09. */
export function reviewDeadline(month: string): string {
  return `${REVIEW_DAYS} ${monthName(shiftMonth(month, 1))}`
}

/** Days 1 to 5 of the following month (spec §2). */
export const REVIEW_DAYS = 5

export const LIVE_NOTE = 'Numbers are live: they change if you edit an entry from this month.'

/** Who pressed Done, as the page shows it: you, a first name, or nobody known. */
export type ReviewedBy = { kind: 'you' } | { kind: 'name'; name: string } | { kind: 'none' }

/** The one line under the title (spec §4.2). */
export function stateLine(s: Pick<StatementOut, 'month' | 'reviewed_on' | 'closed' | 'days_left'>, by: ReviewedBy = { kind: 'none' }): string {
  if (s.reviewed_on) {
    const who = by.kind === 'you' ? ' by you' : by.kind === 'name' ? ` by ${by.name}` : ''
    return `Reviewed on ${dayAndMonth(s.reviewed_on)}${who}`
  }
  if (s.closed) return 'Closed automatically'
  const left = s.days_left === null ? '' : ` · ${daysLeftText(s.days_left)}`
  return `Review by ${reviewDeadline(s.month)}${left}`
}

/** "€240 more than August", "€240 less than August", "Same as August": the words carry the sign. */
export function comparison(current: number, previous: number, previousMonth: string): string {
  const delta = Math.round((current - previous) * 100) / 100
  const name = monthName(previousMonth)
  if (delta === 0) return `Same as ${name}`
  return `${short(Math.abs(delta))} ${delta > 0 ? 'more' : 'less'} than ${name}`
}

/** "€110 over". */
export const overText = (over: number): string => `${short(over)} over`

/** "€1,310 of €1,200". */
export const ofBudget = (spent: number, budget: number): string => `${short(spent)} of ${short(budget)}`

/** "usually €240". */
export const usuallyText = (usual: number | null): string | null => (usual === null ? null : `usually ${short(usual)}`)

/** "Marks September as reviewed for the whole household." */
export const doneNote = (month: string): string => `Marks ${monthName(month)} as reviewed for the whole household.`

/** The month's first and last day, for the category screen's custom period. */
export function monthBounds(month: string): { from: string; to: string } {
  const [y, m] = month.split('-').map(Number)
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, '0')}` }
}
