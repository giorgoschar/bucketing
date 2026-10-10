import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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
  { type: 'x_new', group: 'Zebra alerts', label: 'Something new', enabled: true },
  { type: 'ingest_created', group: 'Apple Pay', label: 'Each new purchase', enabled: true },
  { type: 'month_review', group: 'Insights', label: 'Month ready to review', enabled: true },
  { type: 'bill_due', group: 'Bills', label: 'Due in 3 days', enabled: true },
] }
vi.mock('./hooks', () => ({ useNotificationPrefs: () => query(PREFS) }))

import { Notifications } from './Notifications'

it('renders every group the server sends: known ones first in their order, unknown ones after', () => {
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Notifications /></MemoryRouter></QueryClientProvider>)
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Bills', 'Insights', 'Apple Pay', 'Zebra alerts'])
  expect(screen.getByRole('switch', { name: 'Something new' })).toBeInTheDocument()
})
