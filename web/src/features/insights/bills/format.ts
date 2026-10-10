import type { BillChange } from './types'

/** "€84" for a whole amount, "€84.50" otherwise: the notification's wording (spec §3.7). */
export function moneyShort(n: number, currency = 'EUR'): string {
  const sym = currency === 'EUR' ? '€' : `${currency} `
  const s = Number.isInteger(n) ? String(Math.abs(n)) : Math.abs(n).toFixed(2)
  return `${n < 0 ? '−' : ''}${sym}${s}`
}

const whole = (n: number) => Math.round(Math.abs(n))

/** "↑ 38% vs usual": the arrow and the words carry the direction, never colour alone. */
export function changeLabel(c: BillChange): string {
  return `${c.direction === 'up' ? '↑' : '↓'} ${whole(c.pct)}% vs usual`
}

/** "Electricity was €84, usually €61" (the notification title, the Home row). */
export function changeTitle(name: string, c: BillChange, currency = 'EUR'): string {
  return `${name} was ${moneyShort(c.amount, currency)}, usually ${moneyShort(c.usual, currency)}`
}

/** The notification body (spec §3.7): where the usual comes from, then the reason if there is one. */
export function changeBody(c: BillChange, unit: string | null, currency = 'EUR'): string {
  const usual = moneyShort(c.usual, currency)
  const base = c.basis === 'last_year' ? `Same month last year: ${usual}.` : `Usual from the last 3 payments: ${usual}.`
  if (c.reason === null || c.reason_pct === null || !unit) return base
  const n = whole(c.reason_pct)
  const up = c.reason_pct >= 0
  return c.reason === 'usage'
    ? `${base} You used ${n}% ${up ? 'more' : 'less'} ${unit}.`
    : `${base} The price per ${unit} went ${up ? 'up' : 'down'} ${n}%.`
}

/** Title and body as one sentence pair, for the history screen's change note. */
export function changeSentence(name: string, c: BillChange, unit: string | null, currency = 'EUR'): string {
  return `${changeTitle(name, c, currency)}. ${changeBody(c, unit, currency)}`
}

/** The one line every Bills screen and card carries (spec §5.2). */
export const BILLS_SCOPE_NOTE = 'Bills cover all time. The lens and period do not apply.'
