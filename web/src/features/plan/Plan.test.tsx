import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { budgetRow, categoryUsual, day, entry, monthPicture, readRoutes, shoppingOut, yearMonth, yearOut } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Plan } from './Plan'

afterEach(resetTestEnv)

const routes = () => ({
  ...readRoutes(),
  'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry()], 961.1)],
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/insights/categories-vs-usual': () => [categoryUsual()],
  'GET /api/v1/plan/year': () => yearOut([yearMonth('2026-10', 3000, 1500)]),
  'GET /api/v1/plan/budgets': () => [budgetRow()],
  'GET /api/v1/plan/pace': () => [],
})

it('opens on Upcoming and switches views through the URL', async () => {
  fakeApi(routes())
  const { router } = renderWithProviders(<Plan />, { route: '/plan' })
  expect(screen.getByRole('heading', { level: 1, name: 'Plan' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Upcoming' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByRole('region', { name: 'Fri 9 Oct' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Budgets' }))
  expect(router.state.location.search).toBe('?view=budgets')
  expect(await screen.findByRole('progressbar', { name: 'Day to day' })).toBeInTheDocument()
  // Year folded into Month (cash spec §4.1): Month, then its Year scale.
  fireEvent.click(within(screen.getByRole('group', { name: 'Plan view' })).getByRole('button', { name: 'Month' }))
  fireEvent.click(screen.getByRole('button', { name: 'Year' }))
  expect(await screen.findByText(/Yearly and quarterly bills average/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Upcoming' }))
  expect(router.state.location.search).toBe('')
})

it('has an Items link in the top bar', () => {
  fakeApi(routes())
  renderWithProviders(<Plan />, { route: '/plan?view=month' })
  expect(within(screen.getByRole('group', { name: 'Plan view' })).getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('link', { name: 'Items' })).toHaveAttribute('href', '/plan/items')
})

const planView = () => within(screen.getByRole('group', { name: 'Plan view' }))

it('the segments read exactly Upcoming, Month, Budgets, Cash, Pantry', () => {
  fakeApi(routes())
  renderWithProviders(<Plan />, { route: '/plan' })
  expect(planView().getAllByRole('button').map((b) => b.textContent)).toEqual(['Upcoming', 'Month', 'Budgets', 'Cash', 'Pantry'])
})

it('?view=pantry opens Pantry', async () => {
  fakeApi({ ...routes(), 'GET /api/v1/stock': () => [], 'GET /api/v1/stock/shopping': () => shoppingOut({ items: [], groups: [], lines: [] }) })
  const { router } = renderWithProviders(<Plan />, { route: '/plan' })
  fireEvent.click(planView().getByRole('button', { name: 'Pantry' }))
  expect(router.state.location.search).toBe('?view=pantry')
  expect(planView().getByRole('button', { name: 'Pantry' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByText('Nothing in your pantry yet')).toBeInTheDocument()
})

it('?view=year resolves to Month with the Year scale and shows Year', async () => {
  fakeApi(routes())
  renderWithProviders(<Plan />, { route: '/plan?view=year' })
  expect(planView().getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true')
  const scale = within(screen.getByRole('group', { name: 'Month or year' }))
  expect(scale.getByRole('button', { name: 'Year' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByText(/Yearly and quarterly bills average/)).toBeInTheDocument()
})

it('the Month | Year switch sets scale=year and drops it again for Month', async () => {
  fakeApi(routes())
  const { router } = renderWithProviders(<Plan />, { route: '/plan?view=month' })
  const scale = () => within(screen.getByRole('group', { name: 'Month or year' }))
  expect(scale().getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(scale().getByRole('button', { name: 'Year' }))
  expect(router.state.location.search).toBe('?view=month&scale=year')
  expect(await screen.findByText(/Yearly and quarterly bills average/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Next month' })).not.toBeInTheDocument()
  fireEvent.click(scale().getByRole('button', { name: 'Month' }))
  expect(router.state.location.search).toBe('?view=month')
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
})

it('?view=cash shows the Cash screen', () => {
  fakeApi(routes())
  renderWithProviders(<Plan />, { route: '/plan?view=cash' })
  expect(planView().getByRole('button', { name: 'Cash' })).toHaveAttribute('aria-pressed', 'true')
  expect(document.querySelector('.cash')).not.toBeNull()
})
