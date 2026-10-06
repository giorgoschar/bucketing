import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { forgetKey } from './crypto'
import { db, wipe } from './db'
import { setIdentity } from './identity'
import { enqueue, replay, startReplayTriggers } from './queue'

const ME = { id: 'u1', household_id: 'h1' }
const ME_URL = '/api/v1/auth/me'

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: ME.id, household_id: ME.household_id })
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  setIdentity(null)
})

const ok = () => new Response('{}', { status: 201 })
const post = (body: unknown = {}, path = '/x') => enqueue({ method: 'POST', path, body })

/** Answers /me as the signed-in user (or `me`), and every other URL via `other`. */
function serve(other: (url: string, init: RequestInit) => Response | Promise<Response>, me: () => Response | Promise<Response> = () => Response.json(ME)) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    return url === ME_URL ? me() : other(url, init ?? {})
  })
}
const writes = (f: ReturnType<typeof serve>) => f.mock.calls.filter(([u]) => String(u) !== ME_URL)

it('replays in order and removes sent items', async () => {
  const f = serve(ok)
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'a' } })
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'b' } })
  expect(await replay()).toMatchObject({ sent: 2, failed: 0 })
  expect(await db.queue.count()).toBe(0)
  const bodies = writes(f).map((c) => JSON.parse((c[1] as RequestInit).body as string).client_id)
  expect(bodies).toEqual(['a', 'b'])
})

it('stores the body encrypted', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { note: 'Sklavenitis' } })
  const row = (await db.queue.toArray())[0]
  expect(new TextDecoder().decode(row.data)).not.toContain('Sklavenitis')
})

it('enqueue needs a signed-in identity', async () => {
  setIdentity(null)
  await expect(post()).rejects.toThrow('Not signed in')
  expect(await db.queue.count()).toBe(0)
})

it('stops on a 401 from the write and keeps everything', async () => {
  serve(() => new Response('{}', { status: 401 }))
  await post({}, '/x')
  await post({}, '/y')
  expect(await replay()).toMatchObject({ sent: 0, stoppedOnAuth: true })
  expect(await db.queue.count()).toBe(2)
})

it('stops on a 401 from /me before sending anything, and keeps everything', async () => {
  const f = serve(ok, () => new Response('{}', { status: 401 }))
  await post({}, '/x')
  expect(await replay()).toMatchObject({ sent: 0, stoppedOnAuth: true })
  expect(writes(f)).toHaveLength(0)
  expect(await db.queue.count()).toBe(1)
})

it('treats a network error on /me as offline: stops, keeps, no attempt counted', async () => {
  const f = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
  await post()
  expect(await replay()).toMatchObject({ sent: 0, failed: 0, stoppedOnAuth: false })
  expect(f).toHaveBeenCalledTimes(1)
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'pending', attempts: 0 })
})

it('does not send rows queued by another account; marks them failed without user data', async () => {
  const f = serve(ok)
  await post({ note: 'secret' }, '/mine')
  setIdentity({ user_id: 'someone-else', household_id: 'h1' })
  await post({ note: 'theirs' }, '/theirs')
  setIdentity({ user_id: ME.id, household_id: 'other-household' })
  await post({ note: 'other-hh' }, '/hh')
  expect(await replay()).toMatchObject({ sent: 1, failed: 2 })
  expect(writes(f).map((c) => String(c[0]))).toEqual(['/mine'])
  const rows = await db.queue.toArray()
  expect(rows).toHaveLength(2)
  for (const r of rows) expect(r).toMatchObject({ status: 'failed', error: 'Saved while signed in as a different account' })
})

it('network error backs off and keeps the item pending', async () => {
  serve(() => { throw new TypeError('Failed to fetch') })
  await post()
  await replay()
  const row = (await db.queue.toArray())[0]
  expect(row.status).toBe('pending')
  expect(row.attempts).toBe(1)
  expect(row.nextAttemptAt).toBeGreaterThan(Date.now())
})

it('4xx marks failed with the server message; 409 is dropped', async () => {
  let n = 0
  serve(() => (n++ === 0 ? new Response(JSON.stringify({ detail: 'bad split' }), { status: 422 }) : new Response('{}', { status: 409 })))
  await post({}, '/x')
  await post({}, '/y')
  await replay()
  const rows = await db.queue.toArray()
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ status: 'failed', error: 'bad split' })
})

