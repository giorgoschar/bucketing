/** Swipe delete is held locally for 5 s (spec §4.3; there is no restore
 * endpoint). The DELETE goes when the hold ends, or at once when the page
 * is hidden; Undo cancels it. Module-level so it survives navigation. */
import { useSyncExternalStore } from 'react'

export const HOLD_MS = 5000

/** Why the hold ended: its 5 s ran out, or the page was hidden (backgrounded, closed) first. */
export type FlushReason = 'timer' | 'hidden'
type Send = (reason: FlushReason) => void
type Held = {
  timer: ReturnType<typeof setTimeout>
  send: Send
  /** While this says so (its Undo toast is still on screen), the hold outlasts its time. */
  keep?: () => boolean
  /** The time ran out while kept: send as soon as `settle` is called. */
  due?: boolean
}
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
    if (document.visibilityState === 'hidden') flushAll('hidden')
  })
  window.addEventListener('pagehide', () => flushAll('hidden'))
}

export function holdDelete(id: string, send: Send, ms = HOLD_MS, keep?: () => boolean) {
  const prev = held.get(id)
  if (prev) clearTimeout(prev.timer)
  held.set(id, { timer: setTimeout(() => expire(id), ms), send, keep })
  installFlushOnHide()
  emit()
}

/** The hold's time is up: send, unless its Undo is still on screen (a paused toast); then wait for `settle`. */
function expire(id: string) {
  const h = held.get(id)
  if (!h) return
  if (h.keep?.()) h.due = true
  else flush(id)
}

/** The Undo toast is gone: send a hold whose time already ran out (P3 M5: Undo works until the toast goes). */
export function settle(id: string) {
  if (held.get(id)?.due) flush(id)
}

export function undoDelete(id: string): boolean {
  const h = held.get(id)
  if (!h) return false
  clearTimeout(h.timer)
  held.delete(id)
  emit()
  return true
}

export function flush(id: string, reason: FlushReason = 'timer') {
  const h = held.get(id)
  if (!h) return
  clearTimeout(h.timer)
  held.delete(id)
  emit()
  h.send(reason)
}

export function flushAll(reason: FlushReason = 'timer') {
  for (const id of [...held.keys()]) flush(id, reason)
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
