import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { onUnauthorized } from '../../../api/client'
import { fakeApi, reply, type Routes } from '../../../test/fakeApi'
import { entry, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { asRoutes, statement, statementRoutes } from './fixtures'
import { StatementView } from './Statement'
import type { StatementOut } from './types'

vi.mock('../../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'u1', household_id: 'h1', display_name: 'Giorgos' }, signOut: vi.fn() }),
}))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 2, 12)) // 2 October 2026: September is in its review window
})
afterEach(resetTestEnv)

const routes = (s: StatementOut, extra: Routes = {}): Routes => ({ ...readRoutes(), ...statementRoutes(s), ...extra })
const open = (s: StatementOut, month = s.month) => {
  const fake = fakeApi(routes(s))
  return { fake, ...renderWithProviders(<StatementView month={month} />, { route: `/insights/statements/${month}` }) }
}
/** The change lines under the three tiles, as the reader sees them. */
const comparisons = () => Array.from(document.querySelectorAll('.stmttile__cmp'), (e) => e.textContent)
const section = async (name: string) => within(await screen.findByRole('region', { name }))

const FULL = statement({
  planned: {
    in: { planned: 3000, actual: 3000 }, out: { planned: 910, actual: 934 },
    open: [{ entry_id: 'e1', item_id: 'i1', name: 'Gym', direction: 'out', due_date: '2026-09-28', amount: 35, estimated: true, status: 'expected' }],
  },
  budgets_over: [{ bucket_id: 'b1', name: 'Daily', budget: 1200, spent: 1310, over: 110 }],
  bills_changed: [{
    item_id: 'i1', name: 'Electricity', entry_id: 'e9', due_date: '2026-09-14', amount: 84, usual: 61, basis: 'last_year',
    direction: 'up', pct: 38, reason: null, reason_pct: null,
  }],
  cash: [
    { member_id: 'u1', name: 'Giorgos', not_yet_logged: 45 },
    { member_id: 'u2', name: 'Maria', not_yet_logged: 12.5 },
  ],
  categories_over: [{ category_id: 'c1', name: 'Eating out', icon: '🍽', amount: 370, usual: 240 }],
  biggest: [{ transaction_id: 't1', date: '2026-09-03', label: 'IKEA', category: 'Home', amount: 420 }],
})

// ---- the line under the title

it('in the review window: the deadline and the days left, and the live note', async () => {
  open(statement())
  expect(await screen.findByText('Review by 5 October · 3 days left')).toBeInTheDocument()
  expect(screen.getByText('Numbers are live: they change if you edit an entry from this month.')).toBeInTheDocument()
})

it('reviewed by you, by a named member, and by nobody known', async () => {
  const { unmount } = open(statement({ reviewed_at: '2026-10-02T09:00:00', reviewed_on: '2026-10-02', reviewed_by: 'u1', closed: true, days_left: null }))
  expect(await screen.findByText('Reviewed on 2 October by you')).toBeInTheDocument()
  unmount()
  open(statement({ reviewed_at: '2026-10-02T09:00:00', reviewed_on: '2026-10-02', reviewed_by: 'u2', closed: true, days_left: null }))
  expect(await screen.findByText('Reviewed on 2 October by Maria')).toBeInTheDocument()
})

it('reviewed with no reviewer: no name', async () => {
  open(statement({ reviewed_at: '2026-10-02T09:00:00', reviewed_on: '2026-10-02', reviewed_by: null, closed: true, days_left: null }))
  expect(await screen.findByText('Reviewed on 2 October')).toBeInTheDocument()
})

it('closed without a review', async () => {
  open(statement({ closed: true, days_left: null }))
  expect(await screen.findByText('Closed automatically')).toBeInTheDocument()
  expect(screen.getByText('Numbers are live: they change if you edit an entry from this month.')).toBeInTheDocument()
})

// ---- the sections

