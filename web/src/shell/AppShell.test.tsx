import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { Session } from '../session/SessionProvider'
import { AppShell } from './AppShell'

const stop = vi.fn()
const start = vi.fn(() => stop)
vi.mock('../offline/queue', () => ({ startReplayTriggers: () => start() }))

const session: Session = { status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {} }
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(() => {
  cleanup()
  start.mockClear()
  stop.mockClear()
})

function at(url: string, status: Session['status']) {
  session.status = status
  session.me = status === 'signedIn'
    ? { id: '1', username: 'g', household_id: 'h', display_name: 'G', email: null, avatar_color: null }
    : undefined
  const router = createMemoryRouter(
    [{ path: '/', element: <AppShell />, children: [{ index: true, element: <p>home screen</p> }] }],
    { initialEntries: [url] },
  )
  render(<RouterProvider router={router} />)
  return router
}

it('signed in: a passkey-link result shows as a dismissible status banner and leaves the URL', async () => {
  const router = at('/?linked=1', 'signedIn')
  expect(within(screen.getByRole('main')).getByRole('status')).toHaveTextContent('Passkey linked. You can sign in with Face ID now.')
  expect(screen.getByText('home screen')).toBeInTheDocument()
  expect(router.state.location.search).toBe('')
  act(() => screen.getByRole('button', { name: 'Dismiss' }).click())
  expect(within(screen.getByRole('main')).queryByRole('status')).not.toBeInTheDocument()
})

it('signed in: an auth_error shows as an alert banner with the shared message', () => {
  const router = at('/?auth_error=subject_conflict', 'signedIn')
  expect(screen.getByRole('alert')).toHaveTextContent('This passkey is already linked to a different account.')
  expect(router.state.location.search).toBe('')
})

it('signed out: the result goes to the sign-in screen and the URL is cleaned', () => {
  const router = at('/?auth_error=denied', 'signedOut')
  expect(screen.getByRole('alert')).toHaveTextContent('Sign-in was cancelled.')
  expect(screen.getByRole('link', { name: /Sign in with Face ID/ })).toBeInTheDocument()
  expect(router.state.location.search).toBe('')
})

it('signed out after a failed server logout: error and a Retry button', () => {
  const retry = vi.fn(async () => {})
  session.logoutFailed = true
  session.retryLogout = retry
  at('/', 'signedOut')
  expect(screen.getByRole('alert')).toHaveTextContent('Couldn’t end the session on the server. Try again.')
  act(() => screen.getByRole('button', { name: 'Retry' }).click())
  expect(retry).toHaveBeenCalled()
  session.logoutFailed = false
})

it('starts the offline replay triggers only while signed in, and stops them on unmount', () => {
  at('/', 'signedOut')
  expect(start).not.toHaveBeenCalled()
  cleanup()
  at('/', 'signedIn')
  expect(start).toHaveBeenCalledTimes(1)
  cleanup()
  expect(stop).toHaveBeenCalledTimes(1)
})
