import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../../data/keys'
import { db } from '../../../offline/db'
import { listQueuedBodies } from '../../../offline/queuedBodies'
import { fakeApi, reply } from '../../../test/fakeApi'
import { shoppingItem, shoppingOut, shoppingRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline, testQueryClient } from '../../../test/render'
import { ShoppingList } from './ShoppingList'

afterEach(resetTestEnv)

const TICKS = 'POST /api/v1/stock/shopping/ticks' as const
const UNTICK = 'DELETE /api/v1/stock/shopping/ticks/{tick_id}' as const
const LINES = 'POST /api/v1/stock/shopping/lines' as const
const LINE = 'PATCH /api/v1/stock/shopping/lines/{line_id}' as const
const LINE_DEL = 'DELETE /api/v1/stock/shopping/lines/{line_id}' as const
const APPLY = 'POST /api/v1/stock/shopping/apply-ticked' as const

const store = (name: string) => screen.getByRole('region', { name })
const row = (name: string) => screen.getByRole('checkbox', { name })
const loaded = () => screen.findByRole('region', { name: 'Lidl' })

it('the header counts the items and stores and shows the total', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  const head = screen.getByRole('region', { name: 'Shopping total' })
  expect(head).toHaveTextContent('4 items · 2 stores')
  expect(head).toHaveTextContent('€13.05')
})

it('"saves €X vs one store" shows when splitting saves more than €0.50', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(screen.getByText('saves €2.40 vs one store')).toBeInTheDocument()
})

it.each([
  ['saves only €0.40', { retailer: 'lidl', retailer_name: 'Lidl', total: 13.45, covers: 3, missing: 0 }],
  ['saves exactly €0.50', { retailer: 'lidl', retailer_name: 'Lidl', total: 13.55, covers: 3, missing: 0 }],
  ['the single store misses an item', { retailer: 'lidl', retailer_name: 'Lidl', total: 15.45, covers: 2, missing: 1 }],
  ['no single store', null],
])('no saves badge when %s', async (_why, best) => {
  fakeApi(shoppingRoutes(shoppingOut({ best_single_store: best })))
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(screen.queryByText(/vs one store/)).toBeNull()
})

it('groups rows by store with subtotals, and No price comes last', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  const names = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
  expect(names.slice(0, 3)).toEqual(['Lidl', 'Sklavenitis', 'No price'])
  expect(store('Lidl')).toHaveTextContent('€10.67')
  expect(within(store('Lidl')).getAllByRole('checkbox').map((c) => c.getAttribute('aria-label'))).toEqual(['Olive oil × 1', 'Milk × 2'])
  expect(store('Sklavenitis')).toHaveTextContent('€2.38')
  expect(within(store('No price')).getByRole('checkbox', { name: 'Salt × 1' })).toBeInTheDocument()
})

it('each row has its reason line and line price', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Olive oil × 1')).toHaveTextContent('Low · 1 left')
  expect(row('Olive oil × 1')).toHaveTextContent('€8.49')
  expect(row('Milk × 2')).toHaveTextContent('Low · 0 left · €1.09 each')
  expect(row('Milk × 2')).toHaveTextContent('€2.18')
  expect(row('Barilla spaghetti × 2')).toHaveTextContent('Runs out in ~5 d')
  expect(row('Barilla spaghetti × 2')).toHaveTextContent('Price drop')
})

it('a row without the current quantity reads just "Low"', async () => {
  fakeApi(shoppingRoutes(shoppingOut({ items: [shoppingItem({ quantity: undefined })], groups: [
    { retailer: 'lidl', retailer_name: 'Lidl', total: 8.49, item_ids: ['s-oil'] },
  ] })))
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Olive oil × 1')).toHaveTextContent(/^Olive oil × 1Low€8\.49$/)
})