it('the page reads the same every time: one h1, seven h2 in order', async () => {
  open(FULL)
  await screen.findByText('Review by 5 October · 3 days left')
  expect(screen.getAllByRole('heading', { level: 1 }).map((h) => h.textContent)).toEqual(['September 2026'])
  expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
    'In, out and net', 'Planned vs actual', 'Budgets that ran over', 'Bills that changed', 'Cash not logged',
    'Categories above usual', 'Biggest expenses',
  ])
})

it('1. three tiles with the change from the month before, in words', async () => {
  open(statement())
  const s = await section('In, out and net')
  expect(s.getByText('€3,000.00')).toBeInTheDocument()
  expect(s.getByText('€2,240.00')).toBeInTheDocument()
  expect(s.getByText('+€760.00')).toBeInTheDocument()
  expect(comparisons()).toEqual(['Same as August', '€240 more than August', '€240 less than August'])
})

it('1. no comparison lines when there is no month before', async () => {
  open(statement({ totals: { in: 100, out: 40, net: 60, previous: null } }))
  const s = await section('In, out and net')
  expect(s.queryByText(/than August|Same as/)).toBeNull()
  expect(s.getByText('+€60.00')).toBeInTheDocument()
})

it('1. a lower month than the one before says "less" and a negative net keeps its minus', async () => {
  open(statement({ totals: { in: 1000, out: 1500, net: -500, previous: { month: '2026-08', in: 2000, out: 1000, net: 1000 } } }))
  const s = await section('In, out and net')
  expect(comparisons()).toEqual(['€1,000 less than August', '€500 more than August', '€1,500 less than August'])
  expect(s.getByText('−€500.00')).toBeInTheDocument()
})

it('2. planned, actual and the difference for In and Out, and the open entries', async () => {
  open(FULL)
  const s = await section('Planned vs actual')
  const out = s.getByRole('row', { name: /^Out/ })
  expect(out).toHaveTextContent('€910.00')
  expect(out).toHaveTextContent('€934.00')
  expect(out).toHaveTextContent('+€24.00')
  expect(s.getByRole('row', { name: /^In/ })).toHaveTextContent('€0.00')
  expect(s.getByRole('heading', { level: 3, name: 'Still open' })).toBeInTheDocument()
  const gym = s.getByRole('button', { name: /Gym/ })
  expect(gym).toHaveTextContent('28 Sep')
  expect(gym).toHaveTextContent('≈ €35.00')
})

it('2. nothing open: "Everything planned was done or skipped."', async () => {
  open(statement())
  expect((await section('Planned vs actual')).getByText('Everything planned was done or skipped.')).toBeInTheDocument()
})

it('2. an open entry opens that entry\'s sheet', async () => {
  const fake = fakeApi(routes(FULL, {
    'GET /api/v1/recurring/entries': () => [entry({ id: 'e1', item_id: 'i1', name: 'Gym', due_date: '2026-09-28', amount: 35, estimated: true })],
  }))
  renderWithProviders(<StatementView month="2026-09" />, { route: '/insights/statements/2026-09' })
  fireEvent.click((await (await section('Planned vs actual')).findByRole('button', { name: /Gym/ })))
  expect(await screen.findByRole('dialog', { name: 'Gym' })).toBeInTheDocument()
  expect(fake.callsTo('GET /api/v1/recurring/entries')[0].query.get('from')).toBe('2026-09-28')
  expect(fake.callsTo('GET /api/v1/recurring/entries')[0].query.get('to')).toBe('2026-09-28')
})

it('3. a budget that ran over: "€1,310 of €1,200" and "€110 over"; empty says so', async () => {
  const { unmount } = open(FULL)
  const s = await section('Budgets that ran over')
  expect(s.getByText('Daily')).toBeInTheDocument()
  expect(s.getByText('Daily').closest('li')).toHaveTextContent('€1,310 of €1,200')
  expect(s.getByText('Daily').closest('li')).toHaveTextContent('€110 over')
  unmount()
  open(statement())
  expect((await section('Budgets that ran over')).getByText('No budget ran over.')).toBeInTheDocument()
})

