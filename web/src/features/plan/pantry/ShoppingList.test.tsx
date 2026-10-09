import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../../data/keys'
import { db } from '../../../offline/db'
import { listQueuedBodies } from '../../../offline/queuedBodies'
import { fakeApi, reply } from '../../../test/fakeApi'
import { replay } from '../../../offline/queue'
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
/** A client-made id: a uuid4, lower-case, as the server requires (pantry fix round 1, I2). */
const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const anId = expect.stringMatching(UUID4)

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
  expect(api.callsTo(TICKS)[0].body).toEqual({ id: anId, stock_item_id: 's-milk' })
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
    expect.objectContaining({ method: 'POST', path: '/api/v1/stock/shopping/ticks', body: { id: anId, stock_item_id: 's-milk' } }),
  ])
  expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'true')
  expect(row('Milk × 2')).toHaveTextContent('Waiting to sync')
  // The tick carries its own id from the start, so it can be taken back before it syncs.
  expect(row('Milk × 2')).toBeEnabled()
})

it('offline, a tick and then an untick queue in that order and replay in order: nothing stays ticked', async () => {
  const api = fakeApi({ ...shoppingRoutes(), 'GET /api/v1/auth/me': () => ME })
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false'))
  await waitFor(async () => expect(await db.queue.count()).toBe(2))
  const [tick, untick] = await listQueuedBodies('/api/v1/stock')
  const id = (tick.body as { id: string }).id
  expect(tick).toMatchObject({ method: 'POST', path: '/api/v1/stock/shopping/ticks', body: { id: anId, stock_item_id: 's-milk' } })
  expect(untick).toMatchObject({ method: 'DELETE', path: `/api/v1/stock/shopping/ticks/${id}` })

  setOnline(true)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(0)
  expect(api.calls.filter((c) => c.path.startsWith('/api/v1/stock/shopping/ticks')).map((c) => `${c.method} ${c.path}`))
    .toEqual(['POST /api/v1/stock/shopping/ticks', `DELETE /api/v1/stock/shopping/ticks/${id}`])
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false'))
  expect(screen.queryByRole('region', { name: 'Ticked items' })).toBeNull()
})

it('a replayed tick (its reply was lost) does not tick twice: the same id is sent again', async () => {
  const server = shoppingRoutes()
  const api = fakeApi({ ...server, 'GET /api/v1/auth/me': () => ME })
  const tickHandler = server[TICKS]!
  let lost = true
  api.on(TICKS, async (r) => {
    const out = await tickHandler(r)
    if (lost) { lost = false; throw new TypeError('Failed to fetch') } // applied, but the reply never arrives
    return out
  })
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  setOnline(true)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(1)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(0)
  const [first, second] = api.callsTo(TICKS)
  expect(second.body).toEqual(first.body)
  const after = await (await fetch('/api/v1/stock/shopping')).json() as { items: { id: string; ticked: boolean }[]; ticked_count: number }
  expect(after.ticked_count).toBe(1)
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
  expect(api.callsTo(LINES)[0].body).toEqual({ id: anId, name: 'Kitchen roll', quantity: 3 })
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
  // The line has its client-made id from the start: it can be checked or deleted before it syncs.
  expect(line).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Delete Kitchen roll' })).toBeEnabled()
})

it('offline, a new line checked and then deleted queues create, check, delete in order and replays in order', async () => {
  const api = fakeApi({ ...shoppingRoutes(), 'GET /api/v1/auth/me': () => ME })
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: 'Kitchen roll' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Kitchen roll' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Kitchen roll' })).toHaveAttribute('aria-checked', 'true'))
  await waitFor(async () => expect(await db.queue.count()).toBe(2))
  fireEvent.click(screen.getByRole('button', { name: 'Delete Kitchen roll' }))
  await waitFor(() => expect(screen.queryByRole('checkbox', { name: 'Kitchen roll' })).toBeNull())
  await waitFor(async () => expect(await db.queue.count()).toBe(3))

  const queued = await listQueuedBodies('/api/v1/stock')
  const id = (queued[0].body as { id: string }).id
  expect(queued).toEqual([
    expect.objectContaining({ method: 'POST', path: '/api/v1/stock/shopping/lines', body: { id: anId, name: 'Kitchen roll' } }),
    expect.objectContaining({ method: 'PATCH', path: `/api/v1/stock/shopping/lines/${id}`, body: { checked: true } }),
    expect.objectContaining({ method: 'DELETE', path: `/api/v1/stock/shopping/lines/${id}` }),
  ])

  setOnline(true)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(0)
  expect(api.calls.filter((c) => c.path.startsWith('/api/v1/stock/shopping/lines')).map((c) => c.method)).toEqual(['POST', 'PATCH', 'DELETE'])
  expect(api.callsTo(LINE)[0].path).toBe(`/api/v1/stock/shopping/lines/${id}`)
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Batteries' })).toBeInTheDocument())
  expect(screen.queryByRole('checkbox', { name: 'Kitchen roll' })).toBeNull()
})

