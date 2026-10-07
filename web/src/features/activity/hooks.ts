import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { components } from '../../api/schema'
import { useAction } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { ApiError, unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import { useCategories, useHousehold } from '../../data/reads'
import type { Category, Member } from '../../data/types'
import { toQuery, type TransactionFilter } from './filters'

type S = components['schemas']
export type Txn = S['TransactionOut']
export type TxnPage = S['TransactionPage']
export type Counts = S['CountsOut']
export type DuplicateGroup = S['DuplicateGroupOut']
export type HistoryEvent = S['HistoryEventOut']
export type TxnUpdate = S['TransactionUpdate']
export type TxnPatch = Partial<
  Pick<Txn, 'category_id' | 'bucket_id' | 'paid_by' | 'payer_mode' | 'payment_method' | 'notes' | 'exclude_from_forecast'>
>
export type RefData = {
  buckets: { id: string; name: string; kind: string; status: string; show_income: boolean; icon: string | null }[]
  categories: Pick<Category, 'id' | 'name' | 'icon'>[]
  members: Pick<Member, 'user_id' | 'display_name'>[]
}

export const PAGE_SIZE = 50
export const OFFLINE_MESSAGE = "Couldn't reach the server. Nothing was changed."
/** What a delete, edit, bulk apply or undo invalidates (spec §6): 2a's `affects.entry` (plan, home, recurring,
 * matches, transactions, insights) plus the two keys this plan adds. */
export const ACTIVITY_WRITES = [...affects.entry, keys.duplicates(), keys.bulkRecent()] as const

/** Online-only calls (bulk, undo, dismiss): a network failure is never queued. `ApiError` is 2a's (data/http). */
export async function online<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call()
  } catch (e) {
    if (e instanceof ApiError) throw e
    throw new ApiError(0, OFFLINE_MESSAGE)
  }
}

export function useFeedPage(filter: TransactionFilter, page: number) {
  return useCachedQuery(keys.transactions.list(filter, page), (signal) =>
    unwrap(api.GET('/api/v1/transactions', { params: { query: { ...toQuery(filter), page, page_size: PAGE_SIZE } }, signal })),
  )
}
export function useCounts() {
  return useCachedQuery(keys.transactions.counts(), (signal) => unwrap(api.GET('/api/v1/transactions/counts', { signal })))
}
export function useDuplicates() {
  return useCachedQuery(keys.duplicates(), (signal) => unwrap(api.GET('/api/v1/transactions/duplicates', { signal })))
}
export function useTransaction(id: string) {
  return useCachedQuery(keys.transactions.one(id), (signal) =>
    unwrap(api.GET('/api/v1/transactions/{txn_id}', { params: { path: { txn_id: id } }, signal })),
  )
}
export function useHistory(id: string) {
  return useCachedQuery(keys.transactions.history(id), (signal) =>
    unwrap(api.GET('/api/v1/transactions/{txn_id}/history', { params: { path: { txn_id: id } }, signal })),
  )
}
/** Buckets (raw rows, for show_income and icon), plus 2a's categories and household reads. */
export function useRefData(): RefData | undefined {
  const buckets = useCachedQuery(keys.bucketsFull(), async (signal) =>
    (await unwrap(api.GET('/api/v1/buckets', { signal }))) as RefData['buckets'],
  )
  const categories = useCategories()
  const household = useHousehold()
  if (!buckets.data || !categories.data || !household.data) return undefined
  return { buckets: buckets.data, categories: categories.data, members: household.data.members }
}

export const receiptUrl = (id: string) => `/api/v1/transactions/${encodeURIComponent(id)}/receipt`

export async function uploadReceipt(id: string, file: File): Promise<void> {
  const form = new FormData()
  form.append('file', file)
  await online(() =>
    unwrap(api.POST('/api/v1/transactions/{txn_id}/receipt', {
      params: { path: { txn_id: id } },
      body: form as never,
      bodySerializer: (b: unknown) => b as FormData,
    })),
  )
}

/** The full PUT body from the cached row. splits and payer_mode are copied:
 * update_transaction replaces the splits, so a PUT without them deletes them. */
export function editBody(t: Txn, patch: TxnPatch): TxnUpdate {
  return {
    amount: t.amount,
    currency: t.currency ?? 'EUR',
    exchange_rate: t.exchange_rate,
    type: t.type as TxnUpdate['type'],
    bucket_id: t.bucket_id,
    paid_by: t.paid_by,
    payer_mode: t.payer_mode,
    category_id: t.category_id,
    notes: t.notes,
    transaction_date: t.transaction_date,
    payment_method: t.payment_method,
    merchant: t.merchant,
    fuel_price_per_litre: t.fuel_price_per_litre,
    exclude_from_forecast: t.exclude_from_forecast,
    exclude_from_settlement: t.exclude_from_settlement,
    splits: t.splits.map((s) => ({ user_id: s.user_id, amount: s.amount })),
    ...patch,
  } as TxnUpdate
}

/** Patch (or drop, when fn returns null) one row in every cached list and
 * single-row query. It returns nothing: useAction rolls back by restoring every
 * query under the `invalidates` prefixes, and keys.transactions.all is one of them. */
export function patchRows(qc: QueryClient, id: string, fn: (t: Txn) => Txn | null): void {
  for (const [key, data] of qc.getQueriesData({ queryKey: keys.transactions.all })) {
    if (!data || typeof data !== 'object') continue
    if ('items' in data) {
      const page = data as TxnPage
      qc.setQueryData(key, { ...page, items: page.items.flatMap((t) => (t.id === id ? (fn(t) ?? []) : [t])) })
    } else if ((data as Txn).id === id) {
      const next = fn(data as Txn)
      if (next) qc.setQueryData(key, next)
    }
  }
}

export function useEditTransaction() {
  return useAction<{ txn: Txn; patch: TxnPatch }, Txn>({
    method: 'PUT',
    path: ({ txn }) => `/api/v1/transactions/${txn.id}`,
    // body is typed `unknown`, so its parameter gets no contextual type: annotate it.
    body: ({ txn, patch }: { txn: Txn; patch: TxnPatch }) => editBody(txn, patch),
    optimistic: (qc, { txn, patch }) => patchRows(qc, txn.id, (row) => ({ ...row, ...patch })),
    invalidates: ACTIVITY_WRITES,
    pendingId: ({ txn }) => txn.id,
  })
}

export function useDeleteTransaction() {
  return useAction<{ id: string }>({
    method: 'DELETE',
    path: ({ id }) => `/api/v1/transactions/${id}`,
    optimistic: (qc, { id }) => patchRows(qc, id, () => null),
    invalidates: ACTIVITY_WRITES,
    pendingId: ({ id }) => id,
  })
}
