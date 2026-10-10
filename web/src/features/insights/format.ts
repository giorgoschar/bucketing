const money = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })
const whole = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const MINUS = '−'

const signed = (s: string) => s.replace('-', MINUS)
export const eur = (n: number) => signed(money.format(n))
export const eurWhole = (n: number) => signed(whole.format(n))
/** Net with its sign as text: "+€1,000.00" or "−€100.00", never colour alone. */
export const signedEur = (n: number) => (n > 0 ? `+${eur(n)}` : eur(n))
export const pctText = (n: number) => `${Math.abs(Math.round(n))}%`

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const parts = (iso: string) => iso.split('-').map(Number) as [number, number, number]

/** "Oct 1 – 6", "Sep 3 – Oct 6", or "All time" without a range. */
export function dayRange(start: string | null, end: string | null): string {
  if (!start || !end) return 'All time'
  const [, sm, sd] = parts(start)
  const [, em, ed] = parts(end)
  return sm === em ? `${MON[sm - 1]} ${sd} – ${ed}` : `${MON[sm - 1]} ${sd} – ${MON[em - 1]} ${ed}`
}

/** "Oct 31": the last day of the month `iso` is in. */
export function monthEnd(iso: string): string {
  const [y, m] = parts(iso)
  return `${MON[m - 1]} ${new Date(Date.UTC(y, m, 0)).getUTCDate()}`
}
