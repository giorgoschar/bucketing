import { readCsrf } from '../api/client'
import { keyGeneration, open, seal } from './crypto'
import { db, type QueueRow } from './db'
import { getIdentity, type Identity } from './identity'

type Method = 'POST' | 'PUT' | 'PATCH' | 'DELETE'
interface Req { method: Method; path: string; body?: unknown }
/** What is sealed into a row: the request plus who queued it, so another account never replays it. */
interface Stored extends Req { owner: Identity }
interface Result { sent: number; failed: number; stoppedOnAuth: boolean }

const MAX_BACKOFF_MS = 5 * 60_000
const MAX_ERROR_CHARS = 200
const ME_TIMEOUT_MS = 10_000
const LOCK_NAME = 'tameio-queue'
const CSRF_DETAIL = 'CSRF token missing or invalid'
let running: Promise<Result> | null = null
let rerunForced = false

export async function enqueue(req: Req): Promise<number> {
  const owner = getIdentity()
  if (!owner) throw new Error('Not signed in')
  const gen = keyGeneration()
  const stored: Stored = { ...req, owner }
  const sealed = await seal(stored)
  const now = Date.now()
  // A wipe since we started means this ciphertext's key is gone; do not resurrect data.
  return db.transaction('rw', db.queue, async () => {
    if (gen !== keyGeneration()) throw new Error('Store was wiped while queueing')
    return db.queue.add({ ...sealed, createdAt: now, attempts: 0, nextAttemptAt: now, status: 'pending' })
  })
}

/**
 * Single-flight in this tab; across tabs a Web Lock keeps two drains from double-sending.
 * `force` ignores the head row's backoff (the browser just told us we are back online).
 */
export function replay(opts: { force?: boolean } = {}): Promise<Result> {
  if (running) {
    // Don't lose a forced request that arrives mid-drain: run one forced drain right after.
    if (opts.force) rerunForced = true
    return running
  }
  running = (async () => {
    try {
      let r = await withLock(() => drain(!!opts.force))
      while (rerunForced && !r.stoppedOnAuth) {
        rerunForced = false
        const next = await withLock(() => drain(true))
        r = { sent: r.sent + next.sent, failed: r.failed + next.failed, stoppedOnAuth: next.stoppedOnAuth }
      }
      return r
    } finally {
      rerunForced = false
      running = null
    }
  })()
  return running
}

function withLock(fn: () => Promise<Result>): Promise<Result> {
  const locks = globalThis.navigator?.locks
  // No Web Locks: fall back to the in-tab single-flight above.
  return locks ? locks.request(LOCK_NAME, fn) : fn()
}

/**
 * Update a row without Dexie's read-modify-write (`update`), whose deep clone can degrade the
 * ArrayBuffer and make the ciphertext undecryptable. Skips rows a wipe has already removed.
 */
const patch = (row: QueueRow, fields: Partial<QueueRow>) =>
  db.transaction('rw', db.queue, async () => {
    if (await db.queue.where(':id').equals(row.id!).count()) await db.queue.put({ ...row, ...fields })
  })

const backoff = (attempts: number) => Math.min(MAX_BACKOFF_MS, 2 ** attempts * 1000)

type Who = { status: 'ok'; id: string; household: string } | { status: 'auth' } | { status: 'offline' }

/** Raw fetch on purpose: a 401 here must not go through the client's session-expiry handling. */
async function whoAmI(): Promise<Who> {
  try {
    const res = await fetch('/api/v1/auth/me', {
      credentials: 'same-origin',
      signal: AbortSignal.timeout(ME_TIMEOUT_MS),
    })
    if (res.status === 401) return { status: 'auth' }
    if (!res.ok) return { status: 'offline' }
    const me = await res.json()
    return { status: 'ok', id: String(me.id), household: String(me.household_id) }
  } catch {
    return { status: 'offline' }
  }
}

