import { act, render, renderHook, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it } from 'vitest'
import { db } from '../../../offline/db'
import { fakeApi, reply } from '../../../test/fakeApi'
import { resetTestEnv, setOnline, testQueryClient } from '../../../test/render'
import { Toaster } from '../../../ui/Toast'
import { loose } from '../testHelpers'
import { pendingStore } from './pendingStore'
import { useUndoCreate } from './undo'

afterEach(async () => {
  pendingStore.unhide('t1')
  await resetTestEnv()
})

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={testQueryClient()}>{children}</QueryClientProvider>
)
const ROUTE = 'DELETE /api/v1/transactions/t1'
const hidden = () => pendingStore.snapshot().hidden.has('t1')

async function undo() {
  render(<Toaster />)
  const { result } = renderHook(() => useUndoCreate(), { wrapper })
  await act(() => result.current('t1'))
}

it('a successful undo keeps the row hidden', async () => {
  const api = fakeApi(loose({ [ROUTE]: () => reply(204) }))
  await undo()
  expect(api.calls.filter((c) => c.method === 'DELETE')).toHaveLength(1)
  expect(hidden()).toBe(true)
})

it('a 404 means the row is already gone: done, no toast', async () => {
  fakeApi(loose({ [ROUTE]: () => reply(404, { detail: 'Not found' }) }))
  await undo()
  expect(hidden()).toBe(true)
  expect(screen.queryByText(/undo/i)).not.toBeInTheDocument()
})

it('a network error is ambiguous: nothing is queued, the row comes back and a toast says the undo failed', async () => {
  const api = fakeApi()
  api.down()
  await undo()
  expect(await db.queue.count()).toBe(0)
  expect(hidden()).toBe(false)
  expect(screen.getByText("Couldn't undo. Check the entry.")).toBeInTheDocument()
})

it('another refusal (403, 5xx) brings the row back with a toast', async () => {
  fakeApi(loose({ [ROUTE]: () => reply(403, { detail: 'Not allowed' }) }))
  await undo()
  expect(hidden()).toBe(false)
  expect(screen.getByText("Couldn't undo. Check the entry.")).toBeInTheDocument()
})

it('offline: undo is online-only, so nothing is queued and the toast says so', async () => {
  fakeApi()
  setOnline(false)
  await undo()
  expect(await db.queue.count()).toBe(0)
  expect(hidden()).toBe(false)
  expect(screen.getByText('Undo needs a connection.')).toBeInTheDocument()
})
