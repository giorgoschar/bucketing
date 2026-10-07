/** 2b's queued creates, rebuilt from the offline queue. Until 2b lands this
 * returns [] (spec §10, F1 dependency); then replace the body with
 * `export { usePendingTransactions } from '../composer/hooks'`. */
import type { Txn } from './hooks'

export type PendingTxn = Txn & { pending: true }

export function usePendingTransactions(): PendingTxn[] {
  return []
}
