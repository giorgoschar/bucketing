import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: vi.fn() }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('../../pwa/pushClient', () => ({
  usePushState: () => ({ state: 'off', refresh: vi.fn() }),
  enablePush: vi.fn(), disablePush: vi.fn(), sendTestPush: vi.fn(),
}))
const PREFS = { push_devices: 1, types: [
  { type: 'bill_due', group: 'Bills', label: 'Due in 3 days', enabled: true },
  { type: 'month_review', group: 'Insights', label: 'Month ready to review', enabled: true },
] }
vi.mock('./hooks', () => ({ useNotificationPrefs: () => query(PREFS) }))

import { Notifications } from './Notifications'

it('a group the screen has not seen before ("Insights") renders with its switch, from the server list', () => {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Notifications /></MemoryRouter></QueryClientProvider>)
  expect(screen.getByRole('heading', { name: 'Insights' })).toBeInTheDocument()
  const group = screen.getByRole('heading', { name: 'Insights' }).closest('section') as HTMLElement
  expect(within(group).getByRole('switch', { name: 'Month ready to review' })).toHaveAttribute('aria-checked', 'true')
})
