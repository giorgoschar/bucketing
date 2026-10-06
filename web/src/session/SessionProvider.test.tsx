import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionProvider, useSession } from './SessionProvider'
import { cachePut, cacheGet, wipe } from '../offline/db'
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

it('401 signs out and wipes local data', async () => {
  await cachePut('x', 1)
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
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

it('a 401 on /me tells other tabs and clears the query cache', async () => {
  const clear = vi.spyOn(queryClient, 'clear')
  const other = new BroadcastChannel('tameio-session')
  const heard = vi.fn()
  other.onmessage = (e) => heard(e.data)
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
  render(<SessionProvider><Probe /></SessionProvider>)
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())
  await waitFor(() => expect(heard).toHaveBeenCalledWith('signedOut'))
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
