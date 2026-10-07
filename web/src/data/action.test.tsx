import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import type { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { fakeApi, reply } from '../test/fakeApi'
import { day, entry } from '../test/fixtures'
import { Providers, resetTestEnv, setOnline, TEST_IDENTITY, testQueryClient } from '../test/render'
import { Toaster } from '../ui/Toast'
import { useAction, type ActionResult, type ActionSpec } from './action'
import { keys } from './keys'
import { isPending } from './pending'
import type { EntryOut, UpcomingDayOut } from './types'

const KEY = keys.plan.upcoming(30)
const SKIP = 'POST /api/v1/recurring/entries/{entry_id}/skip' as const

const markSkipped = (qc: QueryClient) =>
  qc.setQueryData<UpcomingDayOut[]>(KEY, (old) =>
    old?.map((d) => ({ ...d, entries: d.entries.map((e) => ({ ...e, status: 'skipped' })) })))

const spec = (over: Partial<ActionSpec<void, EntryOut>> = {}): ActionSpec<void, EntryOut> => ({
  method: 'POST', path: '/api/v1/recurring/entries/e1/skip', optimistic: markSkipped,
  invalidates: [keys.plan.all], pendingId: 'e1', ...over,
})

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

function setup(s = spec()) {
  const client = testQueryClient()
  client.setQueryData(KEY, [day('2026-10-09', [entry()], 1200)])
  render(<Toaster />)
  const hook = renderHook(() => useAction(s), {
    wrapper: ({ children }) => <Providers client={client}>{children}</Providers>,
  })
  const run = async () => {
    let r: ActionResult<EntryOut> | undefined
    await act(async () => { r = await hook.result.current.run() })
    return r!
  }
  const status = () => client.getQueryData<UpcomingDayOut[]>(KEY)![0].entries[0].status
  return { client, run, status }
}

it('online 2xx: keeps the patch, resolves done with the data and invalidates', async () => {
  fakeApi({ [SKIP]: () => entry({ status: 'skipped' }) })
  const { client, run, status } = setup()
  const spy = vi.spyOn(client, 'invalidateQueries')
  expect(await run()).toEqual({ status: 'done', data: entry({ status: 'skipped' }) })
  expect(status()).toBe('skipped')
  expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] })
})

it('409: rolls back, toasts the server detail, invalidates and resolves rejected', async () => {
  fakeApi({ [SKIP]: () => reply(409, { detail: 'This entry is already done.' }) })
  const { client, run, status } = setup()
  const spy = vi.spyOn(client, 'invalidateQueries')
  expect(await run()).toEqual({ status: 'rejected', code: 409, detail: 'This entry is already done.' })
  expect(status()).toBe('expected')
  expect(screen.getByRole('status')).toHaveTextContent('This entry is already done.')
  expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] })
})

it('422 with a list detail toasts a readable message', async () => {
  fakeApi({ [SKIP]: () => reply(422, { detail: [{ loc: ['body'], msg: 'Field required', type: 'missing' }] }) })
  const { run } = setup()
  await run()
  expect(screen.getByRole('status')).toHaveTextContent('Some values aren’t valid. Check them and try again.')
  expect(screen.getByRole('status')).not.toHaveTextContent('[object Object]')
})

it('toastRejections false: no toast, but the detail is returned for the caller to show', async () => {
  fakeApi({ [SKIP]: () => reply(409, { detail: 'Delete it too.' }) })
  const { run } = setup(spec({ toastRejections: false }))
  expect(await run()).toEqual({ status: 'rejected', code: 409, detail: 'Delete it too.' })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('offline: queues without sending, keeps the patch and marks the row pending', async () => {
  const fake = fakeApi({})
  setOnline(false)
  const { run, status } = setup()
  expect(await run()).toEqual({ status: 'queued' })
  expect(status()).toBe('skipped')
  expect(await db.queue.count()).toBe(1)
  expect(isPending('e1')).toBe(true)
  expect(fake.calls).toHaveLength(0)
})

it('a network failure or a 5xx while online is queued too', async () => {
  const fake = fakeApi({ [SKIP]: () => reply(503) })
  const { run } = setup()
  expect(await run()).toEqual({ status: 'queued' })
  fake.down()
  expect(await run()).toEqual({ status: 'queued' })
  expect(await db.queue.count()).toBe(2)
})

it('401: rolls back, no toast and nothing queued', async () => {
  fakeApi({ [SKIP]: () => reply(401, { detail: 'Not authenticated' }) })
  const { run, status } = setup()
  expect(await run()).toMatchObject({ status: 'rejected', code: 401 })
  expect(status()).toBe('expected')
  expect(await db.queue.count()).toBe(0)
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('a 503 while online is replayed shortly after, without an online or visibility event', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true })
  let n = 0
  const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }
  const fake = fakeApi({
    'GET /api/v1/auth/me': () => ME,
    [SKIP]: () => (++n === 1 ? reply(503) : entry({ status: 'skipped' })),
  })
  const { run } = setup()
  expect(await run()).toEqual({ status: 'queued' })
  expect(fake.callsTo(SKIP)).toHaveLength(1)
  await act(() => vi.advanceTimersByTimeAsync(2_000))
  await waitFor(() => expect(fake.callsTo(SKIP)).toHaveLength(2))
  await waitFor(async () => expect(await db.queue.count()).toBe(0))
})
