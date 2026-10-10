import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { categoryUsual, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { installMemoryStorage } from '../../test/storage'
import { DESKTOP_QUERY } from '../../ui/useIsDesktop'
import { billRow, billsRoutes, change } from './bills/fixtures'
import { makeInsights } from './fixtures'

installMemoryStorage()
vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'u1', household_id: 'h1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))

import { Insights } from './Insights'

const MONTHS = ['Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
const twelve = MONTHS.map((label, i) => ({
  year: i < 2 ? 2025 : 2026, month: ((i + 10) % 12) + 1, label, in: 3000, out: i === 11 ? 3100 : 2000, net: i === 11 ? -100 : 1000,
}))

function stubDesktop(on: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() { return on && query === DESKTOP_QUERY }, media: query, addEventListener: () => {}, removeEventListener: () => {},
  }))
}

const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/insights': (req) => (req.query.get('months') === '12' ? makeInsights({ monthly_in_out: twelve }) : makeInsights()),
  'GET /api/v1/insights/categories-vs-usual': () => [
    categoryUsual({ category_id: 'g', name: 'Groceries', this_month: 362.4, usual: 300 }),
    categoryUsual({ category_id: 'x', name: 'Other', this_month: 10, usual: 30, flagged: false }),
  ],
  ...billsRoutes(Array.from({ length: 10 }, (_, i) => billRow({ item_id: `i${i}`, name: `Bill ${i}`, total_12m: 1000 - i, change: i === 0 ? change() : null }))),
  ...over,
})

beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date(2026, 9, 7, 12)) })
afterEach(async () => { vi.unstubAllGlobals(); await resetTestEnv() })

it('phone: the screen is as before plus the Bills card, and no request carries months=12', async () => {
  const fake = fakeApi(routes())
  const { container } = renderWithProviders(<Insights />, { route: '/insights' })
  await screen.findByRole('region', { name: 'Bills' })
  expect(fake.callsTo('GET /api/v1/insights').every((c) => !c.query.has('months'))).toBe(true)
  expect(screen.queryByRole('table', { name: 'Last 12 months' })).toBeNull()
  expect(screen.queryByRole('table', { name: 'Categories' })).toBeNull()
  expect(container.querySelector('[data-widget="billsPanel"]')).toBeNull()
  // The Bills card shows three rows, not the panel's eight.
  expect(within(screen.getByRole('region', { name: 'Bills' })).getAllByRole('link', { name: /Bill \d/ })).toHaveLength(3)
})

it('desktop: the Bills panel (up to 8 rows), the 12-month table and the categories table', async () => {
  stubDesktop(true)
  const fake = fakeApi(routes())
  renderWithProviders(<Insights />, { route: '/insights' })
  const panel = await screen.findByRole('region', { name: 'Bills' })
  expect(within(panel).getAllByRole('link', { name: /Bill \d/ })).toHaveLength(8)
  expect(within(panel).getByRole('link', { name: 'All bills' })).toHaveAttribute('href', '/insights/bills')
  await screen.findByRole('table', { name: 'Last 12 months' })
  await screen.findByRole('table', { name: 'Categories' })
  expect(fake.callsTo('GET /api/v1/insights').some((c) => c.query.get('months') === '12')).toBe(true)
  expect(fake.callsTo('GET /api/v1/insights').some((c) => !c.query.has('months'))).toBe(true)
})

it('the months table has Month, In, Out and Net, the net with its sign as text', async () => {
  stubDesktop(true)
  fakeApi(routes())
  renderWithProviders(<Insights />, { route: '/insights' })
  const table = await screen.findByRole('table', { name: 'Last 12 months' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Month', 'In', 'Out', 'Net'])
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows).toHaveLength(12)
  expect(rows[0]).toHaveTextContent('Nov')
  expect(rows[0]).toHaveTextContent('+€1,000.00')
  expect(rows[11]).toHaveTextContent('Oct')
  expect(rows[11]).toHaveTextContent('−€100.00')
})

it('the categories table lists every category with its amount, share and against-usual', async () => {
  stubDesktop(true)
  fakeApi(routes())
  renderWithProviders(<Insights />, { route: '/insights' })
  const table = await screen.findByRole('table', { name: 'Categories' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Category', 'Amount', 'Share', 'Against usual'])
  const rows = within(table).getAllByRole('row').slice(1)
  expect(rows).toHaveLength(3) // Groceries, Uncategorised and the cash row: every category, not the top few
  await waitFor(() => expect(rows[0]).toHaveTextContent('€62.40 above usual'))
  expect(rows[0]).toHaveTextContent('Groceries')
  expect(rows[0]).toHaveTextContent('€362.40')
  expect(rows[0]).toHaveTextContent('28%')
  expect(within(rows[0]).getByRole('link', { name: /Groceries/ })).toHaveAttribute('href', expect.stringContaining('/insights/category/g'))
  expect(rows[1]).toHaveTextContent('—') // no usual for Uncategorised
})

it('desktop: the lens sits in the same row as the period controls', async () => {
  stubDesktop(true)
  fakeApi(routes())
  const { container } = renderWithProviders(<Insights />, { route: '/insights' })
  const lens = await screen.findByRole('radiogroup', { name: 'Whose spending' })
  expect(container.querySelector('.insights__bar')?.contains(lens)).toBe(true)
})

it('phone: the lens stays where it was, under the period bar', async () => {
  fakeApi(routes())
  const { container } = renderWithProviders(<Insights />, { route: '/insights' })
  const lens = await screen.findByRole('radiogroup', { name: 'Whose spending' })
  expect(container.querySelector('.insights__bar')?.contains(lens)).toBe(false)
})

it('the screen asks for the wide column', async () => {
  fakeApi(routes())
  const { container } = renderWithProviders(<Insights />, { route: '/insights' })
  await screen.findByRole('region', { name: 'Bills' })
  expect(container.querySelector('section.insights')).toHaveClass('shell__main--wide')
})

it('F7: the panel lists paused bills when nothing is active, not the empty copy', async () => {
  stubDesktop(true)
  fakeApi(routes({ ...billsRoutes([billRow({ name: 'Old gym', is_active: false })]) }))
  renderWithProviders(<Insights />, { route: '/insights' })
  const panel = await screen.findByRole('region', { name: 'Bills' })
  await within(panel).findByRole('link', { name: /Old gym/ })
  expect(within(panel).queryByText(/No recurring bills yet/)).toBeNull()
})

it('F2: an empty period still shows the Bills card (phone) and panel (desktop)', async () => {
  const empty = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0 } })
  fakeApi(routes({ 'GET /api/v1/insights': () => empty }))
  renderWithProviders(<Insights />, { route: '/insights' })
  expect(await screen.findByText('No spending in this period')).toBeInTheDocument()
  expect(await screen.findByRole('region', { name: 'Bills' })).toBeInTheDocument()
})
