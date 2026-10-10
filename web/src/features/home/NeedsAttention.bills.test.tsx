import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi, type Routes } from '../../test/fakeApi'
import { day, entry, readRoutes } from '../../test/fixtures'
import { installMemoryStorage } from '../../test/storage'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { billRow, billsRoutes, change } from '../insights/bills/fixtures'
import { buildAttention } from './attention'
import { resetBillDismissals } from './billDismiss'
import { NeedsAttention } from './NeedsAttention'

installMemoryStorage()
beforeEach(() => {
  resetBillDismissals()
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const changed = billRow({ change: change({ entry_id: 'e9' }) })
const routes = (rows = [changed], over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/matches': () => [],
  'GET /api/v1/recurring/entries': () => [],
  'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [entry({ id: 'e5', name: 'Gym', estimated: true, amount: 30 })], 900)],
  'GET /api/v1/plan/budgets': () => [],
  'GET /api/v1/insights/categories-vs-usual': () => [],
  ...billsRoutes(rows),
  ...over,
})
const kinds = () => Array.from(document.querySelectorAll('[data-attn]')).map((n) => n.getAttribute('data-attn'))

it('a changed bill shows "Electricity was €84, usually €61" with See why, after missingAmount', async () => {
  fakeApi(routes())
  const { router } = renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['missingAmount', 'billChange']))
  const row = document.querySelector('[data-attn="billChange"]') as HTMLElement
  expect(row).toHaveTextContent('Electricity was €84, usually €61')
  fireEvent.click(screen.getByRole('button', { name: 'See why' }))
  expect(router.state.location.pathname).toBe('/insights/bills/i1')
})

it('sits before the cash row (pure order)', () => {
  const order = buildAttention({
    today: '2026-10-07', failed: [], cashNotLogged: 12, bills: [changed],
    upcoming: [day('2026-10-09', [entry({ estimated: true })], 0)],
  }).map((i) => i.kind)
  expect(order).toEqual(['missingAmount', 'billChange', 'cash'])
})

it('only items with a change make a row, and a dismissed entry makes none', () => {
  const none = buildAttention({ today: '2026-10-07', failed: [], bills: [billRow()] })
  expect(none).toEqual([])
  const hidden = buildAttention({ today: '2026-10-07', failed: [], bills: [changed], dismissedBills: new Set(['e9']) })
  expect(hidden).toEqual([])
})

it('dismiss hides the row; a newer entry brings it back', async () => {
  const fake = fakeApi(routes())
  const { unmount, client } = renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toContain('billChange'))
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Electricity' }))
  expect(kinds()).not.toContain('billChange')
  expect(JSON.parse(localStorage.getItem('tameio.billDismissed') ?? '[]')).toEqual(['e9'])
  unmount()
  renderWithProviders(<NeedsAttention />, { client })
  await waitFor(() => expect(kinds()).toEqual(['missingAmount']))
  // A newer entry changes again.
  fake.on('GET /api/v1/insights/bills' as never, (() => [billRow({ change: change({ entry_id: 'e10', amount: 90 }) })]) as never)
  await client.invalidateQueries()
  await waitFor(() => expect(kinds()).toContain('billChange'))
  expect(document.querySelector('[data-attn="billChange"]')).toHaveTextContent('Electricity was €90')
})

it('localStorage throwing does not break Home: the row shows and can be dismissed for the session', async () => {
  const deny = () => { throw new Error('denied') }
  vi.stubGlobal('localStorage', { getItem: deny, setItem: deny, removeItem: deny, clear: deny, key: deny, length: 0 })
  resetBillDismissals()
  fakeApi(routes())
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toContain('billChange'))
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss Electricity' }))
  expect(kinds()).not.toContain('billChange')
})

it('no Bills data at all: no row and no error', async () => {
  fakeApi(routes([], { 'GET /api/v1/insights/bills': () => new Response(null, { status: 500 }) } as unknown as Routes))
  renderWithProviders(<NeedsAttention />)
  await waitFor(() => expect(kinds()).toEqual(['missingAmount']))
  expect(screen.queryByRole('alert')).toBeNull()
})
