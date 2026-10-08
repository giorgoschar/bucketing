import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useCallback, useSyncExternalStore } from 'react'
import { isOnline } from '../../../data/online'
import { keys } from '../../../data/keys'
import { db } from '../../../offline/db'
import { fetchStockSummary } from './shoppingHooks'

/**
 * The one-time "Add ticked items to the pantry?" offer after a new expense saves (pantry spec §4.6).
 * Module state, like the toast: the composer leaves before the answer comes back, and AppShell's
 * <TickedPrompt /> shows it wherever the user lands. null = nothing to offer.
 */
let offered: number | null = null
const subs = new Set<() => void>()
const emit = () => subs.forEach((cb) => cb())
const subscribe = (cb: () => void) => {
  subs.add(cb)
  return () => { subs.delete(cb) }
}

/** How many ticked items to offer, or null. */
export function useTickedOffer(): number | null {
  return useSyncExternalStore(subscribe, () => offered, () => null)
}

/** Not now, Add, or a sign-out: drop the offer until the next new expense. */
export function resetTickedPrompt(): void {
  if (offered === null) return
  offered = null
  emit()
}

/**
 * Ask GET /stock/summary (through the cached query) and offer the prompt when something is ticked. Never
 * throws and never awaited by the save: offline, queued changes, a failed or slow call, or nothing ticked all
 * mean no prompt.
 */
export async function offerTickedPrompt(qc: QueryClient): Promise<void> {
  if (!isOnline()) return
  try {
    // Earlier pantry writes still queued would have to reach the server before apply-ticked: no offer then.
    if ((await db.queue.where('status').equals('pending').count()) > 0) return
    const summary = await qc.fetchQuery({ queryKey: keys.stockSummary(), queryFn: ({ signal }) => fetchStockSummary(signal), staleTime: 0, retry: false })
    if (summary.ticked_count > 0) {
      offered = summary.ticked_count
      emit()
    }
  } catch {
    // No prompt. The expense is saved either way.
  }
}

/** For the composer: call after a new expense saved online (status 'done'). Fire and forget. */
export function useOfferTickedPrompt(): () => void {
  const qc = useQueryClient()
  return useCallback(() => { void offerTickedPrompt(qc) }, [qc])
}
