import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../../data/keys'
import { notifyDrained } from '../../../offline/queueDrain'
import { fakeApi } from '../../../test/fakeApi'
import { pantryRoutes, productSummary, stockDetail, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, testQueryClient } from '../../../test/render'
import { AddSheet } from './AddSheet'
import { Detail } from './Detail'
import { PANTRY_INVALIDATES, PANTRY_SHOPPING_COUNT_KEY } from './hooks'
import { Pantry } from './Pantry'

afterEach(resetTestEnv)

// Pantry spec §4.8 / §5 "Invalidation after writes": the list, the shopping list, the item and Home.
// Inactive seeded queries stay invalidated after the write, so isInvalidated proves the write asked for them.
const HOME = keys.home.overdue('2026-09-01', '2026-10-06')
const STALE: QueryKey[] = [keys.stockList(), PANTRY_SHOPPING_COUNT_KEY, keys.stockItem('s9'), HOME]
function seeded(): QueryClient {
  const client = testQueryClient()
  for (const k of STALE) client.setQueryData(k, { seeded: true })
  return client
}
const flags = (client: QueryClient) => STALE.map((k) => client.getQueryState(k)?.isInvalidated)

const LIST = 'GET /api/v1/stock' as const
const SHOPPING = 'GET /api/v1/stock/shopping' as const
const DETAIL = 'GET /api/v1/stock/{item_id}' as const

function detailRoutes() {
  return {
    ...pantryRoutes(),
    [DETAIL]: () => stockDetail(),
    'PATCH /api/v1/stock/{item_id}': () => stockItem({ min_quantity: 2 }),
    'POST /api/v1/stock/{item_id}/refresh': () => stockDetail(),
    'POST /api/v1/stock/{item_id}/archive': () => null,
  } as const
}

it('the pantry invalidations cover every stock read and Home', () => {
  expect(PANTRY_INVALIDATES).toEqual(expect.arrayContaining([['stock'], keys.home.all]))
})

it('a stepper adjust refetches the list and the shopping list', async () => {
  const fake = fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  const milk = await screen.findByRole('listitem', { name: 'Milk' })
  await waitFor(() => expect(fake.callsTo(SHOPPING)).toHaveLength(1))
  const before = [fake.callsTo(LIST).length, fake.callsTo(SHOPPING).length]
  fireEvent.click(within(milk).getByRole('button', { name: 'Increase Milk' }))
  await waitFor(() => expect(fake.callsTo(LIST).length).toBeGreaterThan(before[0]))
  await waitFor(() => expect(fake.callsTo(SHOPPING).length).toBeGreaterThan(before[1]))
})

it('adding a product invalidates the list, the shopping list, items and Home', async () => {
  const client = seeded()
  const fake = fakeApi({
    ...pantryRoutes(),
    'GET /api/v1/products/search': () => [productSummary()],
    'POST /api/v1/stock': () => Response.json(stockItem({ id: 'new' }), { status: 201 }),
  })
  renderWithProviders(<AddSheet open onClose={() => {}} />, { client })
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search PosoKanei' }), { target: { value: 'feta' } })
  fireEvent.click(await screen.findByRole('button', { name: 'Add Dodoni Feta PDO' }))
  await waitFor(() => expect(fake.callsTo('POST /api/v1/stock')).toHaveLength(1))
  await waitFor(() => expect(flags(client)).toEqual([true, true, true, true]))
})

it('a settings PATCH and a refresh refetch the item and invalidate the rest', async () => {
  const client = seeded()
  client.removeQueries({ queryKey: keys.stockList() })
  const fake = fakeApi(detailRoutes())
  renderWithProviders(<Detail id="s1" />, { client })
  fireEvent.click(await screen.findByRole('switch', { name: 'Track price' }))
  await waitFor(() => expect(fake.callsTo(DETAIL)).toHaveLength(2))
  await waitFor(() => expect(client.getQueryState(PANTRY_SHOPPING_COUNT_KEY)?.isInvalidated).toBe(true))
  expect(client.getQueryState(HOME)?.isInvalidated).toBe(true)

  fireEvent.click(screen.getByRole('button', { name: 'Refresh prices' }))
  await waitFor(() => expect(fake.callsTo(DETAIL)).toHaveLength(3))
})

it('archive invalidates the pantry but never refetches the archived item', async () => {
  const client = seeded()
  const fake = fakeApi(detailRoutes())
  renderWithProviders(<Detail id="s1" />, { client })
  fireEvent.click(await screen.findByRole('button', { name: 'Archive product' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Archive' }))
  await waitFor(() => expect(fake.callsTo('POST /api/v1/stock/{item_id}/archive')).toHaveLength(1))
  await waitFor(() => expect(client.getQueryState(keys.stockList())?.isInvalidated).toBe(true))
  expect(client.getQueryState(HOME)?.isInvalidated).toBe(true)
  expect(fake.callsTo(DETAIL)).toHaveLength(1)
})

it('after the offline queue replays, the pantry is refetched (a queued adjust gets the server’s numbers)', async () => {
  const fake = fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  await screen.findByRole('listitem', { name: 'Milk' })
  const before = fake.callsTo(LIST).length
  act(() => notifyDrained({ sent: 1, failed: 0, stoppedOnAuth: false }))
  await waitFor(() => expect(fake.callsTo(LIST).length).toBeGreaterThan(before))
})
