import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi, reply } from '../../test/fakeApi'
import { budgetRow } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Budgets } from './Budgets'
import { BucketDetail } from './bucket/BucketDetail'
import { makeTxn, pageOf, refRoutes, renderActivity } from '../activity/testing'

afterEach(resetTestEnv)

const POST = 'POST /api/v1/buckets' as const
const PUT = 'PUT /api/v1/buckets/{bucket_id}' as const
const ARCHIVE = 'POST /api/v1/buckets/{bucket_id}/archive' as const
const raw = { id: 'b1', name: 'Day to day', type: 'custom', kind: 'monthly', color: '#112233', icon: '🛒', budget: 1200, description: 'x',
  show_income: false, enable_settlement: true, start_date: null, end_date: null, status: 'active' }

function setupDetail(extra = {}) {
  const fake = fakeApi({
    ...refRoutes(),
    'GET /api/v1/buckets/{bucket_id}': () => ({ ...raw, balance: { income: 0, expenses: 10, net: -10 } }),
    'GET /api/v1/buckets/{bucket_id}/summary': () => ({ trip: null, savings: null }),
    'GET /api/v1/transactions': () => pageOf([makeTxn()]),
    ...extra,
  } as never)
  renderActivity(<BucketDetail />, { route: '/plan/buckets/b1', path: '/plan/buckets/:id' })
  return fake
}

function setup(extra = {}) {
  let rows = [raw]
  const fake = fakeApi({
    'GET /api/v1/plan/budgets': () => rows.map((r) => budgetRow({ bucket_id: r.id, name: r.name })),
    'GET /api/v1/plan/pace': () => [],
    'GET /api/v1/buckets': () => rows,
    [ARCHIVE]: () => { rows = []; return reply(200, {}) },
    ...extra,
  } as never)
  renderWithProviders(<Budgets />)
  return fake
}
const dialog = () => screen.getByRole('dialog')
const type = (label: string, value: string) => fireEvent.change(within(dialog()).getByLabelText(label), { target: { value } })

it('creates a monthly bucket with a name and a budget', async () => {
  const fake = setup({ [POST]: () => reply(201, raw) })
  fireEvent.click(await screen.findByRole('button', { name: 'New bucket' }))
  type('Name', '  Holidays ')
  type('Budget (optional)', '250,5')
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Add bucket' }))
  await waitFor(() => expect(fake.callsTo(POST)).toHaveLength(1))
  expect(fake.callsTo(POST)[0].body).toMatchObject({ name: 'Holidays', kind: 'monthly', budget: '250.50', start_date: null, end_date: null })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('creates a trip with its dates', async () => {
  const fake = setup({ [POST]: () => reply(201, raw) })
  fireEvent.click(await screen.findByRole('button', { name: 'New bucket' }))
  type('Name', 'Naxos')
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Trip or event' }))
  type('Starts', '2026-10-01')
  type('Ends', '2026-10-08')
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Add bucket' }))
  await waitFor(() => expect(fake.callsTo(POST)).toHaveLength(1))
  expect(fake.callsTo(POST)[0].body).toMatchObject({ name: 'Naxos', kind: 'event', budget: null, start_date: '2026-10-01', end_date: '2026-10-08' })
})

it('refuses an empty name and an event without dates, sending nothing', async () => {
  const fake = setup()
  fireEvent.click(await screen.findByRole('button', { name: 'New bucket' }))
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Add bucket' }))
  expect(await within(dialog()).findByRole('alert')).toHaveTextContent('Give the bucket a name.')
  type('Name', 'Trip')
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Trip or event' }))
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Add bucket' }))
  expect(await within(dialog()).findByRole('alert')).toHaveTextContent('needs a start and an end date')
  expect(fake.callsTo(POST)).toHaveLength(0)
})

it('shows a server rejection inline and keeps the sheet open', async () => {
  setup({ [POST]: () => reply(400, { detail: 'The end date is before the start date.' }) })
  fireEvent.click(await screen.findByRole('button', { name: 'New bucket' }))
  type('Name', 'Trip')
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Add bucket' }))
  expect(await within(dialog()).findByRole('alert')).toHaveTextContent('The end date is before the start date.')
})

it('Edit opens the saved bucket and PUTs it back with its stored fields', async () => {
  const fake = setupDetail({ [PUT]: () => raw })
  fireEvent.click(await screen.findByRole('button', { name: 'Edit bucket' }))
  expect(within(dialog()).getByLabelText('Name')).toHaveValue('Day to day')
  type('Name', 'Daily')
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(fake.callsTo(PUT)).toHaveLength(1))
  expect(fake.callsTo(PUT)[0].path).toBe('/api/v1/buckets/b1')
  expect(fake.callsTo(PUT)[0].body).toMatchObject({ name: 'Daily', kind: 'monthly', budget: '1200.00', color: '#112233', icon: '🛒', enable_settlement: true })
})

it('Archive asks inside the sheet first, then POSTs', async () => {
  const fake = setupDetail({ [ARCHIVE]: () => reply(200, {}) })
  fireEvent.click(await screen.findByRole('button', { name: 'Edit bucket' }))
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Archive' }))
  expect(fake.callsTo(ARCHIVE)).toHaveLength(0)
  expect(within(dialog()).getByText(/Archive Day to day\? There is no undo/)).toBeInTheDocument()
  fireEvent.click(within(dialog()).getByRole('button', { name: 'Confirm archive' }))
  await waitFor(() => expect(fake.callsTo(ARCHIVE)).toHaveLength(1))
  expect(fake.callsTo(ARCHIVE)[0].path).toBe('/api/v1/buckets/b1/archive')
})
