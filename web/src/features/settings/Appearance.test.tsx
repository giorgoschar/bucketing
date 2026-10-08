import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'
import { installMemoryStorage } from '../../test/storage'
import { THEME_KEY, bootTheme, setTheme } from '../../shell/theme'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))
vi.mock('../../pwa/pushClient', () => ({ usePushState: () => ({ state: 'on', refresh: vi.fn() }) }))
vi.mock('./hooks', () => ({
  useProfile: () => query(undefined), useSecurity: () => query(undefined), useHousehold: () => query(undefined),
  useCategories: () => query(undefined), useRules: () => query(undefined), useTokens: () => query(undefined),
  useNotificationPrefs: () => query(undefined),
}))

import { Appearance } from './Appearance'
import { Settings } from './Settings'

installMemoryStorage()
afterEach(() => {
  cleanup()
  setTheme('system')
})

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient()}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>,
)
const html = () => document.documentElement

describe('Settings › Appearance', () => {
  it('the hub has an Appearance row showing the current choice', () => {
    wrap(<Settings />)
    const row = screen.getByRole('link', { name: /Appearance/ })
    expect(row).toHaveAttribute('href', '/settings/appearance')
    expect(row).toHaveTextContent('System')
  })

  it('a segmented System / Light / Dark that applies at once and is saved on this device', () => {
    wrap(<Appearance />)
    const group = screen.getByRole('group', { name: 'Appearance' })
    expect([...group.querySelectorAll('button')].map((b) => b.textContent)).toEqual(['System', 'Light', 'Dark'])
    expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Dark' }))
    expect(html().getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'Light' }))
    expect(html().getAttribute('data-theme')).toBe('light')

    fireEvent.click(screen.getByRole('button', { name: 'System' }))
    expect(html().hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
  })

  it('after a reload the saved choice is shown and applied', () => {
    localStorage.setItem(THEME_KEY, 'light')
    bootTheme()
    wrap(<Appearance />)
    expect(screen.getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'true')
    expect(html().getAttribute('data-theme')).toBe('light')
  })
})
