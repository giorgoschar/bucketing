import { afterEach, beforeEach, expect, it } from 'vitest'
import { fakeApi } from '../test/fakeApi'
import { entry } from '../test/fixtures'
import { resetTestEnv, TEST_IDENTITY } from '../test/render'
import { setIdentity } from './identity'
import { enqueue, onQueueDrained, replay } from './queue'

const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

const post = () => enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/skip' })

it('tells drain listeners what a replay sent, and stays quiet when nothing happened', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => entry({ status: 'skipped' }),
  })
  const seen: unknown[] = []
  const off = onQueueDrained((r) => seen.push(r))
  await replay()
  expect(seen).toEqual([])
  await post()
  await replay()
  expect(seen).toEqual([{ sent: 1, failed: 0, stoppedOnAuth: false }])
  off()
  await post()
  await replay()
  expect(seen).toHaveLength(1)
})

it('a listener that throws never breaks the drain or the other listeners', async () => {
  fakeApi({
    'GET /api/v1/auth/me': () => ME,
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => entry({ status: 'skipped' }),
  })
  const seen: unknown[] = []
  const offBad = onQueueDrained(() => { throw new Error('boom') })
  const offGood = onQueueDrained((r) => seen.push(r))
  await post()
  await expect(replay()).resolves.toEqual({ sent: 1, failed: 0, stoppedOnAuth: false })
  expect(seen).toHaveLength(1)
  offBad()
  offGood()
})
