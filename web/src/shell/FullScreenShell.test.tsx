import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { Session } from '../session/SessionProvider'
import { FullScreenShell } from './FullScreenShell'

const stop = vi.fn()
const start = vi.fn(() => stop)
vi.mock('../offline/queue', () => ({ startReplayTriggers: () => start() }))
const bridgeStop = vi.fn()
vi.mock('../data/queueBridge', () => ({ installQueueBridge: () => bridgeStop }))

const session: Session = { status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {} }
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(() => {
  cleanup()
  start.mockClear()
  stop.mockClear()
  bridgeStop.mockClear()
})

function at(status: Session['status']) {
  session.status = status
  const router = createMemoryRouter(
    [{ element: <FullScreenShell />, children: [{ path: '/new', element: <p>composer</p> }] }],
    { initialEntries: ['/new'] },
  )
  render(<RouterProvider router={router} />)
}

it('signed in: renders the child with no tab bar, starts the replay triggers and the queue bridge', () => {
  at('signedIn')
  expect(screen.getByText('composer')).toBeInTheDocument()
  expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  expect(start).toHaveBeenCalledTimes(1)
  cleanup()
  expect(stop).toHaveBeenCalledTimes(1)
  expect(bridgeStop).toHaveBeenCalledTimes(1)
})

it('signed out: the sign-in screen, never the composer', () => {
  at('signedOut')
  expect(screen.queryByText('composer')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Sign in with Face ID/ })).toBeInTheDocument()
  expect(start).not.toHaveBeenCalled()
})

it('loading: a blank boot screen', () => {
  at('loading')
  expect(screen.queryByText('composer')).not.toBeInTheDocument()
})