it('a tick is optimistic and posts the item; it never touches stock', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'true'))
  await waitFor(() => expect(api.callsTo(TICKS)).toHaveLength(1))
  expect(api.callsTo(TICKS)[0].body).toEqual({ stock_item_id: 's-milk' })
  expect(api.calls.some((c) => c.path.includes('/adjust') || c.path.includes('/transactions'))).toBe(false)
})

it('offline, a tick is queued and stays ticked', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  expect(api.callsTo(TICKS)).toHaveLength(0)
  expect(await listQueuedBodies('/api/v1/stock')).toEqual([
    expect.objectContaining({ method: 'POST', path: '/api/v1/stock/shopping/ticks', body: { stock_item_id: 's-milk' } }),
  ])
  expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'true')
  expect(row('Milk × 2')).toHaveTextContent('Waiting to sync')
})

it('unticking deletes the tick by its id, queued offline', async () => {
  const data = shoppingOut({ ticked_count: 1 })
  data.items[1] = { ...data.items[1], ticked: true, tick_id: 'tick-9' }
  const api = fakeApi(shoppingRoutes(data))
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'true')
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  expect(await listQueuedBodies('/api/v1/stock')).toEqual([
    expect.objectContaining({ method: 'DELETE', path: '/api/v1/stock/shopping/ticks/tick-9' }),
  ])
  expect(api.callsTo(UNTICK)).toHaveLength(0)
})

it('one-off lines: add with an optional quantity', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: '  Kitchen roll ' } })
  fireEvent.change(within(sheet).getByLabelText('Quantity (optional)'), { target: { value: '3' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(api.callsTo(LINES)).toHaveLength(1))
  expect(api.callsTo(LINES)[0].body).toEqual({ name: 'Kitchen roll', quantity: 3 })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('checkbox', { name: 'Kitchen roll × 3' })).toBeInTheDocument()
})

it('one-off lines: an empty name cannot be added', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: '   ' } })
  expect(within(sheet).getByRole('button', { name: 'Add' })).toBeDisabled()
  expect(api.callsTo(LINES)).toHaveLength(0)
})

it('one-off lines: add is queued offline and shows as waiting', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: 'Kitchen roll' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  expect(api.callsTo(LINES)).toHaveLength(0)
  const line = screen.getByRole('checkbox', { name: 'Kitchen roll' })
  expect(line).toHaveTextContent('Waiting to sync')
  // No id yet: it can't be checked or deleted until it syncs.
  expect(line).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Delete Kitchen roll' })).toBeDisabled()
})

it('one-off lines: check and uncheck PATCH the line; offline it is queued', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(screen.getByRole('checkbox', { name: 'Batteries' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Batteries' })).toHaveAttribute('aria-checked', 'true'))
  await waitFor(() => expect(api.callsTo(LINE)).toHaveLength(1))
  expect(api.callsTo(LINE)[0]).toMatchObject({ path: '/api/v1/stock/shopping/lines/l1', body: { checked: true } })
  setOnline(false)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Batteries' }))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  expect(api.callsTo(LINE)).toHaveLength(1)
})

it('one-off lines: Delete removes the line; offline it is queued', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(screen.getByRole('button', { name: 'Delete Batteries' }))
  await waitFor(() => expect(screen.queryByRole('checkbox', { name: 'Batteries' })).toBeNull())
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  expect(api.callsTo(LINE_DEL)).toHaveLength(0)
  expect(await listQueuedBodies('/api/v1/stock')).toEqual([
    expect.objectContaining({ method: 'DELETE', path: '/api/v1/stock/shopping/lines/l1' }),
  ])
})

it('the footer reads "N ticked · Add to pantry" only with something ticked', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(screen.queryByRole('button', { name: 'Add to pantry' })).toBeNull()
  fireEvent.click(row('Milk × 2'))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Batteries' }))
  const foot = await screen.findByRole('region', { name: 'Ticked items' })
  expect(foot).toHaveTextContent('2 ticked')
  expect(within(foot).getByRole('button', { name: 'Add to pantry' })).toBeEnabled()
})

