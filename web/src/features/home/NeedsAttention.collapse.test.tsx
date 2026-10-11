import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { budgetRow, categoryUsual, day, entry, match, readRoutes } from '../../test/fixtures'
import { installMemoryStorage } from '../../test/storage'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { billRow, billsRoutes, change } from '../insights/bills/fixtures'
import { resetBillDismissals } from './billDismiss'
import { NeedsAttention } from './NeedsAttention'
import { setAttentionExpanded } from './attentionExpanded'

installMemoryStorage()
beforeEach(() => {
  resetBillDismissals()
  setAttentionExpanded(false)
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const base = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
  ...billsRoutes([]),
  ...over,
})
const kinds = () => Array.from(document.querySelectorAll('[data-attn]')).map((n) => n.getAttribute('data-attn'))
const filled = () => document.querySelectorAll('.btn--primary').length

const many = () => base({
  'GET /api/v1/matches': () => [match()],
  'GET /api/v1/recurring/entries': () => [entry({ id: 'e9', item_id: 'i9', name: 'Rent', overdue: true, due_date: '2026-10-01', amount: 650 })],
  'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry({ id: 'e5', name: 'Electricity', estimated: true, amount: 83.5 })], 900)],
  'GET /api/v1/plan/budgets': () => [budgetRow({ spent: 1050, pct: 87.5 })],
  'GET /api/v1/insights/categories-vs-usual': () => [categoryUsual()],
})

it('3 rows, then "Show 2 more" which expands in place, becomes "Show fewer", and keeps the total in the badge', async () => {
  fakeApi(many())
  renderWithProviders(<NeedsAttention />)
  const more = await screen.findByRole('button', { name: 'Show 2 more' })
  expect(kinds()).toEqual(['overdue', 'match', 'missingAmount'])
  expect(more).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByRole('heading', { name: /Needs attention/ })).toHaveTextContent('Needs attention5')
  fireEvent.click(more)
  expect(kinds()).toEqual(['overdue', 'match', 'missingAmount', 'budget', 'category'])
  const fewer = screen.getByRole('button', { name: 'Show fewer' })
  expect(fewer).toHaveAttribute('aria-expanded', 'true')
  fireEvent.click(fewer)
  expect(kinds()).toHaveLength(3)
})

it('one hidden row reads "Show 1 more"', async () => {
  fakeApi(base({ ...many(), 'GET /api/v1/insights/categories-vs-usual': () => [] }))
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByRole('button', { name: 'Show 1 more' })).toBeInTheDocument()
})

it('the badge counts the things that need attention, merged lines included; Show N more counts rows', async () => {
  fakeApi(rentRoutes())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['overdue']))
  expect(screen.getByRole('heading', { name: /Needs attention/ })).toHaveTextContent('Needs attention3')
  expect(screen.queryByRole('button', { name: /Show/ })).toBeNull()
})

it('exactly 3 rows or fewer: no expander, no "Show 0 more"', async () => {
  fakeApi(base({ ...many(), 'GET /api/v1/plan/budgets': () => [], 'GET /api/v1/insights/categories-vs-usual': () => [] }))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toHaveLength(3))
  expect(screen.queryByRole('button', { name: /Show/ })).toBeNull()
  expect(screen.queryByText(/Show 0/)).toBeNull()
})

it('one attention row keeps its filled button and has no expander; none shows All clear without one', async () => {
  fakeApi(base({ 'GET /api/v1/matches': () => [match()] }))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match']))
  expect(screen.getByRole('button', { name: /^Link/ })).toHaveClass('btn--primary')
  expect(screen.getByRole('button', { name: /^Not this/ })).not.toHaveClass('btn--primary')
  expect(screen.queryByRole('button', { name: /Show/ })).toBeNull()
})

it('only the first row has a filled button; every other action is quiet', async () => {
  fakeApi(base({
    'GET /api/v1/matches': () => [match(), match({ id: 'm2' })],
  }))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'match']))
  expect(filled()).toBe(1)
  const links = screen.getAllByRole('button', { name: /^Link/ })
  expect(links[0]).toHaveClass('btn--primary')
  expect(links[1]).toHaveClass('btn--ghost')
  expect(screen.getAllByRole('button', { name: /^Not this/ }).every((b) => b.classList.contains('btn--ghost'))).toBe(true)
})

it('budget and category rows are links to Plan › Budgets and to the category screen', async () => {
  setAttentionExpanded(true)
  fakeApi(many())
  renderWithProviders(<NeedsAttention />)
  const budget = await screen.findByRole('link', { name: /Day to day/ })
  expect(budget).toHaveAttribute('href', '/plan?view=budgets')
  expect(budget).toHaveTextContent('€1,050 of €1,200')
  expect(screen.getByRole('link', { name: /Groceries above usual/ })).toHaveAttribute('href', '/insights/category/c1?p=this_month&lens=household')
})

// Review Focus 2: overdue + needs an amount + changed, then the change is dismissed.
const rentRoutes = () => base({
  'GET /api/v1/recurring/entries': () => [entry({ id: 'r1', item_id: 'rent', name: 'Rent', overdue: true, due_date: '2026-10-03', amount: 650 })],
  'GET /api/v1/plan/upcoming': () => [day('2026-10-13', [entry({ id: 'r2', item_id: 'rent', name: 'Rent', amount: null, due_date: '2026-10-13' })], 0)],
  ...billsRoutes([billRow({ item_id: 'rent', name: 'Rent', change: change({ entry_id: 'r3' }) })]),
})

