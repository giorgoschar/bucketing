import { fireEvent, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { budgetRow, categoryUsual, day, entry, monthPicture, readRoutes, yearMonth, yearOut } from '../../test/fixtures'
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
  fireEvent.click(screen.getByRole('button', { name: 'Year' }))
  expect(await screen.findByText(/Yearly and quarterly bills average/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Upcoming' }))
  expect(router.state.location.search).toBe('')
})

it('has an Items link in the top bar', () => {
  fakeApi(routes())
  renderWithProviders(<Plan />, { route: '/plan?view=month' })
  expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('link', { name: 'Items' })).toHaveAttribute('href', '/plan/items')
})
