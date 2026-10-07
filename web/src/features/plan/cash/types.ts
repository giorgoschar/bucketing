/**
 * Plan › Cash wire types, hand-written from the cash spec §3.2/§3.3 while the server half (p4/cash-b) is
 * built in parallel. The integration step replaces these bodies with aliases of the generated schema types
 * (components['schemas']['CashWalletsOut'] and friends).
 *
 * Money: every cash amount (stash, movement amount, each wallet field) is a JSON number on the wire
 * (confirmed by the server stream, p4/cash-b).
 */
export type CashMoney = number

/** `out` is legacy (read-only, history only); `stash_count` is a recount (a signed correction). */
export type CashKind = 'stash_in' | 'take' | 'put_back' | 'still_have' | 'out' | 'stash_count'

export interface CashMovementOut {
  id: string
  user_id: string
  kind: CashKind
  stash_owner_id: string | null
  amount: CashMoney
  currency: string
  category_id: string | null
  note: string | null
  movement_date: string | null
  transaction_id: string | null
  created_at: string | null
  /** Only ever true on another member's take from the viewer's stash. */
  deleted: boolean
}

export interface CashMovementsOut {
  items: CashMovementOut[]
  /** The viewer's own stash. */
  stash: CashMoney
}

export interface WalletOut {
  carried: CashMoney
  taken: CashMoney
  /** The member's own wallet only; null for everyone else, whose `taken` is net of it. */
  put_back: CashMoney | null
  still_have: CashMoney | null
  spent: CashMoney
  logged: CashMoney
  outs: CashMoney
  not_yet_logged: CashMoney
}

export interface CashSummaryOut {
  month: string
  member_id: string
  stash: CashMoney
  wallet: WalletOut
}

export interface CashWalletMemberOut {
  member_id: string
  name: string
  is_me: boolean
  wallet: WalletOut
}

export interface CashWalletsOut {
  month: string
  /** The viewer's own stash. */
  stash: CashMoney
  /** Every household member: the viewer first, then the others by name. */
  members: CashWalletMemberOut[]
}

/** POST /cash/movements. `stash_count`'s amount is what was counted (≥ 0); the server stores the correction. */
export interface MovementBody {
  kind: 'stash_in' | 'take' | 'put_back' | 'still_have' | 'stash_count'
  amount: string
  movement_date?: string | null
  note?: string | null
  stash_owner_id?: string | null
  spend_bucket_id?: string | null
  category_id?: string | null
}

/** A nullable amount as a number (null counts as 0). */
export const num = (v: CashMoney | null | undefined): number => v ?? 0