it('one row per item: the sub-lines are links, and ✕ removes only the bill-change line (and survives a reload)', async () => {
  fakeApi(rentRoutes())
  const { unmount, client } = renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['overdue']))
  const row = document.querySelector('[data-attn="overdue"]') as HTMLElement
  expect(screen.getByRole('heading', { name: /Needs attention/ })).toHaveTextContent('Needs attention3')
  const bill = within(row).getByRole('link', { name: 'Was €84, usually €61' })
  expect(bill).toHaveAttribute('href', '/insights/bills/rent')
  expect(within(row).getByRole('button', { name: 'Needs an amount for 13 Oct' })).toBeInTheDocument()

  fireEvent.click(within(row).getByRole('button', { name: 'Dismiss Rent' }))
  expect(kinds()).toEqual(['overdue'])
  expect(within(row).queryByText(/usually/)).toBeNull()
  expect(within(row).getByRole('button', { name: 'Needs an amount for 13 Oct' })).toBeInTheDocument()

  unmount()
  renderWithProviders(<NeedsAttention />, { client })
  await waitFor(() => expect(kinds()).toEqual(['overdue']))
  expect(document.body).not.toHaveTextContent('usually €61')
})

it('a sub-line for a missing amount opens the entry sheet on Set amount', async () => {
  fakeApi(rentRoutes())
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: 'Needs an amount for 13 Oct' }))
  expect(screen.getByRole('dialog', { name: 'Rent' })).toBeInTheDocument()
  expect(screen.getByLabelText('Amount')).toBeInTheDocument() // the amount step, not the menu
})

// ---- The first row always has one filled button (spec 2.1, Review Focus 1)
const twoOverdue = () => base({
  'GET /api/v1/recurring/entries': () => [
    entry({ id: 'o1', item_id: 'a', name: 'Rent', overdue: true, due_date: '2026-10-01', amount: 650 }),
    entry({ id: 'o2', item_id: 'b', name: 'Water', overdue: true, due_date: '2026-10-02', amount: 20 }),
  ],
})

it('overdue first: a filled "Paid" that opens the entry sheet; the same action is quiet on the next row; the row tap still works', async () => {
  fakeApi(twoOverdue())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['overdue', 'overdue']))
  expect(filled()).toBe(1)
  const paid = screen.getAllByRole('button', { name: /^Paid/ })
  expect(paid[0]).toHaveClass('btn--primary')
  expect(paid[1]).toHaveClass('btn--ghost')
  fireEvent.click(paid[0])
  expect(screen.getByRole('dialog', { name: 'Rent' })).toHaveTextContent('Overdue')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: /^Water/ }))
  expect(screen.getByRole('dialog', { name: 'Water' })).toBeInTheDocument()
})

it('an overdue income entry reads "Received"', async () => {
  fakeApi(base({ 'GET /api/v1/recurring/entries': () => [entry({ id: 'o1', item_id: 'a', name: 'Salary', direction: 'in', overdue: true, due_date: '2026-10-01' })] }))
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByRole('button', { name: /^Received/ })).toHaveClass('btn--primary')
})

it('missing amount first: "Set" is the filled button and opens the amount step', async () => {
  fakeApi(base({ 'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry({ id: 'e5', name: 'Electricity', estimated: true, amount: 83.5 })], 900)] }))
  renderWithProviders(<NeedsAttention />)
  const set = await screen.findByRole('button', { name: /^Set/ })
  expect(filled()).toBe(1)
  expect(set).toHaveClass('btn--primary')
  fireEvent.click(set)
  expect(screen.getByLabelText('Amount')).toBeInTheDocument()
})

// ---- Hidden rows are reachable and work
it('Show 2 more, then the revealed budget row opens Plan › Budgets', async () => {
  fakeApi(many())
  const { router } = renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: 'Show 2 more' }))
  fireEvent.click(screen.getByRole('link', { name: /Day to day/ }))
  expect(router.state.location.pathname).toBe('/plan')
  expect(router.state.location.search).toBe('?view=budgets')
})

it('the expanded choice outlasts leaving Home and coming back in the same session', async () => {
  fakeApi(many())
  const first = renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: 'Show 2 more' }))
  first.unmount()
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByRole('button', { name: 'Show fewer' })).toBeInTheDocument()
  expect(kinds()).toHaveLength(5)
})

// ---- The category row opens this month for the household, whatever Insights last showed
it('the category row carries this month and the household lens, even with a stored 6-month period and a member lens', async () => {
  localStorage.setItem('tameio.insights.period', JSON.stringify({ preset: 'last_6m' }))
  localStorage.setItem('tameio.insights.lens', 'me')
  setAttentionExpanded(true)
  fakeApi(many())
  renderWithProviders(<NeedsAttention />)
  const href = (await screen.findByRole('link', { name: /Groceries above usual/ })).getAttribute('href') ?? ''
  const [path, query] = href.split('?')
  expect(path).toBe('/insights/category/c1')
  const q = new URLSearchParams(query)
  expect(q.get('p')).toBe('this_month')
  expect(q.get('lens')).toBe('household')
})

it('one row, or none, has no expander (none shows All clear)', async () => {
  fakeApi(base())
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByText('All clear')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Show/ })).toBeNull()
})
