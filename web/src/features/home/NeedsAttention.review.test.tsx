import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { day, entry, readRoutes } from '../../test/fixtures'
import { installMemoryStorage } from '../../test/storage'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { billRow, billsRoutes, change } from '../insights/bills/fixtures'
import { listMonth, listRoutes, statementList } from '../insights/statements/fixtures'
import { buildAttention } from './attention'
import { resetBillDismissals } from './billDismiss'
import { NeedsAttention } from './NeedsAttention'

installMemoryStorage()
beforeEach(() => {
  resetBillDismissals()
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 2, 12))
})
afterEach(resetTestEnv)

const review = { month: '2026-09', label: 'September 2026', days_left: 3 }
const routes = (list: Parameters<typeof listRoutes>[0] | null, over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [day('2026-10-04', [entry({ id: 'e5', name: 'Gym', estimated: true, amount: 30 })], 900)],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
  ...billsRoutes([billRow({ change: change({ entry_id: 'e9' }) })]),
  ...(list ? listRoutes(list) : {}),
  ...over,
})
const kinds = () => Array.from(document.querySelectorAll('[data-attn]')).map((n) => n.getAttribute('data-attn'))

it('"Review September" is the first row, and Review opens the statement', async () => {
  fakeApi(routes(statementList({ review, months: [listMonth()] })))
  const { router } = renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['monthReview', 'missingAmount', 'billChange']))
  expect(document.querySelector('[data-attn="monthReview"]')).toHaveTextContent('Review September')
  fireEvent.click(screen.getByRole('button', { name: 'Review' }))
  expect(router.state.location.pathname).toBe('/insights/statements/2026-09')
})

it('no row when the review is null (no data, reviewed, or outside the window)', async () => {
  fakeApi(routes(statementList({ review: null, months: [] })))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['missingAmount', 'billChange']))
  expect(screen.queryByText(/Review September/)).toBeNull()
})

it('no row and no error when the list is not cached and cannot load', async () => {
  fakeApi(routes(null))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['missingAmount', 'billChange']))
  expect(screen.queryByText(/Review|Couldn/)).toBeNull()
})

it('does not hold back "All clear" while the list loads', async () => {
  fakeApi(routes(null, {
    'GET /api/v1/plan/upcoming': () => [], ...billsRoutes([]),
  }))
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByText('All clear')).toBeInTheDocument()
})

it('comes before every other row (pure order)', () => {
  const order = buildAttention({
    today: '2026-10-02', failed: [], cashNotLogged: 12, review,
    bills: [billRow({ change: change() })],
    upcoming: [day('2026-10-04', [entry({ estimated: true })], 0)],
  }).map((i) => i.kind)
  expect(order).toEqual(['monthReview', 'missingAmount', 'billChange', 'cash'])
  expect(buildAttention({ today: '2026-10-02', failed: [], review: null }).map((i) => i.kind)).toEqual([])
  expect(buildAttention({ today: '2026-10-02', failed: [] }).map((i) => i.kind)).toEqual([])
})
