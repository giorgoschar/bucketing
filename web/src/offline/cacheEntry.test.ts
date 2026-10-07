import { beforeEach, expect, it } from 'vitest'
import { cacheEntry, cachePut, wipe } from './db'

beforeEach(() => wipe())

it('cacheEntry returns the value with its updatedAt, and undefined when missing', async () => {
  const before = Date.now()
  await cachePut('k', { a: 1 })
  const row = await cacheEntry<{ a: number }>('k')
  expect(row?.value).toEqual({ a: 1 })
  expect(row!.updatedAt).toBeGreaterThanOrEqual(before)
  expect(await cacheEntry('missing')).toBeUndefined()
})
