import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { affects, keys } from '../../../data/keys'
import { fakeApi } from '../../../test/fakeApi'
import { cashMovement, cashRoutes, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, testQueryClient } from '../../../test/render'
import { Cash } from './Cash'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

// Spec §4.7 / §5 "Invalidation after writes". Inactive queries (another month, Home, Plan, Insights, the
// feed) stay invalidated after the write, so isInvalidated proves the write asked for them.
const STALE: QueryKey[] = [
  keys.cashWallets('2026-01'), keys.cashMovements('2026-01'), keys.cashStash(),
  keys.home.overdue('2026-09-01', '2026-10-06'), keys.plan.month('2026-10'), keys.insights.categoriesVsUsual('2026-10'),
  keys.transactions.recent(), keys.transactions.list({}, 1), keys.matches(),
]
function seeded(): QueryClient {
  const client = testQueryClient()
  for (const k of STALE) client.setQueryData(k, { seeded: true })
  return client
}
const flags = (client: QueryClient) => STALE.map((k) => client.getQueryState(k)?.isInvalidated)

it('affects.cash covers the cash reads, Home, Plan, Insights and the transaction feed', () => {
  expect(affects.cash).toEqual(expect.arrayContaining([
    keys.cashAll(), keys.cashStash(), keys.home.all, keys.plan.all, keys.insights.all, keys.transactions.all, keys.matches(),
  ]))
})

it('a cash sheet save invalidates every key spec §4.7 lists (and the feed: a spend-take logs an expense)', async () => {
  const client = seeded()
  const api = fakeApi({ ...readRoutes(), ...cashRoutes() })
  renderWithProviders(<Cash />, { client })
  const stash = await screen.findByRole('region', { name: 'My stash' })
  fireEvent.click(within(stash).getByRole('button', { name: 'Add' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add to stash' })
  fireEvent.change(within(sheet).getByLabelText('Amount'), { target: { value: '20' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add €20.00' }))
  await waitFor(() => expect(api.callsTo('POST /api/v1/cash/movements')).toHaveLength(1))
  await waitFor(() => expect(flags(client)).toEqual(STALE.map(() => true)))
})

it('a movement delete invalidates every key spec §4.7 lists', async () => {
  const client = seeded()
  const api = fakeApi({ ...readRoutes(), ...cashRoutes({ movements: [cashMovement()] }) })
  renderWithProviders(<Cash />, { client })
  const list = await screen.findByRole('list', { name: 'Movements' })
  fireEvent.click(within(list).getByRole('button', { name: /Took from the bank/ }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Cash entry' })).getByRole('button', { name: 'Delete' }))
  await waitFor(() => expect(api.callsTo('DELETE /api/v1/cash/movements/{movement_id}')).toHaveLength(1))
  await waitFor(() => expect(flags(client)).toEqual(STALE.map(() => true)))
})

it('a refused write invalidates nothing', async () => {
  const client = seeded()
  const api = fakeApi({ ...readRoutes(), ...cashRoutes({ movements: [cashMovement()] }) })
  api.on('DELETE /api/v1/cash/movements/{movement_id}', () => Response.json({ detail: 'No.' }, { status: 400 }))
  renderWithProviders(<Cash />, { client })
  const list = await screen.findByRole('list', { name: 'Movements' })
  fireEvent.click(within(list).getByRole('button', { name: /Took from the bank/ }))
  const sheet = await screen.findByRole('dialog', { name: 'Cash entry' })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Delete' }))
  await within(sheet).findByRole('alert')
  expect(flags(client)).toEqual(STALE.map(() => false))
})
