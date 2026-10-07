import type { components } from '../../../api/schema'

/**
 * Plan › Cash wire types: aliases of the generated schema (cash spec §3.2/§3.3).
 *
 * Money: every cash amount (stash, movement amount, each wallet field) is a JSON number on the wire.
 */
type S = components['schemas']

export type CashMoney = number

/** `out` is legacy (read-only, history only); `stash_count` is a recount (a signed correction). */
export type CashKind = S['CashMovementOut']['kind']

/** `deleted` is only ever true on another member's take from the viewer's stash. */
export type CashMovementOut = S['CashMovementOut']

/** The viewer's movements in a month; `stash` is the viewer's own stash. */
export type CashMovementsOut = S['CashMovementsOut']

/** `put_back` is the member's own wallet only; null for everyone else, whose `taken` is net of it. */
export type WalletOut = S['WalletOut']

/** `/summary`'s wallet: its pre-model shape, plus `labelled_out`, and `put_back` absent for another member. */
export type SummaryWalletOut = S['SummaryWalletOut']

export type CashSummaryOut = S['CashSummaryOut']

export type CashWalletMemberOut = S['CashWalletMemberOut']

/** The month's wallets: every household member (the viewer first, then the others by name) and the
 *  viewer's own stash. */
export type CashWalletsOut = S['CashWalletsOut']

/** POST /cash/movements. `stash_count`'s amount is what was counted (≥ 0); the server stores the correction. */
export type MovementBody = S['MovementIn']

/** A nullable amount as a number (null counts as 0). */
export const num = (v: CashMoney | null | undefined): number => v ?? 0
