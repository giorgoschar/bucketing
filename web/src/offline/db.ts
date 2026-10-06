import Dexie, { type Table } from 'dexie'

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

export async function wipe(): Promise<void> {
  const { forgetKey } = await import('./crypto')
  forgetKey()
  await db.transaction('rw', db.keys, db.cache, db.queue, async () => {
    await Promise.all([db.keys.clear(), db.cache.clear(), db.queue.clear()])
  })
}

export async function cachePut(key: string, value: unknown): Promise<void> {
  const { seal } = await import('./crypto')
  await db.cache.put({ key, ...(await seal(value)), updatedAt: Date.now() })
}

export async function cacheGet<T>(key: string): Promise<T | undefined> {
  const row = await db.cache.get(key)
  if (!row) return undefined
  const { open } = await import('./crypto')
  return open<T>(row)
}
