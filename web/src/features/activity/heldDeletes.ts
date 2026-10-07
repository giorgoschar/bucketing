/** Swipe delete is held locally for 5 s (spec §4.3; there is no restore
 * endpoint). The DELETE goes when the hold ends, or at once when the page
 * is hidden; Undo cancels it. Module-level so it survives navigation. */
import { useSyncExternalStore } from 'react'

export const HOLD_MS = 5000

type Held = { timer: ReturnType<typeof setTimeout>; send: () => void }
const held = new Map<string, Held>()
const listeners = new Set<() => void>()
let snapshot: ReadonlySet<string> = new Set()
let installed = false

function emit() {
  snapshot = new Set(held.keys())
  listeners.forEach((l) => l())
}

function installFlushOnHide() {
  if (installed) return
  installed = true
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushAll()
  })
  window.addEventListener('pagehide', flushAll)
}

export function holdDelete(id: string, send: () => void, ms = HOLD_MS) {
  const prev = held.get(id)
  if (prev) clearTimeout(prev.timer)
  held.set(id, { timer: setTimeout(() => flush(id), ms), send })
  installFlushOnHide()
  emit()
}

export function undoDelete(id: string): boolean {
  const h = held.get(id)
  if (!h) return false
  clearTimeout(h.timer)
  held.delete(id)
  emit()
  return true
}

export function flush(id: string) {
  const h = held.get(id)
  if (!h) return
  clearTimeout(h.timer)
  held.delete(id)
  emit()
  h.send()
}

export function flushAll() {
  for (const id of [...held.keys()]) flush(id)
}

const subscribe = (cb: () => void) => {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

export function useHeldDeletes(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, () => snapshot, () => snapshot)
}

export function _resetHeldForTests() {
  held.forEach((h) => clearTimeout(h.timer))
  held.clear()
  emit()
}
