import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionProvider, useSession } from './SessionProvider'
import { cachePut, cacheGet, db, wipe } from '../offline/db'
import { setIdentity } from '../offline/identity'
import { enqueue, replay } from '../offline/queue'
import { keyGeneration } from '../offline/crypto'
import { queryClient } from '../queryClient'

function Probe() {
  const s = useSession()
  return (
    <>
      <p>{s.status}{s.me ? `:${s.me.username}` : ''}</p>
      {s.logoutFailed && <p>logout-failed</p>}
      <button onClick={() => void s.signOut()}>out</button>
      <button onClick={() => void s.retryLogout()}>retry</button>
    </>
  )
}

const ME = { id: '1', username: 'g', household_id: 'h', display_name: 'G', email: null, avatar_color: null }

beforeEach(async () => { await wipe() })
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT'
})

const urlOf = (input: unknown) => (input instanceof Request ? input.url : String(input))

/** /me answers with `me`; /app/auth/logout answers with each of `logout` in turn (an Error rejects). */
function backend(me: Response, ...logout: (number | Error)[]) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (urlOf(input).endsWith('/api/v1/auth/me')) return me.clone()
    const next = logout.length > 1 ? logout.shift()! : logout[0] ?? 204
    if (next instanceof Error) throw next
    return new Response(null, { status: next })
  })
}
const ok = () => new Response(JSON.stringify(ME), { status: 200 })
const logoutCalls = (f: ReturnType<typeof backend>) => f.mock.calls.filter(([u]) => urlOf(u) === '/app/auth/logout')

it('signed in when /me returns 200', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify({ id: '1', username: 'g', household_id: 'h' }), { status: 200 }),
  )
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
})

it('401 shows sign-in but keeps the encrypted store and its queue', async () => {
  await cachePut('x', 1)
  await cachePut('me', ME)
  setIdentity({ user_id: ME.id, household_id: ME.household_id })
  await enqueue({ method: 'POST', path: '/x', body: { a: 1 } })
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  expect(await cacheGet('x')).toBe(1)
  expect(await db.queue.count()).toBe(1)
})

it('the same user signing back in after a 401 finds the queue and replays it', async () => {
  await cachePut('me', ME)
  setIdentity({ user_id: ME.id, household_id: ME.household_id })
  await enqueue({ method: 'POST', path: '/x', body: { a: 1 } })
  // First load: the session has expired.
  const expired = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  const first = render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  expect(await db.queue.count()).toBe(1)
  first.unmount()
  expired.mockRestore()
  // They sign in again as the same account.
  backend(ok())
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  expect(await db.queue.count()).toBe(1)
  expect(await replay()).toMatchObject({ sent: 1 })
  expect(await db.queue.count()).toBe(0)
})

it('an account switch wipes the queue and cache before signing in as the new user', async () => {
  await cachePut('me', { ...ME, id: '2', username: 'old' })
  await cachePut('x', 1)
  setIdentity({ user_id: '2', household_id: 'h' })
  await enqueue({ method: 'POST', path: '/x', body: { a: 1 } })
  backend(ok())
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  expect(await db.queue.count()).toBe(0)
  expect(await cacheGet('x')).toBeUndefined()
  await waitFor(async () => expect(await cacheGet<typeof ME>('me')).toMatchObject({ id: '1' }))
})

it('a household change also counts as an account switch', async () => {
  await cachePut('me', { ...ME, household_id: 'other' })
  await cachePut('x', 1)
  backend(ok())
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  expect(await cacheGet('x')).toBeUndefined()
})

it('offline with a cached profile stays signed in', async () => {
  await cachePut('me', { id: '1', username: 'g', household_id: 'h' })
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
})

it('offline with no cached profile is signed out', async () => {
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
})

it('signOut posts logout with the CSRF header, wipes and tells other tabs', async () => {
  document.cookie = 'csrf_token=tok'
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = input instanceof Request ? input.url : String(input)
    if (url.endsWith('/api/v1/auth/me')) return new Response(JSON.stringify(ME), { status: 200 })
    return new Response(null, { status: 204 })
  })
  const other = new BroadcastChannel('tameio-session')
  const heard = vi.fn()
  other.onmessage = (e) => heard(e.data)
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  await cachePut('x', 1)
  const clear = vi.spyOn(queryClient, 'clear')

  act(() => screen.getByText('out').click())
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  expect(clear).toHaveBeenCalled()
  expect(screen.queryByText('logout-failed')).not.toBeInTheDocument()

  const logout = fetch.mock.calls.find(([u]) => String(u) === '/app/auth/logout')
  expect(logout?.[1]).toMatchObject({ method: 'POST', headers: { 'X-CSRF-Token': 'tok' } })
  expect(await cacheGet('x')).toBeUndefined()
  await waitFor(() => expect(heard).toHaveBeenCalledWith('signedOut'))
  other.close()
})

it('a sign-out in another tab signs this tab out', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(ME), { status: 200 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())

  const other = new BroadcastChannel('tameio-session')
  other.postMessage('signedOut')
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  other.close()
})

