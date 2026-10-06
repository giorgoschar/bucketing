import { readCsrf } from '../api/client'
import { keyGeneration, open, seal } from './crypto'
import { db } from './db'

type Method = 'POST' | 'PUT' | 'PATCH' | 'DELETE'
interface Req { method: Method; path: string; body?: unknown }
interface Result { sent: number; failed: number; stoppedOnAuth: boolean }

const MAX_BACKOFF_MS = 5 * 60_000
const MAX_ERROR_CHARS = 200
const LOCK_NAME = 'tameio-queue'
let running: Promise<Result> | null = null

export async function enqueue(req: Req): Promise<number> {
  const gen = keyGeneration()
  const sealed = await seal(req)
  const now = Date.now()
  // A wipe since we started means this ciphertext's key is gone; do not resurrect data.
  return db.transaction('rw', db.queue, async () => {
    if (gen !== keyGeneration()) throw new Error('Store was wiped while queueing')
    return db.queue.add({ ...sealed, createdAt: now, attempts: 0, nextAttemptAt: now, status: 'pending' })
  })
}

/** Single-flight in this tab; across tabs a Web Lock keeps two drains from double-sending. */
export function replay(): Promise<Result> {
  running ??= withLock(drain).finally(() => { running = null })
  return running
}

function withLock(fn: () => Promise<Result>): Promise<Result> {
  const locks = globalThis.navigator?.locks
  // No Web Locks: fall back to the in-tab single-flight above.
  return locks ? locks.request(LOCK_NAME, fn) : fn()
}

const backoff = (attempts: number) => Math.min(MAX_BACKOFF_MS, 2 ** attempts * 1000)

async function drain(): Promise<Result> {
  let sent = 0, failed = 0
  const gen = keyGeneration()
  try {
    // Read inside the lock so a drain that waited sees what the other tab already sent.
    const rows = await db.queue.where('status').equals('pending').sortBy('id')
    for (const row of rows) {
      if (gen !== keyGeneration()) break
      if (row.nextAttemptAt > Date.now()) continue
      let req: Req
      try {
        req = await open<Req>(row)
      } catch {
        if (gen !== keyGeneration()) break // wiped: stop quietly
        await db.queue.update(row.id!, { status: 'failed', error: 'Could not decrypt this item' })
        failed++
        continue
      }
      let res: Response
      try {
        res = await fetch(req.path, {
          method: req.method,
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': readCsrf() },
          body: req.body === undefined ? undefined : JSON.stringify(req.body),
        })
      } catch {
        await db.queue.update(row.id!, { attempts: row.attempts + 1, nextAttemptAt: Date.now() + backoff(row.attempts + 1) })
        break // offline: stop, keep order
      }
      if (res.status === 401) return { sent, failed, stoppedOnAuth: true }
      // 409 = the transaction was deleted since; dropped for now (Phase 2 surfaces it).
      if (res.ok || res.status === 409) {
        await db.queue.delete(row.id!)
        sent++
        continue
      }
      if (res.status >= 500) {
        await db.queue.update(row.id!, { attempts: row.attempts + 1, nextAttemptAt: Date.now() + backoff(row.attempts + 1) })
        break
      }
      const detail = await res.json().then((j) => (typeof j?.detail === 'string' ? j.detail : ''), () => '')
      await db.queue.update(row.id!, {
        status: 'failed',
        error: (detail || `HTTP ${res.status}`).slice(0, MAX_ERROR_CHARS),
      })
      failed++
    }
  } catch (e) {
    // A wipe mid-drain (sign-out) surfaces as a rejection from IndexedDB/crypto: stop quietly.
    if (gen === keyGeneration()) throw e
  }
  return { sent, failed, stoppedOnAuth: false }
}

export function startReplayTriggers(): () => void {
  const run = () => void replay().catch(() => {})
  const vis = () => { if (document.visibilityState === 'visible') run() }
  window.addEventListener('online', run)
  document.addEventListener('visibilitychange', vis)
  run()
  return () => {
    window.removeEventListener('online', run)
    document.removeEventListener('visibilitychange', vis)
  }
}
