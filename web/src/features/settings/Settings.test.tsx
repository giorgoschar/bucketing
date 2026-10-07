import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const signOut = vi.hoisted(() => vi.fn())
vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos', email: 'g@x.t' }, signOut }),
}))
vi.mock('../../pwa/pushClient', () => ({ usePushState: () => ({ state: 'on', refresh: vi.fn() }) }))
vi.mock('./hooks', () => ({
  useProfile: () => query({ id: 'me', username: 'g', display_name: 'Giorgos', email: 'g@x.t', avatar_color: '#6366f1', totp_enabled: true, household_id: 'hh1' }),
  useSecurity: () => query({ totp_enabled: true, backup_codes_remaining: 8, passkey_available: true, passkey_linked: true, password_session: true }),
  useHousehold: () => query({ id: 'hh1', name: 'Home', default_currency: 'EUR', members: [{ user_id: 'me' }, { user_id: 'm' }] }),
  useCategories: () => query(Array.from({ length: 11 }, (_, i) => ({ id: `c${i}` }))),
  useRules: () => query(Array.from({ length: 96 }, (_, i) => ({ id: `r${i}` }))),
  useTokens: () => query([{ id: 't1' }]),
  useNotificationPrefs: () => query({ types: Array.from({ length: 9 }, (_, i) => ({ type: `t${i}`, group: 'Bills', label: 'x', enabled: true })), push_devices: 1 }),
}))

import { TopBar } from '../../shell/TopBar'
import { Settings } from './Settings'
import { buildString, hubSubtitles } from './subtitles'

const renderHub = () => render(
  <QueryClientProvider client={new QueryClient()}><MemoryRouter><Settings /></MemoryRouter></QueryClientProvider>,
)

describe('Settings hub', () => {
  it('shows live subtitles and links to each screen', () => {
    renderHub()
    for (const [name, sub, href] of [
      ['Profile & security', '2FA on · passkey linked', '/settings/profile'],
      ['Household', 'Home · 2 members · EUR', '/settings/household'],
      ['Categories & rules', '11 categories · 96 rules', '/settings/categories'],
      ['Automations', 'Apple Pay Shortcut · 1 token', '/settings/automations'],
      ['Notifications', 'Push on · 9 of 9 alerts', '/settings/notifications'],
    ]) {
      const link = screen.getByRole('link', { name: new RegExp(name) })
      expect(link).toHaveAttribute('href', href)
      expect(link).toHaveTextContent(sub)
    }
  })

  it('the identity card opens the profile', () => {
    renderHub()
    expect(screen.getByRole('link', { name: /Your profile/ })).toHaveAttribute('href', '/settings/profile')
  })

  it('signs out', () => {
    renderHub()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(signOut).toHaveBeenCalled()
  })
})

describe('account sheet', () => {
  it('has a Settings entry', () => {
    render(<MemoryRouter><TopBar title="Home" /></MemoryRouter>)
    expect(screen.getByRole('link', { name: 'Settings', hidden: true })).toHaveAttribute('href', '/settings')
  })
})

describe('hubSubtitles', () => {
  it('copes with missing data and the mutes API not being there yet', () => {
    const s = hubSubtitles({ push: 'off', prefs: null, tokens: [], security: { totp_enabled: false, backup_codes_remaining: 0, passkey_available: false, passkey_linked: false, password_session: true } })
    expect(s.profile).toBe('2FA off')
    expect(s.automations).toBe('Apple Pay Shortcut · no tokens')
    expect(s.notifications).toBe('Push off')
    expect(s.household).toBe('')
  })
  it('reads the build from the script name', () => {
    expect(buildString('https://x.test/app/assets/index-Ab12Cd.js')).toBe('Build Ab12Cd')
    expect(buildString('https://x.test/src/main.tsx')).toBe('Build dev')
  })
})