it('a replayed line create (its reply was lost) does not add the line twice', async () => {
  const server = shoppingRoutes()
  const api = fakeApi({ ...server, 'GET /api/v1/auth/me': () => ME })
  const create = server[LINES]!
  let lost = true
  api.on(LINES, async (r) => {
    const out = await create(r)
    if (lost) { lost = false; throw new TypeError('Failed to fetch') } // applied, but the reply never arrives
    return out
  })
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: 'Kitchen roll' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  setOnline(true)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(1)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(0)
  const [first, second] = api.callsTo(LINES)
  expect(second.body).toEqual(first.body)
  await waitFor(() => expect(screen.getAllByRole('checkbox', { name: 'Kitchen roll' })).toHaveLength(1))
  const after = await (await fetch('/api/v1/stock/shopping')).json() as { lines: { name: string }[] }
  expect(after.lines.filter((l) => l.name === 'Kitchen roll')).toHaveLength(1)
})

it('a tick answered with the item\'s existing tick adopts that id', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  // Another phone ticked Milk already: the server answers with that tick, not the one this phone made.
  api.on(TICKS, () => Response.json({ id: 'tick-other', stock_item_id: 's-milk', quantity: 2 }, { status: 201 }))
  api.on('GET /api/v1/stock/shopping', () => reply(500, { detail: 'boom' }))
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(TICKS)).toHaveLength(1))
  const sent = (api.callsTo(TICKS)[0].body as { id: string }).id
  expect(sent).not.toBe('tick-other')
  await waitFor(() => expect(api.callsTo('GET /api/v1/stock/shopping').length).toBeGreaterThan(1))
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(UNTICK)).toHaveLength(1))
  expect(api.callsTo(UNTICK)[0].path).toBe('/api/v1/stock/shopping/ticks/tick-other')
})

it('a row listed only because it is ticked reads "Ticked"', async () => {
  const data = shoppingOut({ ticked_count: 1 })
  data.items[0] = { ...data.items[0], reason: 'ticked', ticked: true, tick_id: 'tick-7' }
  fakeApi(shoppingRoutes(data))
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Olive oil × 1')).toHaveAccessibleDescription('Ticked €8.49')
  expect(row('Olive oil × 1')).not.toHaveTextContent('Low')
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
  expect(api.callsTo(APPLY)[0].body).toBeUndefined() // the route takes no body
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

// ---- Fix round 1

const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }

/** Olive oil and Milk ticked on the server. */
function twoTicked() {
  const data = shoppingOut({ ticked_count: 2 })
  data.items[0] = { ...data.items[0], ticked: true, tick_id: 'tick-8' }
  data.items[1] = { ...data.items[1], ticked: true, tick_id: 'tick-9' }
  return data
}

it('I-1: an untick still in the queue blocks Add to pantry; once the queue drains it is enabled again', async () => {
  const api = fakeApi({ ...shoppingRoutes(twoTicked()), 'GET /api/v1/auth/me': () => ME })
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  setOnline(true)
  const foot = screen.getByRole('region', { name: 'Ticked items' })
  const add = within(foot).getByRole('button', { name: 'Add to pantry' })
  await waitFor(() => {
    expect(add).toBeDisabled()
    expect(foot).toHaveTextContent('Waiting to sync 1 change') // the queued marker renders after the in-flight one
  })
  fireEvent.click(add)
  expect(api.callsTo(APPLY)).toHaveLength(0)
  await replay()
  expect(api.callsTo(UNTICK)).toHaveLength(1)
  await waitFor(() => expect(within(screen.getByRole('region', { name: 'Ticked items' })).getByRole('button', { name: 'Add to pantry' })).toBeEnabled())
  expect(screen.getByRole('region', { name: 'Ticked items' })).not.toHaveTextContent('Waiting to sync')
})

it('I-1: two queued changes read in the plural', async () => {
  fakeApi(shoppingRoutes(twoTicked()))
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Batteries' }))
  fireEvent.click(row('Salt × 1'))
  await waitFor(async () => expect(await db.queue.count()).toBe(2))
  setOnline(true)
  await waitFor(() => expect(screen.getByRole('region', { name: 'Ticked items' })).toHaveTextContent('Waiting to sync 2 changes'))
})

it('I-2: an online tick keeps its tick id across a failed refetch, so it can be unticked at once', async () => {
  const api = fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  api.on('GET /api/v1/stock/shopping', () => reply(500, { detail: 'boom' }))
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(TICKS)).toHaveLength(1))
  await waitFor(() => expect(row('Milk × 2')).toBeEnabled())
  expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'true')
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(UNTICK)).toHaveLength(1))
  const sent = (api.callsTo(TICKS)[0].body as { id: string }).id
  expect(api.callsTo(UNTICK)[0].path).toBe(`/api/v1/stock/shopping/ticks/${sent}`)
})

