import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { makeInsights, query } from '../fixtures'

const hooks = vi.hoisted(() => ({ usePlanMonth: vi.fn(), useCategoriesVsUsual: vi.fn() }))
vi.mock('../hooks', () => hooks)

import { Biggest, BudgetsCard, FuelCard, HowYouPaid, InOut, InOutMonths, OnTrack, SavingsRate, SpendTrend, VsUsual, WhereItWent } from './cards'

const ctx = { data: makeInsights(), period: { preset: 'this_month' as const }, lens: 'household', members: [], meId: 'me', setPeriod: vi.fn() }

function Where() { const l = useLocation(); return <p data-testid="at">{l.pathname + l.search}</p> }
const wrap = (ui: ReactNode) => render(
  <MemoryRouter initialEntries={['/insights']}>
    <Routes><Route path="/insights" element={ui} /><Route path="*" element={<Where />} /></Routes>
  </MemoryRouter>,
)

describe('Where it went', () => {
  it('opens a category, opens Uncategorised, and leaves cash not logged untappable', () => {
    wrap(<WhereItWent {...ctx} lens="m" />)
    expect(screen.getByText('not logged')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cash \(not yet logged\)/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Uncategorised/ }))
    expect(screen.getByTestId('at')).toHaveTextContent('/insights/category/uncategorised?p=this_month&lens=m')
  })

  it('shows the top 8 categories and still the cash row', () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ category_id: `c${i}`, name: `Cat ${i}`, icon: '•', color: '#000', amount: 100 - i, pct: 5 }))
    const cash = { category_id: '__cash_not_logged__', name: 'Cash (not yet logged)', icon: '💵', color: '#aaa', amount: 1, pct: 1 }
    wrap(<WhereItWent {...ctx} data={makeInsights({ categories: [...many, cash] })} />)
    expect(screen.getAllByRole('button')).toHaveLength(8)
    expect(screen.getByText('Cash (not yet logged)')).toBeInTheDocument()
  })
})

describe('cards', () => {
  it('On track uses Out projected from the plan', () => {
    hooks.usePlanMonth.mockReturnValue(query({ month: '2026-10', fixed: { so_far: 600, still_to_come: 200, projected: 800 }, buckets: { so_far: 684.6, still_to_come: 825.4, projected: 1510, rows: [] }, income: { so_far: 3000, still_to_come: 0, projected: 3000 }, net_projected: 690, events_spent: 0, cash: 45, estimated: false }))
    wrap(<OnTrack {...ctx} />)
    expect(screen.getByText('On track for €2,310 by Oct 31')).toBeInTheDocument()
    expect(hooks.usePlanMonth).toHaveBeenCalledWith('2026-10')
  })

  it('In / Out / Net, and In is what the member received under a lens', () => {
    wrap(<InOut {...ctx} lens="m" members={[{ user_id: 'm', role: 'member', display_name: 'Maria P', username: 'maria', avatar_color: null }]} />)
    expect(screen.getByText('In · received by Maria')).toBeInTheDocument()
    expect(screen.getByText('€1,715.40')).toBeInTheDocument()
  })

  it('In and Out by month has a table and the six-month totals', () => {
    wrap(<InOutMonths {...ctx} />)
    expect(screen.getByRole('table', { name: 'In and Out by month' })).toBeInTheDocument()
    expect(screen.getByText(/6 months: In €18,000.00 · Out €13,124.60 · Net €4,875.40/)).toBeInTheDocument()
  })

  it('Spend trend survives an all-zero series and averages full months only', () => {
    const zero = makeInsights().monthly_trend.map((r) => ({ ...r, total: 0 }))
    wrap(<SpendTrend {...ctx} data={makeInsights({ monthly_trend: zero })} />)
    expect(screen.getByRole('table', { name: 'Spend by month' })).toBeInTheDocument()
    expect(screen.getByText('Average €0.00 a month')).toBeInTheDocument()
  })

  it('Biggest expense is one row', () => {
    wrap(<Biggest {...ctx} />)
    expect(screen.getByText('IKEA')).toBeInTheDocument()
    expect(screen.getByText('€420.00')).toBeInTheDocument()
  })

  it('How you paid leaves out cash not logged and says so', () => {
    wrap(<HowYouPaid {...ctx} />)
    expect(screen.getByRole('img', { name: 'How you paid: Card €1,100.00, Cash €139.60' })).toBeInTheDocument()
    expect(screen.getByText('Leaves out the €45.00 cash not logged yet')).toBeInTheDocument()
  })

  it('Budgets says "over" in words and links to Plan', () => {
    wrap(<BudgetsCard {...ctx} />)
    expect(screen.getByText('€1,310.00 of €1,200.00 · over')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Plan › Budgets' })).toHaveAttribute('href', '/plan?view=budgets')
  })

  it('Savings rate reads as a sentence', () => {
    wrap(<SavingsRate {...ctx} />)
    expect(screen.getByText('You kept 57% of what came in')).toBeInTheDocument()
  })

  it('Categories vs usual lists flagged rows first with words', () => {
    hooks.useCategoriesVsUsual.mockReturnValue(query([
      { category_id: 'a', name: 'Eating out', icon: '🍽', color: '#f00', this_month: 90, usual: 120, flagged: false },
      { category_id: 'g', name: 'Groceries', icon: '🛒', color: '#0f0', this_month: 480, usual: 395, flagged: true },
    ]))
    wrap(<VsUsual {...ctx} />)
    const rows = within(screen.getByRole('list', { name: 'Categories vs usual' })).getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Groceries')
    expect(rows[0]).toHaveTextContent('above usual')
    expect(hooks.useCategoriesVsUsual).toHaveBeenCalledWith('2026-10')
  })

  it('Fuel has one row per car opening the fuel screen', () => {
    wrap(<FuelCard {...ctx} />)
    fireEvent.click(screen.getByRole('link', { name: /Yaris/ }))
    expect(screen.getByTestId('at')).toHaveTextContent('/insights/fuel?p=this_month&lens=household&car=car2')
  })
})
