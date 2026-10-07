import { useSyncExternalStore } from 'react'

/**
 * Ids of rows whose change is waiting in the offline queue (spec §3.2: the "queued" marker).
 * In memory only: the queue bridge clears it when nothing is pending any more.
 */
let ids: ReadonlySet<string> = new Set()
const subs = new Set<() => void>()
const emit = () => subs.forEach((cb) => cb())
const subscribe = (cb: () => void) => {
  subs.add(cb)
  return () => { subs.delete(cb) }
}

export function markPending(id: string): void {
  if (ids.has(id)) return
  ids = new Set([...ids, id])
  emit()
}

export function clearPending(): void {
  if (ids.size === 0) return
  ids = new Set()
  emit()
}

export const isPending = (id: string): boolean => ids.has(id)

export function usePendingIds(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, () => ids, () => ids)
}
