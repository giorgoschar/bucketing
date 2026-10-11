import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { makeInsights, query } from '../fixtures'

const hooks = vi.hoisted(() => ({ usePlanMonth: vi.fn(), useCategoriesVsUsual: vi.fn() }))
vi.mock('../hooks', () => hooks)

import { ByMonth } from './cards'
import { Summary } from './summary'

const PLAN = query({ month: '2026-10', fixed: { so_far: 600, still_to_come: 200, projected: 800 }, buckets: { so_far: 684.6, still_to_come: 825.4, projected: 1510, rows: [] }, income: { so_far: 3000, still_to_come: 0, projected: 3000 }, net_projected: 690, events_spent: 0, cash: 45, estimated: false })
const THIS = { preset: 'this_month' as const }
const MARIA = [{ user_id: 'm', role: 'member', display_name: 'Maria P', username: 'maria', avatar_color: null }]
const base = { data: makeInsights(), period: THIS, lens: 'household', members: [] as typeof MARIA }
const wrap = (ui: ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>)
const EMPTY = makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, total: 0, savings_rate: null } })

describe('Summary', () => {
  it('household this month: every old sentence and figure, in one card', () => {
    hooks.usePlanMonth.mockReturnValue(PLAN)
    wrap(<Summary {...base} />)
    const card = screen.getByRole('region', { name: 'Summary' })
    expect(within(card).getByText('Spent · Oct 1 – 6')).toBeInTheDocument()
    expect(within(card).getAllByText('€1,284.60')).toHaveLength(2) // the big figure and Out
    expect(within(card).getByText('−8% vs the previous period')).toBeInTheDocument()
    expect(within(card).getByText('On track for €2,310 by Oct 31')).toBeInTheDocument()
    expect(within(card).getByText('In')).toBeInTheDocument()
    expect(within(card).getByText('Out')).toBeInTheDocument()
    expect(within(card).getByText('Net')).toBeInTheDocument()
    expect(within(card).getByText('€3,000.00')).toBeInTheDocument()
    expect(within(card).getByText('€1,715.40')).toBeInTheDocument()
    expect(within(card).getByText('You kept 57% of what came in')).toBeInTheDocument()
  })

  it('"How these are counted" is closed by default and holds the old On track footnote', () => {
    hooks.usePlanMonth.mockReturnValue(PLAN)
    wrap(<Summary {...base} />)
    const details = screen.getByText('How these are counted').closest('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(within(details).getByText('Spent so far plus the bills and budgets still to come.')).toBeInTheDocument()
    fireEvent.click(screen.getByText('How these are counted'))
    expect(details.open).toBe(true)
  })

  it('the On track line is absent when the month plan is not saved, and so is its footnote', () => {
    hooks.usePlanMonth.mockReturnValue(query(undefined))
    wrap(<Summary {...base} />)
    expect(screen.queryByText(/On track for/)).toBeNull()
    expect(screen.queryByText('How these are counted')).toBeNull()
    expect(screen.getByText('You kept 57% of what came in')).toBeInTheDocument()
  })

  it('outside this month, or under a member lens, there is no On track line', () => {
    hooks.usePlanMonth.mockReturnValue(PLAN)
    const { unmount } = wrap(<Summary {...base} period={{ preset: 'last_month' }} />)
    expect(screen.queryByText(/On track for/)).toBeNull()
    expect(screen.queryByText('How these are counted')).toBeNull()
    unmount()
    wrap(<Summary {...base} lens="m" members={MARIA} />)
    expect(screen.queryByText(/On track for/)).toBeNull()
    expect(screen.getByText('In · received by Maria')).toBeInTheDocument()
  })

  it('the savings line follows the savings rate: absent without one, negative in words', () => {
    hooks.usePlanMonth.mockReturnValue(query(undefined))
    const noRate = makeInsights({ kpis: { ...makeInsights().kpis, savings_rate: null } })
    const { unmount } = wrap(<Summary {...base} data={noRate} />)
    expect(screen.queryByText(/of what came in|more than came in/)).toBeNull()
    unmount()
    wrap(<Summary {...base} data={makeInsights({ kpis: { ...makeInsights().kpis, savings_rate: -12.4 } })} />)
    expect(screen.getByText('You spent 12% more than came in')).toBeInTheDocument()
  })

  it('an empty period keeps only the spent figure: no In / Out / Net, no sentences', () => {
    hooks.usePlanMonth.mockReturnValue(PLAN)
    wrap(<Summary {...base} data={EMPTY} />)
    expect(screen.getByText('Spent · Oct 1 – 6')).toBeInTheDocument()
    expect(screen.queryByText('Net')).toBeNull()
    expect(screen.queryByText(/On track for/)).toBeNull()
    expect(screen.queryByText(/of what came in/)).toBeNull()
  })

  it('no delta badge without a previous period', () => {
    hooks.usePlanMonth.mockReturnValue(query(undefined))
    wrap(<Summary {...base} data={makeInsights({ kpis: { ...makeInsights().kpis, change_pct: null } })} />)
    expect(screen.queryByText(/vs the previous period/)).toBeNull()
  })
})

describe('Summary, fix round 1', () => {
  it('shows the savings line only where parts.savings says so, whatever the other parts', () => {
    hooks.usePlanMonth.mockReturnValue(query(undefined))
    // not empty, but no rate: no line; empty with a rate: still no line
    const noRate = makeInsights({ kpis: { ...makeInsights().kpis, savings_rate: null } })
    const { unmount } = wrap(<Summary {...base} data={noRate} />)
    expect(screen.queryByText(/came in/)).toBeNull()
    unmount()
    wrap(<Summary {...base} data={makeInsights({ total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...makeInsights().kpis, count: 0, savings_rate: 57.2 } })} />)
    expect(screen.queryByText(/of what came in/)).toBeNull()
  })

  it('asks for the month plan only where the On track line can show', () => {
    hooks.usePlanMonth.mockClear()
    hooks.usePlanMonth.mockReturnValue(PLAN)
    const { unmount } = wrap(<Summary {...base} period={{ preset: 'last_3m' }} />)
    unmount()
    wrap(<Summary {...base} lens="m" members={MARIA} />)
    expect(hooks.usePlanMonth).not.toHaveBeenCalled()
    wrap(<Summary {...base} />)
    expect(hooks.usePlanMonth).toHaveBeenCalledWith('2026-10')
  })

  it('the In / Out / Net row has no aria-label on a bare dl', () => {
    hooks.usePlanMonth.mockReturnValue(query(undefined))
    const { container } = wrap(<Summary {...base} />)
    expect(container.querySelector('dl')?.hasAttribute('aria-label')).toBe(false)
  })
})

