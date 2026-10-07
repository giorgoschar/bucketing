import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../../test/storage'
import { formatShortDate } from '../../ui/format'
import { makeInsights, query } from './fixtures'

installMemoryStorage()
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
const hooks = vi.hoisted(() => ({ useCategoryDetail: vi.fn(), useInsights: vi.fn(), useMembers: vi.fn(), useHouseholdId: () => 'hh1' }))
vi.mock('./hooks', () => hooks)

import { CategoryScreen } from './CategoryScreen'
import { FuelScreen } from './FuelScreen'

const DETAIL = {
  category: { id: 'g', name: 'Groceries', icon: '🛒', color: '#10b981' },
  total: 362.4, count: 12, avg_per_month: 395,
  months: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'].map((label, i) => ({ year: 2026, month: i + 5, label, total: [402, 388, 371, 356, 458, 362.4][i] })),
  merchants: [{ merchant: 'Sklavenitis', count: 6, total: 210 }, { merchant: 'Other', count: 1, total: 5 }],
  recent: [{ id: 't1', date: '2026-10-05', merchant: 'Lidl', notes: null, amount: 40, paid_by: 'm' }],
  rules: [{ id: 'r1', pattern: 'sklaven', match_count: 48 }],
}

const at = (url: string, path: string, el: ReactElement) => render(
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={[url]}><Routes><Route path={path} element={el} /></Routes></MemoryRouter>
  </QueryClientProvider>,
)

beforeEach(() => {
  hooks.useMembers.mockReturnValue(query({ members: [{ user_id: 'm', role: 'member', display_name: 'Maria', username: 'maria', avatar_color: null }] }))
  hooks.useCategoryDetail.mockReturnValue(query(DETAIL))
  hooks.useInsights.mockReturnValue(query(makeInsights()))
})

describe('CategoryScreen', () => {
  it('shows the total, average, months, shops, rules and recent expenses', () => {
    at('/insights/category/g?p=last_month&lens=m', '/insights/category/:id', <CategoryScreen />)
    expect(hooks.useCategoryDetail).toHaveBeenCalledWith('g', { preset: 'last_month' }, 'm')
    expect(screen.getByRole('heading', { name: 'Groceries', level: 1 })).toBeInTheDocument()
    expect(screen.getByText('Average €395.00/mo')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Groceries per month' })).toBeInTheDocument()
    expect(screen.getByText('Sklavenitis')).toBeInTheDocument()
    expect(screen.getByText('sklaven 48')).toBeInTheDocument()
    expect(screen.getByText(`Maria · ${formatShortDate('2026-10-05')}`)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Edit rules' })).toHaveAttribute('href', '/settings/categories')
    expect(screen.queryByRole('link', { name: 'See all' })).toBeNull() // until 2c ships Activity
  })

  it('names uncategorised', () => {
    hooks.useCategoryDetail.mockReturnValue(query({ ...DETAIL, category: null, rules: [] }))
    at('/insights/category/uncategorised', '/insights/category/:id', <CategoryScreen />)
    expect(screen.getByRole('heading', { name: 'Uncategorised', level: 1 })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit rules' })).toBeNull()
  })

  it('the period chips change the period', () => {
    at('/insights/category/g', '/insights/category/:id', <CategoryScreen />)
    fireEvent.click(screen.getByRole('button', { name: 'Last month' }))
    expect(hooks.useCategoryDetail).toHaveBeenLastCalledWith('g', { preset: 'last_month' }, 'household')
  })
})

describe('FuelScreen', () => {
  it('has a chip per car plus All cars, and ?car= picks one', () => {
    at('/insights/fuel?car=car2', '/insights/fuel', <FuelScreen />)
    expect(screen.getByRole('button', { name: 'All cars' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Yaris' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('heading', { name: 'Last fill' })).toBeInTheDocument()
    expect(screen.getByText(new RegExp(`^${formatShortDate('2026-10-05')} · 24 L · €1.775/L$`))).toBeInTheDocument()
  })

  it('All cars shows the latest fill across cars', () => {
    at('/insights/fuel', '/insights/fuel', <FuelScreen />)
    expect(screen.getByRole('button', { name: 'All cars' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Golf' }))
    expect(screen.getByText(new RegExp(`^${formatShortDate('2026-10-02')} · 40 L`))).toBeInTheDocument()
  })

  it('says when there are no fills with litres', () => {
    hooks.useInsights.mockReturnValue(query(makeInsights({ fuel: null })))
    at('/insights/fuel', '/insights/fuel', <FuelScreen />)
    expect(screen.getByText('No fill-ups with litres in this period.')).toBeInTheDocument()
  })

  it('notes unpriced fills', () => {
    at('/insights/fuel', '/insights/fuel', <FuelScreen />)
    expect(screen.getByText('1 fill-up has no price and is left out')).toBeInTheDocument()
  })
})
