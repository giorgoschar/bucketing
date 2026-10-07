import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAction } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import { toTransactionPage } from '../../data/reads'
import type { EntryOut, MatchOut } from '../../data/types'
import { useFailedQueueRows } from '../../offline/useQueue'
import { todayISO } from '../../ui/format'
import { patchEntryEverywhere } from '../plan/entryPatch'
import { useBudgets, useCategoriesVsUsual, usePlanUpcoming } from '../plan/hooks'
import { attentionReady, buildAttention, overdueWindow, type AttentionInput, type AttentionItem } from './attention'

export const RECENT_COUNT = 10

export function useOverdueEntries(today: string = todayISO()) {
  const { from, to } = overdueWindow(today)
  return useCachedQuery(keys.home.overdue(from, to), (signal) =>
    unwrap(api.GET('/api/v1/recurring/entries', { params: { query: { from, to } }, signal })))
}

export function useMatches() {
  return useCachedQuery(keys.matches(), (signal) => unwrap(api.GET('/api/v1/matches', { signal })))
}

/** The last 10 transactions, newest first (spec §5.3). 2b merges its pending rows into this key. */
export function useRecentTransactions() {
  return useCachedQuery(keys.transactions.recent(), async (signal) =>
    toTransactionPage(await unwrap(api.GET('/api/v1/transactions', { params: { query: { page_size: RECENT_COUNT } }, signal }))).items)
}

const dropMatch = (qc: QueryClient, id: string) =>
  qc.setQueryData<MatchOut[]>(keys.matches(), (old) => old?.filter((m) => m.id !== id))

/** Link and Not this (spec §5.2.1); both optimistic and queueable. */
export function useMatchActions(match: MatchOut) {
  const link = useAction<void, EntryOut>({
    method: 'POST',
    path: `/api/v1/matches/${match.id}/link`,
    optimistic: (qc) => {
      dropMatch(qc, match.id)
      patchEntryEverywhere(qc, match.entry, { kind: 'linked' })
    },
    invalidates: affects.entry,
    pendingId: match.id,
  })
  const dismiss = useAction<void, null>({
    method: 'POST',
    path: `/api/v1/matches/${match.id}/dismiss`,
    optimistic: (qc) => dropMatch(qc, match.id),
    invalidates: [keys.matches()],
    pendingId: match.id,
  })
  return { link: () => link.run(), dismiss: () => dismiss.run(), busy: link.busy || dismiss.busy }
}

export function useAttention(): { items: AttentionItem[]; ready: boolean } {
  const today = todayISO()
  const matches = useMatches().data
  const overdue = useOverdueEntries(today).data
  const upcoming = usePlanUpcoming().data
  const budgets = useBudgets().data
  const categories = useCategoriesVsUsual(today.slice(0, 7)).data
  const failed = useFailedQueueRows()
  const input: AttentionInput = { today, matches, overdue, upcoming, budgets, categories, failed }
  return { items: buildAttention(input), ready: attentionReady(input) }
}
