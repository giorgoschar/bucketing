import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { enqueue } from '../../offline/queue'
import { fakeApi, hang, reply, type Routes } from '../../test/fakeApi'
import { budgetRow, categoryUsual, day, entry, match, readRoutes } from '../../test/fixtures'
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
