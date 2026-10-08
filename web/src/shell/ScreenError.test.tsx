import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { lazy, type ReactElement } from 'react'
import { createMemoryRouter, RouterProvider, type RouteObject } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Session } from '../session/SessionProvider'
import { AppShell } from './AppShell'
import { ScreenError } from './ScreenError'

vi.mock('../offline/queue', () => ({ startReplayTriggers: () => () => {} }))
const session: Session = {
  status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {},
  me: { id: '1', username: 'g', household_id: 'h', display_name: 'G', email: null, avatar_color: null },
}
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// A lazy screen whose chunk 404s after a deploy (P3 final review M2).
const Broken = lazy(() => Promise.reject(new TypeError('Failed to fetch dynamically imported module: /app/assets/Settings-x.js')))

describe('a screen that fails to load', () => {
  it('shows "This screen didn’t load" with Reload, and the tab bar stays', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const reload = vi.fn()
    vi.spyOn(window, 'location', 'get').mockReturnValue({ ...window.location, reload } as Location)
    const router = createMemoryRouter(
      [{ path: '/', element: <AppShell />, children: [{ path: 'settings', element: <Broken />, errorElement: <ScreenError /> }] }],
      { initialEntries: ['/settings'] },
    )
    render(<RouterProvider router={router} />)
    expect(await screen.findByText('This screen didn’t load')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('every screen route in the app router has it, under the shell (so the tab bar stays)', async () => {
    const { router } = await import('../router')
    const children = (r: RouteObject) => r.children ?? []
    const screens = [...children(router.routes[0]), ...children(router.routes[1])]
    expect(screens.length).toBeGreaterThan(10)
    for (const r of screens) {
      expect((r.errorElement as ReactElement | undefined)?.type, r.path ?? '(index)').toBe(ScreenError)
    }
  })
})
