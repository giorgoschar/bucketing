import { centsToString, parseScaled, toCents } from './amount'
import type { Share } from './state'

/** Shares in cents by user id. */
export type ShareMap = Record<string, number>

/** total / n rounded down to the cent; leftover cents to the payer when a member, else the first id (server equal_split). */
export function equalShares(total: number, memberIds: string[], payer: string | null): ShareMap {
  const ids = [...new Set(memberIds)].sort()
  if (!ids.length) return {}
  const per = Math.floor(total / ids.length)
  const out: ShareMap = Object.fromEntries(ids.map((id) => [id, per]))
  out[payer && payer in out ? payer : ids[0]] += total - per * ids.length
  return out
}

/** Typed amounts for everyone but the payer; the payer's share is what is left (negative = invalid). */
export function amountShares(total: number, memberIds: string[], payer: string, typed: Record<string, string>): ShareMap {
  const out: ShareMap = {}
  let rest = total
  for (const id of memberIds) {
    if (id === payer) continue
    out[id] = toCents(typed[id] ?? '')
    rest -= out[id]
  }
  out[payer] = rest
  return out
}

/** Percent (up to 2 decimals) for non-payers, each rounded down to the cent; the payer takes the rest. */
export function percentShares(total: number, memberIds: string[], payer: string, typed: Record<string, string>): ShareMap {
  const out: ShareMap = {}
  let rest = total
  for (const id of memberIds) {
    if (id === payer) continue
    const hundredths = parseScaled(typed[id] ?? '', 2)
    out[id] = hundredths === null ? 0 : Number((BigInt(total) * hundredths) / 10000n)
    rest -= out[id]
  }
  out[payer] = rest
  return out
}

/** "Each paid own share": everyone's typed amount, no remainder. */
export function ownShares(memberIds: string[], typed: Record<string, string>): ShareMap {
  return Object.fromEntries(memberIds.map((id) => [id, toCents(typed[id] ?? '')]))
}

export type SplitProblem = 'negative' | 'over' | 'mismatch' | null

export function splitProblem(total: number, shares: ShareMap, own: boolean): SplitProblem {
  const values = Object.values(shares)
  if (values.some((x) => x < 0)) return 'negative'
  const sum = values.reduce((a, x) => a + x, 0)
  if (own) return Math.abs(sum - total) <= 1 ? null : 'mismatch'
  return sum > total ? 'over' : null
}

export const toShareList = (memberIds: string[], shares: ShareMap): Share[] =>
  memberIds.map((id) => ({ user_id: id, amount: centsToString(shares[id] ?? 0) }))

export const typedFromShares = (shares: Share[]): Record<string, string> =>
  Object.fromEntries(shares.map((s) => [s.user_id, s.amount]))
