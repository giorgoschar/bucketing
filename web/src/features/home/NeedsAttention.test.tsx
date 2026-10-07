import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { enqueue } from '../../offline/queue'
import { fakeApi, hang, reply, type Routes } from '../../test/fakeApi'
import type { CashWalletsOut } from '../plan/cash/types'
import { budgetRow, cashWallets, categoryUsual, day, entry, match, readRoutes, wallet, walletMember } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline, TEST_IDENTITY } from '../../test/render'
import { setIdentity } from '../../offline/identity'
import { NeedsAttention } from './NeedsAttention'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const LINK = 'POST /api/v1/matches/{match_id}/link' as const
const DISMISS = 'POST /api/v1/matches/{match_id}/dismiss' as const
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/matches': () => [match()],
  'GET /api/v1/recurring/entries': () => [entry({ id: 'e9', item_id: 'i9', name: 'Rent', overdue: true, due_date: '2026-10-01', amount: 650 })],
  'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry({ id: 'e5', name: 'Electricity', estimated: true, amount: 83.5 })], 900)],
  'GET /api/v1/plan/budgets': () => [budgetRow({ spent: 1050, pct: 87.5 })],
  'GET /api/v1/insights/categories-vs-usual': () => [categoryUsual()],
  [LINK]: () => entry({ status: 'done' }),
  [DISMISS]: () => null,
  ...over,
})
// The server stops suggesting a match once it is linked or dismissed.
let served = false
beforeEach(() => { served = false })
const kinds = () => Array.from(document.querySelectorAll('[data-attn]')).map((n) => n.getAttribute('data-attn'))

it('lists what needs a tap in the spec order, with words for each state', async () => {
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'budget', 'category']))
  expect(screen.getByRole('heading', { name: /Needs attention/ })).toHaveTextContent('Needs attention5')
  expect(document.querySelector('[data-attn="match"]')).toHaveTextContent('Payment €38.90 at Cosmote on 3 Oct looks like Cosmote due 5 Oct')
  expect(document.querySelector('[data-attn="overdue"]')).toHaveTextContent('Overdue')
  expect(document.querySelector('[data-attn="missingAmount"]')).toHaveTextContent('Electricity needs an amount')
  expect(document.querySelector('[data-attn="budget"]')).toHaveTextContent('€1,050 of €1,200')
  expect(document.querySelector('[data-attn="category"]')).toHaveTextContent('Groceries above usual')
})

it.each([
  ['Link', LINK, '/api/v1/matches/m1/link', entry({ status: 'done' })],
  ['Not this', DISMISS, '/api/v1/matches/m1/dismiss', null],
] as const)('%s removes the suggestion at once, before the server answers', async (button, route, path, body) => {
  let answer!: (r: Response) => void
  const fake = fakeApi(routes({ 'GET /api/v1/matches': () => (served ? [] : [match()]) }))
  fake.on(route, () => new Promise<Response>((r) => { answer = r }))
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: button }))
  await waitFor(() => expect(fake.callsTo(route)).toHaveLength(1))
  expect(fake.callsTo(route)[0].path).toBe(path)
  // The request is still pending: only the optimistic patch can have removed the row.
  expect(kinds()).not.toContain('match')
  served = true
  answer(body === null ? new Response(null, { status: 204 }) : Response.json(body))
  await new Promise((r) => setTimeout(r, 20))
  expect(kinds()).not.toContain('match')
})

it.each([['Link', LINK], ['Not this', DISMISS]] as const)(
  'a 409 on %s brings the suggestion back',
  async (button, route) => {
    let answer!: (r: Response) => void
    let reads = 0
    // Later reads (the invalidation after the 409) never answer: what the screen shows is the rollback.
    const fake = fakeApi(routes({ 'GET /api/v1/matches': () => (++reads === 1 ? [match()] : hang()) }))
    fake.on(route, () => new Promise<Response>((r) => { answer = r }))
    renderWithProviders(<NeedsAttention />)
    fireEvent.click(await screen.findByRole('button', { name: button }))
    await waitFor(() => expect(kinds()).not.toContain('match'))
    answer(reply(409, { detail: 'This payment is already linked.' }))
    await waitFor(() => expect(kinds()).toContain('match'))
    expect(document.querySelector('[data-attn="match"]')).toHaveTextContent('looks like Cosmote due 5 Oct')
  },
)

it('Not this dismisses', async () => {
  const fake = fakeApi(routes({ 'GET /api/v1/matches': () => (served ? [] : [match()]) }))
  fake.on(DISMISS, () => { served = true; return null })
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: 'Not this' }))
  await waitFor(() => expect(fake.callsTo(DISMISS)).toHaveLength(1))
  expect(kinds()).not.toContain('match')
})

