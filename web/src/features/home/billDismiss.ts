import { useSyncExternalStore } from 'react'

/**
 * Dismissed bill-change rows (spec §5.5): the entry ids the user closed with the ✕, kept in localStorage on
 * this device only. A row is tied to the entry that caused it, so a newer entry brings it back. Storage can
 * throw (private window, blocked site data): then the dismissals last for the session and nothing breaks.
 */
const KEY = 'tameio.billDismissed'
const KEEP = 100

let ids: string[] | null = null
const listeners = new Set<() => void>()
let snapshot: ReadonlySet<string> = new Set()

function load(): string[] {
  if (ids) return ids
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]')
    ids = Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : []
  } catch {
    ids = []
  }
  snapshot = new Set(ids)
  return ids
}

export function dismissedBills(): ReadonlySet<string> {
  load()
  return snapshot
}

export function dismissBill(entryId: string): void {
  const next = [...load().filter((x) => x !== entryId), entryId].slice(-KEEP)
  ids = next
  snapshot = new Set(next)
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Kept in memory for this session.
  }
  listeners.forEach((l) => l())
}

/** Forget the in-memory copy (tests; and a re-read after storage changed under us). */
export function resetBillDismissals(): void {
  ids = null
  snapshot = new Set()
  listeners.forEach((l) => l())
}

export function useDismissedBills(): ReadonlySet<string> {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => { listeners.delete(cb) } },
    dismissedBills,
    dismissedBills,
  )
}