it('truncates a long server message', async () => {
  serve(() => new Response(JSON.stringify({ detail: 'x'.repeat(500) }), { status: 422 }))
  await post()
  await replay()
  expect((await db.queue.toArray())[0].error).toHaveLength(200)
})

it('5xx backs off and keeps order', async () => {
  const f = serve(() => new Response('{}', { status: 503 }))
  await post({}, '/x')
  await post({}, '/y')
  expect(await replay()).toMatchObject({ sent: 0, failed: 0 })
  expect(writes(f)).toHaveLength(1)
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'pending', attempts: 1 })
})

it('a 429 and a CSRF 403 back off instead of failing the row; another 403 fails it', async () => {
  const statuses = [
    new Response('{}', { status: 429 }),
    new Response(JSON.stringify({ detail: 'CSRF token missing or invalid' }), { status: 403 }),
    new Response(JSON.stringify({ detail: 'Forbidden' }), { status: 403 }),
  ]
  serve(() => statuses.shift()!)
  await post()
  await replay({ force: true })
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'pending', attempts: 1 })
  await replay({ force: true })
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'pending', attempts: 2 })
  await replay({ force: true })
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'failed', error: 'Forbidden' })
})

it('sends the CSRF header, and Content-Type only with a body', async () => {
  document.cookie = 'csrf_token=tok'
  const f = serve(ok)
  await post()
  await enqueue({ method: 'DELETE', path: '/gone' })
  await replay()
  const [withBody, bodiless] = writes(f).map((c) => new Headers((c[1] as RequestInit).headers))
  expect(withBody.get('X-CSRF-Token')).toBe('tok')
  expect(withBody.get('Content-Type')).toBe('application/json')
  expect(bodiless.get('X-CSRF-Token')).toBe('tok')
  expect(bodiless.has('Content-Type')).toBe(false)
})

it('a backed-off head blocks later rows; online forces a retry and both go out in order', async () => {
  let fail = true
  const f = serve((url) => {
    if (fail && url === '/first') throw new TypeError('Failed to fetch')
    return ok()
  })
  await post({}, '/first')
  await replay() // head fails and backs off
  await post({}, '/second')
  f.mockClear()

  await replay() // inside the window: nothing may overtake the head
  expect(f).not.toHaveBeenCalled()

  fail = false
  expect(await replay({ force: true })).toMatchObject({ sent: 2 })
  expect(writes(f).map((c) => String(c[0]))).toEqual(['/first', '/second'])
  expect(await db.queue.count()).toBe(0)
})

it('is single-flight within a tab', async () => {
  const f = serve(ok)
  await post()
  const [a, b] = [replay(), replay()]
  expect(a).toBe(b)
  await a
  expect(writes(f)).toHaveLength(1)
})

/** A Web Locks stand-in shared by every "tab": requests run one at a time, in order. */
function fakeLocks() {
  let tail: Promise<unknown> = Promise.resolve()
  const log = { requested: [] as string[], entered: 0, maxHeld: 0 }
  let held = 0
  vi.stubGlobal('navigator', {
    locks: {
      request: (name: string, cb: () => Promise<unknown>) => {
        log.requested.push(name)
        const run = tail.then(async () => {
          log.entered++
          held++
          log.maxHeld = Math.max(log.maxHeld, held)
          try { return await cb() } finally { held-- }
        })
        tail = run.catch(() => {})
        return run
      },
    },
  })
  return log
}

it('two tabs contend for the lock: the second waits, then finds the queue drained', async () => {
  const log = fakeLocks()
  let release!: () => void
  const gate = new Promise<void>((r) => { release = r })
  const f = serve(async () => { await gate; return ok() })
  await post()

  // A second tab is a second copy of the module (its own single-flight state) on the same IndexedDB.
  vi.resetModules()
  const tabB = await import('./queue')
  const identityB = await import('./identity')
  identityB.setIdentity({ user_id: ME.id, household_id: ME.household_id })

  const a = replay()
  await vi.waitFor(() => expect(writes(f)).toHaveLength(1)) // tab A is mid-send, holding the lock
  const b = tabB.replay()
  await new Promise((r) => setTimeout(r, 50))
  expect(log.entered).toBe(1) // B is queued behind A and has not started
  release()
  expect(await a).toMatchObject({ sent: 1 })
  expect(await b).toMatchObject({ sent: 0 })
  expect(log.entered).toBe(2)
  expect(log.maxHeld).toBe(1)
  expect(log.requested).toEqual(['tameio-queue', 'tameio-queue'])
  expect(writes(f)).toHaveLength(1) // sent exactly once
})

