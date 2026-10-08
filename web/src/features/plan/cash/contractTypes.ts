import type { MovementBody, WalletOut } from './types'

/**
 * Polish round contracts C5 and C6, hand-typed while the server builds them (stream S). Integration replaces
 * these with aliases of the generated schema after `gen:api`, and renames the C6 terms if the server named
 * them differently.
 */

/** C5: POST /cash/movements with the sheet's `client_id` (a uuid4): a retry of the same write applies once. */
export type MovementWrite = MovementBody & { client_id?: string }

/**
 * C6: the two terms of `not_yet_logged` the card left out (Cash final review m2). The sum the card shows is
 * carried + taken − put_back − still_have − logged − outs − logged_cross_month + over_logged = not_yet_logged.
 */
export interface WalletTerms {
  /** Cash of this month that was logged in another month. */
  logged_cross_month?: number
  /** Logged (or put back) beyond what was taken or in hand. */
  over_logged?: number
}

export type WalletWithTerms = WalletOut & WalletTerms
