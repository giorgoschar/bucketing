import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { makeTxn, pageOf, refRoutes, renderActivity } from '../../activity/testing'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv } from '../../../test/render'
import { BucketDetail } from './BucketDetail'

afterEach(resetTestEnv)

const base = { id: 'b-trip', household_id: 'h', name: 'Crete', type: 'trip', kind: 'event', color: '#6366f1', icon: '🏝', status: 'active',
  budget: 1000, description: null, show_income: false, enable_settlement: false, start_date: '2026-09-28', end_date: '2026-10-04',
  balance: { income: 0, expenses: 900, net: -900 } }
const trip = {
  total: 900, start: '2026-09-28', end: '2026-10-04', days: 7, nights: 6, per_day: 128.57, status: 'past', days_until: null,
  days_remaining: null, remaining: 100, transaction_count: 2,
  people: [{ user_id: 'u-me', name: 'Giorgos', color: '#000', share: 450, paid: 700 }, { user_id: 'u-maria', name: 'Maria', color: '#000', share: 450, paid: 200 }],
}
const routes = (summary: unknown) => ({
  ...refRoutes(),
  'GET /api/v1/buckets/{bucket_id}': () => base as never,
  'GET /api/v1/buckets/{bucket_id}/summary': () => summary as never,
  'GET /api/v1/transactions': () => pageOf([makeTxn({ id: 'tx1', merchant: 'Taverna', bucket_id: 'b-trip' })]),
})
const open = () => renderActivity(<BucketDetail />, { route: '/plan/buckets/b-trip', path: '/plan/buckets/:id' })

it('shows spent against budget, the trip summary with paid and share, and its entries', async () => {
  const api = fakeApi(routes({ trip, savings: null }))
  open()
  expect(await screen.findByRole('progressbar', { name: 'Crete' })).toBeInTheDocument()
  expect(screen.getByText('Spent').closest('.ui-card')).toHaveTextContent('€900 of €1,000')
  const card = (await screen.findByText('Trip')).closest('.ui-card')!
  expect(card).toHaveTextContent('7 days')
  expect(card).toHaveTextContent('finished')
  expect(card).toHaveTextContent('Total€900')
  expect(card).toHaveTextContent('Per day€129')
  expect(card).toHaveTextContent('Left€100')
  const people = within(screen.getByRole('list', { name: 'Per person' })).getAllByRole('listitem')
  expect(people[0]).toHaveTextContent('Giorgospaid €700share €450')
  expect(await screen.findByText('Taverna')).toBeInTheDocument()
  expect(api.calls.find((c) => c.path === '/api/v1/transactions')?.query.get('bucket_id')).toBe('b-trip')
})

it('a tap on an entry opens it in Activity', async () => {
  fakeApi(routes({ trip: null, savings: null }))
  open()
  fireEvent.click(await screen.findByText('Taverna'))
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/activity/tx1'))
})

it('a bucket with no typed card shows just the balance and entries; over budget says so', async () => {
  fakeApi({ ...routes({ trip: null, savings: null }), 'GET /api/v1/buckets/{bucket_id}': () => ({ ...base, balance: { income: 0, expenses: 1200, net: -1200 } }) as never })
  open()
  expect(await screen.findByText('over budget')).toBeInTheDocument()
  expect(screen.queryByText('Trip')).toBeNull()
})

it('a savings bucket shows progress to the goal', async () => {
  fakeApi(routes({ trip: null, savings: { saved: 250, goal: 1000, pct: 25, pct_actual: 25, remaining: 750, per_month: 125, months_left: 6, reached: false, target_date: null } }))
  open()
  const card = (await screen.findByText('Savings goal', { selector: 'span' })).closest('.ui-card')!
  expect(card).toHaveTextContent('€250 of €1,000')
  expect(card).toHaveTextContent('€125 a month for 6 months')
})

it('ends with a link to Activity filtered to this bucket, and Edit is an icon in the header', async () => {
  fakeApi(routes({ trip: null, savings: null }))
  open()
  expect(await screen.findByRole('link', { name: 'See all in Activity' })).toHaveAttribute('href', '/activity?bucket_id=b-trip')
  fireEvent.click(screen.getByRole('button', { name: 'Edit bucket' }))
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
})
