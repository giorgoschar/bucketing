import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useAction, type ActionResult } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import type { EntryDoneIn, EntryOut } from '../../data/types'
import { todayISO } from '../../ui/format'
import { patchEntryEverywhere, type EntryChange } from './entryPatch'

export const UPCOMING_DAYS = 30

export function usePlanUpcoming(days: number = UPCOMING_DAYS) {
  return useCachedQuery(keys.plan.upcoming(days), (signal) =>
    unwrap(api.GET('/api/v1/plan/upcoming', { params: { query: { days } }, signal })))
}

export function usePlanMonth(month: string) {
  return useCachedQuery(keys.plan.month(month), (signal) =>
    unwrap(api.GET('/api/v1/plan/month', { params: { query: { month } }, signal })))
}

export function useCategoriesVsUsual(month: string) {
  return useCachedQuery(keys.insights.categoriesVsUsual(month), (signal) =>
    unwrap(api.GET('/api/v1/insights/categories-vs-usual', { params: { query: { month } }, signal })))
}

export function usePlanYear() {
  return useCachedQuery(keys.plan.year(), (signal) => unwrap(api.GET('/api/v1/plan/year', { signal })))
}

export function useBudgets() {
  return useCachedQuery(keys.plan.budgets(), (signal) => unwrap(api.GET('/api/v1/plan/budgets', { signal })))
}

export function usePace() {
  return useCachedQuery(keys.plan.pace(), (signal) => unwrap(api.GET('/api/v1/plan/pace', { signal })))
}

export interface EntryActions {
  markDone: (body: EntryDoneIn) => Promise<ActionResult<EntryOut>>
  skip: () => Promise<ActionResult<EntryOut>>
  setAmount: (amount: string) => Promise<ActionResult<EntryOut>>
  undo: (deleteTransaction: boolean) => Promise<ActionResult<EntryOut>>
  busy: boolean
}

/** Spec §4.6: POST /recurring/entries/{id}/done|skip|amount|undo, optimistic and queueable. */
export function useEntryActions(entry: EntryOut): EntryActions {
  const base = `/api/v1/recurring/entries/${entry.id}`
  const shared = { method: 'POST' as const, invalidates: affects.entry, pendingId: entry.id }
  const patch = (change: EntryChange) => (qc: QueryClient) => patchEntryEverywhere(qc, entry, change)

  const done = useAction<EntryDoneIn, EntryOut>({
    ...shared,
    path: `${base}/done`,
    body: (b: EntryDoneIn) => b,
    optimistic: (qc, b) =>
      patchEntryEverywhere(qc, entry, { kind: 'done', amount: b.amount == null ? null : Number(b.amount), today: todayISO() }),
  })
  const skip = useAction<void, EntryOut>({ ...shared, path: `${base}/skip`, optimistic: patch({ kind: 'skip' }) })
  const amount = useAction<string, EntryOut>({
    ...shared,
    path: `${base}/amount`,
    body: (a: string) => ({ amount: a }),
    optimistic: (qc, a) => patchEntryEverywhere(qc, entry, { kind: 'amount', amount: Number(a) }),
  })
  // Quiet rejections: the sheet shows a Fixed-cost 409 inline next to "Delete the expense".
  const undoKeep = useAction<void, EntryOut>({
    ...shared, path: `${base}/undo`, body: { delete_transaction: false }, toastRejections: false, optimistic: patch({ kind: 'undo' }),
  })
  const undoDelete = useAction<void, EntryOut>({
    ...shared, path: `${base}/undo`, body: { delete_transaction: true }, toastRejections: false, optimistic: patch({ kind: 'undo' }),
  })

  return {
    markDone: done.run,
    skip: () => skip.run(),
    setAmount: amount.run,
    undo: (deleteTransaction) => (deleteTransaction ? undoDelete : undoKeep).run(),
    busy: done.busy || skip.busy || amount.busy || undoKeep.busy || undoDelete.busy,
  }
}
