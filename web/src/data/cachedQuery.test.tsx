import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { api } from '../api/client'
import { cacheEntry, cachePut, db } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { fakeApi, hang, reply } from '../test/fakeApi'
import { day, entry } from '../test/fixtures'
import { Providers, resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../test/render'
import { cacheKeyFor, useCachedQuery } from './cachedQuery'
import { unwrap } from './http'
import { keys } from './keys'

const KEY = keys.plan.upcoming(30)
const fetchUpcoming = (signal: AbortSignal) =>
  unwrap(api.GET('/api/v1/plan/upcoming', { params: { query: { days: 30 } }, signal }))
const cached = [day('2026-10-09', [entry()], 1200)]
const fresh = [day('2026-10-09', [entry({ amount: 40 })], 1198.9)]

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

const mount = () =>
  renderHook(() => useCachedQuery(KEY, fetchUpcoming), {
    wrapper: ({ children }) => <Providers client={testQueryClient()}>{children}</Providers>,
  })

it('seeds from the device cache before the network answers', async () => {
  await cachePut(await cacheKeyFor('h1', KEY), cached)
  const stored = await cacheEntry(await cacheKeyFor('h1', KEY))
  fakeApi({ 'GET /api/v1/plan/upcoming': () => hang() })
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(cached))
  expect(result.current.fromCache).toBe(true)
  expect(result.current.dataUpdatedAt).toBe(stored!.updatedAt)
  expect(result.current.stale).toBe(false)
})

it('writes a successful fetch to the cache under this household only', async () => {
  fakeApi({ 'GET /api/v1/plan/upcoming': () => fresh })
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(fresh))
  expect(result.current.fromCache).toBe(false)
  await waitFor(async () => expect((await cacheEntry(await cacheKeyFor('h1', KEY)))?.value).toEqual(fresh))
  expect(await cacheEntry(await cacheKeyFor('h2', KEY))).toBeUndefined()
})

it('a fresh answer wins over the older device copy, whichever arrives first', async () => {
  await cachePut(await cacheKeyFor('h1', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => fresh })
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(fresh))
  await new Promise((r) => setTimeout(r, 30))
  expect(result.current.data).toEqual(fresh)
})

it('offline with a cache: shows it and flags the stale banner', async () => {
  await cachePut(await cacheKeyFor('h1', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => fresh }).down()
  setOnline(false)
  const { result } = mount()
  await waitFor(() => expect(result.current.data).toEqual(cached))
  expect(result.current).toMatchObject({ offline: true, stale: true, noData: false })
})

it('offline without a cache: noData once the cache was checked, never before', async () => {
  fakeApi({}).down()
  setOnline(false)
  const { result } = mount()
  expect(result.current.noData).toBe(false)
  await waitFor(() => expect(result.current.noData).toBe(true))
  expect(result.current.isLoading).toBe(false)
})

it('online but the refetch failed: keeps the cached data and flags stale', async () => {
  await cachePut(await cacheKeyFor('h1', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => reply(503, { detail: 'down' }) })
  const { result } = mount()
  await waitFor(() => expect(result.current.stale).toBe(true))
  expect(result.current.data).toEqual(cached)
})

it("never reads another household's copy", async () => {
  await cachePut(await cacheKeyFor('h2', KEY), cached)
  fakeApi({ 'GET /api/v1/plan/upcoming': () => hang() })
  const { result } = mount()
  await new Promise((r) => setTimeout(r, 50))
  expect(result.current.data).toBeUndefined()
  expect(result.current.isLoading).toBe(true)
})

it('the device cache key is a digest: no query-key text (search terms) is stored in plain text', async () => {
  const key = ['transactions', 'search', 'cosmote'] as const
  const { result } = renderHook(() => useCachedQuery(key, async () => ['row']), {
    wrapper: ({ children }) => <Providers client={testQueryClient()}>{children}</Providers>,
  })
  await waitFor(() => expect(result.current.data).toEqual(['row']))
  await waitFor(async () => expect(await db.cache.count()).toBe(1))
  const stored = (await db.cache.toCollection().primaryKeys()).map(String)
  expect(stored[0]).toMatch(/^q:h1:[0-9a-f]{64}$/)
  expect(stored.join(' ')).not.toMatch(/cosmote|search|transactions/i)
  expect(stored[0]).toBe(await cacheKeyFor('h1', key))
})
