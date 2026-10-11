import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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

const MEMBERS = { id: 'hh1', name: 'Home', default_currency: 'EUR', members: [
  { user_id: 'me', role: 'owner', joined_at: null, display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'm', role: 'member', joined_at: null, display_name: 'Maria', username: 'maria', avatar_color: null },
] }

beforeEach(() => {
  hooks.useInsights.mockReturnValue(query(makeInsights()))
  hooks.usePersonShare.mockReturnValue(query(null))
  hooks.useMembers.mockReturnValue(query(MEMBERS))
  hooks.useCategoriesVsUsual.mockReturnValue(query([{ category_id: 'g', name: 'Groceries', icon: '🛒', color: '#0f0', this_month: 480, usual: 395, flagged: true }]))
  hooks.usePlanMonth.mockReturnValue(query(undefined))
})

function Where() { const l = useLocation(); return <p data-testid="at">{l.pathname + l.search + l.hash}</p> }
function renderAt(url: string) {
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={new QueryClient()}><MemoryRouter initialEntries={[url]}>{children}<Where /></MemoryRouter></QueryClientProvider>
  )
  return render(<Insights />, { wrapper: wrap })
}
const order = (c: HTMLElement) => [...c.querySelectorAll('[data-widget]')].map((e) => e.getAttribute('data-widget'))
const at = () => screen.getByTestId('at').textContent ?? ''

describe('the tabs', () => {
  it('are a tablist of Overview, Trends and Bills & statements, Overview selected by default', () => {
    renderAt('/insights')
    const list = screen.getByRole('tablist', { name: 'Insights sections' })
    expect(within(list).getAllByRole('tab').map((t) => t.textContent)).toEqual(['Overview', 'Trends', 'Bills & statements'])
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'false')
  })

  it('show each tab\'s cards (household)', () => {
    const { container } = renderAt('/insights')
    expect(order(container)).toEqual(['summary', 'where', 'vsUsual', 'budgets'])
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    expect(order(container)).toEqual(['byMonth', 'biggest', 'method', 'fuel'])
    fireEvent.click(screen.getByRole('tab', { name: 'Bills & statements' }))
    expect(order(container)).toEqual(['bills', 'statements'])
  })

  it('show each tab\'s cards (member lens)', () => {
    const { container } = renderAt('/insights?lens=m')
    expect(order(container)).toEqual(['identity', 'share', 'summary', 'where', 'budgets'])
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    expect(order(container)).toEqual(['byMonth', 'biggest', 'method', 'fuel'])
  })

  it('live in the query string: Overview writes nothing, the others write ?tab=', () => {
    renderAt('/insights')
    expect(at()).toBe('/insights')
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    expect(at()).toContain('tab=trends')
    fireEvent.click(screen.getByRole('tab', { name: 'Bills & statements' }))
    expect(at()).toContain('tab=bills')
    fireEvent.click(screen.getByRole('tab', { name: 'Overview' }))
    expect(at()).not.toContain('tab=')
  })

  it('open from ?tab=', () => {
    const { container } = renderAt('/insights?tab=trends')
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true')
    expect(order(container)[0]).toBe('byMonth')
  })

  it('stay put when the lens or the period changes', () => {
    renderAt('/insights?tab=trends')
    fireEvent.click(screen.getByRole('radio', { name: 'Maria' }))
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true')
    expect(at()).toContain('tab=trends')
    fireEvent.click(screen.getByRole('button', { name: 'Last month' }))
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true')
    expect(at()).toMatch(/tab=trends/)
    expect(at()).toMatch(/p=last_month/)
  })

  it('move with the arrow keys', () => {
    renderAt('/insights')
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Overview' }), { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('tabindex', '0')
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('tabindex', '-1')
  })

  it('an empty period: Overview shows the empty message, the other tabs work as usual', () => {
    const base = makeInsights()
    hooks.useInsights.mockReturnValue(query(makeInsights({
      total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, kpis: { ...base.kpis, count: 0, total: 0, largest: null },
    })))
    const { container } = renderAt('/insights')
    expect(screen.getByText('No spending in this period')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    expect(container.querySelector('[data-widget="byMonth"]')).not.toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: 'Bills & statements' }))
    expect(screen.getByRole('region', { name: 'Statements' })).toBeInTheDocument()
  })
})

