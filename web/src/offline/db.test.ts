import { beforeEach, expect, it } from 'vitest'
import { cacheGet, cachePut, db, wipe } from './db'

beforeEach(() => wipe())

it('cache round-trips through encryption', async () => {
  await cachePut('dashboard', { total: 893.79 })
  expect(await cacheGet('dashboard')).toEqual({ total: 893.79 })
  const raw = await db.cache.get('dashboard')
  expect(raw && 'data' in raw && !('total' in raw)).toBe(true)
})

it('wipe empties every table', async () => {
  await cachePut('a', 1)
  await wipe()
  expect(await db.cache.count()).toBe(0)
  expect(await db.keys.count()).toBe(0)
})
