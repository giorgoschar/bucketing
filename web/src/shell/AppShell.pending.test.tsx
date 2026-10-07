import { act, cleanup, render, screen } from '@testing-library/react'
import { type JSX, lazy } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { isPending, markPending } from '../data/pending'
import type { Session } from '../session/SessionProvider'
import { AppShell } from './AppShell'

vi.mock('../offline/queue', () => ({ startReplayTriggers: () => () => {} }))
// The real bridge clears markers when the queue is empty; this test is about AppShell alone.
vi.mock('../data/queueBridge', () => ({ installQueueBridge: () => () => {} }))
const session: Session = { status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {} }
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(cleanup)

it('pending markers survive leaving for the composer (outside AppShell) and coming back; signing out clears them', async () => {
  session.status = 'signedIn'
  session.me = { id: '1', username: 'g', household_id: 'h', display_name: 'G', email: null, avatar_color: null }
  const router = createMemoryRouter(
    [
      { path: '/', element: <AppShell />, children: [{ index: true, element: <p>home screen</p> }] },
      { path: '/new', element: <p>composer</p> },
    ],
    { initialEntries: ['/'] },
  )
  render(<RouterProvider router={router} />)
  markPending('t1')
  await act(() => router.navigate('/new'))
  expect(screen.getByText('composer')).toBeInTheDocument()
  await act(() => router.navigate('/'))
  expect(screen.getByText('home screen')).toBeInTheDocument()
  expect(isPending('t1')).toBe(true)
  session.status = 'signedOut'
  await act(() => router.navigate('/?again')) // re-render AppShell with the new status
  expect(isPending('t1')).toBe(false)
})

it('a lazy-loaded tab (Plan) shows a loading placeholder inside the shell while its code loads', async () => {
  session.status = 'signedIn'
  let load!: (m: { default: () => JSX.Element }) => void
  const Lazy = lazy(() => new Promise<{ default: () => JSX.Element }>((r) => { load = r }))
  const router = createMemoryRouter(
    [{ path: '/', element: <AppShell />, children: [{ index: true, element: <Lazy /> }] }],
    { initialEntries: ['/'] },
  )
  render(<RouterProvider router={router} />)
  expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
  expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument() // the tab bar stays
  await act(async () => load({ default: () => <p>plan screen</p> }))
  expect(await screen.findByText('plan screen')).toBeInTheDocument()
})
