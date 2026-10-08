import Dexie, { type Table } from 'dexie'
import { clearPending } from '../data/pending'
import { cancelKick } from './kickTimer'

// NOTE: cache keys and queue `error` are stored in plaintext; never put sensitive values in them.
export interface Sealed { iv: Uint8Array<ArrayBuffer>; data: ArrayBuffer }
export interface KeyRow { id: 'device'; key: CryptoKey }
export interface CacheRow extends Sealed { key: string; updatedAt: number }
export interface QueueRow extends Sealed {
  id?: number
  createdAt: number
  attempts: number
  nextAttemptAt: number
  status: 'pending' | 'failed'
  error?: string
}

class LocalDB extends Dexie {
  keys!: Table<KeyRow, string>
  cache!: Table<CacheRow, string>
  queue!: Table<QueueRow, number>
  constructor() {
    super('tameio')
    this.version(1).stores({ keys: 'id', cache: 'key', queue: '++id, status, nextAttemptAt' })
  }
}

export const db = new LocalDB()

const EVICT_AFTER_MS = 60 * 24 * 60 * 60 * 1000
let evictedThisSession = false

export async function wipe(): Promise<void> {
  cancelKick() // a replay scheduled for the old session must not run after sign-out
  const { forgetKey } = await import('./crypto')
  forgetKey()
  clearPending() // the queued rows go with the store, so their "Waiting to sync" markers must too
  evictedThisSession = false // a new session starts with the next sign-in
  await db.transaction('rw', db.keys, db.cache, db.queue, async () => {
    await Promise.all([db.keys.clear(), db.cache.clear(), db.queue.clear()])
  })
}

/** Drop cached rows nobody has refreshed for 60 days (old months, old searches). Once per session. */
async function evictOld(): Promise<void> {
  if (evictedThisSession) return
  evictedThisSession = true
  const cutoff = Date.now() - EVICT_AFTER_MS
  await db.cache.filter((row) => row.updatedAt < cutoff).delete().catch(() => {})
}

/**
 * Seal and store `value`. `generation` is the key generation the caller's work started under (default:
 * now); a wipe since then drops the write, so data fetched for a signed-out session never lands.
 */
export async function cachePut(key: string, value: unknown, generation?: number): Promise<void> {
  const { seal, keyGeneration } = await import('./crypto')
  const gen = generation ?? keyGeneration()
  const sealed = await seal(value)
  await db.transaction('rw', db.cache, async () => {
    // A wipe since we started means this ciphertext's key is gone; do not resurrect data.
    if (gen !== keyGeneration()) throw new Error('Store was wiped while writing')
    await db.cache.put({ key, ...sealed, updatedAt: Date.now() })
  })
  await evictOld()
}

export async function cacheGet<T>(key: string): Promise<T | undefined> {
  const row = await db.cache.get(key)
  if (!row) return undefined
  const { open } = await import('./crypto')
  return open<T>(row)
}

/** Like cacheGet, plus when the value was stored (the "updated HH:MM" of the offline banner). */
export async function cacheEntry<T>(key: string): Promise<{ value: T; updatedAt: number } | undefined> {
  const row = await db.cache.get(key)
  if (!row) return undefined
  const { open } = await import('./crypto')
  return { value: await open<T>(row), updatedAt: row.updatedAt }
}
