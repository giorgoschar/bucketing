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
import { useCashWallets, useQueuedCashLogged } from '../plan/cash/hooks'
import { useStockSummary } from '../plan/pantry/shoppingHooks'
import { patchEntryEverywhere } from '../plan/entryPatch'
import { useBudgets, useCategoriesVsUsual, usePlanUpcoming } from '../plan/hooks'
import { useBills } from '../insights/bills/hooks'
import { useStatements } from '../insights/statements/hooks'
import { useDismissedBills } from './billDismiss'
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
  const wallets = useCashWallets(today.slice(0, 7)).data
  const me = wallets?.members.find((m) => m.is_me)
  // Cash already logged but still queued (offline) counts as logged: the row hides until the wallets catch up,
  // and comes back if the server refuses the write (Cash final review m5).
  const queuedCash = useQueuedCashLogged(today.slice(0, 7), me?.member_id)
  const cashNotLogged = me && Math.max(0, Math.round((me.wallet.not_yet_logged - queuedCash) * 100) / 100)
  const pantryLow = useStockSummary().data?.low_count
  const failed = useFailedQueueRows()
  const bills = useBills().data
  const dismissedBills = useDismissedBills()
  const review = useStatements().data?.review
  const input: AttentionInput = {
    today, matches, overdue, upcoming, budgets, categories, cashNotLogged, pantryLow, failed, bills, dismissedBills, review,
  }
  return { items: buildAttention(input), ready: attentionReady(input) }
}
