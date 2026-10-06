import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionProvider, useSession } from './SessionProvider'
import { cachePut, cacheGet, wipe } from '../offline/db'

function Probe() {
  const s = useSession()
  return (
    <>
      <p>{s.status}{s.me ? `:${s.me.username}` : ''}</p>
      <button onClick={() => void s.signOut()}>out</button>
    </>
  )
}

const ME = { id: '1', username: 'g', household_id: 'h', display_name: 'G', email: null, avatar_color: null }

beforeEach(async () => { await wipe() })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

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

  act(() => screen.getByText('out').click())
  await waitFor(() => expect(screen.getByText('signedOut')).toBeInTheDocument())

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
