import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { api } from '../../../api/client'
import { useAction } from '../../../data/action'
import { useCachedQuery } from '../../../data/cachedQuery'
import { useOnlineAction } from '../../../data/onlineAction'
import type { RawResult } from '../../../data/rawJson'
import { unwrap } from '../../../data/http'
import { keys } from '../../../data/keys'
import type { PantryShoppingCount, ProductSummary, StockAddBody, StockAdjustBody, StockDetail, StockItem } from './types'

/**
 * The shopping list's count, for "Shopping list (N)". Stream Wb owns keys.shopping; until the integration
 * joins them this read has its own key under the 'stock' prefix.
 */
export const PANTRY_SHOPPING_COUNT_KEY = ['stock', 'shopping-count'] as const

/**
 * Everything a pantry write makes stale (pantry spec §4.8). The 'stock' prefix covers the list, every item
 * and the shopping count. The integration adds Wb's keys.shopping and keys.stockSummary here.
 */
export const PANTRY_INVALIDATES: readonly QueryKey[] = [['stock'], keys.home.all]

/** GET /stock. */
export function useStockList() {
  return useCachedQuery(keys.stockList(), async (signal) =>
    (await unwrap(api.GET('/api/v1/stock', { signal }))) as StockItem[])
}

/** GET /stock/shopping, read only for its item count. */
export function usePantryShoppingCount() {
  return useCachedQuery(PANTRY_SHOPPING_COUNT_KEY, async (signal): Promise<PantryShoppingCount> => {
    const out = (await unwrap(api.GET('/api/v1/stock/shopping', { signal }))) as PantryShoppingCount
    return { items: (out.items ?? []).map((i) => ({ id: i.id })) }
  })
}

/** GET /stock/{id}: not in the generated schema yet, so through the client untyped (CSRF and 401 still apply). */
export function useStockDetail(id: string) {
  return useCachedQuery(keys.stockItem(id), async (signal) =>
    (await unwrap(api.GET(`/api/v1/stock/${encodeURIComponent(id)}` as never, { signal } as never))) as StockDetail)
}

/** The restock quantity the server would compute: max(1, ceil(2*min − qty)). */
export const needQty = (quantity: number, min: number): number => Math.max(1, Math.ceil(2 * min - quantity))

/** An item after a ± change, as the server will return it (clamped at 0). */
export function adjusted<T extends StockItem>(item: T, delta: number): T {
  const quantity = Math.max(0, Math.round((item.quantity + delta) * 100) / 100)
  return { ...item, quantity, low: quantity <= item.min_quantity, need_qty: needQty(quantity, item.min_quantity) }
}

function patchItem(qc: QueryClient, id: string, change: <T extends StockItem>(item: T) => T) {
  qc.setQueryData<StockItem[]>(keys.stockList(), (list) => list?.map((i) => (i.id === id ? change(i) : i)))
  qc.setQueryData<StockDetail>(keys.stockItem(id), (d) => (d ? change(d) : d))
}

const newClientId = (): string => crypto.randomUUID()

/**
 * The ± stepper (pantry spec §4.8): optimistic, queued offline with a "Waiting to sync" marker. An adjust is
 * a relative delta, so each tap carries its own client_id and the server applies a replay once.
 */
export function useAdjustStock(item: { id: string }) {
  const { run, busy } = useAction<number, StockItem>({
    method: 'POST',
    path: `/api/v1/stock/${encodeURIComponent(item.id)}/adjust`,
    body: (delta: number): StockAdjustBody => ({ delta, client_id: newClientId() }),
    optimistic: (qc, delta) => patchItem(qc, item.id, (i) => adjusted(i, delta)),
    invalidates: PANTRY_INVALIDATES,
    pendingId: item.id,
  })
  return { adjust: run, busy }
}

/** POST /stock: online only (spec §4.8). Failures are toasted; success invalidates the pantry. */
export function useAddProduct() {
  const act = useOnlineAction()
  return (body: StockAddBody) =>
    act<StockItem>(
      () => api.POST('/api/v1/stock', { body: body as never }) as Promise<RawResult<StockItem>>,
      { invalidates: PANTRY_INVALIDATES },
    )
}

/** What a lookup result adds: the PosoKanei product, with a minimum of 1 (spec §4.3). */
export function addBodyFor(p: ProductSummary): StockAddBody {
  return {
    name: p.name, brand: p.brand, barcode: p.barcode, posokanei_id: p.id, unit: p.unit, unit_quantity: p.unit_quantity,
    image_url: p.image_url, quantity: 1, min_quantity: 1,
  }
}
