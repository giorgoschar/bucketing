import { waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { cashWallets, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, TEST_IDENTITY } from '../../test/render'
import { queuedCashLogged } from '../plan/cash/hooks'
import { NeedsAttention } from './NeedsAttention'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

/** Cash final review m5: a logged cash expense still in the offline queue hides the Home cash row. */

const routes = () => ({
  ...readRoutes(),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
  // Giorgos (u1) has €45.00 cash not logged this month.
  'GET /api/v1/cash/wallets': () => cashWallets(),
})

/** What the composer queues for "Log it" (`/new?mode=cash&take=none`): a cash expense that takes nothing. */
const cashExpense = (over: Record<string, unknown> = {}) => ({
  type: 'expense', amount: '45.00', currency: 'EUR', exchange_rate: '1', paid_by: 'u1', payer_mode: 'single',
  payment_method: 'cash', took_cash: false, transaction_date: '2026-10-07', client_id: crypto.randomUUID(), ...over,
})
const queue = (body: unknown) => enqueue({ method: 'POST', path: '/api/v1/transactions', body })
const cashRow = () => document.querySelector('[data-attn="cash"]')

it('a queued cash expense that covers the amount hides the row; refused on replay, the row comes back', async () => {
  setIdentity(TEST_IDENTITY)
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(cashRow()).toHaveTextContent('€45.00 cash not logged yet'))
  await queue(cashExpense())
  await waitFor(() => expect(cashRow()).toBeNull())
  // The server refuses the queued write: it leaves the pending queue, and the cash is not logged after all.
  const [row] = await db.queue.toArray()
  await db.queue.put({ ...row, status: 'failed', error: 'Bucket not found' })
  await waitFor(() => expect(cashRow()).toHaveTextContent('€45.00 cash not logged yet'))
})

it('a queued cash expense covering part of it leaves the rest to log', async () => {
  setIdentity(TEST_IDENTITY)
  await queue(cashExpense({ amount: '30.00' }))
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(cashRow()).toHaveTextContent('€15.00 cash not logged yet'))
})

it('only the viewer\'s own cash expenses this month that take nothing count', () => {
  const q = (body: unknown, path = '/api/v1/transactions', method: 'POST' | 'PUT' = 'POST') => ({ id: 1, method, path, body })
  const counted = [
    q(cashExpense({ amount: '10.00' })),
    q(cashExpense({ amount: '20.00', currency: 'USD', exchange_rate: '0.5' })), // €10.00
  ]
  const ignored = [
    q(cashExpense({ payment_method: 'card' })),
    q(cashExpense({ took_cash: true })), // a take-and-log adds to the wallet what it logs
    q(cashExpense({ paid_by: 'u2' })),
    q(cashExpense({ transaction_date: '2026-09-30' })),
    q(cashExpense({ type: 'income' })),
    q(cashExpense(), '/api/v1/transactions/t1', 'PUT'),
  ]
  expect(queuedCashLogged([...counted, ...ignored], '2026-10', 'u1')).toBe(20)
})
