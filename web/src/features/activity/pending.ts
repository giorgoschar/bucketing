/** 2b's pending writes (in flight or in the offline queue) in Activity's shape.
 * 2b's `usePendingTransactions` returns a `PendingView` of `PendingRow`s; Activity
 * works on `Txn`s, so this adapts it: creates become read-only rows, queued edits
 * overlay the server row, and queued or in-flight deletes are hidden. */
import { useMemo } from 'react'
import type { PendingRow } from '../composer/hooks/pendingStore'
import { usePendingTransactions as usePendingView } from '../composer/hooks/usePendingTransactions'
import type { Txn } from './hooks'

export type PendingTxn = Txn & { pending: true }

/** A pending row as a Txn. `base` is the server row a queued edit applies to. A create has no
 * server id yet, so its id is its client key (Detail looks it up by that). */
export function toPendingTxn(row: PendingRow, base?: Txn): PendingTxn {
  const fields = {
    type: row.type,
    amount: Number(row.amount),
    currency: row.currency,
    bucket_id: row.bucket_id,
    category_id: row.category_id,
    merchant: row.merchant,
    transaction_date: row.transaction_date || null,
  }
  if (base) return { ...base, ...fields, pending: true }
  return {
    id: row.key, household_id: '', exchange_rate: 1, paid_by: null, payer_mode: 'single', notes: null,
    receipt_path: null, payment_method: 'card', fuel_price_per_litre: null, fuel_litres: null,
    exclude_from_forecast: false, exclude_from_settlement: false, recurring_bill_id: null, created_at: null,
    splits: [], has_take: false, missing_payer: false,
    ...fields,
    pending: true,
  } as unknown as PendingTxn
}

export type PendingActivity = {
  /** Creates not yet on the server, newest first. */
  creates: PendingTxn[]
  /** Queued full edits by transaction id. */
  edits: ReadonlyMap<string, PendingRow>
  /** Deleted (queued or in flight): keep these server rows out of view. */
  hidden: ReadonlySet<string>
}

export function usePendingActivity(): PendingActivity {
  const view = usePendingView()
  return useMemo(
    () => ({ creates: view.rows.map((r) => toPendingTxn(r)), edits: view.edits, hidden: view.hiddenIds }),
    [view],
  )
}

/** Creates only (the Feed's top rows). */
export function usePendingTransactions(): PendingTxn[] {
  return usePendingActivity().creates
}
