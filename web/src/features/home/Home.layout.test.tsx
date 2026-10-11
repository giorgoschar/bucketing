import { screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { monthPicture, page, readRoutes, txn } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Home } from './Home'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const eight = Array.from({ length: 8 }, (_, i) => txn({ id: `t${i}`, merchant: `Shop ${i}` }))
const routes = (): Routes => ({
  ...readRoutes(),
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/transactions': () => page(eight),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
})

it('asks for 5 recent transactions and shows 5 rows, with See all', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<Home />)
  const recent = await screen.findByRole('region', { name: 'Recent activity' })
  await within(recent).findByText('Shop 0')
  expect(recent.querySelectorAll('.ui-row')).toHaveLength(5)
  expect(within(recent).getByRole('link', { name: 'See all' })).toHaveAttribute('href', '/activity')
  expect(fake.calls.find((c) => c.path === '/api/v1/transactions')?.query.get('page_size')).toBe('5')
})

it('phone order is unchanged: hero, then Needs attention, then Recent, the last two inside the columns wrapper', async () => {
  fakeApi(routes())
  const { container } = renderWithProviders(<Home />)
  await screen.findByText('All clear')
  const cols = container.querySelector('.home__cols') as HTMLElement
  expect(cols).not.toBeNull()
  expect(Array.from(cols.children).map((c) => c.className)).toEqual(['home-attn', 'home-recent'])
  const home = container.querySelector('section.home') as HTMLElement
  expect(home.lastElementChild).toBe(cols)
  expect(home.querySelector('.home-hero')?.compareDocumentPosition(cols)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
})
