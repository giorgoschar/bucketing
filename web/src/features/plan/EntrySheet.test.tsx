import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { fakeApi, reply, type Routes } from '../../test/fakeApi'
import { entry, household, item, member, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { EntrySheet } from './EntrySheet'

afterEach(resetTestEnv)

const DONE = 'POST /api/v1/recurring/entries/{entry_id}/done' as const
const AMOUNT = 'POST /api/v1/recurring/entries/{entry_id}/amount' as const
const SKIP = 'POST /api/v1/recurring/entries/{entry_id}/skip' as const
const UNDO = 'POST /api/v1/recurring/entries/{entry_id}/undo' as const
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/recurring': () => [item({ paid_by_default: 'u2' })],
  ...over,
})

it('expected out entry: Paid prefills amount, the item payer and card, then posts done and closes', async () => {
  const fake = fakeApi(routes({ [DONE]: () => entry({ status: 'done' }) }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry()} onClose={onClose} />)
  const sheet = screen.getByRole('dialog', { name: 'Cosmote' })
  expect(sheet).toHaveTextContent('Due Fri 9 Oct')
  expect(sheet).toHaveTextContent('€38.90')
  fireEvent.click(within(sheet).getByRole('button', { name: 'Paid' }))
  expect(screen.getByLabelText('Amount')).toHaveValue('38.90')
  await waitFor(() => expect(screen.getByRole('button', { name: 'Maria' })).toHaveAttribute('aria-pressed', 'true'))
  expect(screen.getByRole('button', { name: 'Card' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(DONE)).toMatchObject([
    { path: '/api/v1/recurring/entries/e1/done', body: { amount: '38.90', person: 'u2', payment_method: 'card' } },
  ])
})

it('expected in entry: Received, "Received by" and transfer by default', async () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ direction: 'in', name: 'Salary', amount: 1500, payment_method: 'transfer' })} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Received' }))
  expect(screen.getByRole('button', { name: 'Transfer' })).toHaveAttribute('aria-pressed', 'true')
  expect(await screen.findByRole('group', { name: 'Received by' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Mark received €1,500.00' })).toBeEnabled()
})

it('Set amount accepts a comma and sends a dot; garbage is refused before sending', async () => {
  const fake = fakeApi(routes({ [AMOUNT]: () => entry({ amount: 86.4 }) }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry({ name: 'Electricity', estimated: true, amount: 83.5 })} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Set amount' }))
  const input = screen.getByLabelText('Amount')
  expect(input).toHaveAttribute('placeholder', 'Usually ≈ €83.50')
  fireEvent.change(input, { target: { value: 'abc' } })
  expect(screen.getByText('Enter an amount like 86.40')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save amount' })).toBeDisabled()
  fireEvent.change(input, { target: { value: '86,40' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save amount' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(AMOUNT)[0].body).toEqual({ amount: '86.40' })
})

it('intent amount opens straight on Set amount', () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ estimated: true })} intent="amount" onClose={() => {}} />)
  expect(screen.getByLabelText('Amount')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Paid' })).toBeNull()
})

it('undo of a paid out entry asks; a Fixed-cost 409 is shown inline and only Delete the expense remains', async () => {
  const fixed = "This expense has no bucket, so it can't stay without its bill. Delete it too, or give it a bucket first."
  const fake = fakeApi(routes({
    [UNDO]: (req) => ((req.body as { delete_transaction: boolean }).delete_transaction ? entry() : reply(409, { detail: fixed })),
  }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry({ status: 'done', transaction_id: 't1' })} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  fireEvent.click(screen.getByRole('button', { name: 'Keep the expense' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(fixed)
  expect(screen.queryByRole('button', { name: 'Keep the expense' })).toBeNull()
  expect(onClose).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete the expense' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(UNDO).map((c) => c.body)).toEqual([{ delete_transaction: false }, { delete_transaction: true }])
})

it('undo of a skipped entry is direct', async () => {
  const fake = fakeApi(routes({ [UNDO]: () => entry() }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry({ status: 'skipped' })} onClose={onClose} />)
  expect(screen.getByRole('dialog')).toHaveTextContent('Skipped')
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(UNDO)[0].body).toEqual({ delete_transaction: false })
})

it('a one-member household gets no "Paid by" choice and sends that member', async () => {
  const fake = fakeApi(routes({
    'GET /api/v1/settings/household': () => household([member()]),
    'GET /api/v1/recurring': () => [item({ paid_by_default: null })],
    [DONE]: () => entry({ status: 'done' }),
  }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  await waitFor(() => expect(fake.callsTo('GET /api/v1/settings/household')).toHaveLength(1))
  await new Promise((r) => setTimeout(r, 20))
  expect(screen.queryByRole('group', { name: 'Paid by' })).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(DONE)[0].body).toMatchObject({ person: 'u1' })
})

it('offline: Skip is queued and the sheet closes', async () => {
  const fake = fakeApi(routes())
  setOnline(false)
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={entry()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(await db.queue.count()).toBe(1)
  expect(fake.callsTo(SKIP)).toHaveLength(0)
})

it('an overdue entry says so in words', () => {
  fakeApi(routes())
  renderWithProviders(<EntrySheet entry={entry({ overdue: true })} onClose={() => {}} />)
  expect(screen.getByRole('dialog')).toHaveTextContent('Overdue')
})

it.each([
  ['Skip', SKIP, () => {}],
  ['Mark paid €38.90', DONE, () => fireEvent.click(screen.getByRole('button', { name: 'Paid' }))],
  ['Save amount', AMOUNT, () => {
    fireEvent.click(screen.getByRole('button', { name: 'Set amount' }))
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '40' } })
  }],
] as const)('a rejected %s shows the server message once, inline, with no toast on top', async (button, route, open) => {
  const detail = 'This entry is already done.'
  fakeApi(routes({ [route]: () => reply(409, { detail }) }))
  renderWithProviders(<EntrySheet entry={entry()} onClose={() => {}} />)
  open()
  if (route === DONE) await waitFor(() => expect(screen.getByRole('button', { name: button })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: button }))
  const inline = await screen.findByRole('alert')
  expect(inline).toHaveTextContent(detail)
  expect(within(screen.getByRole('dialog')).getByRole('alert')).toBe(inline)
  await new Promise((r) => setTimeout(r, 20))
  expect(screen.getAllByRole('alert')).toHaveLength(1)
})

it('Paid opens with the item\'s payment method and sends it', async () => {
  const fake = fakeApi(routes({ [DONE]: () => entry({ status: 'done' }) }))
  renderWithProviders(<EntrySheet entry={entry({ payment_method: 'cash' })} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  expect(screen.getByRole('button', { name: 'Cash' })).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByRole('button', { name: 'Card' })).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(fake.callsTo(DONE)).toHaveLength(1))
  expect(fake.callsTo(DONE)[0].body).toMatchObject({ payment_method: 'cash' })
})
