import { beforeEach, expect, it } from 'vitest'
import { cacheEntry, cachePut, db, wipe } from './db'

beforeEach(() => wipe())

it('cacheEntry returns the value with its updatedAt, and undefined when missing', async () => {
  const before = Date.now()
  await cachePut('k', { a: 1 })
  const row = await cacheEntry<{ a: number }>('k')
  expect(row?.value).toEqual({ a: 1 })
  expect(row!.updatedAt).toBeGreaterThanOrEqual(before)
  expect(await cacheEntry('missing')).toBeUndefined()
})

it('the first cachePut of a session evicts rows older than 60 days', async () => {
  const day = 24 * 60 * 60 * 1000
  const sealed = { iv: new Uint8Array(12), data: new ArrayBuffer(8) }
  await db.cache.put({ key: 'old', ...sealed, updatedAt: Date.now() - 61 * day })
  await db.cache.put({ key: 'recent', ...sealed, updatedAt: Date.now() - 59 * day })
  await cachePut('k', 1)
  expect(await db.cache.toCollection().primaryKeys()).toEqual(['k', 'recent'])
  // Once per session: a later old row stays until the next session (wipe starts one).
  await db.cache.put({ key: 'old2', ...sealed, updatedAt: Date.now() - 61 * day })
  await cachePut('k2', 2)
  expect(await db.cache.get('old2')).toBeDefined()
})
