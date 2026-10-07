import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi, reply, type Routes } from '../../../test/fakeApi'
import { bucket, entry, item, page, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import { ItemSheet } from './ItemSheet'

afterEach(resetTestEnv)

const HISTORY_409 = "This bill has payment history, so it can't be deleted — deleting it would erase those payments. Deactivate it instead (the pause toggle on the bill)."
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/buckets': () => [bucket(), bucket({ id: 'b9', name: 'Naxos trip', kind: 'event' }), bucket({ id: 'b8', name: 'Old', status: 'archived' })],
  'GET /api/v1/transactions': () => page([]),
  'POST /api/v1/recurring/preview': () => ({ dates: ['2026-10-26'] }),
  ...over,
})

it('a new In item posts its rule fields and no bucket, auto-pay or shares', async () => {
  const fake = fakeApi(routes({ 'POST /api/v1/recurring': () => item({ id: 'i9', name: 'Salary', direction: 'in' }) }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={null} onClose={onClose} />)
  expect(screen.getByRole('dialog', { name: 'New item' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Salary' } })
  fireEvent.click(screen.getByRole('button', { name: 'In' }))
  expect(screen.queryByLabelText('Budget')).toBeNull()
  expect(screen.queryByRole('checkbox', { name: 'Pay automatically on the due date' })).toBeNull()
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '1500' } })
  fireEvent.change(screen.getByLabelText('Starts'), { target: { value: '2026-10-01' } })
  fireEvent.change(screen.getByLabelText('Day of the month'), { target: { value: '26' } })
  fireEvent.click(screen.getByRole('button', { name: 'Business day before' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo('POST /api/v1/recurring')[0].body).toMatchObject({
    name: 'Salary', direction: 'in', amount: '1500.00', currency: 'EUR', rule_kind: 'monthly_day', rule_day: 26,
    rule_adjust: 'previous_business_day', start_date: '2026-10-01', bucket_id: null, is_auto_pay: false,
    splits: [], payer_mode: 'single',
  })
})

it('out items choose among active monthly budgets only', async () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={null} onClose={() => {}} />)
  await waitFor(() => expect(within(screen.getByLabelText('Budget')).getAllByRole('option')).toHaveLength(2))
  expect(within(screen.getByLabelText('Budget')).getAllByRole('option').map((o) => o.textContent))
    .toEqual(['No budget (a Fixed cost)', 'Day to day'])
})

it('saving an edit keeps shares, payer mode, contract end and occurrence count', async () => {
  const shared = item({
    payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24, contract_end_date: '2027-12-31',
    splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
  })
  const fake = fakeApi(routes({ 'PUT /api/v1/recurring/{item_id}': () => shared }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={shared} onClose={onClose} />)
  expect(screen.getByRole('dialog', { name: 'Edit item' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Paid by')).toBeNull()
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Cosmote fibre' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo('PUT /api/v1/recurring/{item_id}')[0]).toMatchObject({
    path: '/api/v1/recurring/i1',
    body: {
      name: 'Cosmote fibre', payer_mode: 'own_share', paid_by_default: null, total_occurrences: 24,
      contract_end_date: '2027-12-31', splits: [{ user_id: 'u1', amount: 20 }, { user_id: 'u2', amount: 18.9 }],
    },
  })
})

it('an item with history locks direction and currency and offers no Delete', () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={item({ has_history: true })} onClose={() => {}} />)
  expect(screen.getByText("This item has payments, so its direction and currency can't change.")).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'In' })).toBeDisabled()
  expect(screen.getByLabelText('Currency')).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Delete item' })).toBeNull()
})

it('an item without history can change both and can be deleted', () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={item({ has_history: false })} onClose={() => {}} />)
  expect(screen.getByRole('button', { name: 'In' })).toBeEnabled()
  expect(screen.getByLabelText('Currency')).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Delete item' })).toBeInTheDocument()
})

it('unknown history (stale cached item) is treated as locked', () => {
  fakeApi(routes())
  const stale = { ...item(), has_history: undefined } as unknown as ReturnType<typeof item>
  renderWithProviders(<ItemSheet open item={stale} onClose={() => {}} />)
  expect(screen.getByLabelText('Currency')).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Delete item' })).toBeNull()
})

it('changing the amount of a shared item sends scaled shares and says so', async () => {
  const shared = item({ amount: 100, splits: [{ user_id: 'u1', amount: 50 }, { user_id: 'u2', amount: 50 }] })
  const fake = fakeApi(routes({ 'PUT /api/v1/recurring/{item_id}': () => shared }))
  renderWithProviders(<ItemSheet open item={shared} onClose={() => {}} />)
  expect(screen.queryByText('Shares are scaled to the new amount')).toBeNull()
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '90' } })
  expect(screen.getByText('Shares are scaled to the new amount')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(fake.callsTo('PUT /api/v1/recurring/{item_id}')).toHaveLength(1))
  expect(fake.callsTo('PUT /api/v1/recurring/{item_id}')[0].body).toMatchObject({
    splits: [{ user_id: 'u1', amount: 45 }, { user_id: 'u2', amount: 45 }],
  })
})

it('an item whose budget is archived keeps it as an extra option', async () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={item({ bucket_id: 'b8' })} onClose={() => {}} />)
  await waitFor(() => expect(within(screen.getByLabelText('Budget')).getAllByRole('option')).toHaveLength(3))
  expect(screen.getByLabelText('Budget')).toHaveValue('b8')
  expect(within(screen.getByLabelText('Budget')).getByRole('option', { name: 'Old (archived)' })).toBeInTheDocument()
})

it('an item on an event budget shows it as not monthly', async () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={item({ bucket_id: 'b9' })} onClose={() => {}} />)
  expect(await screen.findByRole('option', { name: 'Naxos trip (not monthly)' })).toBeInTheDocument()
})

it('Delete without history deletes; a 409 offers Pause instead, which pauses the saved item', async () => {
  const fake = fakeApi(routes({
    'DELETE /api/v1/recurring/{item_id}': () => reply(409, { detail: HISTORY_409 }),
    'PUT /api/v1/recurring/{item_id}': () => item({ is_active: false }),
  }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={item()} onClose={onClose} />)
  fireEvent.click(await screen.findByRole('button', { name: 'Delete item' }))
  expect(await screen.findByText(HISTORY_409)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Pause instead' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo('PUT /api/v1/recurring/{item_id}')[0].body).toMatchObject({ is_active: false, name: 'Cosmote' })
})

it('nothing is sent while the form has a problem', () => {
  const fake = fakeApi(routes())
  renderWithProviders(<ItemSheet open item={null} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Give the item a name.')
  expect(fake.callsTo('POST /api/v1/recurring')).toHaveLength(0)
})

it('the next entry opens the Entry sheet', () => {
  fakeApi(routes())
  const onOpenEntry = vi.fn()
  renderWithProviders(<ItemSheet open item={item()} onClose={() => {}} onOpenEntry={onOpenEntry} />)
  fireEvent.click(screen.getByRole('button', { name: /Next: 9 Oct/ }))
  expect(onOpenEntry).toHaveBeenCalledWith(entry())
})

it('links an existing item to its payments in Activity', async () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={item({ id: 'r-cosmote' })} onClose={() => {}} />)
  expect(await screen.findByRole('link', { name: 'See payments' })).toHaveAttribute(
    'href',
    '/activity?recurring_bill_id=r-cosmote',
  )
})

it('a new item has no See payments link', () => {
  fakeApi(routes())
  renderWithProviders(<ItemSheet open item={null} onClose={() => {}} />)
  expect(screen.queryByRole('link', { name: 'See payments' })).toBeNull()
})
