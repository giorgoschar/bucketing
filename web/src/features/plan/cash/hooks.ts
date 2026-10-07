import { type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '../../../api/client'
import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import { keys } from '../../../data/keys'
import { type OnlineOutcome, runOnline } from '../../../data/onlineAction'
import { fetchJson } from '../../../data/rawJson'
import { useToast } from '../../../ui/Toast'
import type { CashMovementOut, CashMovementsOut, CashWalletsOut, MovementBody } from './types'

/** Everything a cash write (or a composer save of a cash expense) makes stale (spec §4.7). */
export const CASH_INVALIDATES: readonly QueryKey[] = [
  keys.cashAll(), keys.cashStash(), keys.home.all, keys.plan.all, keys.insights.all,
]

/** The month's wallets and the viewer's stash. /cash/wallets is not in the generated types until the
 *  integration step, so it goes through fetchJson (switch to api.GET then). */
export function useCashWallets(month: string) {
  return useCachedQuery(keys.cashWallets(month), () =>
    unwrap(fetchJson<CashWalletsOut>('GET', `/api/v1/cash/wallets?month=${encodeURIComponent(month)}`)))
}

/** The viewer's movements in the month, plus others' takes from their stash; newest first. */
export function useCashMovements(month: string) {
  return useCachedQuery(keys.cashMovements(month), async (signal) => {
    const out = (await unwrap(api.GET('/api/v1/cash/movements', { params: { query: { month, limit: 500 } }, signal }))) as CashMovementsOut
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
    /** POST /cash/movements. `stash_count` is not in the generated MovementIn until integration. */
    run: (body: MovementBody) => act(() => fetchJson<CashMovementOut>('POST', '/api/v1/cash/movements', body)),
    remove: (id: string) =>
      act(() => api.DELETE('/api/v1/cash/movements/{movement_id}', { params: { path: { movement_id: id } } })),
  }
}
