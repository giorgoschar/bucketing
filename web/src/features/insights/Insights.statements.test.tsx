import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../../test/storage'
import { makeInsights, query } from './fixtures'
import { listMonth, statementList } from './statements/fixtures'

installMemoryStorage()

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))
const hooks = vi.hoisted(() => ({
  useInsights: vi.fn(), usePersonShare: vi.fn(), useMembers: vi.fn(), useCategoriesVsUsual: vi.fn(), usePlanMonth: vi.fn(), useHouseholdId: () => 'hh1',
}))
vi.mock('./hooks', () => hooks)
vi.mock('./bills/hooks', () => ({ useBills: () => query([]) }))
vi.mock('./statements/hooks', () => ({ useStatements: () => query(statementList({ months: [listMonth()] })) }))
vi.mock('../settings/hooks', () => ({ useBuckets: () => query([]), useCategories: () => query([]) }))

import { Insights } from './Insights'

beforeEach(() => {
  hooks.useInsights.mockReturnValue(query(makeInsights()))
  hooks.usePersonShare.mockReturnValue(query(null))
  hooks.useMembers.mockReturnValue(query({ id: 'hh1', name: 'Home', default_currency: 'EUR', members: [] }))
  hooks.useCategoriesVsUsual.mockReturnValue(query([]))
  hooks.usePlanMonth.mockReturnValue(query(undefined))
})

const renderIt = () => render(
  <QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={['/insights']}><Insights /></MemoryRouter></QueryClientProvider>,
)

it('the Statements card is on the Insights screen, after the Bills card', () => {
  const { container } = renderIt()
  const order = [...container.querySelectorAll('[data-widget]')].map((e) => e.getAttribute('data-widget'))
  expect(order.indexOf('statements')).toBe(order.indexOf('bills') + 1)
  expect(within(screen.getByRole('region', { name: 'Statements' })).getByRole('link', { name: /September 2026/ })).toBeInTheDocument()
})

it('and in an empty period too', () => {
  const base = makeInsights()
  hooks.useInsights.mockReturnValue(query(makeInsights({
    total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...base.kpis, count: 0 },
  })))
  const { container } = renderIt()
  expect(container.querySelector('[data-widget="empty"]')).not.toBeNull()
  expect(screen.getByRole('region', { name: 'Statements' })).toBeInTheDocument()
})
