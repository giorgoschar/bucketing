import { afterEach, beforeEach, expect, it } from 'vitest'
import { fakeApi, reply } from '../test/fakeApi'
import { resetTestEnv, TEST_IDENTITY } from '../test/render'
import { db } from './db'
import { setIdentity } from './identity'
import { enqueue, replay } from './queue'

const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('a 408 on replay is retried later with backoff, like 429 and 5xx (never marked failed)', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => reply(408, { detail: 'Request Timeout' }),
  })
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })
  const before = Date.now()
  expect(await replay()).toEqual({ sent: 0, failed: 0, stoppedOnAuth: false })
  const [row] = await db.queue.toArray()
  expect(row).toMatchObject({ status: 'pending', attempts: 1 })
  expect(row.nextAttemptAt).toBeGreaterThan(before)
})
