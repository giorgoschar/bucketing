import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { listQueuedBodies } from '../../offline/queuedBodies'
import { fakeApi, type Routes } from '../../test/fakeApi'
import type { EntryOut, RecurringItemOut } from '../../data/types'
import { entry, item, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { EntrySheet } from './EntrySheet'
import { applyChange } from './entryPatch'
import { parseUsage } from '../insights/bills/usage'

afterEach(resetTestEnv)

const DONE = 'POST /api/v1/recurring/entries/{entry_id}/done' as const
const AMOUNT = 'POST /api/v1/recurring/entries/{entry_id}/amount' as const
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/recurring': () => [item({ paid_by_default: 'u2' })],
  ...over,
})
const metered = (over: Partial<EntryOut> = {}): EntryOut =>
  ({ ...entry({ name: 'Electricity' }), usage: null, usage_unit: 'kWh', ...over })

it('parseUsage: comma or point, three decimals, blank is null, garbage is undefined', () => {
  expect(parseUsage('412,5')).toBe(412.5)
  expect(parseUsage('412.125')).toBe(412.125)
  expect(parseUsage('  ')).toBeNull()
  expect(parseUsage('0')).toBe(0)
  expect(parseUsage('1.2345')).toBeUndefined()
  expect(parseUsage('-3')).toBeUndefined()
  expect(parseUsage('abc')).toBeUndefined()
  expect(parseUsage('1234567890')).toBeUndefined()
})

it('Pay shows "Usage (kWh)" only for an item with a unit', () => {
  fakeApi(routes())
  const { unmount } = renderWithProviders(<EntrySheet entry={metered()} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  expect(screen.getByLabelText('Usage (kWh)')).toBeInTheDocument()
  unmount()
  renderWithProviders(<EntrySheet entry={entry()} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  expect(screen.queryByLabelText(/^Usage/)).toBeNull()
})

it('the unit can come from the item when the entry does not carry it', async () => {
  fakeApi(routes({ 'GET /api/v1/recurring': () => [{ ...item(), usage_unit: 'm³' } as RecurringItemOut] }))
  renderWithProviders(<EntrySheet entry={entry()} onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  expect(await screen.findByLabelText('Usage (m³)')).toBeInTheDocument()
})

it('Pay with a decimal comma sends usage as a number; empty sends no usage key', async () => {
  const fake = fakeApi(routes({ [DONE]: () => entry({ status: 'done' }) }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={metered()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: '412,5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(DONE)[0].body).toMatchObject({ amount: '38.90', usage: 412.5 })
})

it('Pay with the usage left empty omits the key', async () => {
  const fake = fakeApi(routes({ [DONE]: () => entry({ status: 'done' }) }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={metered()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(DONE)[0].body).not.toHaveProperty('usage')
})

it('Set amount sends usage when filled and omits it when empty; bad usage blocks saving', async () => {
  const fake = fakeApi(routes({ [AMOUNT]: () => entry() }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={metered()} intent="amount" onClose={onClose} />)
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '86,40' } })
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: 'lots' } })
  expect(screen.getByRole('button', { name: 'Save amount' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: '412,5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save amount' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(AMOUNT)[0].body).toEqual({ amount: '86.40', usage: 412.5 })
})

it('Set amount with no usage typed sends only the amount, as before', async () => {
  const fake = fakeApi(routes({ [AMOUNT]: () => entry() }))
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={metered()} intent="amount" onClose={onClose} />)
  fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '86.40' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save amount' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(AMOUNT)[0].body).toEqual({ amount: '86.40' })
})

it('offline: the queued Pay body carries usage', async () => {
  fakeApi(routes())
  setOnline(false)
  const onClose = vi.fn()
  renderWithProviders(<EntrySheet entry={metered()} onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
  fireEvent.change(screen.getByLabelText('Usage (kWh)'), { target: { value: '300' } })
  fireEvent.click(screen.getByRole('button', { name: 'Mark paid €38.90' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(await db.queue.count()).toBe(1)
  const queued = await listQueuedBodies('/api/v1/recurring/entries/')
  expect(queued[0].body).toMatchObject({ amount: '38.90', usage: 300 })
})

it('the optimistic patch keeps the entry usage, and sets it when a change brings one', () => {
  const e = metered({ usage: 100 })
  expect(applyChange(e, { kind: 'amount', amount: 90 })).toMatchObject({ amount: 90, usage: 100 })
  expect(applyChange(e, { kind: 'done', amount: 90, today: '2026-10-09' })).toMatchObject({ usage: 100 })
  expect(applyChange(e, { kind: 'done', amount: 90, today: '2026-10-09', usage: 120 })).toMatchObject({ usage: 120 })
  expect(applyChange(e, { kind: 'undo' })).toMatchObject({ usage: 100 })
  expect(applyChange(e, { kind: 'skip' })).toMatchObject({ usage: 100 })
})
