/** Money and date formatting shared by every screen. Pure: no data access. */

const MINUS = '−'
const moneyFormats = new Map<string, Intl.NumberFormat | null>()

function moneyFormat(currency: string, whole: boolean): Intl.NumberFormat | null {
  const id = `${currency}:${whole}`
  if (!moneyFormats.has(id)) {
    let f: Intl.NumberFormat | null = null
    try {
      f = new Intl.NumberFormat('en-IE', {
        style: 'currency',
        currency,
        minimumFractionDigits: whole ? 0 : 2,
        maximumFractionDigits: whole ? 0 : 2,
      })
    } catch {
      f = null // not an ISO 4217 code: fall back to "12.50 XYZ"
    }
    moneyFormats.set(id, f)
  }
  return moneyFormats.get(id) ?? null
}

export interface MoneyOptions { currency?: string; signed?: boolean; whole?: boolean }

/** "€1,284.60". Negatives get a real minus ("−€64.20"); `signed` adds "+" to positives. */
export function formatMoney(amount: number, { currency = 'EUR', signed = false, whole = false }: MoneyOptions = {}): string {
  const rounded = whole ? Math.round(amount) : Math.round(amount * 100) / 100
  const magnitude = Math.abs(rounded)
  const f = moneyFormat(currency, whole)
  const text = f ? f.format(magnitude) : `${magnitude.toFixed(whole ? 0 : 2)} ${currency}`
  if (rounded < 0) return `${MINUS}${text}`
  if (signed && rounded > 0) return `+${text}`
  return text
}

/**
 * Text typed into an amount field → the decimal string the API takes ("86,4" → "86.40").
 * Blank → null. Anything that isn't a non-negative amount with up to two decimals → undefined.
 */
export function parseAmount(input: string): string | null | undefined {
  const s = input.replace(/[\s€]/g, '').replace(',', '.')
  if (s === '') return null
  if (!/^(\d+(\.\d{0,2})?|\.\d{1,2})$/.test(s)) return undefined
  return Number(s).toFixed(2)
}

const pad = (n: number) => String(n).padStart(2, '0')

/** "2026-10-26" → local midnight (never UTC: a UTC parse shows the previous day west of Greenwich). */
export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}
export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
export function todayISO(now: Date = new Date()): string {
  return toISODate(now)
}
export function addDays(iso: string, days: number): string {
  const d = parseISODate(iso)
  d.setDate(d.getDate() + days)
  return toISODate(d)
}
/** "2026-12" + 1 → "2027-01". */
export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`
}
export function monthsBetween(from: string, to: string): number {
  const [fy, fm] = from.split('-').map(Number)
  const [ty, tm] = to.split('-').map(Number)
  return (ty - fy) * 12 + (tm - fm)
}

const dateFormat = (opts: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-GB', opts)
const DAY_HEADER = dateFormat({ weekday: 'short', day: 'numeric', month: 'short' })
const SHORT_DATE = dateFormat({ day: 'numeric', month: 'short' })
const MONTH_LABEL = dateFormat({ month: 'short', year: 'numeric' })
const MONTH_SHORT = dateFormat({ month: 'short' })
const MONTH_NAME = dateFormat({ month: 'long' })
const TIME = dateFormat({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

export const formatDayHeader = (iso: string): string => DAY_HEADER.format(parseISODate(iso))
export const formatShortDate = (iso: string): string => SHORT_DATE.format(parseISODate(iso))
export const formatMonthLabel = (month: string): string => MONTH_LABEL.format(parseISODate(`${month}-01`))
export const formatMonthShort = (month: string): string => MONTH_SHORT.format(parseISODate(`${month}-01`))
export const formatMonthName = (month: number): string => MONTH_NAME.format(new Date(2000, month - 1, 1))
export const formatTime = (ms: number): string => TIME.format(new Date(ms))

export function ordinal(n: number): string {
  const suffixes = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return `${n}${suffixes[(v - 20) % 10] ?? suffixes[v] ?? suffixes[0]}`
}
