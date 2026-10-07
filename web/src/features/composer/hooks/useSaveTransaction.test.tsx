import { act, renderHook } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db, wipe } from '../../../offline/db'
import { setIdentity } from '../../../offline/identity'
import { replay } from '../../../offline/queue'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv, setOnline, testQueryClient } from '../../../test/render'
import { ToastHost } from '../bridge'
import { EMPTY_DEFAULTS, loadDefaults } from '../defaults'
import { blankState, type ComposerState } from '../state'
import { goOffline, loose, writes } from '../testHelpers'
import { pendingStore } from './pendingStore'
import { type SaveOutcome, useSaveTransaction } from './useSaveTransaction'

const CTX = { hh: 'h1', householdCurrency: 'EUR', fuelCategoryId: null, meId: 'u1' }
const STATE: ComposerState = {
  ...blankState({ type: 'expense', currency: 'EUR', date: '2026-10-07', clientId: 'cid-1', meId: 'u1' }),
  amount: '3', bucketId: 'b-day',
}
const CREATED = { id: 't1', amount: 3, currency: 'EUR', type: 'expense' }

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
})
afterEach(resetTestEnv)

function setup(state: ComposerState = STATE) {
  const qc = testQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}><ToastHost>{children}</ToastHost></QueryClientProvider>
  )
  return renderHook(() => useSaveTransaction(state, CTX, EMPTY_DEFAULTS), { wrapper })
}
type Hook = ReturnType<typeof setup>
async function saveNew(h: Hook): Promise<SaveOutcome> {
  let r!: SaveOutcome
  await act(async () => { r = await h.result.current.saveNew() })
  return r
}

it('online success returns the id; the optimistic row is replaced by the highlight', async () => {
  let during: string[] = []
  const api = fakeApi(loose({
    'POST /api/v1/transactions': () => {
      during = pendingStore.snapshot().inFlight.map((r) => r.key)
      return Response.json(CREATED, { status: 201 })
    },
  }))
  expect(await saveNew(setup())).toEqual({ status: 'done', id: 't1' })
  expect(during).toEqual(['cid-1'])
  expect(pendingStore.snapshot()).toMatchObject({ inFlight: [], justSaved: 't1' })
  expect(writes(api)).toHaveLength(1)
})

it('a network error queues the body with the same client_id; the defaults are written anyway', async () => {
  goOffline()
  expect(await saveNew(setup())).toEqual({ status: 'queued' })
  expect(await db.queue.count()).toBe(1)
  expect((await loadDefaults('h1')).last?.bucket_id).toBe('b-day')
})

it('the replay of a request whose response was lost gets 200 for the same client_id: one row', async () => {
  goOffline()
  await saveNew(setup())
  vi.restoreAllMocks()
  setOnline(true)
  const api = fakeApi(loose({
    'GET /api/v1/auth/me': { id: 'u1', household_id: 'h1' },
    'POST /api/v1/transactions': () => Response.json(CREATED, { status: 200 }), // already created server-side
  }))
  expect(await replay({ force: true })).toMatchObject({ sent: 1, failed: 0 })
  expect(await db.queue.count()).toBe(0)
  expect(writes(api).map((c) => (c.body as { client_id: string }).client_id)).toEqual(['cid-1'])
})

it('a second save while one is in flight is refused: one POST', async () => {
  let release: (() => void) | undefined
  const api = fakeApi(loose({
    'POST /api/v1/transactions': () =>
      new Promise<Response>((resolve) => { release = () => resolve(Response.json(CREATED, { status: 201 })) }),
  }))
  const h = setup()
  let first!: Promise<SaveOutcome>
  let second!: Promise<SaveOutcome>
  act(() => {
    first = h.result.current.saveNew()
    second = h.result.current.saveNew()
  })
  await vi.waitFor(() => expect(release).toBeDefined())
  release!()
  await act(async () => { await first })
  expect(await second).toEqual({ status: 'busy' })
  expect(await first).toEqual({ status: 'done', id: 't1' })
  expect(writes(api)).toHaveLength(1)
})

it('delete: a 404 counts as success, without an error toast', async () => {
  fakeApi(loose({ 'DELETE /api/v1/transactions/t9': () => Response.json({ detail: 'Transaction not found' }, { status: 404 }) }))
  const h = setup({ ...STATE, mode: 'edit', editId: 't9', clientId: null })
  let r!: SaveOutcome
  await act(async () => { r = await h.result.current.deleteEntry() })
  expect(r).toEqual({ status: 'done', id: 't9' })
})

it('delete offline is queued and the row hidden at once', async () => {
  goOffline()
  const h = setup({ ...STATE, mode: 'edit', editId: 't9', clientId: null })
  let r!: SaveOutcome
  await act(async () => { r = await h.result.current.deleteEntry() })
  expect(r).toEqual({ status: 'queued' })
  expect(await db.queue.count()).toBe(1)
  expect(pendingStore.snapshot().hidden.has('t9')).toBe(true)
})

it('delete: an online 5xx is ambiguous, so it is not queued; the row comes back', async () => {
  fakeApi(loose({ 'DELETE /api/v1/transactions/t9': () => Response.json({ detail: 'boom' }, { status: 503 }) }))
  const h = setup({ ...STATE, mode: 'edit', editId: 't9', clientId: null })
  let r!: SaveOutcome
  await act(async () => { r = await h.result.current.deleteEntry() })
  expect(r.status).toBe('failed')
  expect(await db.queue.count()).toBe(0)
  expect(pendingStore.snapshot().hidden.has('t9')).toBe(false)
})
