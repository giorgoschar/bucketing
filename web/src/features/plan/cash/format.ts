import { formatMoney } from '../../../ui/format'
import { parseCents } from '../../composer/amount'
import { type CashWalletMemberOut, num } from './types'

/** Below half a cent counts as zero (spec §4.2, §4.6). */
export const CENT_EPS = 0.005

export const euros = (v: number, currency = 'EUR', signed = false) => formatMoney(v, { currency, signed })

/** Who a member is on screen: their initial, tinted by their place in the list. */
export const initial = (name: string) => (name.trim()[0] ?? '?').toUpperCase()
export const tint = (i: number) => `var(--c${(i % 6) + 1})`

/** The parts of the wallet sum (spec §4.2.2): Took − [In hand] − Logged = not yet logged. */
export function walletSum(m: CashWalletMemberOut) {
  const w = m.wallet
  return {
    took: num(w.carried) + num(w.taken) - num(w.put_back),
    inHand: w.still_have === null || w.still_have === undefined ? null : num(w.still_have),
    logged: num(w.logged) + num(w.outs),
    notLogged: num(w.not_yet_logged),
  }
}


/** Typed money ("12,5" or "12.50") in cents, or null when blank or malformed (composer parsing). */
export function typedCents(v: string): number | null {
  return v.trim() === '' ? null : parseCents(v.replace(/[\s€]/g, ''))
}