it('4. a changed bill: the Phase A sentence and a link to its history; empty says so', async () => {
  const { unmount } = open(FULL)
  const s = await section('Bills that changed')
  const link = s.getByRole('link', { name: /Electricity was €84, usually €61/ })
  expect(link).toHaveAttribute('href', '/insights/bills/i1')
  expect(link).toHaveTextContent('↑ 38% vs usual')
  unmount()
  open(statement())
  expect((await section('Bills that changed')).getByText('No bill changed much.')).toBeInTheDocument()
})

it('5. cash: one row per member, Log it only on your own row; empty says so', async () => {
  const { unmount } = open(FULL)
  const s = await section('Cash not logged')
  expect(s.getByText('Giorgos')).toBeInTheDocument()
  expect(s.getByText('€45')).toBeInTheDocument()
  expect(s.queryByText('not logged yet')).toBeNull()
  expect(s.getByText('€12.50')).toBeInTheDocument()
  const log = s.getAllByRole('link', { name: 'Log it' })
  expect(log).toHaveLength(1)
  expect(log[0]).toHaveAttribute('href', '/new?mode=cash&take=none&amount=45.00')
  unmount()
  open(statement())
  expect((await section('Cash not logged')).getByText('All cash is logged.')).toBeInTheDocument()
})

it('6. a category above usual opens its screen for that month; empty says so', async () => {
  const { unmount } = open(FULL)
  const s = await section('Categories above usual')
  const link = s.getByRole('link', { name: /Eating out/ })
  expect(link).toHaveTextContent('€370')
  expect(link).toHaveTextContent('usually €240')
  expect(link.getAttribute('href')).toBe('/insights/category/c1?p=custom&from=2026-09-01&to=2026-09-30')
  unmount()
  open(statement())
  expect((await section('Categories above usual')).getByText('Nothing above its usual.')).toBeInTheDocument()
})

it('7. the biggest expenses open the entry; empty says so', async () => {
  const { unmount } = open(FULL)
  const s = await section('Biggest expenses')
  const link = s.getByRole('link', { name: /IKEA/ })
  expect(link).toHaveAttribute('href', '/activity/t1')
  expect(link).toHaveTextContent('Home')
  expect(link).toHaveTextContent('€420.00')
  unmount()
  open(statement())
  expect((await section('Biggest expenses')).getByText('No expenses this month.')).toBeInTheDocument()
})

it('a month with no data at all opens with zeros and the quiet lines, not an error', async () => {
  open(statement({
    totals: { in: 0, out: 0, net: 0, previous: null },
    planned: { in: { planned: 0, actual: 0 }, out: { planned: 0, actual: 0 }, open: [] },
  }))
  const s = await section('In, out and net')
  expect(s.getAllByText('€0.00')).toHaveLength(3)
  for (const line of ['Everything planned was done or skipped.', 'No budget ran over.', 'No bill changed much.', 'All cash is logged.',
    'Nothing above its usual.', 'No expenses this month.']) expect(screen.getByText(line)).toBeInTheDocument()
})

// ---- Done

