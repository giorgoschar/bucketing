import type { QueryClient } from '@tanstack/react-query'
import { api, readCsrf } from '../../api/client'
import type { components } from '../../api/schema'
import { useAction } from '../../data/action'
import { useCachedQuery } from '../../data/cachedQuery'
import { ApiError, unwrap } from '../../data/http'
import { affects, keys } from '../../data/keys'
import { useCategories, useHousehold } from '../../data/reads'
import type { Category, Member, RecurringItemOut } from '../../data/types'
import { DEFAULT_SORT, type Sort, toQuery, type TransactionFilter } from './filters'

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
export type RecurringItem = Pick<RecurringItemOut, 'id' | 'name' | 'direction'>
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

/** One page of the feed. `sort` is sent (and keyed) only when it is not the default, so the phone's requests
 *  and cache keys are unchanged. */
export function useFeedPage(filter: TransactionFilter, page: number, sort: Sort = DEFAULT_SORT) {
  const sorted = sort !== DEFAULT_SORT
  return useCachedQuery(keys.transactions.list(sorted ? { ...filter, sort } : filter, page), (signal) =>
    unwrap(api.GET('/api/v1/transactions', {
      // `sort` is spec §3.8's, not in the generated types until stream S lands: cast at this one call site.
      params: { query: { ...toQuery(filter), ...(sorted ? { sort } : {}), page, page_size: PAGE_SIZE } as never },
      signal,
    })),
  )
}
/** Count, money out and money in over every match of the filter (server-side, household currency). Only
 *  fetched while `enabled`; offline it shows the saved copy, or nothing. */
export function useTotals(filter: TransactionFilter, enabled: boolean) {
  const query = toQuery(filter)
  return useCachedQuery(
    keys.activityTotals(JSON.stringify(query)),
    (signal) => unwrap(api.GET('/api/v1/transactions/totals', { params: { query }, signal })),
    { enabled },
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
    // A delete that failed while online may have been applied; replaying it would 404. Queue it only offline.
    queue: 'offline-only',
  })
}

export type LinkedEntry = S['EntryOut']
/** The plan entry this transaction paid, looked up within ±45 days (2a's entries read). */
export function useLinkedEntry(t: Txn | undefined): LinkedEntry | undefined {
  const day = t?.transaction_date ?? '2000-01-01'
  const shift = (d: string, n: number) => new Date(Date.parse(d) + n * 864e5).toISOString().slice(0, 10)
  const from = shift(day, -45)
  const to = shift(day, 45)
  const q = useCachedQuery(
    keys.recurring.entries(from, to),
    (signal) => unwrap(api.GET('/api/v1/recurring/entries', { params: { query: { from, to } }, signal })),
    { enabled: !!t?.recurring_bill_id },
  )
  return t?.recurring_bill_id ? q.data?.find((e) => e.transaction_id === t.id) : undefined
}

/** "Keep both": hide the pair from the duplicates list for good. Online only, never queued. */
export async function dismissDuplicates(ids: string[]): Promise<void> {
  await online(() => unwrap(api.POST('/api/v1/transactions/duplicates/dismiss', { body: { ids } })))
}

export type BulkChanges = S['ChangesIn']
export type BulkResult = S['BulkResult']
export type BulkReq = { select: import('./selection').BulkSelect; changes: BulkChanges; move_bill: boolean }

/** Bulk preview and apply are online only: a network failure is never queued (spec §6). */
export function previewBulk(req: BulkReq): Promise<BulkResult> {
  return online(() => unwrap(api.POST('/api/v1/transactions/bulk', { body: { ...req, dry_run: true } as never })))
}
/** `expected` (filter and bill selections) makes the server answer 409 if the selection drifted. */
export function applyBulk(req: BulkReq, expected: number | null): Promise<BulkResult> {
  return online(() =>
    unwrap(api.POST('/api/v1/transactions/bulk', { body: { ...req, dry_run: false, expected_count: expected } as never })),
  )
}

export type UndoResult = S['UndoResult']
export type RecentBatch = S['RecentBatchOut']

/** Undo a bulk batch (24 h, once, any member). Online only; a 409 carries the reason. */
export function undoBulk(batchId: string): Promise<UndoResult> {
  return online(() =>
    unwrap(api.POST('/api/v1/transactions/bulk/{batch_id}/undo', { params: { path: { batch_id: batchId } } })),
  )
}
export function useRecentBulk() {
  return useCachedQuery(keys.bulkRecent(), (signal) =>
    unwrap(api.GET('/api/v1/transactions/bulk', { params: { query: { limit: 10 } }, signal })),
  )
}

/** The DELETE for a held swipe delete flushed while the page is going away (pagehide/hidden): a plain
 * fetch with `keepalive`, so the browser finishes it after teardown. useAction's client can't set
 * keepalive, so this adds the CSRF header itself. Rejects on a network failure. */
export function deleteKeepalive(id: string): Promise<Response> {
  return fetch(`/api/v1/transactions/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    keepalive: true,
    credentials: 'same-origin',
    headers: { 'X-CSRF-Token': readCsrf() },
  })
}
