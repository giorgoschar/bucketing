import { type QueryClient, type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '../../../api/client'
import { useAction } from '../../../data/action'
import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import { keys } from '../../../data/keys'
import { type OnlineOutcome, runOnline } from '../../../data/onlineAction'
import type { RawResult } from '../../../data/rawJson'
import { useToast } from '../../../ui/Toast'
import type {
  AppliedOut, ApplyTickedOut, LineIn, ShoppingItem, ShoppingLine, ShoppingOut, StockSummary, TickOut,
} from './shoppingTypes'

/**
 * What every pantry write makes stale (pantry spec §4.8): every pantry read (the list, the item, the
 * shopping list and the summary all sit under ['stock']) and Home's attention rows.
 */
export const PANTRY_INVALIDATES: readonly QueryKey[] = [['stock'], keys.home.all]

/** Shown on an online-only pantry control while offline (spec §4.8). */
export const PANTRY_OFFLINE = 'Connect to change the pantry'

// The new stock routes are not in the generated schema until the pantry integration runs gen:api. They go
// through the typed client untyped (like data/action.ts does), so the CSRF header and 401 handling still apply.
const get = <T,>(path: string, signal: AbortSignal) =>
  unwrap(api.GET(path as never, { signal } as never) as unknown as Promise<RawResult<T>>)

export const fetchShopping = (signal: AbortSignal) => get<ShoppingOut>('/api/v1/stock/shopping', signal)
export const fetchStockSummary = (signal: AbortSignal) => get<StockSummary>('/api/v1/stock/summary', signal)

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
    const out = await runOnline(() =>
      api.POST('/api/v1/stock/shopping/apply-ticked' as never, { body: {} } as never) as unknown as Promise<RawResult<ApplyTickedOut>>)
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

const setTicked = (id: string, ticked: boolean) => (qc: QueryClient) =>
  patchList(qc, (s) => {
    const was = s.items.find((i) => i.id === id)?.ticked
    if (was === undefined || was === ticked) return s
    return {
      ...s,
      items: s.items.map((i) => (i.id === id ? { ...i, ticked, tick_id: null } : i)),
      ticked_count: Math.max(0, s.ticked_count + (ticked ? 1 : -1)),
    }
  })

export interface NewLine extends LineIn { tempId: string }

/**
 * Ticks and one-off lines (spec §4.5, §4.8): optimistic and queued offline, because people shop with poor
 * signal. A tick is idempotent on the server and the PATCH/DELETEs are too, so they queue on any failure; a
 * line create is not, so it queues only when offline (a failure while online could already have added it).
 */
export function useShoppingActions() {
  const shared = { invalidates: PANTRY_INVALIDATES }
  const tick = useAction<ShoppingItem, TickOut>({
    ...shared,
    method: 'POST',
    path: '/api/v1/stock/shopping/ticks',
    body: (i: ShoppingItem) => ({ stock_item_id: i.id }),
    optimistic: (qc, i) => setTicked(i.id, true)(qc),
    pendingId: (i: ShoppingItem) => i.id,
  })
  const untick = useAction<ShoppingItem, null>({
    ...shared,
    method: 'DELETE',
    path: (i: ShoppingItem) => `/api/v1/stock/shopping/ticks/${i.tick_id}`,
    optimistic: (qc, i) => setTicked(i.id, false)(qc),
    pendingId: (i: ShoppingItem) => i.id,
  })
  const addLine = useAction<NewLine, ShoppingLine>({
    ...shared,
    method: 'POST',
    path: '/api/v1/stock/shopping/lines',
    body: ({ name, quantity }: NewLine) => (quantity == null ? { name } : { name, quantity }),
    queue: 'offline-only',
    optimistic: (qc, l) =>
      patchList(qc, (s) => ({ ...s, lines: [...s.lines, { id: l.tempId, name: l.name, quantity: l.quantity ?? null, checked: false }] })),
    pendingId: (l: NewLine) => l.tempId,
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
    toggle: (i: ShoppingItem) => (i.ticked ? untick.run(i) : tick.run(i)),
    addLine: addLine.run,
    checkLine: (line: ShoppingLine, checked: boolean) => checkLine.run({ line, checked }),
    deleteLine: deleteLine.run,
  }
}
