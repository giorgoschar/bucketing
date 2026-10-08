import { type QueryClient, type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '../../../api/client'
import { useAction } from '../../../data/action'
import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import { keys } from '../../../data/keys'
import { type OnlineOutcome, runOnline } from '../../../data/onlineAction'
import { useQueue } from '../../../offline/useQueue'
import { useToast } from '../../../ui/Toast'
import type {
  AppliedOut, ApplyTickedOut, LineIn, ShoppingItem, ShoppingLine, ShoppingOut, StockSummary, TickIn, TickOut,
} from './shoppingTypes'

/**
 * What every pantry write makes stale (pantry spec §4.8): every pantry read (the list, the item, the
 * shopping list and the summary all sit under ['stock']) and Home's attention rows.
 */
export const PANTRY_INVALIDATES: readonly QueryKey[] = [['stock'], keys.home.all]

/** Shown on an online-only pantry control while offline (spec §4.8). */
export const PANTRY_OFFLINE = 'Connect to change the pantry'

/**
 * Writes still in the offline queue (pending or backing off). apply-ticked must wait for them: a queued
 * untick or tick has to reach the server first, or stock would follow ticks the user no longer has. The
 * queue's paths are sealed, so this counts every queued write, not only pantry ones.
 */
export function useQueuedChanges(): number {
  return useQueue().pending
}

export const syncingText = (n: number) => `Waiting to sync ${n === 1 ? '1 change' : `${n} changes`}`

export const fetchShopping = (signal: AbortSignal): Promise<ShoppingOut> =>
  unwrap(api.GET('/api/v1/stock/shopping', { signal }))
export const fetchStockSummary = (signal: AbortSignal): Promise<StockSummary> =>
  unwrap(api.GET('/api/v1/stock/summary', { signal }))

export function useShopping() {
  return useCachedQuery(keys.shopping(), fetchShopping)
}

/** {low_count, ticked_count}: cheap, counts only (spec §3.3). */
export function useStockSummary() {
  return useCachedQuery(keys.stockSummary(), fetchStockSummary)
}

/** Splitting the list across stores is worth a badge only above this (spec §4.5). */
export const SAVES_MIN = 0.5

/** What buying each item at its cheapest store saves against the best single store, or null. Only a store
 *  that stocks every priced item is a like-for-like comparison. */
export function savesVsOneStore(s: ShoppingOut): number | null {
  const best = s.best_single_store
  if (!best || best.missing > 0) return null
  const cents = Math.round((best.total - s.total) * 100)
  return cents > SAVES_MIN * 100 ? cents / 100 : null
}

/** "2", "0.5": quantities without trailing zeros. */
export const formatQty = (n: number): string => String(Math.round(n * 100) / 100)

/** The apply-ticked toast: "Milk 0 → 2 · Olive oil 1 → 2" (spec §4.5). */
export function appliedText(out: ApplyTickedOut): string {
  if (out.applied.length) {
    return out.applied.map((a: AppliedOut) => `${a.name} ${formatQty(a.before)} → ${formatQty(a.after)}`).join(' · ')
  }
  if (out.cleared_lines) return out.cleared_lines === 1 ? 'Cleared 1 checked item' : `Cleared ${out.cleared_lines} checked items`
  return 'Nothing ticked to add'
}

/**
 * POST /stock/shopping/apply-ticked: online only, never queued (spec §4.8). Success toasts what went into
 * the pantry and invalidates PANTRY_INVALIDATES; a failure is toasted as an error (401 is the session's).
 */
export function useApplyTicked() {
  const qc = useQueryClient()
  const toast = useToast()
  return useCallback(async (): Promise<OnlineOutcome<ApplyTickedOut>> => {
    const out = await runOnline(() => api.POST('/api/v1/stock/shopping/apply-ticked'))
    if (out.ok) {
      await Promise.all(PANTRY_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })))
      toast.show(appliedText(out.data))
    } else if (out.kind !== 'auth') {
      toast.show(out.message, { tone: 'error' })
    }
    return out
  }, [qc, toast])
}

// ---- Optimistic patches of the cached shopping list (inside PANTRY_INVALIDATES, so a rollback restores them).

const patchList = (qc: QueryClient, fn: (s: ShoppingOut) => ShoppingOut) =>
  qc.setQueryData<ShoppingOut>(keys.shopping(), (old) => (old ? fn(old) : old))

