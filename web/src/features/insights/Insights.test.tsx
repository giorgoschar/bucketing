import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../../test/storage'
import { makeInsights, query } from './fixtures'

installMemoryStorage()

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))
const hooks = vi.hoisted(() => ({
  useInsights: vi.fn(), usePersonShare: vi.fn(), useMembers: vi.fn(), useCategoriesVsUsual: vi.fn(), usePlanMonth: vi.fn(), useHouseholdId: () => 'hh1',
}))
vi.mock('./hooks', () => hooks)
vi.mock('../settings/hooks', () => ({
  useBuckets: () => query([{ id: 'b1', name: 'Daily' }]),
  useCategories: () => query([]),
}))

import { Insights } from './Insights'

const MEMBERS = { id: 'hh1', name: 'Home', default_currency: 'EUR', members: [
  { user_id: 'me', role: 'owner', joined_at: null, display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'm', role: 'member', joined_at: null, display_name: 'Maria', username: 'maria', avatar_color: null },
] }

function renderAt(url: string) {
  const qc = new QueryClient()
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}><MemoryRouter initialEntries={[url]}>{children}</MemoryRouter></QueryClientProvider>
  )
  return render(<Insights />, { wrapper: wrap })
}

beforeEach(() => {
  hooks.useInsights.mockReturnValue(query(makeInsights()))
  hooks.usePersonShare.mockReturnValue(query(null))
  hooks.useMembers.mockReturnValue(query(MEMBERS))
  hooks.useCategoriesVsUsual.mockReturnValue(query([]))
  hooks.usePlanMonth.mockReturnValue(query(undefined))
})

const order = (c: HTMLElement) => [...c.querySelectorAll('[data-widget]')].map((e) => e.getAttribute('data-widget'))

describe('Insights', () => {
  it('renders the widgets in the fixed order with the headline', () => {
    const { container } = renderAt('/insights')
    expect(order(container)[0]).toBe('headline')
    expect(screen.getByText('Spent · Oct 1 – 6')).toBeInTheDocument()
    expect(screen.getByText('−8% vs the previous period')).toBeInTheDocument()
  })

  it('the lens is a labelled group of Household, Me and Maria', () => {
    renderAt('/insights')
    expect(screen.getByRole('radiogroup', { name: 'Whose spending' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Maria' })).toBeInTheDocument()
  })

  it('arrow keys move the lens', () => {
    renderAt('/insights')
    fireEvent.keyDown(screen.getByRole('radio', { name: 'Household' }), { key: 'ArrowRight' })
    expect(screen.getByRole('radio', { name: 'Me' })).toHaveAttribute('aria-checked', 'true')
  })

  it('a member lens shows identity, the share card and its sentence', () => {
    hooks.usePersonShare.mockReturnValue(query({ user_id: 'm', paid_out: 600, my_share: 458.8, balance: 141.2, share_pct: 36, household_total: 1284.6, largest: null, shared_count: 4, transaction_count: 31 }))
    const { container } = renderAt('/insights?lens=m')
    expect(order(container).slice(0, 3)).toEqual(['identity', 'headline', 'share'])
    expect(screen.getByText('Maria paid €141.20 more than their share this month')).toBeInTheDocument()
    expect(hooks.usePersonShare).toHaveBeenLastCalledWith({ preset: 'this_month' }, 'm')
  })

  it('the share card fails on its own with Retry', () => {
    const refetch = vi.fn()
    hooks.usePersonShare.mockReturnValue(query(undefined, { isError: true, refetch }))
    renderAt('/insights?lens=m')
    expect(screen.getByText("Couldn't load this")).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(refetch).toHaveBeenCalled()
    expect(screen.getByText('Spent · Oct 1 – 6')).toBeInTheDocument() // the rest renders
  })

  it('an empty period links to the previous one when it had spending', () => {
    hooks.useInsights.mockReturnValue(query(makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, total: 0, previous_total: 900 } })))
    renderAt('/insights')
    expect(screen.getByText('No spending in this period')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'See the previous period' }))
    expect(screen.getByRole('button', { name: 'Last month' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('offline without cache says so', () => {
    hooks.useInsights.mockReturnValue(query(undefined, { noData: true, offline: true, isLoading: false }))
    renderAt('/insights')
    expect(screen.getByText('No saved data yet. Connect once to load Insights.')).toBeInTheDocument()
  })

  it('another view never loaded says so', () => {
    hooks.useInsights.mockReturnValue(query(undefined, { noData: true, offline: true, isLoading: false }))
    renderAt('/insights?p=last_month')
    expect(screen.getByText('No saved data for this view. Connect once to load it.')).toBeInTheDocument()
  })

  it('Filters opens the sheet, and URL filters reach the query', () => {
    renderAt('/insights?bucket_ids=b1')
    expect(hooks.useInsights).toHaveBeenLastCalledWith({ preset: 'this_month' }, 'household', { bucketIds: ['b1'], categoryIds: [] })
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
    expect(screen.getByRole('dialog', { name: 'Filters' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Daily' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('the Custom chip opens the sheet and Apply sets a custom period', () => {
    renderAt('/insights')
    fireEvent.click(screen.getByRole('button', { name: 'Custom' }))
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(hooks.useInsights).toHaveBeenLastCalledWith({ preset: 'custom', from: '2026-10-01', to: '2026-10-06' }, 'household', { bucketIds: [], categoryIds: [] })
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
