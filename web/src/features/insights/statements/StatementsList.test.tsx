import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { listMonth, listRoutes, statementList } from './fixtures'
import { StatementsList } from './StatementsList'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 2, 12))
})
afterEach(resetTestEnv)

const months = [
  listMonth(),
  listMonth({ month: '2026-08', label: 'August 2026', in: 3000, out: 3200, net: -200, reviewed_at: '2026-09-03T09:00:00', reviewed_on: '2026-09-03', closed: true }),
  listMonth({ month: '2026-07', label: 'July 2026', in: 0, out: 0, net: 0, closed: true }),
]

it('a row per month: label, In, Out and Net as signed text, linking to the statement', async () => {
  fakeApi(listRoutes(statementList({ months })))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  const aug = await screen.findByRole('link', { name: /August 2026/ })
  expect(aug).toHaveAttribute('href', '/insights/statements/2026-08')
  expect(aug).toHaveTextContent('In€3,000.00')
  expect(aug).toHaveTextContent('Out€3,200.00')
  expect(aug).toHaveTextContent('Net−€200.00')
  expect(screen.getByRole('link', { name: /September 2026/ })).toHaveTextContent('Net+€760.00')
})

it('a month with no data is listed with zeros', async () => {
  fakeApi(listRoutes(statementList({ months })))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  const jul = await screen.findByRole('link', { name: /July 2026/ })
  expect(jul).toHaveTextContent('In€0.00')
  expect(jul).toHaveTextContent('Net€0.00')
})

it('marks: Reviewed, Open for review, and none for a month that closed by itself', async () => {
  fakeApi(listRoutes(statementList({ months })))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  expect(within(await screen.findByRole('link', { name: /August 2026/ })).getByText('Reviewed')).toBeInTheDocument()
  expect(within(screen.getByRole('link', { name: /September 2026/ })).getByText('Open for review')).toBeInTheDocument()
  expect(within(screen.getByRole('link', { name: /July 2026/ })).queryByText(/Reviewed|Open for review/)).toBeNull()
})

it('the month in review is the first row, with "Review" and the days left', async () => {
  fakeApi(listRoutes(statementList({ review: { month: '2026-09', label: 'September 2026', days_left: 3 }, months })))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  await screen.findByRole('link', { name: /August 2026/ })
  const rows = screen.getAllByRole('link', { name: /20\d\d/ })
  expect(rows[0]).toHaveTextContent('September 2026')
  expect(within(rows[0]).getByText('Review')).toBeInTheDocument()
  expect(rows[0]).not.toHaveTextContent('days left')
  expect(within(rows[0]).queryByText('Open for review')).toBeNull()
})

it('the review month is moved to the top if the list does not have it first', async () => {
  fakeApi(listRoutes(statementList({ review: { month: '2026-08', label: 'August 2026', days_left: 1 }, months })))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  await screen.findByRole('link', { name: /July 2026/ })
  const rows = screen.getAllByRole('link', { name: /20\d\d/ })
  expect(rows.map((r) => r.getAttribute('href'))).toEqual([
    '/insights/statements/2026-08', '/insights/statements/2026-09', '/insights/statements/2026-07',
  ])
})

it('empty: "No past months yet."', async () => {
  fakeApi(listRoutes(statementList()))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  expect(await screen.findByText('No past months yet.')).toBeInTheDocument()
})

it('has one h1 and links back to Insights', async () => {
  fakeApi(listRoutes(statementList({ months })))
  renderWithProviders(<StatementsList />, { route: '/insights/statements' })
  await screen.findByRole('link', { name: /August 2026/ })
  expect(screen.getAllByRole('heading', { level: 1 }).map((h) => h.textContent)).toEqual(['Statements'])
  expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/insights')
})

it('offline with a saved copy: the rows and "Offline · showing saved statement"', async () => {
  const fake = fakeApi(listRoutes(statementList({ months })))
  const { unmount, client } = renderWithProviders(<StatementsList />)
  await screen.findByRole('link', { name: /August 2026/ })
  unmount()
  setOnline(false)
  fake.down()
  renderWithProviders(<StatementsList />, { client })
  expect(await screen.findByText('Offline · showing saved statement')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /August 2026/ })).toBeInTheDocument()
})

it('offline with nothing saved: an empty state, not a spinner', async () => {
  setOnline(false)
  fakeApi(listRoutes(statementList())).down()
  renderWithProviders(<StatementsList />)
  expect(await screen.findByText(/No saved statements yet/)).toBeInTheDocument()
})