it('I-3: each row describes its reason, price and sync state to screen readers', async () => {
  fakeApi(shoppingRoutes())
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Milk × 2')).toHaveAccessibleDescription('Low · 0 left · €1.09 each €2.18')
  expect(row('Barilla spaghetti × 2')).toHaveAccessibleDescription('Price drop Runs out in ~5 d · €1.19 each €2.38')
  expect(row('Salt × 1')).toHaveAccessibleDescription('Low · 0 left')
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(row('Milk × 2')).toHaveAccessibleDescription('Low · 0 left · €1.09 each Waiting to sync €2.18'))
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: 'Soap' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Soap' })).toHaveAccessibleDescription('Waiting to sync'))
})

// The rollback tests make the shopping GET fail before the action: otherwise the refetch after the rejection
// would restore the row by itself and hide a missing rollback. (Seen red with useAction's snapshot emptied in
// the test's own setup: vi.spyOn(client, 'getQueriesData').mockReturnValue([]).)
it('I-4: a rejected tick rolls back and says why', async () => {
  const api = fakeApi(shoppingRoutes())
  api.on(TICKS, () => reply(404, { detail: 'Stock item not found' }))
  renderWithProviders(<ShoppingList />)
  await loaded()
  api.on('GET /api/v1/stock/shopping', () => reply(500, { detail: 'boom' }))
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo('GET /api/v1/stock/shopping').length).toBeGreaterThan(1))
  expect(await screen.findByRole('alert')).toHaveTextContent('Stock item not found')
  expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false')
  expect(await db.queue.count()).toBe(0)
})

it('I-4: a rejected line check rolls back', async () => {
  const api = fakeApi(shoppingRoutes())
  api.on(LINE, () => reply(404, { detail: 'Line not found' }))
  renderWithProviders(<ShoppingList />)
  await loaded()
  api.on('GET /api/v1/stock/shopping', () => reply(500, { detail: 'boom' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'Batteries' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Line not found')
  await waitFor(() => expect(api.callsTo('GET /api/v1/stock/shopping').length).toBeGreaterThan(1))
  expect(screen.getByRole('checkbox', { name: 'Batteries' })).toHaveAttribute('aria-checked', 'false')
})

it('I-4: a line add that fails while online is rolled back, not queued (it may have been added)', async () => {
  const api = fakeApi(shoppingRoutes())
  api.on(LINES, () => reply(500, { detail: 'boom' }))
  renderWithProviders(<ShoppingList />)
  await loaded()
  api.on('GET /api/v1/stock/shopping', () => reply(500, { detail: 'boom' }))
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: 'Soap' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t confirm the change')
  await waitFor(() => expect(api.callsTo('GET /api/v1/stock/shopping').length).toBeGreaterThan(1))
  expect(screen.queryByRole('checkbox', { name: 'Soap' })).toBeNull()
  expect(await db.queue.count()).toBe(0)
})

it('a run-out estimate is rounded up to a whole day', async () => {
  const data = shoppingOut()
  data.items[2] = { ...data.items[2], runout_days_estimate: 4.3 }
  fakeApi(shoppingRoutes(data))
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Barilla spaghetti × 2')).toHaveTextContent('Runs out in ~5 d')
})

it('the row title is "name × need_qty": the pack-size unit never follows the count ("Pasta × 1", not "× 1 g")', async () => {
  const data = shoppingOut()
  data.items[2] = { ...data.items[2], unit: 'g' }
  data.items[1] = { ...data.items[1], unit: 'L' }
  fakeApi(shoppingRoutes(data))
  renderWithProviders(<ShoppingList />)
  await loaded()
  expect(row('Barilla spaghetti × 2')).toBeInTheDocument()
  expect(row('Milk × 2')).toBeInTheDocument()
  expect(screen.queryByText(/× \d+ (g|L)\b/)).toBeNull()
})
