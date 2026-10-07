import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cachePut } from '../../offline/db'
import { cacheKeyFor } from '../../data/cachedQuery'
import { keys } from '../../data/keys'
import { setIdentity } from '../../offline/identity'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { monthPicture, page, readRoutes, txn } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline, TEST_IDENTITY } from '../../test/render'
import { Home } from './Home'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const recent = [
  txn(),
  txn({ id: 't2', type: 'income', amount: 2450, merchant: null, notes: 'Salary', bucket_id: null, transaction_date: '2026-10-01' }),
]
const routes = (): Routes => ({
  ...readRoutes(),
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/transactions': () => page(recent),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
})

it('leads with the projected net and what came in and went out so far', async () => {
  fakeApi(routes())
  renderWithProviders(<Home />)
  expect(screen.getByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
  expect(screen.getByText(/October · projected/)).toBeInTheDocument()
  expect(screen.getByText(/so far ·/).closest('p')).toHaveTextContent('In €3,150.00 so far · Out €1,285.00 so far')
})

it('lists recent activity read-only, signed, with the bucket, and links to Activity', async () => {
  fakeApi(routes())
  renderWithProviders(<Home />)
  const recentSection = await screen.findByRole('region', { name: 'Recent activity' })
  const sklav = (await within(recentSection).findByText('Sklavenitis')).closest('.ui-row')!
  expect(sklav.tagName).toBe('DIV')
  expect(sklav).toHaveTextContent('6 Oct · Day to day')
  expect(sklav).toHaveTextContent('−€64.20')
  expect(within(recentSection).getByText('Salary').closest('.ui-row')).toHaveTextContent('+€2,450.00')
  expect(within(recentSection).getByRole('link', { name: 'See all' })).toHaveAttribute('href', '/activity')
  expect(await screen.findByText('All clear')).toBeInTheDocument()
})

it('offline with a saved month: shows it once with the banner', async () => {
  setIdentity(TEST_IDENTITY)
  await cachePut(cacheKeyFor('h1', keys.plan.month('2026-10')), monthPicture())
  await cachePut(cacheKeyFor('h1', keys.transactions.recent()), recent)
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<Home />)
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
  expect(await screen.findByText('Sklavenitis')).toBeInTheDocument()
  expect(screen.getAllByText(/Offline · updated/)).toHaveLength(1)
})