// Review Focus 3: a link that lands on /insights expecting Bills or Statements reaches them without hunting.
describe('old links to Bills and Statements', () => {
  it.each(['#bills', '#statements'])('/insights%s opens the Bills & statements tab', (hash) => {
    renderAt(`/insights${hash}`)
    expect(screen.getByRole('tab', { name: 'Bills & statements' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('region', { name: 'Statements' })).toBeInTheDocument()
  })

  it('the tab then survives a lens change (the hash becomes ?tab=bills)', () => {
    renderAt('/insights#bills')
    expect(at()).toContain('tab=bills')
    fireEvent.click(screen.getByRole('radio', { name: 'Maria' }))
    expect(screen.getByRole('tab', { name: 'Bills & statements' })).toHaveAttribute('aria-selected', 'true')
  })

  it('an explicit ?tab= wins over the hash', () => {
    renderAt('/insights?tab=trends#bills')
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true')
  })
})

describe('a lone flowing card spans (desktop columns)', () => {
  // the contract with the CSS: the visible flowing cards are the non-empty .insights__flow wrappers
  const solo = (c: HTMLElement) => [...c.querySelectorAll('.insights__flow:not(:empty)')].map((e) => e.getAttribute('data-widget'))
  const emptyPeriod = () => hooks.useInsights.mockReturnValue(query(makeInsights({
    total_spent: 0, in_out: { in: 0, out: 0, logged: 0, cash_not_logged: 0, net: 0 }, by_method: [], fuel: null,
    kpis: { ...makeInsights().kpis, count: 0, total: 0, largest: null },
  })))

  it('Trends in an empty period: By month is the only flowing card', () => {
    emptyPeriod()
    const { container } = renderAt('/insights?tab=trends')
    expect(solo(container)).toEqual(['byMonth'])
  })

  it('Overview with only Where it went: the only flowing card', () => {
    hooks.useInsights.mockReturnValue(query(makeInsights({ budget_status: [] })))
    hooks.useCategoriesVsUsual.mockReturnValue(query([]))
    const { container } = renderAt('/insights')
    expect(order(container)).toEqual(['summary', 'where', 'vsUsual'])
    expect(solo(container)).toEqual(['where']) // vsUsual renders nothing, so it does not count
  })

  it('the normal multi-card case has several flowing cards', () => {
    const { container } = renderAt('/insights')
    expect(solo(container).length).toBeGreaterThan(1)
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    expect(solo(container).length).toBeGreaterThan(1)
  })
})

describe('the tab in the URL, edge cases', () => {
  it.each(['constructor', 'toString', '__proto__', 'xyz', 'overview', ''])('?tab=%s falls back to Overview, selected and focusable', (v) => {
    renderAt(`/insights?tab=${v}`)
    const overview = screen.getByRole('tab', { name: 'Overview' })
    expect(overview).toHaveAttribute('aria-selected', 'true')
    expect(overview).toHaveAttribute('tabindex', '0')
    expect(screen.getAllByRole('tab').filter((t) => t.getAttribute('aria-selected') === 'true')).toHaveLength(1)
  })

  it('?tab=xyz#bills opens Bills & statements', () => {
    renderAt('/insights?tab=xyz#bills')
    expect(screen.getByRole('tab', { name: 'Bills & statements' })).toHaveAttribute('aria-selected', 'true')
  })

  it('changing the tab keeps every other parameter, and Overview drops only tab', () => {
    renderAt('/insights?add=1&mode=cash&p=last_month&lens=m&bucket_ids=b1')
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    const q = new URLSearchParams(at().split('?')[1])
    expect([...q.keys()].sort()).toEqual(['add', 'bucket_ids', 'lens', 'mode', 'p', 'tab'])
    fireEvent.click(screen.getByRole('tab', { name: 'Overview' }))
    expect([...new URLSearchParams(at().split('?')[1]).keys()].sort()).toEqual(['add', 'bucket_ids', 'lens', 'mode', 'p'])
  })

  it('tab changes replace the history entry (Back leaves Insights, like period and lens)', () => {
    renderAt('/insights')
    fireEvent.click(screen.getByRole('tab', { name: 'Trends' }))
    // MemoryRouter: a replace leaves a single entry, so the location is the only one; push would keep /insights behind it
    expect(at()).toContain('tab=trends')
  })
})

describe('tab accessibility', () => {
  it('each tab controls the panel, and the panel is named by the selected tab', () => {
    renderAt('/insights?tab=trends')
    const trends = screen.getByRole('tab', { name: 'Trends' })
    const panel = screen.getAllByRole('tabpanel').find((p) => p.id === 'insights-panel') as HTMLElement
    expect(trends).toHaveAttribute('aria-controls', panel.id)
    expect(panel).toHaveAttribute('aria-labelledby', trends.id)
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-controls', panel.id)
    expect(within(panel).queryByRole('tablist', { name: 'Insights sections' })).toBeNull()
  })
})
