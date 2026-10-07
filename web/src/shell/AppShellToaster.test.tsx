import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { Session } from '../session/SessionProvider'
import { isPending, markPending } from '../data/pending'
import { dismissToast, toast } from '../ui/Toast'
import { AppShell } from './AppShell'

const stop = vi.fn()
const start = vi.fn(() => stop)
vi.mock('../offline/queue', () => ({ startReplayTriggers: () => start() }))

const session: Session = { status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {} }
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(() => {
  cleanup()
  dismissToast()
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

it('renders the toast region while signed in', () => {
  at('/', 'signedIn')
  act(() => toast('Saved'))
  expect(screen.getByText('Saved')).toBeInTheDocument()
  act(() => dismissToast())
})

it('the toast region sits outside <main>, so it never mixes with the page banners', () => {
  at('/?linked=1', 'signedIn')
  act(() => toast('Saved'))
  const regions = screen.getAllByRole('status')
  expect(regions).toHaveLength(2)
  expect(screen.getByRole('main')).not.toContainElement(screen.getByText('Saved'))
})

it('leaving the signed-in shell clears the pending markers', () => {
  at('/', 'signedIn')
  markPending('e1')
  cleanup()
  expect(isPending('e1')).toBe(false)
})
