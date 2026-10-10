// The statement's wording as pure functions (spec §4). Money in a sentence is whole when it is whole.

const group = new Intl.NumberFormat('en-IE', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
const cents = new Intl.NumberFormat('en-IE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const MINUS = '−'

/** "€1,310" for a whole amount, "€84.50" otherwise: the alert money format. */
export function short(n: number): string {
  const abs = Math.abs(n)
  const rounded = Math.round(abs * 100) / 100
  const body = Number.isInteger(rounded) ? group.format(rounded) : cents.format(rounded)
  return `${n < 0 && rounded !== 0 ? MINUS : ''}€${body}`
}

/** "3 days left", "1 day left". */
export function daysLeftText(n: number): string {
  return `${n} ${n === 1 ? 'day' : 'days'} left`
}