/** Tick (with the tick's client-made id) or untick (tickId null) one row. */
const setTicked = (id: string, tickId: string | null) => (qc: QueryClient) =>
  patchList(qc, (s) => {
    const ticked = tickId !== null
    const was = s.items.find((i) => i.id === id)?.ticked
    if (was === undefined || was === ticked) return s
    return {
      ...s,
      items: s.items.map((i) => (i.id === id ? { ...i, ticked, tick_id: tickId } : i)),
      ticked_count: Math.max(0, s.ticked_count + (ticked ? 1 : -1)),
    }
  })

/** A one-off line to add; `id` is made on the phone (a uuid4), so the row is real from the start. */
export interface NewLine { id: string; name: string; quantity?: number | null }

/** A uuid4 for a new tick or line: the server takes it as the row's id, so a replayed create is a no-op. */
export const newRowId = (): string => crypto.randomUUID()

/**
 * Ticks and one-off lines (spec §4.5, §4.8): optimistic and queued offline, because people shop with poor
 * signal. Creates carry a client-made id (pantry fix round 1, I2), so a row made offline can be unticked,
 * checked or deleted offline too: its PATCH/DELETE queue behind its create and replay in order. Ticks and the
 * PATCH/DELETEs queue on any failure; a line create still queues only when offline (a failure while online
 * is rolled back and said, as before).
 */
export function useShoppingActions() {
  const qc = useQueryClient()
  const shared = { invalidates: PANTRY_INVALIDATES }
  type NewTick = { item: ShoppingItem; id: string }
  const tick = useAction<NewTick, TickOut>({
    ...shared,
    method: 'POST',
    path: '/api/v1/stock/shopping/ticks',
    body: ({ item, id }: NewTick): TickIn => ({ id, stock_item_id: item.id }),
    optimistic: (qc, { item, id }: NewTick) => setTicked(item.id, id)(qc),
    pendingId: ({ item }: NewTick) => item.id,
  })
  const untick = useAction<ShoppingItem, null>({
    ...shared,
    method: 'DELETE',
    path: (i: ShoppingItem) => `/api/v1/stock/shopping/ticks/${i.tick_id}`,
    optimistic: (qc, i) => setTicked(i.id, null)(qc),
    pendingId: (i: ShoppingItem) => i.id,
  })
  const addLine = useAction<NewLine, ShoppingLine>({
    ...shared,
    method: 'POST',
    path: '/api/v1/stock/shopping/lines',
    body: ({ id, name, quantity }: NewLine): LineIn => (quantity == null ? { id, name } : { id, name, quantity }),
    queue: 'offline-only',
    optimistic: (qc, l) =>
      patchList(qc, (s) => ({ ...s, lines: [...s.lines, { id: l.id, name: l.name, quantity: l.quantity ?? null, checked: false }] })),
    pendingId: (l: NewLine) => l.id,
  })
  const checkLine = useAction<{ line: ShoppingLine; checked: boolean }, ShoppingLine>({
    ...shared,
    method: 'PATCH',
    path: ({ line }: { line: ShoppingLine }) => `/api/v1/stock/shopping/lines/${line.id}`,
    body: ({ checked }: { checked: boolean }) => ({ checked }),
    optimistic: (qc, { line, checked }) =>
      patchList(qc, (s) => ({
        ...s,
        lines: s.lines.map((l) => (l.id === line.id ? { ...l, checked } : l)),
        ticked_count: line.checked === checked ? s.ticked_count : Math.max(0, s.ticked_count + (checked ? 1 : -1)),
      })),
    pendingId: ({ line }: { line: ShoppingLine }) => line.id,
  })
  const deleteLine = useAction<ShoppingLine, null>({
    ...shared,
    method: 'DELETE',
    path: (l: ShoppingLine) => `/api/v1/stock/shopping/lines/${l.id}`,
    optimistic: (qc, line) =>
      patchList(qc, (s) => ({
        ...s,
        lines: s.lines.filter((l) => l.id !== line.id),
        ticked_count: line.checked ? Math.max(0, s.ticked_count - 1) : s.ticked_count,
      })),
  })
  return {
    toggle: async (i: ShoppingItem) => {
      if (i.ticked) return untick.run(i)
      const id = newRowId()
      const r = await tick.run({ item: i, id })
      // The item was already ticked (another phone): the server answers with that tick. Adopt its id, so an
      // untick deletes the real tick even if the refetch fails.
      if (r.status === 'done' && r.data?.id && r.data.id !== id) {
        const adopted = r.data.id
        patchList(qc, (s) => ({ ...s, items: s.items.map((x) => (x.tick_id === id ? { ...x, tick_id: adopted } : x)) }))
      }
      return r
    },
    addLine: addLine.run,
    checkLine: (line: ShoppingLine, checked: boolean) => checkLine.run({ line, checked }),
    deleteLine: deleteLine.run,
  }
}
