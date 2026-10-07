/**
 * Money is typed as a string and computed in integer cents. Never parseFloat a money value:
 * cents fit a Number exactly (at most 999,999,999), and anything multiplied by a rate or divided
 * by a fuel price goes through BigInt.
 */
export type AmountKey = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back' | 'clear'

export const MAX_INT_DIGITS = 7
export const MAX_DECIMALS = 2

export function pressKey(v: string, k: AmountKey): string {
  if (k === 'clear') return ''
  if (k === 'back') return v.slice(0, -1)
  const dot = v.indexOf('.')
  if (k === '.') {
    if (dot !== -1) return v
    return v === '' ? '0.' : `${v}.`
  }
  if (dot !== -1) return v.length - dot - 1 >= MAX_DECIMALS ? v : v + k
  if (v === '0') return k
  return v.length >= MAX_INT_DIGITS ? v : v + k
}

export function toCents(v: string): number {
  const m = /^(\d*)(?:\.(\d{0,2}))?$/.exec(v.trim())
  if (!m || (m[1] === '' && !m[2])) return 0
  return Number(m[1] || '0') * 100 + Number(`${m[2] ?? ''}00`.slice(0, 2))
}

export function centsToString(c: number): string {
  const a = Math.abs(c)
  return `${c < 0 ? '-' : ''}${Math.floor(a / 100)}.${String(a % 100).padStart(2, '0')}`
}

export const toApiAmount = (v: string): string => centsToString(toCents(v))

/** A stored amount (a JSON number with at most 2 decimals) as a keypad string: 3 → "3", 4.1 → "4.10". */
export function fromApiAmount(n: number | string): string {
  const c = Math.round(Number(n) * 100)
  return c % 100 === 0 ? String(c / 100) : centsToString(c)
}

export function displayAmount(v: string): string {
  if (v === '') return '0'
  const [i, f] = v.split('.')
  const grouped = (i || '0').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return f === undefined ? grouped : `${grouped}.${f}`
}

/** "1.153" at 6 decimals → 1153000n. Accepts "," as the decimal mark; null if malformed or too precise. */
export function parseScaled(s: string, decimals: number): bigint | null {
  const m = /^(\d*)(?:[.,](\d*))?$/.exec(s.trim())
  if (!m || (m[1] === '' && !m[2])) return null
  const frac = m[2] ?? ''
  if (frac.length > decimals) return null
  const scale = 10n ** BigInt(decimals)
  return BigInt(m[1] || '0') * scale + BigInt((frac + '0'.repeat(decimals)).slice(0, decimals) || '0')
}

const MICRO = 1_000_000n
const MAX_RATE_MICROS = 1_000_000n * MICRO

/** Units of household currency per 1 unit, in millionths: > 0 and at most 1,000,000. */
export function parseRate(s: string): bigint | null {
  const r = parseScaled(s, 6)
  return r !== null && r > 0n && r <= MAX_RATE_MICROS ? r : null
}

/** Household-currency cents for `cents` of a foreign currency, half-up. */
export function convertCents(cents: number, rateMicros: bigint): number {
  return Number((BigInt(cents) * rateMicros * 2n + MICRO) / (2n * MICRO))
}

/** Price per litre in thousandths, > 0. */
export function parseFuelPrice(s: string): bigint | null {
  const p = parseScaled(s, 3)
  return p !== null && p > 0n ? p : null
}

/** Litres in thousandths: (cents / 100) / (price / 1000), half-up (the server's litres_for). */
export function litresMilli(cents: number, priceMilli: bigint): bigint {
  return (BigInt(cents) * 10000n * 2n + priceMilli) / (2n * priceMilli)
}

export function formatLitres(milli: bigint): string {
  return `${milli / 1000n}.${String(milli % 1000n).padStart(3, '0')}`.replace(/\.?0+$/, '')
}