it('Done: the button and its note; it posts, then the page says reviewed by you and the button is gone', async () => {
  const reviewed = statement({ reviewed_at: '2026-10-02T10:00:00', reviewed_on: '2026-10-02', reviewed_by: 'u1', closed: true, days_left: null })
  const fake = fakeApi(routes(statement(), asRoutes({
    'POST /api/v1/insights/statements/2026-09/review': () => reviewed,
  })))
  renderWithProviders(<StatementView month="2026-09" />, { route: '/insights/statements/2026-09' })
  expect(await screen.findByText('Marks September as reviewed for the whole household.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(await screen.findByText('Reviewed on 2 October by you')).toBeInTheDocument()
  expect(fake.calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/v1/insights/statements/2026-09/review'])
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Done' })).toBeNull())
  expect(screen.queryByText(/Marks September/)).toBeNull()
})

it('Done after it succeeded refreshes the list too', async () => {
  const reviewed = statement({ reviewed_at: '2026-10-02T10:00:00', reviewed_on: '2026-10-02', reviewed_by: 'u1', closed: true, days_left: null })
  fakeApi(routes(statement(), asRoutes({
    'POST /api/v1/insights/statements/2026-09/review': () => reviewed,
    'GET /api/v1/insights/statements': () => ({ review: null, months: [] }),
  })))
  const { client } = renderWithProviders(<StatementView month="2026-09" />)
  client.setQueryData(['insights', 'statements', 'list'], { review: { month: '2026-09', label: 'September 2026', days_left: 3 }, months: [] })
  fireEvent.click(await screen.findByRole('button', { name: 'Done' }))
  await screen.findByText('Reviewed on 2 October by you')
  expect(client.getQueryState(['insights', 'statements', 'list'])?.isInvalidated).toBe(true)
})

it('Done is disabled offline, with "Connect to finish the review", and sends nothing', async () => {
  const fake = open(statement()).fake
  await screen.findByRole('button', { name: 'Done' })
  setOnline(false)
  expect(await screen.findByText('Connect to finish the review')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Done' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(fake.calls.filter((c) => c.method === 'POST')).toEqual([])
})

it('no Done button once reviewed or closed', async () => {
  const { unmount } = open(statement({ reviewed_at: '2026-10-02T10:00:00', reviewed_on: '2026-10-02', reviewed_by: 'u1', closed: true, days_left: null }))
  await screen.findByText(/Reviewed on/)
  expect(screen.queryByRole('button', { name: 'Done' })).toBeNull()
  unmount()
  open(statement({ closed: true, days_left: null }))
  await screen.findByText('Closed automatically')
  expect(screen.queryByRole('button', { name: 'Done' })).toBeNull()
})

// ---- live numbers, offline, bad months

it('an entry edited after the review: the new numbers and still "Reviewed on"', async () => {
  const reviewed = { reviewed_at: '2026-10-02T10:00:00', reviewed_on: '2026-10-02', reviewed_by: 'u1', closed: true, days_left: null }
  let current = statement(reviewed)
  const fake = fakeApi(routes(current, asRoutes({ 'GET /api/v1/insights/statements/2026-09': () => current })))
  const { client } = renderWithProviders(<StatementView month="2026-09" />)
  expect(await screen.findByText('€2,240.00')).toBeInTheDocument()
  current = statement({ ...reviewed, totals: { in: 3000, out: 2500, net: 500, previous: null } })
  await client.invalidateQueries({ queryKey: ['insights'] })
  expect(await screen.findByText('€2,500.00')).toBeInTheDocument()
  expect(screen.getByText('+€500.00')).toBeInTheDocument()
  expect(screen.getByText('Reviewed on 2 October by you')).toBeInTheDocument()
  expect(fake.calls.filter((c) => c.path === '/api/v1/insights/statements/2026-09').length).toBeGreaterThan(1)
})

it('offline with a saved copy: the page and "Offline · showing saved statement"', async () => {
  const fake = fakeApi(routes(FULL))
  const { unmount, client } = renderWithProviders(<StatementView month="2026-09" />)
  await screen.findByText('IKEA')
  unmount()
  setOnline(false)
  fake.down()
  renderWithProviders(<StatementView month="2026-09" />, { client })
  expect(await screen.findByText('Offline · showing saved statement')).toBeInTheDocument()
  expect(screen.getByText('IKEA')).toBeInTheDocument()
})

it('a malformed month is never asked for: "No statement for this month yet." and a way back', async () => {
  for (const month of ['soon', '2026-13']) {
    const fake = fakeApi(readRoutes())
    const { unmount } = renderWithProviders(<StatementView month={month} />, { route: `/insights/statements/${month}` })
    expect(await screen.findByText('No statement for this month yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All statements' })).toHaveAttribute('href', '/insights/statements')
    expect(fake.calls.filter((c) => c.path.includes('/insights/statements'))).toEqual([])
    unmount()
  }
})

it('a month the server refuses (404 current or future, 400) shows the same empty state, not "Couldn\u2019t load this."', async () => {
  for (const [month, status] of [['2026-10', 404], ['2027-01', 404], ['2026-05', 400]] as const) {
    const fake = fakeApi({ ...readRoutes(), ...asRoutes({ [`GET /api/v1/insights/statements/${month}`]: () => reply(status, { detail: 'nope' }) }) })
    const { unmount } = renderWithProviders(<StatementView month={month} />, { route: `/insights/statements/${month}` })
    expect(await screen.findByText('No statement for this month yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'All statements' })).toHaveAttribute('href', '/insights/statements')
    expect(screen.queryByText(/Couldn/)).toBeNull()
    expect(fake.calls.filter((c) => c.path === `/api/v1/insights/statements/${month}`)).toHaveLength(1)
    unmount()
  }
})

it('a server error other than 400 or 404 is still "Couldn\u2019t load this."', async () => {
  fakeApi({ ...readRoutes(), ...asRoutes({ 'GET /api/v1/insights/statements/2026-09': () => reply(500) }) })
  renderWithProviders(<StatementView month="2026-09" />)
  expect(await screen.findByText('Couldn’t load this.')).toBeInTheDocument()
})

it('Reviewed on shows the household date, not the UTC one: Done at 00:30 on 1 October in Athens is stored on 30 September', async () => {
  open(statement({ reviewed_at: '2026-09-30T21:30:00', reviewed_on: '2026-10-01', reviewed_by: 'u1', closed: true, days_left: null }))
  expect(await screen.findByText('Reviewed on 1 October by you')).toBeInTheDocument()
})

it('by: "you" from the id, else the household name, else the server\u2019s name, else no name', async () => {
  const base = { reviewed_at: '2026-10-02T09:00:00', reviewed_on: '2026-10-02', closed: true, days_left: null }
  const { unmount: u1 } = open(statement({ ...base, reviewed_by: 'u2', reviewed_by_name: 'Server Maria' }))
  expect(await screen.findByText('Reviewed on 2 October by Maria')).toBeInTheDocument()
  u1()
  const { unmount: u2 } = open(statement({ ...base, reviewed_by: 'gone', reviewed_by_name: 'Nikos' }))
  expect(await screen.findByText('Reviewed on 2 October by Nikos')).toBeInTheDocument()
  u2()
  const { unmount: u3 } = open(statement({ ...base, reviewed_by: 'gone', reviewed_by_name: null }))
  expect(await screen.findByText('Reviewed on 2 October')).toBeInTheDocument()
  u3()
  open(statement({ ...base, reviewed_by: 'u1', reviewed_by_name: 'Giorgos' }))
  expect(await screen.findByText('Reviewed on 2 October by you')).toBeInTheDocument()
})

it('Done goes through the API client: a 401 is announced like everywhere else', async () => {
  const heard = vi.fn()
  const off = onUnauthorized(heard)
  fakeApi(routes(statement(), asRoutes({ 'POST /api/v1/insights/statements/2026-09/review': () => reply(401, { detail: 'no' }) })))
  renderWithProviders(<StatementView month="2026-09" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Done' }))
  await waitFor(() => expect(heard).toHaveBeenCalled())
  off()
})

it('a category with no usual figure or amount never shows NaN', async () => {
  open(statement({ categories_over: [{ category_id: 'c1', name: 'Eating out', icon: '🍽', amount: 370, usual: null as unknown as number }, { category_id: 'c2', name: 'Odd', icon: '?', amount: undefined as unknown as number, usual: 10 }] }))
  const s = await section('Categories above usual')
  expect(s.getByRole('link', { name: /Eating out/ })).not.toHaveTextContent('usually')
  expect(document.body.textContent).not.toMatch(/NaN/)
})

it('amounts in a sentence are ui-num spans, and the sentence still wraps', async () => {
  open(FULL)
  const s = await section('Budgets that ran over')
  expect(s.getByText('€1,310').className).toContain('ui-num')
  expect(s.getByText('€110').className).toContain('ui-num')
  expect(s.getByText('€110').closest('.stmtitem__flag')).toHaveTextContent('€110 over')
})
