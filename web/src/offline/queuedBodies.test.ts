import { afterEach, beforeEach, expect, it } from 'vitest'
import { db, wipe } from './db'
import { setIdentity } from './identity'
import { enqueue } from './queue'
import { listQueuedBodies } from './queuedBodies'

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
})
afterEach(() => setIdentity(null))

it('lists pending bodies under a path prefix, oldest first, decrypted', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/recurring/entries/e1/done', body: {} })
  await enqueue({ method: 'DELETE', path: '/api/v1/transactions/t9' })
  expect(await listQueuedBodies('/api/v1/transactions')).toEqual([
    { id: expect.any(Number), method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } },
    { id: expect.any(Number), method: 'DELETE', path: '/api/v1/transactions/t9', body: undefined },
  ])
})

it("skips failed rows, another account's rows and rows it cannot decrypt", async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'failed' } })
  const [row] = await db.queue.toArray()
  await db.queue.put({ ...row, status: 'failed' })
  setIdentity({ user_id: 'u2', household_id: 'h1' })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'theirs' } })
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  await db.queue.add({ iv: new Uint8Array(12), data: new ArrayBuffer(8), createdAt: 0, attempts: 0, nextAttemptAt: 0, status: 'pending' })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'mine' } })
  expect((await listQueuedBodies('/api/v1/transactions')).map((b) => (b.body as { client_id: string }).client_id)).toEqual(['mine'])
})

it('signed out: nothing', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: {} })
  setIdentity(null)
  expect(await listQueuedBodies('/api/v1/transactions')).toEqual([])
})
