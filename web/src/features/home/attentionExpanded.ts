import { useSyncExternalStore } from 'react'

/** Whether Needs attention shows every row (spec §2.1): lasts for the session, never stored. */
let expanded = false
const listeners = new Set<() => void>()

export function setAttentionExpanded(next: boolean): void {
  expanded = next
  listeners.forEach((l) => l())
}

export const useAttentionExpanded = (): boolean =>
  useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => { listeners.delete(cb) } },
    () => expanded,
    () => expanded,
  )