async function drain(force: boolean): Promise<Result> {
  let sent = 0, failed = 0
  const gen = keyGeneration()
  try {
    // Read inside the lock so a drain that waited sees what the other tab already sent.
    const rows = await db.queue.where('status').equals('pending').sortBy('id')
    // A backed-off head blocks everything behind it: later writes must not overtake it.
    if (!rows.length || (!force && rows[0].nextAttemptAt > Date.now())) return { sent, failed, stoppedOnAuth: false }
    const who = await whoAmI()
    if (who.status === 'auth') return { sent, failed, stoppedOnAuth: true }
    if (who.status === 'offline') {
      // Server down or slow while we think we're online: back the head off so a timer retries it.
      await patch(rows[0], { attempts: rows[0].attempts + 1, nextAttemptAt: Date.now() + backoff(rows[0].attempts + 1) })
      return { sent, failed, stoppedOnAuth: false }
    }
    for (const [i, row] of rows.entries()) {
      if (gen !== keyGeneration()) break
      if (!(force && i === 0) && row.nextAttemptAt > Date.now()) break
      let req: Stored
      try {
        req = await open<Stored>(row)
      } catch {
        if (gen !== keyGeneration()) break // wiped: stop quietly
        await patch(row, { status: 'failed', error: 'Could not decrypt this item' })
        failed++
        continue
      }
      if (req.owner?.user_id !== who.id || req.owner?.household_id !== who.household) {
        // Another account's offline payloads must never stay readable here: drop, don't keep.
        await db.queue.delete(row.id!)
        failed++
        continue
      }
      if (gen !== keyGeneration()) break // wiped or switched while decrypting: don't send
      const retryLater = () =>
        patch(row, { attempts: row.attempts + 1, nextAttemptAt: Date.now() + backoff(row.attempts + 1) })
      let res: Response
      try {
        res = await fetch(req.path, {
          method: req.method,
          credentials: 'same-origin',
          headers: {
            ...(req.body === undefined ? {} : { 'Content-Type': 'application/json' }),
            'X-CSRF-Token': readCsrf(),
            // The server refuses the write if the shared session cookie has flipped to someone else.
            'X-Expected-Account': `${req.owner.user_id}:${req.owner.household_id}`,
          },
          body: req.body === undefined ? undefined : JSON.stringify(req.body),
        })
      } catch {
        await retryLater()
        break // offline: stop, keep order
      }
      if (res.status === 401) return { sent, failed, stoppedOnAuth: true }
      if (res.status === 412) {
        // The session belongs to a different account than the row's owner: drop the row, check the next.
        await db.queue.delete(row.id!)
        failed++
        continue
      }
      // 409 = the transaction was deleted since; dropped for now (Phase 2 surfaces it).
      if (res.ok || res.status === 409) {
        await db.queue.delete(row.id!)
        sent++
        continue
      }
      if (res.status >= 500 || res.status === 429) {
        await retryLater()
        break
      }
      const detail = await res.json().then((j) => (typeof j?.detail === 'string' ? j.detail : ''), () => '')
      if (res.status === 403 && detail === CSRF_DETAIL) {
        await retryLater() // a stale token is ours to refresh, not the item's fault
        break
      }
      await patch(row, {
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
  let timer: ReturnType<typeof setTimeout> | undefined
  let stopped = false

  // After a backoff, wake up exactly when the head row is due (no Background Sync on iOS).
  const arm = async () => {
    try {
      const head = (await db.queue.where('status').equals('pending').sortBy('id'))[0]
      if (stopped || !head || head.nextAttemptAt <= Date.now()) return
      clearTimeout(timer)
      timer = setTimeout(() => run(false), head.nextAttemptAt - Date.now() + 50)
    } catch {
      // storage unavailable or wiped: the next trigger will try again
    }
  }
  const run = (force: boolean) => {
    clearTimeout(timer)
    void replay({ force })
      .then((r) => { if (!r.stoppedOnAuth) return arm() })
      .catch(() => {})
  }
  const online = () => run(true)
  const vis = () => { if (document.visibilityState === 'visible') run(false) }
  window.addEventListener('online', online)
  document.addEventListener('visibilitychange', vis)
  run(false)
  return () => {
    stopped = true
    clearTimeout(timer)
    window.removeEventListener('online', online)
    document.removeEventListener('visibilitychange', vis)
  }
}