it('Add to pantry calls apply-ticked and toasts what went in', async () => {
  const data = shoppingOut({ ticked_count: 2 })
  data.items[0] = { ...data.items[0], ticked: true, tick_id: 't1' }
  data.items[1] = { ...data.items[1], ticked: true, tick_id: 't2' }
  const api = fakeApi(shoppingRoutes(data))
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(screen.getByRole('button', { name: 'Add to pantry' }))
  expect(await screen.findByText('Olive oil 1 → 2 · Milk 0 → 2')).toBeInTheDocument()
  expect(api.callsTo(APPLY)).toHaveLength(1)
  expect(api.callsTo(APPLY)[0].body).toEqual({})
})

it('Add to pantry is online only: disabled offline, never queued', async () => {
  const api = fakeApi(shoppingRoutes(shoppingOut({ ticked_count: 1 })))
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  const foot = screen.getByRole('region', { name: 'Ticked items' })
  await waitFor(() => expect(within(foot).getByRole('button', { name: 'Add to pantry' })).toBeDisabled())
  expect(foot).toHaveTextContent('Connect to change the pantry')
  expect(api.callsTo(APPLY)).toHaveLength(0)
  expect(await db.queue.count()).toBe(0)
})

it('a failed apply-ticked says so and changes nothing', async () => {
  const api = fakeApi(shoppingRoutes(shoppingOut({ ticked_count: 1 })))
  api.on(APPLY, () => reply(400, { detail: 'Nothing to apply.' }))
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(screen.getByRole('button', { name: 'Add to pantry' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Nothing to apply.')
})

it('says that ticking never changes expenses', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(screen.getByText('Ticked items go into your pantry when you confirm. Nothing here changes your expenses.')).toBeInTheDocument()
})

it('Back goes to Plan › Pantry', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/plan?view=pantry')
})

it('an empty list says so and still offers Add item', async () => {
  fakeApi(shoppingRoutes(shoppingOut({ items: [], groups: [], lines: [], total: 0, best_single_store: null, unpriced: 0 })))
  renderWithProviders(<ShoppingList />)
  expect(await screen.findByText('Nothing to buy')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Add item' })).toBeInTheDocument()
})

// ---- Invalidation (spec §4.8): the pantry reads (under ['stock']) and Home's attention.

const STALE: QueryKey[] = [['stock', 'list'], ['stock', 'item', 's-milk'], keys.stockSummary(), keys.home.overdue('2026-09-01', '2026-10-06')]
function seeded(): QueryClient {
  const client = testQueryClient()
  for (const k of STALE) client.setQueryData(k, { seeded: true })
  return client
}
const flags = (client: QueryClient) => STALE.map((k) => client.getQueryState(k)?.isInvalidated)

it.each([
  ['a tick', () => fireEvent.click(row('Milk × 2')), TICKS],
  ['a line check', () => fireEvent.click(screen.getByRole('checkbox', { name: 'Batteries' })), LINE],
  ['a line delete', () => fireEvent.click(screen.getByRole('button', { name: 'Delete Batteries' })), LINE_DEL],
] as const)('%s invalidates the pantry reads and Home', async (_what, act, route) => {
  const client = seeded()
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />, { client })
  await loaded()
  act()
  await waitFor(() => expect(api.callsTo(route)).toHaveLength(1))
  await waitFor(() => expect(flags(client)).toEqual(STALE.map(() => true)))
})

it('Add to pantry invalidates the pantry reads and Home', async () => {
  const client = seeded()
  const api = fakeApi(shoppingRoutes(shoppingOut({ ticked_count: 1 })))
  renderWithProviders(<ShoppingList />, { client })
  await loaded()
  fireEvent.click(screen.getByRole('button', { name: 'Add to pantry' }))
  await waitFor(() => expect(api.callsTo(APPLY)).toHaveLength(1))
  await waitFor(() => expect(flags(client)).toEqual(STALE.map(() => true)))
})
