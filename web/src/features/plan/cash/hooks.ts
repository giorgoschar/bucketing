import { type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useLiveQuery } from 'dexie-react-hooks'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import { affects, keys } from '../../../data/keys'
import { type OnlineOutcome, runOnline } from '../../../data/onlineAction'
import { db } from '../../../offline/db'
import { listQueuedBodies, type QueuedBody } from '../../../offline/queuedBodies'
import { useToast } from '../../../ui/Toast'
import type { MovementWrite } from './contractTypes'
import type { CashMovementOut } from './types'

/** Everything a cash write (or a composer save of a cash expense) makes stale (spec §4.7). */
export const CASH_INVALIDATES: readonly QueryKey[] = affects.cash

/** The month's wallets and the viewer's stash. */
export function useCashWallets(month: string) {
  return useCachedQuery(keys.cashWallets(month), (signal) =>
    unwrap(api.GET('/api/v1/cash/wallets', { params: { query: { month } }, signal })))
}

/** The viewer's movements in the month, plus others' takes from their stash; newest first. */
export function useCashMovements(month: string) {
  return useCachedQuery(keys.cashMovements(month), async (signal) => {
    const out = await unwrap(api.GET('/api/v1/cash/movements', { params: { query: { month, limit: 500 } }, signal }))
    return { ...out, items: newestFirst(out.items) }
  })
}

const newestFirst = (items: CashMovementOut[]) =>
  [...items].sort((a, b) =>
    (b.movement_date ?? '').localeCompare(a.movement_date ?? '') || (b.created_at ?? '').localeCompare(a.created_at ?? ''))

/**
 * Cash writes are online only, like Settings (spec §4.7): never queued. Offline, rate-limited or server
 * failures are toasted (role=alert); a rejection (400/422) comes back for the sheet to show inline, since
 * the sheet stays open on it (spec §4.2, §4.3). Success invalidates CASH_INVALIDATES.
 */
export function useCashWrite() {
  const qc = useQueryClient()
  const toast = useToast()
  const act = useCallback(
    async <T,>(call: () => Promise<{ data?: T; error?: unknown; response: Response }>): Promise<OnlineOutcome<T>> => {
      const out = await runOnline(call)
      if (out.ok) await Promise.all(CASH_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })))
      else if (out.kind === 'offline' || out.kind === 'rate') toast.show(out.message, { tone: 'error' })
      return out
    },
    [qc, toast],
  )
  return {
    /** POST /cash/movements. The sheet's `client_id` makes a retry after a lost reply apply once (C5). */
    run: (body: MovementWrite) => act(() => api.POST('/api/v1/cash/movements', { body })),
    remove: (id: string) =>
      act(() => api.DELETE('/api/v1/cash/movements/{movement_id}', { params: { path: { movement_id: id } } })),
  }
}

/** The fields of a queued POST /transactions that say whether it logs the viewer's wallet cash. */
interface QueuedTxn {
  type?: string
  amount?: string | number
  exchange_rate?: string | number | null
  paid_by?: string | null
  payment_method?: string
  took_cash?: boolean
  transaction_date?: string | null
}

/**
 * Cash the viewer logged that is still in the offline queue (Cash final review m5): queued new expenses paid
 * in cash by `memberId`, dated in `month`, that take nothing (a take-and-log adds as much to the wallet as it
 * logs). In the household currency. A write the server refuses on replay leaves the pending queue, so it no
 * longer counts.
 */
export function queuedCashLogged(queued: readonly QueuedBody[], month: string, memberId: string): number {
  let cents = 0
  for (const q of queued) {
    if (q.method !== 'POST' || q.path !== '/api/v1/transactions') continue
    const t = (q.body ?? {}) as QueuedTxn
    if (t.type !== 'expense' || t.payment_method !== 'cash' || t.took_cash || t.paid_by !== memberId) continue
    if (!t.transaction_date?.startsWith(month)) continue
    const amount = Number(t.amount) * Number(t.exchange_rate ?? 1)
    if (Number.isFinite(amount) && amount > 0) cents += Math.round(amount * 100)
  }
  return cents / 100
}

/** queuedCashLogged over the live offline queue; 0 until it is read. */
export function useQueuedCashLogged(month: string, memberId: string | undefined): number {
  // Dexie live query on the raw row ids only; decryption runs outside it (WebCrypto is not a Dexie promise).
  const ids = useLiveQuery(() => db.queue.where('status').equals('pending').primaryKeys(), [], [] as number[])
  const sig = ids.join(',')
  const [queued, setQueued] = useState<QueuedBody[]>([])
  useEffect(() => {
    let live = true
    void listQueuedBodies('/api/v1/transactions').then((b) => { if (live) setQueued(b) })
    return () => { live = false }
  }, [sig])
  return memberId ? queuedCashLogged(queued, month, memberId) : 0
}
