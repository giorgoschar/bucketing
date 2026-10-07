import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery, type QueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import { useAction } from '../../../data/action'
import { useCachedQuery } from '../../../data/cachedQuery'
import { ApiError, unwrap } from '../../../data/http'
import { affects, keys } from '../../../data/keys'
import { useOnline } from '../../../data/online'
import { toTransactionPage } from '../../../data/reads'
import type { RecurringItemIn, RecurringItemOut } from '../../../data/types'
import { pendingItem } from './form'
import { toRuleFields, type RuleChoice } from './rule'

export const PREVIEW_DEBOUNCE_MS = 300

/** `value` once it has stopped changing for `ms` (compared by JSON, so fresh objects don't restart it). */
export function useDebouncedValue<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  const json = JSON.stringify(value)
  useEffect(() => {
    const t = setTimeout(() => setSettled(JSON.parse(json) as T), ms)
    return () => clearTimeout(t)
  }, [json, ms])
  return settled
}

export type PreviewState =
  | { state: 'loading' }
  | { state: 'ready'; dates: string[] }
  | { state: 'offline' }
  | { state: 'error'; message: string }

/** "Next: 26 Oct, 25 Nov, 23 Dec" from POST /recurring/preview, debounced 300 ms (spec §4.7). Online only. */
export function useRulePreview(rule: RuleChoice, startDate: string, endDate: string): PreviewState {
  const online = useOnline()
  const body = useDebouncedValue(
    { ...toRuleFields(rule), start_date: startDate, end_date: endDate || null, count: 3 },
    PREVIEW_DEBOUNCE_MS,
  )
  const q = useQuery({
    queryKey: ['rule-preview', body],
    queryFn: ({ signal }) => unwrap(api.POST('/api/v1/recurring/preview', { body, signal })),
    enabled: online && body.start_date !== '',
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 5 * 60_000,
  })
  if (!online) return { state: 'offline' }
  if (q.error) return { state: 'error', message: q.error instanceof ApiError ? q.error.detail : 'Couldn’t check the dates.' }
  if (q.data) return { state: 'ready', dates: q.data.dates }
  return { state: 'loading' }
}

/** Whether an item has payments (locks its direction, hides Delete). undefined until known. */
export function useItemHasHistory(itemId: string | null): boolean | undefined {
  const q = useCachedQuery(
    keys.transactions.forItem(itemId ?? ''),
    async (signal) =>
      toTransactionPage(await unwrap(api.GET('/api/v1/transactions', {
        params: { query: { recurring_bill_id: itemId ?? '', page_size: 1 } },
        signal,
      }))).total,
    { enabled: itemId !== null },
  )
  return q.data === undefined ? undefined : q.data > 0
}

const editList = (qc: QueryClient, fn: (items: RecurringItemOut[]) => RecurringItemOut[]) =>
  qc.setQueryData<RecurringItemOut[]>(keys.recurring.list(), (old) => (old ? fn(old) : old))

type CreateVars = { body: RecurringItemIn; tempId: string }
type UpdateVars = { id: string; body: RecurringItemIn }
type RemoveVars = { id: string }

export function useItemActions() {
  const create = useAction<CreateVars, RecurringItemOut>({
    method: 'POST',
    path: '/api/v1/recurring',
    body: (v: CreateVars) => v.body,
    optimistic: (qc, v) => editList(qc, (items) => [...items, pendingItem(v.body, v.tempId)]),
    invalidates: affects.item,
    pendingId: (v) => v.tempId,
  })
  const update = useAction<UpdateVars, RecurringItemOut>({
    method: 'PUT',
    path: (v) => `/api/v1/recurring/${v.id}`,
    body: (v: UpdateVars) => v.body,
    optimistic: (qc, v) =>
      editList(qc, (items) => items.map((i) => (i.id === v.id ? { ...pendingItem(v.body, v.id), next_entry: i.next_entry } : i))),
    invalidates: affects.item,
    pendingId: (v) => v.id,
  })
  // Quiet: the sheet shows a 409 ("has payment history") next to "Pause instead".
  const remove = useAction<RemoveVars, null>({
    method: 'DELETE',
    path: (v) => `/api/v1/recurring/${v.id}`,
    optimistic: (qc, v) => editList(qc, (items) => items.filter((i) => i.id !== v.id)),
    invalidates: affects.item,
    pendingId: (v) => v.id,
    toastRejections: false,
  })
  return { create: create.run, update: update.run, remove: remove.run, busy: create.busy || update.busy || remove.busy }
}