it('a sign-out while /me is in flight is not undone by the late 200', async () => {
  let release!: (r: Response) => void
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = input instanceof Request ? input.url : String(input)
    if (url.endsWith('/api/v1/auth/me')) return new Promise<Response>((r) => { release = r })
    return new Response(null, { status: 204 })
  })
  // Vitest fails the run on any unhandled rejection, so a leaked "wiped" error would surface here.
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(release).toBeTypeOf('function'))

  act(() => screen.getByText('out').click())
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  release(new Response(JSON.stringify(ME), { status: 200 }))
  await new Promise((r) => setTimeout(r, 50))

  expect(screen.getByText('signedOut')).toBeInTheDocument()
  expect(await cacheGet('me')).toBeUndefined()
})

it('outside a provider, useSession reports loading', () => {
  render(<Probe />)
  expect(screen.getByText('loading')).toBeInTheDocument()
})

it('a 401 on /me clears the query cache but does not broadcast a sign-out', async () => {
  const clear = vi.spyOn(queryClient, 'clear')
  const other = new BroadcastChannel('tameio-session')
  const heard = vi.fn()
  other.onmessage = (e) => heard(e.data)
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  await new Promise((r) => setTimeout(r, 50))
  expect(heard).not.toHaveBeenCalled()
  expect(clear).toHaveBeenCalled()
  other.close()
})

it('a tab told about a sign-out forgets its device key and clears its query cache', async () => {
  backend(ok())
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  const clear = vi.spyOn(queryClient, 'clear')
  const gen = keyGeneration()

  const other = new BroadcastChannel('tameio-session')
  other.postMessage('signedOut')
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  expect(keyGeneration()).toBeGreaterThan(gen)
  expect(clear).toHaveBeenCalled()
  other.close()
})

it('a logout the server rejects still clears this device, reports it, and Retry re-reads the CSRF cookie', async () => {
  document.cookie = 'csrf_token=old'
  const fetch = backend(ok(), 403, 204)
  const other = new BroadcastChannel('tameio-session')
  const heard = vi.fn()
  other.onmessage = (e) => heard(e.data)
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  await cachePut('x', 1)

  act(() => screen.getByText('out').click())
  await waitFor(() => expect(screen.getByText('logout-failed')).toBeInTheDocument())
  expect(screen.getByText('signedOut')).toBeInTheDocument()
  expect(await cacheGet('x')).toBeUndefined()
  await waitFor(() => expect(heard).toHaveBeenCalledWith('signedOut'))

  document.cookie = 'csrf_token=new'
  act(() => screen.getByText('retry').click())
  await waitFor(() => expect(screen.queryByText('logout-failed')).not.toBeInTheDocument())
  const calls = logoutCalls(fetch)
  expect(calls).toHaveLength(2)
  expect(calls[1][1]).toMatchObject({ method: 'POST', headers: { 'X-CSRF-Token': 'new' } })
  other.close()
})

it('a logout while offline still clears this device and reports it; a failed Retry keeps the error', async () => {
  const fetch = backend(ok(), new TypeError('Failed to fetch'))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())

  act(() => screen.getByText('out').click())
  await waitFor(() => expect(screen.getByText('logout-failed')).toBeInTheDocument())
  expect(screen.getByText('signedOut')).toBeInTheDocument()

  act(() => screen.getByText('retry').click())
  await waitFor(() => expect(logoutCalls(fetch)).toHaveLength(2))
  expect(screen.getByText('logout-failed')).toBeInTheDocument()
})

it('a 401 from logout counts as signed out on the server', async () => {
  backend(ok(), 401)
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  act(() => screen.getByText('out').click())
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  expect(screen.queryByText('logout-failed')).not.toBeInTheDocument()
})

it('a 5xx on /me falls back to the cached profile', async () => {
  await cachePut('me', ME)
  backend(new Response('', { status: 503 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
})

it('another 4xx on /me signs out even with a cached profile', async () => {
  await cachePut('me', ME)
  backend(new Response('{}', { status: 403 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
})

it('a /me that times out after 5 s is treated as offline', async () => {
  await cachePut('me', ME)
  const timeout = vi.spyOn(AbortSignal, 'timeout').mockImplementation(() =>
    AbortSignal.abort(new DOMException('timed out', 'TimeoutError')),
  )
  // A server that never answers: only the abort signal can end the request.
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const req = input as Request
    if (req.signal.aborted) throw req.signal.reason
    return new Promise<Response>(() => {})
  })
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())
  expect(timeout).toHaveBeenCalledWith(5000)
})

it('an account switch tells other tabs, and a tab told about it forgets its key and re-reads /me', async () => {
  await cachePut('me', { ...ME, id: '2' })
  const other = new BroadcastChannel('tameio-session')
  const heard = vi.fn()
  other.onmessage = (e) => heard(e.data)
  backend(ok())
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(heard).toHaveBeenCalledWith({ type: 'ACCOUNT_SWITCHED' }))
  await waitFor(() => expect(screen.getByText('signedIn:g')).toBeInTheDocument())

  const gen = keyGeneration()
  const f = vi.mocked(globalThis.fetch)
  const meCalls = () => f.mock.calls.filter(([u]) => urlOf(u).endsWith('/api/v1/auth/me')).length
  const before = meCalls()
  other.postMessage({ type: 'ACCOUNT_SWITCHED' })
  await waitFor(() => expect(meCalls()).toBe(before + 1))
  expect(keyGeneration()).toBeGreaterThan(gen)
  other.close()
})
