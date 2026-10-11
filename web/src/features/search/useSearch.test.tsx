import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi, reply, type Routes } from '../../test/fakeApi'
import { resetTestEnv, setOnline, testQueryClient } from '../../test/render'
import { setIdentity } from '../../offline/identity'
import { TEST_IDENTITY } from '../../test/render'
import { listMonth, statementList } from '../insights/statements/fixtures'
import type { SearchResponse } from './types'
import { useSearch } from './useSearch'

afterEach(resetTestEnv)

const body = (over: Partial<SearchResponse> = {}): SearchResponse => ({ entries: [], entries_more: false, items: [], pantry: [], ...over })
const lidl = body({
  entries: [{ id: 'e1', date: '2026-10-07', label: 'Lidl', category: 'Groceries', amount: -29.9, currency: 'EUR' }],
  items: [{ id: 'b1', name: 'Lidl plus', direction: 'out', is_active: true }],
  pantry: [{ id: 'p1', name: 'Barilla spaghetti', brand: 'Barilla', quantity: 3 }],
})
// GET /api/v1/search is not in the generated schema until integration regenerates it: the one cast.
const routes = (search: (q: string) => unknown | Promise<unknown>): Routes => ({
  'GET /api/v1/insights/statements': () => statementList({ months: [listMonth(), listMonth({ month: '2026-08', label: 'August 2026' })] }),
  'GET /api/v1/search': (req: { query: URLSearchParams }) => search(req.query.get('q') ?? ''),
} as unknown as Routes)

function setup(initial: string) {
  setIdentity(TEST_IDENTITY)
  const client = testQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return renderHook(({ q }) => useSearch(q), { wrapper, initialProps: { q: initial } })
}
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))

it('waits 200 ms after typing, then sends one request', async () => {
  const api = fakeApi(routes(() => lidl))
  const { rerender } = setup('')
  rerender({ q: 'li' }); await act(() => wait(80))
  rerender({ q: 'lid' }); await act(() => wait(80))
  rerender({ q: 'lidl' })
  await act(() => wait(120))
  expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(0)
  await waitFor(() => expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(1))
  expect(api.callsTo('GET /api/v1/search' as never)[0].query.get('q')).toBe('lidl')
})

it('needs 2 characters, after trimming', async () => {
  const api = fakeApi(routes(() => lidl))
  const { result } = setup(' l ')
  await act(() => wait(300))
  expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(0)
  expect(result.current.active).toBe(false)
  expect(result.current.options).toEqual([])
})

it('groups come in order: Entries, Bills and income, Pantry, Statements, Settings; See all closes Entries', async () => {
  fakeApi(routes(() => lidl))
  const { result } = setup('lidl')
  await waitFor(() => expect(result.current.status).toBe('done'))
  expect(result.current.groups.map((g) => g.title)).toEqual(['Entries', 'Bills and income', 'Pantry'])
  const entries = result.current.groups[0].options
  expect(entries.map((o) => [o.label, o.to])).toEqual([['Lidl', '/activity/e1'], ['See all in Activity', '/activity?q=lidl']])
  expect(entries[0].end).toBe('−€29.90')
  expect(result.current.groups[1].options[0].to).toBe('/insights/bills/b1')
  expect(result.current.groups[2].options[0].to).toBe('/plan/pantry/p1')
  expect(result.current.count).toBe(3)
  const ids = result.current.options.map((o) => o.id)
  expect(new Set(ids).size).toBe(ids.length)
})

it('statements come from the saved list and settings from the index, after the server groups', async () => {
  fakeApi(routes(() => body()))
  const { result } = setup('sep')
  await waitFor(() => expect(result.current.groups.map((g) => g.key)).toEqual(['statements']))
  expect(result.current.groups[0].options[0].to).toBe('/insights/statements/2026-09')
  const dark = setup('dark')
  await waitFor(() => expect(dark.result.current.groups.map((g) => g.key)).toEqual(['settings']))
})

it('an old answer never replaces a newer one', async () => {
  let release: (v: SearchResponse) => void = () => {}
  const slow = new Promise<SearchResponse>((r) => { release = r })
  const api = fakeApi(routes((q) => (q === 'lid' ? slow : body({ entries: [{ id: 'new', date: '2026-10-07', label: 'Lidl new', category: null, amount: -1, currency: 'EUR' }] }))))
  const { result, rerender } = setup('lid')
  await waitFor(() => expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(1))
  rerender({ q: 'lidl' })
  await waitFor(() => expect(result.current.groups[0]?.options[0].label).toBe('Lidl new'))
  await act(async () => { release(body({ entries: [{ id: 'old', date: '2026-10-07', label: 'Lidl old', category: null, amount: -1, currency: 'EUR' }] })); await wait(30) })
  expect(result.current.groups[0].options[0].label).toBe('Lidl new')
})

it('a request already out when the text changes is cancelled', async () => {
  const signals: AbortSignal[] = []
  const orig = globalThis.fetch
  fakeApi(routes((q) => (q === 'lid' ? new Promise(() => {}) : body())))
  const spy = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (input instanceof Request && input.url.includes('/search')) signals.push(input.signal)
    return spy(input, init)
  }) as typeof fetch
  try {
    const { rerender } = setup('lid')
    await waitFor(() => expect(signals).toHaveLength(1))
    rerender({ q: 'lidl' })
    await waitFor(() => expect(signals[0].aborted).toBe(true))
  } finally { globalThis.fetch = orig }
})

it('offline: the device groups still answer, the server groups are missing, no request is sent', async () => {
  const api = fakeApi(routes(() => lidl))
  setOnline(false)
  const { result } = setup('dark')
  await waitFor(() => expect(result.current.status).toBe('offline'))
  expect(result.current.serverMissing).toBe(true)
  expect(result.current.groups.map((g) => g.key)).toEqual(['settings'])
  expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(0)
})

it('a 429 or a failure keeps the device groups and says so', async () => {
  fakeApi(routes(() => reply(429, { detail: 'slow down' })))
  const limited = setup('dark')
  await waitFor(() => expect(limited.result.current.status).toBe('limited'))
  expect(limited.result.current.groups.map((g) => g.key)).toEqual(['settings'])
  fakeApi(routes(() => reply(500, { detail: 'boom' })))
  const failed = setup('dark')
  await waitFor(() => expect(failed.result.current.status).toBe('failed'))
  expect(failed.result.current.serverMissing).toBe(true)
  expect(failed.result.current.groups.map((g) => g.key)).toEqual(['settings'])
})

it('hostile text goes to the server as plain text; a 100+ character string is not sent', async () => {
  const api = fakeApi(routes(() => body()))
  const { rerender } = setup('%_')
  await waitFor(() => expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(1))
  expect(api.callsTo('GET /api/v1/search' as never)[0].query.get('q')).toBe('%_')
  rerender({ q: 'Λιντλ' })
  await waitFor(() => expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(2))
  rerender({ q: 'x'.repeat(101) })
  await act(() => wait(350))
  expect(api.callsTo('GET /api/v1/search' as never)).toHaveLength(2)
})
