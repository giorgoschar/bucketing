import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../../../api/client'
import { useAction } from '../../../data/action'
import { useCachedQuery } from '../../../data/cachedQuery'
import { runOnline, useOnlineAction } from '../../../data/onlineAction'
import { unwrap } from '../../../data/http'
import { onQueueDrained } from '../../../offline/queueDrain'
import { keys } from '../../../data/keys'
import type { PriceIn, Retailer, StockEditBody } from './contractTypes'
import { PANTRY_INVALIDATES, useShopping } from './shoppingHooks'
import type { ProductSummary, StockAddBody, StockAdjustBody, StockDetail, StockItem, StockSettingsBody } from './types'

/**
 * After the offline queue replays, refetch the pantry while the list or the detail is mounted. The queue
 * bridge's affects.sync covers ['stock'] too; this keeps the mounted screen's numbers honest even where the
 * bridge isn't installed. Mounted by the Pantry list and the product detail.
 */
export function usePantryReplaySync() {
  const qc = useQueryClient()
  useEffect(() => onQueueDrained(() => {
    for (const queryKey of PANTRY_INVALIDATES) void qc.invalidateQueries({ queryKey })
  }), [qc])
}

/** GET /stock. */
export function useStockList() {
  return useCachedQuery(keys.stockList(), (signal) => unwrap(api.GET('/api/v1/stock', { signal })))
}

/**
 * "Shopping list (N)": N is the low and running-out rows of GET /stock/shopping (spec §4.2). Rows listed only
 * because they are ticked (`reason: 'ticked'`) are not counted. Shares keys.shopping() with the list screen.
 */
export function usePantryShoppingCount(): number | undefined {
  const items = useShopping().data?.items
  return items?.filter((i) => i.reason !== 'ticked').length
}

/** GET /stock/{id}. */
export function useStockDetail(id: string) {
  return useCachedQuery(keys.stockItem(id), (signal) =>
    unwrap(api.GET('/api/v1/stock/{item_id}', { params: { path: { item_id: id } }, signal })))
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
 * a relative delta, so each tap carries its own client_id and the server applies a replay once. Online, the
 * taps on one item are sent in order, never overlapping.
 */
export function useAdjustStock(item: { id: string }) {
  const { run, busy } = useAction<number, StockItem>({
    method: 'POST',
    path: `/api/v1/stock/${encodeURIComponent(item.id)}/adjust`,
    body: (delta: number): StockAdjustBody => ({ delta, client_id: newClientId() }),
    optimistic: (qc, delta) => patchItem(qc, item.id, (i) => adjusted(i, delta)),
    invalidates: PANTRY_INVALIDATES,
    pendingId: item.id,
    // Taps on one item are sent one after another (polish P2); the count still moves at once.
    serial: `stock:${item.id}`,
  })
  return { adjust: run, busy }
}

/** POST /stock: online only (spec §4.8). Failures are toasted; success invalidates the pantry. */
export function useAddProduct() {
  const act = useOnlineAction()
  return (body: StockAddBody) =>
    act(() => api.POST('/api/v1/stock', { body }), { invalidates: PANTRY_INVALIDATES })
}

/**
 * What a lookup result adds: the PosoKanei product, with a minimum of 1 (spec §4.3) and none in stock. Adding
 * tracks a product (it is then low, so on the shopping list); it never claims one is at home, which is also
 * the server's default and what the old UI sent. The manual form keeps an editable "In stock".
 */
export function addBodyFor(p: ProductSummary & { source?: string }): StockAddBody {
  // An Open Food Facts result's id (`off:<barcode>`) is not a PosoKanei id.
  const posokanei_id = p.source === 'openfoodfacts' ? null : p.id
  return {
    name: p.name, brand: p.brand, barcode: p.barcode, posokanei_id, unit: p.unit, unit_quantity: p.unit_quantity,
    image_url: p.image_url, quantity: 0, min_quantity: 1,
  }
}

/** The stores for Log a price (GET /stock/retailers, C3), "Other" last. Loaded while `open`; null until then. */
export function useRetailers(open: boolean): Retailer[] | null {
  const [list, setList] = useState<Retailer[] | null>(null)
  useEffect(() => {
    if (!open || list) return
    let live = true
    void api.GET('/api/v1/stock/retailers').then(
      // A failed load still offers "Other", so a price can always be logged.
      (r) => { if (live) setList(r.response.ok && Array.isArray(r.data) ? r.data : []) },
      () => { if (live) setList([]) },
    )
    return () => { live = false }
  }, [open, list])
  if (!list) return null
  // "Other" is the server's catch-all code: always offered, and always last.
  return [...list.filter((r) => r.code !== 'other'), { code: 'other', name: 'Other' }]
}

/** The detail's online-only writes (spec §4.4, §4.8): settings, edit, Log a price, refresh and archive. */
export function useStockWrites(id: string) {
  const qc = useQueryClient()
  const act = useOnlineAction()
  const invalidate = useCallback(
    () => Promise.all(PANTRY_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey }))),
    [qc],
  )
  return {
    /** PATCH /stock/{id}: the list item comes back; the detail keeps its prices and history. */
    settings: async (body: StockSettingsBody) => {
      const out = await act(() => api.PATCH('/api/v1/stock/{item_id}', { params: { path: { item_id: id } }, body }))
      if (out.ok) {
        qc.setQueryData<StockDetail>(keys.stockItem(id), (d) => (d ? { ...d, ...out.data } : d))
        await invalidate()
      }
      return out
    },
    /**
     * PATCH /stock/{id} with the product's own fields (C2). Every failure comes back for the Edit sheet to
     * show inline (a taken barcode is a 409), so nothing is toasted here.
     */
    edit: async (body: StockEditBody) => {
      const out = await runOnline(() => api.PATCH('/api/v1/stock/{item_id}', { params: { path: { item_id: id } }, body }))
      if (out.ok) {
        qc.setQueryData<StockDetail>(keys.stockItem(id), (d) => (d ? { ...d, ...out.data } : d))
        await invalidate()
      }
      return out
    },
    /** POST /stock/{id}/prices (C3): the detail comes back with the logged price in it. */
    logPrice: async (body: PriceIn) => {
      const out = await runOnline(() => api.POST('/api/v1/stock/{item_id}/prices', { params: { path: { item_id: id } }, body }))
      if (out.ok) {
        qc.setQueryData(keys.stockItem(id), out.data)
        await invalidate()
      }
      return out
    },
    /** POST /stock/{id}/refresh: 503 when PosoKanei is unavailable; the caller says so inline (not a toast). */
    refresh: async () => {
      const out = await runOnline(() => api.POST('/api/v1/stock/{item_id}/refresh', { params: { path: { item_id: id } } }))
      if (out.ok) {
        qc.setQueryData(keys.stockItem(id), out.data)
        await invalidate()
      }
      return out
    },
    /** POST /stock/{id}/archive (204). */
    archive: async () => {
      const out = await act(() => api.POST('/api/v1/stock/{item_id}/archive', { params: { path: { item_id: id } } }))
      if (out.ok) {
        // The item is gone: never refetch it (a 404) while the screen leaves; everything else refreshes.
        await Promise.all(PANTRY_INVALIDATES.map((queryKey) => qc.invalidateQueries({
          queryKey, predicate: (q) => !(q.queryKey[0] === 'stock' && q.queryKey[1] === 'item' && q.queryKey[2] === id),
        })))
        await qc.invalidateQueries({ queryKey: keys.stockItem(id), refetchType: 'none' })
      }
      return out
    },
  }
}
