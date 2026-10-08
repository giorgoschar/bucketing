import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { resetTestEnv, TEST_IDENTITY } from '../test/render'
import { db } from './db'
import { setIdentity } from './identity'
import { enqueue } from './queue'
import { dismissFailed, useFailedQueueRows } from './useQueue'

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('lists failed rows with their server message, oldest first, and dismisses them', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'b' } })
  const [first, second] = await db.queue.toArray() // primary-key (queue) order
  await db.queue.put({ ...first, status: 'failed', error: 'Your wallet has less cash' })
  const { result } = renderHook(() => useFailedQueueRows())
  await waitFor(() =>
    expect(result.current).toEqual([{ id: first.id, error: 'Your wallet has less cash', createdAt: first.createdAt }]))
  expect(result.current.map((r) => r.id)).not.toContain(second.id)
  await act(() => dismissFailed(first.id!))
  await waitFor(() => expect(result.current).toEqual([]))
  expect(await db.queue.count()).toBe(1)
})
