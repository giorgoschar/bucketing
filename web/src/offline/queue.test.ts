import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { forgetKey } from './crypto'
import { db, wipe } from './db'
import { enqueue, replay, startReplayTriggers } from './queue'

beforeEach(() => wipe())
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const ok = () => new Response('{}', { status: 201 })
const post = (body: unknown = {}, path = '/x') => enqueue({ method: 'POST', path, body })

it('replays in order and removes sent items', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'b' } })
  expect(await replay()).toMatchObject({ sent: 2, failed: 0 })
  expect(await db.queue.count()).toBe(0)
  const bodies = f.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string).client_id)
  expect(bodies).toEqual(['a', 'b'])
})

it('stores the body encrypted', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { note: 'Sklavenitis' } })
  const row = (await db.queue.toArray())[0]
  expect(new TextDecoder().decode(row.data)).not.toContain('Sklavenitis')
})

it('stops on 401 and keeps everything', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  await post({}, '/x')
  await post({}, '/y')
  expect(await replay()).toMatchObject({ sent: 0, stoppedOnAuth: true })
  expect(await db.queue.count()).toBe(2)
})

it('network error backs off and keeps the item pending', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
  await post()
  await replay()
  const row = (await db.queue.toArray())[0]
  expect(row.status).toBe('pending')
  expect(row.attempts).toBe(1)
  expect(row.nextAttemptAt).toBeGreaterThan(Date.now())
})

it('4xx marks failed with the server message; 409 is dropped', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'bad split' }), { status: 422 }))
    .mockResolvedValueOnce(new Response('{}', { status: 409 }))
  await post({}, '/x')
  await post({}, '/y')
  await replay()
  const rows = await db.queue.toArray()
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ status: 'failed', error: 'bad split' })
})

it('truncates a long server message', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ detail: 'x'.repeat(500) }), { status: 422 }),
  )
  await post()
  await replay()
  expect((await db.queue.toArray())[0].error).toHaveLength(200)
})

it('5xx backs off and keeps order', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 503 }))
  await post({}, '/x')
  await post({}, '/y')
  expect(await replay()).toMatchObject({ sent: 0, failed: 0 })
  expect(f).toHaveBeenCalledTimes(1)
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'pending', attempts: 1 })
})

it('sends the CSRF header', async () => {
  document.cookie = 'csrf_token=tok'
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await post()
  await replay()
  expect(new Headers((f.mock.calls[0][1] as RequestInit).headers).get('X-CSRF-Token')).toBe('tok')
})

it('is single-flight within a tab', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await post()
  const [a, b] = [replay(), replay()]
  expect(a).toBe(b)
  await a
  expect(f).toHaveBeenCalledTimes(1)
})

it('serialises drains across tabs through navigator.locks when available', async () => {
  let held = false
  let tail: Promise<unknown> = Promise.resolve()
  const requested: string[] = []
  vi.stubGlobal('navigator', {
    locks: {
      request: (name: string, cb: () => Promise<unknown>) => {
        requested.push(name)
        const run = tail.then(async () => {
          expect(held).toBe(false)
          held = true
          try { return await cb() } finally { held = false }
        })
        tail = run.catch(() => {})
        return run
      },
    },
  })
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await post()
  expect(await replay()).toMatchObject({ sent: 1 })
  expect(requested).toEqual(['tameio-queue'])
})

it('a second tab that waited on the lock finds the queue already drained', async () => {
  // Fake lock: the "other tab" drains first, then ours runs and must not resend.
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await post()
  vi.stubGlobal('navigator', {
    locks: {
      request: async (_n: string, cb: () => Promise<unknown>) => {
        await db.queue.clear() // other tab sent it
        return cb()
      },
    },
  })
  expect(await replay()).toMatchObject({ sent: 0 })
  expect(f).not.toHaveBeenCalled()
})

it('stops quietly when the store is wiped mid-drain', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    await wipe()
    return ok()
  })
  await post({}, '/x')
  await post({}, '/y')
  await expect(replay()).resolves.toMatchObject({ stoppedOnAuth: false })
  expect(await db.queue.count()).toBe(0)
})

it('marks an undecryptable row failed instead of blocking the queue', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  await post({}, '/x')
  const row = (await db.queue.toArray())[0]
  await db.queue.update(row.id!, { data: new ArrayBuffer(32) })
  await post({}, '/y')
  expect(await replay()).toMatchObject({ sent: 1, failed: 1 })
  expect(f).toHaveBeenCalledTimes(1)
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'failed' })
})

it('enqueue does not persist when a wipe happens while sealing', async () => {
  const p = enqueue({ method: 'POST', path: '/x', body: {} })
  forgetKey()
  await expect(p).rejects.toThrow()
  expect(await db.queue.count()).toBe(0)
})

it('triggers: replays on start, online and when visible; cleanup detaches', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockImplementation(async () => ok())
  const flush = () => vi.waitFor(async () => expect(await db.queue.count()).toBe(0))
  await post()
  const stop = startReplayTriggers()
  await flush()
  await post()
  window.dispatchEvent(new Event('online'))
  await flush()
  await post()
  document.dispatchEvent(new Event('visibilitychange'))
  await flush()
  expect(f).toHaveBeenCalledTimes(3)
  stop()
  await post()
  window.dispatchEvent(new Event('online'))
  await new Promise((r) => setTimeout(r, 20))
  expect(await db.queue.count()).toBe(1)
})
