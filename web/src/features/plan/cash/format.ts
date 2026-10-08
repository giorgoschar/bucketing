import { formatMoney } from '../../../ui/format'
import { parseCents } from '../../composer/amount'
import type { WalletWithTerms } from './contractTypes'
import { type CashWalletMemberOut, num } from './types'

/** A cash write's idempotency key (C5): a uuid4. */
export const newClientId = (): string => crypto.randomUUID()

/** Below half a cent counts as zero (spec §4.2, §4.6). */
export const CENT_EPS = 0.005

export const euros = (v: number, currency = 'EUR', signed = false) => formatMoney(v, { currency, signed })

/** Who a member is on screen: their initial, tinted by their place in the list. */
export const initial = (name: string) => (name.trim()[0] ?? '?').toUpperCase()
export const tint = (i: number) => `var(--c${(i % 6) + 1})`

/**
 * The parts of the wallet sum (spec §4.2.2, polish C6):
 * Took − [In hand] − Logged − Logged from last month + Logged more than taken = not yet logged.
 *
 * Took never shows below 0 (Cash final review m3): a put back beyond this month's takes is cash that left
 * the wallet beyond what was taken, so the shortfall is shown with "Logged more than taken" instead, and the
 * shown sum still adds up.
 */
export function walletSum(m: CashWalletMemberOut) {
  const w = m.wallet as WalletWithTerms
  const rawTook = num(w.carried) + num(w.taken) - num(w.put_back)
  return {
    took: Math.max(0, rawTook),
    inHand: w.still_have === null || w.still_have === undefined ? null : num(w.still_have),
    logged: num(w.logged) + num(w.outs),
    crossMonth: num(w.logged_cross_month),
    overLogged: Math.max(0, num(w.over_logged) + Math.min(0, rawTook)),
    notLogged: num(w.not_yet_logged),
  }
}

/** Typed money ("12,5" or "12.50") in cents, or null when blank or malformed (composer parsing). */
export function typedCents(v: string): number | null {
  return v.trim() === '' ? null : parseCents(v.replace(/[\s€]/g, ''))
}