describe('By month', () => {
  const tabs = () => screen.getAllByRole('tab')

  it('is a two-way switch, In and out by default', () => {
    wrap(<ByMonth data={makeInsights()} />)
    expect(screen.getByRole('region', { name: 'By month' })).toBeInTheDocument()
    expect(tabs().map((t) => t.textContent)).toEqual(['In and out', 'Spending'])
    expect(tabs()[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs()[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('In and out is the old card: its chart table and its footnote', () => {
    wrap(<ByMonth data={makeInsights()} />)
    expect(screen.getByRole('table', { name: 'In and Out by month' })).toBeInTheDocument()
    expect(screen.getByText(/6 months: In €18,000.00 · Out €13,124.60 · Net €4,875.40/)).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Spend by month' })).toBeNull()
  })

  it('Spending is the old Spend trend: its chart table and its average', () => {
    wrap(<ByMonth data={makeInsights()} />)
    fireEvent.click(tabs()[1])
    expect(tabs()[1]).toHaveAttribute('aria-selected', 'true')
    expect(tabs()[0]).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('table', { name: 'Spend by month' })).toBeInTheDocument()
    expect(screen.getByText('Average €2,368.00 a month')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'In and Out by month' })).toBeNull()
    fireEvent.click(tabs()[0])
    expect(screen.getByRole('table', { name: 'In and Out by month' })).toBeInTheDocument()
  })

  it('arrow keys move the switch', () => {
    wrap(<ByMonth data={makeInsights()} />)
    fireEvent.keyDown(tabs()[0], { key: 'ArrowRight' })
    expect(tabs()[1]).toHaveAttribute('aria-selected', 'true')
  })
})