it('an overdue row opens the Entry sheet; a missing amount opens it on Set amount', async () => {
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  fireEvent.click(await screen.findByRole('button', { name: /Rent/ }))
  expect(screen.getByRole('dialog', { name: 'Rent' })).toHaveTextContent('Overdue')
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  fireEvent.click(screen.getByRole('button', { name: /Electricity needs an amount/ }))
  expect(screen.getByRole('dialog', { name: 'Electricity' })).toBeInTheDocument()
  expect(screen.getByLabelText('Amount')).toBeInTheDocument()
})

it('a queued change that failed is listed with the server message and can be dismissed', async () => {
  setIdentity(TEST_IDENTITY)
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: {} })
  const [row] = await db.queue.toArray()
  await db.queue.put({ ...row, status: 'failed', error: 'Your wallet has less cash' })
  fakeApi(routes({ 'GET /api/v1/matches': () => [], 'GET /api/v1/recurring/entries': () => [] }))
  renderWithProviders(<NeedsAttention />)
  const failed = await screen.findByText("1 change couldn't be saved")
  expect(failed.closest('[data-attn]')).toHaveTextContent('Your wallet has less cash')
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
  await waitFor(() => expect(kinds()).not.toContain('failed'))
  expect(await db.queue.count()).toBe(0)
})

it('All clear when everything loaded and nothing needs attention', async () => {
  fakeApi(routes({
    'GET /api/v1/matches': () => [], 'GET /api/v1/recurring/entries': () => [], 'GET /api/v1/plan/upcoming': () => [],
    'GET /api/v1/plan/budgets': () => [], 'GET /api/v1/insights/categories-vs-usual': () => [],
  }))
  renderWithProviders(<NeedsAttention />)
  expect(await screen.findByText('All clear')).toBeInTheDocument()
})

it('offline with nothing saved: no false "All clear"', async () => {
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<NeedsAttention />)
  await new Promise((r) => setTimeout(r, 50))
  expect(screen.queryByText('All clear')).toBeNull()
  expect(screen.queryByRole('heading', { name: /Needs attention/ })).toBeNull()
})

// Plan › Cash §4.6
const cashRoute = (wallets: CashWalletsOut | Response): Routes => ({ 'GET /api/v1/cash/wallets': () => wallets })

it('cash not logged: "€45.00 cash not logged yet" with Log it, after missingAmount and before budget', async () => {
  const fake = fakeApi(routes(cashRoute(cashWallets())))
  const { router } = renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'cash', 'budget', 'category']))
  expect(fake.calls.find((c) => c.path === '/api/v1/cash/wallets')?.query.get('month')).toBe('2026-10')
  const row = document.querySelector('[data-attn="cash"]') as HTMLElement
  expect(row).toHaveTextContent('€45.00 cash not logged yet')
  fireEvent.click(within(row).getByRole('button', { name: 'Log it' }))
  expect(router.state.location.pathname).toBe('/new')
  expect(router.state.location.search).toBe('?mode=cash&take=none&amount=45.00')
})

it('no cash row at 0.004, and none for another member\'s not-logged cash', async () => {
  const w = cashWallets({
    members: [
      walletMember({ wallet: wallet({ not_yet_logged: 0.004 }) }),
      walletMember({ member_id: 'u2', name: 'Maria', is_me: false, wallet: wallet({ not_yet_logged: 80 }) }),
    ],
  })
  fakeApi(routes(cashRoute(w)))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'budget', 'category']))
})

it('the wallets query failing or not cached shows no cash row and no error', async () => {
  fakeApi(routes(cashRoute(reply(500, { detail: 'boom' }))))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'budget', 'category']))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText(/cash/)).not.toBeInTheDocument()
})

// ---- Plan › Pantry §4.7
const pantryRoute = (summary: { low_count: number; ticked_count: number } | Response): Routes =>
  ({ 'GET /api/v1/stock/summary': () => summary })

it('pantry: "3 pantry items running low" with List, after cash and before budget', async () => {
  fakeApi(routes({ ...cashRoute(cashWallets()), ...pantryRoute({ low_count: 3, ticked_count: 0 }) }))
  const { router } = renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'cash', 'pantry', 'budget', 'category']))
  const row = document.querySelector('[data-attn="pantry"]') as HTMLElement
  expect(row).toHaveTextContent('3 pantry items running low')
  fireEvent.click(within(row).getByRole('button', { name: 'List' }))
  expect(router.state.location.pathname).toBe('/plan/pantry/list')
})

it('pantry: one item reads in the singular', async () => {
  fakeApi(routes(pantryRoute({ low_count: 1, ticked_count: 0 })))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toContain('pantry'))
  expect(document.querySelector('[data-attn="pantry"]')).toHaveTextContent('1 pantry item running low')
})

it.each([
  ['nothing is low', pantryRoute({ low_count: 0, ticked_count: 2 })],
  ['the summary fails', pantryRoute(reply(500, { detail: 'boom' }))],
  ['there is no summary at all', {}],
])('no pantry row and no error when %s', async (_why, extra) => {
  fakeApi(routes(extra))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['match', 'overdue', 'missingAmount', 'budget', 'category']))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText(/pantry/)).not.toBeInTheDocument()
})
