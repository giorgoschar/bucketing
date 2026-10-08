/**
 * Drain listeners for the offline queue. Kept apart from queue.ts so modules that only listen
 * (data/queueBridge) don't pull in, or depend on mocks of, the replay machinery.
 */
export interface ReplayResult { sent: number; failed: number; stoppedOnAuth: boolean }

const drainListeners = new Set<(r: ReplayResult) => void>()

/** Called after every replay that sent or failed at least one row (2a: invalidate, clear pending markers). */
export function onQueueDrained(cb: (r: ReplayResult) => void): () => void {
  drainListeners.add(cb)
  return () => { drainListeners.delete(cb) }
}

/** queue.ts calls this once per replay; listeners never see a replay that did nothing. */
export function notifyDrained(r: ReplayResult): void {
  if (r.sent === 0 && r.failed === 0) return
  for (const cb of drainListeners) {
    try { cb(r) } catch { /* a listener must never break the drain */ }
  }
}
