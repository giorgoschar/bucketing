import { waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db, wipe } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { enqueue, replay } from '../offline/queue'
import { fakeApi, reply } from '../test/fakeApi'
import { entry } from '../test/fixtures'
import { resetTestEnv, TEST_IDENTITY, testQueryClient } from '../test/render'
import { isPending, markPending } from './pending'
import { installQueueBridge } from './queueBridge'

const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('after a replay: invalidates plan, home and the rest, and clears pending markers once nothing is pending', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => entry({ status: 'skipped' }),
  })
  const client = testQueryClient()
  const spy = vi.spyOn(client, 'invalidateQueries')
  const stop = installQueueBridge(client)
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })
  markPending('e1')
  await replay()
  await waitFor(() => expect(isPending('e1')).toBe(false))
  expect(spy).toHaveBeenCalledWith({ queryKey: ['plan'] })
  expect(spy).toHaveBeenCalledWith({ queryKey: ['home'] })
  stop()
})

it('a row that is still pending (backed off) keeps the markers', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => entry({ status: 'skipped' }),
    'POST /api/v1/recurring/entries/{entry_id}/amount': () => reply(503),
  })
  const stop = installQueueBridge(testQueryClient())
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e2/amount', body: { amount: '10.00' } })
  markPending('e2')
  await replay()
  await new Promise((r) => setTimeout(r, 30))
  expect(isPending('e2')).toBe(true)
  stop()
})

it('clears the markers when the pending count reaches 0 without a drain here (another tab sent them)', async () => {
  const stop = installQueueBridge(testQueryClient())
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })
  markPending('e1')
  await new Promise((r) => setTimeout(r, 30))
  expect(isPending('e1')).toBe(true)
  await db.queue.clear()
  await waitFor(() => expect(isPending('e1')).toBe(false))
  stop()
})

it('wipe (sign-out, account switch) clears the markers', async () => {
  markPending('e1')
  await wipe()
  expect(isPending('e1')).toBe(false)
})