it('stops quietly when the store is wiped mid-drain', async () => {
  serve(async () => {
    await wipe()
    return ok()
  })
  await post({}, '/x')
  await post({}, '/y')
  await expect(replay()).resolves.toMatchObject({ stoppedOnAuth: false })
  expect(await db.queue.count()).toBe(0)
})

it('marks an undecryptable row failed instead of blocking the queue', async () => {
  const f = serve(ok)
  await post({}, '/x')
  const row = (await db.queue.toArray())[0]
  await db.queue.update(row.id!, { data: new ArrayBuffer(32) })
  await post({}, '/y')
  expect(await replay()).toMatchObject({ sent: 1, failed: 1 })
  expect(writes(f)).toHaveLength(1)
  expect((await db.queue.toArray())[0]).toMatchObject({ status: 'failed' })
})

it('enqueue does not persist when a wipe happens while sealing', async () => {
  const p = enqueue({ method: 'POST', path: '/x', body: {} })
  forgetKey()
  await expect(p).rejects.toThrow()
  expect(await db.queue.count()).toBe(0)
})

it('triggers: replays on start, online and when visible; cleanup detaches', async () => {
  const f = serve(ok)
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
  expect(writes(f)).toHaveLength(3)
  stop()
  await post()
  window.dispatchEvent(new Event('online'))
  await new Promise((r) => setTimeout(r, 20))
  expect(await db.queue.count()).toBe(1)
})

it('triggers: online forces a retry inside the backoff window, and a timer retries when it is due', async () => {
  // Capture the long backoff timer instead of really waiting for it; short timers run normally.
  const real = globalThis.setTimeout
  const long: { cb: () => void; ms: number; id: number }[] = []
  const cleared: unknown[] = []
  vi.spyOn(globalThis, 'setTimeout').mockImplementation(((cb: () => void, ms?: number) => {
    if ((ms ?? 0) < 1000) return real(cb, ms)
    const t = { cb, ms: ms!, id: long.length + 1000 }
    long.push(t)
    return t.id as unknown as ReturnType<typeof setTimeout>
  }) as typeof setTimeout)
  vi.spyOn(globalThis, 'clearTimeout').mockImplementation(((id: unknown) => { cleared.push(id) }) as typeof clearTimeout)

  let fail = true
  const f = serve(() => { if (fail) throw new TypeError('Failed to fetch'); return ok() })
  await post({}, '/first')
  const stop = startReplayTriggers()
  await vi.waitFor(() => expect(long).toHaveLength(1)) // armed for the head's backoff
  expect(long[0].ms).toBeGreaterThan(1000)

  await post({}, '/second')
  fail = false
  f.mockClear()
  window.dispatchEvent(new Event('online')) // forced: ignores the backoff
  await vi.waitFor(async () => expect(await db.queue.count()).toBe(0))
  expect(writes(f).map((c) => String(c[0]))).toEqual(['/first', '/second'])
  expect(cleared).toContain(long[0].id) // a new drain cancels the pending wake-up

  // Timer path: back off again, then fire the captured timer.
  fail = true
  await post({}, '/third')
  window.dispatchEvent(new Event('online'))
  await vi.waitFor(() => expect(long).toHaveLength(2))
  fail = false
  f.mockClear()
  const t0 = Date.now()
  vi.spyOn(Date, 'now').mockReturnValue(t0 + long[1].ms + 100) // the wake-up time has come
  long[1].cb()
  await vi.waitFor(async () => expect(await db.queue.count()).toBe(0))
  expect(writes(f).map((c) => String(c[0]))).toEqual(['/third'])

  stop()
})
