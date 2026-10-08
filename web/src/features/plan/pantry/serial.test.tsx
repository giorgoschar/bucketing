import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { db } from '../../../offline/db'
import { listQueuedBodies } from '../../../offline/queuedBodies'
import { replay } from '../../../offline/queue'
import { fakeApi, reply } from '../../../test/fakeApi'
import { pantryRoutes, shoppingOut, shoppingRoutes, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { Pantry } from './Pantry'
import { ShoppingList } from './ShoppingList'
import type { ShoppingOut } from './shoppingTypes'

afterEach(resetTestEnv)

/** Polish P2: item-scoped untick (C4), and one write at a time per row. */

const TICKS = 'POST /api/v1/stock/shopping/ticks' as const
const UNTICK = 'DELETE /api/v1/stock/shopping/ticks' as const
const APPLY = 'POST /api/v1/stock/shopping/apply-ticked' as const
const ADJUST = 'POST /api/v1/stock/{item_id}/adjust' as const
const ME = { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null }

const row = (name: string) => screen.getByRole('checkbox', { name })
const loaded = () => screen.findByRole('region', { name: 'Lidl' })
const serverShopping = async () => (await (await fetch('/api/v1/stock/shopping')).json()) as ShoppingOut

/** A handler that answers only when the test says so, passing the request on to `real`. */
function held<T>(real: (r: never) => T) {
  const waiting: (() => void)[] = []
  return {
    handler: (r: never) => new Promise<T>((done) => { waiting.push(() => done(real(r))) }),
    release: () => waiting.shift()?.(),
    get count() { return waiting.length },
  }
}

it('pantry review M-1: a replayed tick that met another phone\'s tick is still unticked', async () => {
  const api = fakeApi({ ...shoppingRoutes(), 'GET /api/v1/auth/me': () => ME })
  renderWithProviders(<ShoppingList />)
  await loaded()
  setOnline(false)
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(2))
  // Meanwhile another phone ticks Milk: the replayed POST gets that tick back, not this phone's.
  await fetch('/api/v1/stock/shopping/ticks', { method: 'POST', body: JSON.stringify({ id: 'tick-other', stock_item_id: 's-milk' }) })
  setOnline(true)
  await replay({ force: true })
  expect(await db.queue.count()).toBe(0)
  expect(api.callsTo(UNTICK)[0].query.get('stock_item_id')).toBe('s-milk')
  expect((await serverShopping()).items.find((i) => i.id === 's-milk')?.ticked).toBe(false)
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false'))
})

it('online, an untick waits for its tick to be answered: never sent alongside it', async () => {
  const server = shoppingRoutes()
  const api = fakeApi(server)
  const tick = held(server[TICKS]! as (r: never) => unknown)
  api.on(TICKS, tick.handler as never)
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(TICKS)).toHaveLength(1))
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'true'))
  fireEvent.click(row('Milk × 2'))
  // The untick shows at once, but is not sent while the tick is unanswered.
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false'))
  await new Promise((r) => setTimeout(r, 30))
  expect(api.callsTo(UNTICK)).toHaveLength(0)
  tick.release()
  await waitFor(() => expect(api.callsTo(UNTICK)).toHaveLength(1))
  await waitFor(async () => expect((await serverShopping()).items.find((i) => i.id === 's-milk')?.ticked).toBe(false))
  await waitFor(() => expect(row('Milk × 2')).toHaveAttribute('aria-checked', 'false'))
})

it('a tick queued after a failure while online keeps its untick behind it in the queue', async () => {
  const api = fakeApi({ ...shoppingRoutes(), 'GET /api/v1/auth/me': () => ME })
  api.on(TICKS, () => { throw new TypeError('Failed to fetch') })
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  fireEvent.click(row('Milk × 2'))
  await waitFor(async () => expect(await db.queue.count()).toBe(2))
  expect(api.callsTo(UNTICK)).toHaveLength(0)
  expect((await listQueuedBodies('/api/v1/stock')).map((b) => `${b.method} ${b.path}`)).toEqual([
    'POST /api/v1/stock/shopping/ticks', 'DELETE /api/v1/stock/shopping/ticks?stock_item_id=s-milk',
  ])
})

it('Add to pantry waits for a tick still being sent', async () => {
  const server = shoppingRoutes(shoppingOut({ ticked_count: 1, items: shoppingOut().items.map((i, n) => (n === 0 ? { ...i, ticked: true, tick_id: 't-0' } : i)) }))
  const api = fakeApi(server)
  const tick = held(server[TICKS]! as (r: never) => unknown)
  api.on(TICKS, tick.handler as never)
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(TICKS)).toHaveLength(1))
  fireEvent.click(within(screen.getByRole('region', { name: 'Ticked items' })).getByRole('button', { name: 'Add to pantry' }))
  await new Promise((r) => setTimeout(r, 30))
  expect(api.callsTo(APPLY)).toHaveLength(0)
  tick.release()
  await waitFor(() => expect(api.callsTo(APPLY)).toHaveLength(1))
  // Milk's tick reached the server first, so the apply took it in.
  expect(await screen.findByText(/Milk 0 → 2/)).toBeInTheDocument()
})

it('stepper taps on one item are sent one after another; the count moves at once', async () => {
  const items = [stockItem()]
  const server = pantryRoutes({ items })
  const fake = fakeApi(server)
  const adjust = held(server[ADJUST]! as (r: never) => unknown)
  fake.on(ADJUST, adjust.handler as never)
  renderWithProviders(<Pantry />)
  const pasta = await screen.findByRole('listitem', { name: 'Barilla spaghetti' })
  const plus = within(pasta).getByRole('button', { name: 'Increase Barilla spaghetti' })
  fireEvent.click(plus)
  await waitFor(() => expect(within(pasta).getByTestId('pantry-qty')).toHaveTextContent('4'))
  fireEvent.click(plus)
  await waitFor(() => expect(within(pasta).getByTestId('pantry-qty')).toHaveTextContent('5'))
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(1))
  await new Promise((r) => setTimeout(r, 30))
  expect(fake.callsTo(ADJUST)).toHaveLength(1)
  adjust.release()
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(2))
  adjust.release()
  await waitFor(() => expect(within(pasta).getByTestId('pantry-qty')).toHaveTextContent('5'))
  const ids = fake.callsTo(ADJUST).map((c) => (c.body as { client_id: string }).client_id)
  expect(new Set(ids).size).toBe(2)
})

// ---- Fix round 1

it('review I-2: deleting a line whose add is still queued queues behind it, and is not sent online', async () => {
  const LINES = 'POST /api/v1/stock/shopping/lines' as const
  const LINE_DEL = 'DELETE /api/v1/stock/shopping/lines/{line_id}' as const
  const api = fakeApi({ ...shoppingRoutes(), 'GET /api/v1/auth/me': () => ME })
  api.on(LINES, () => reply(503, { detail: 'busy' }))
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(screen.getByRole('button', { name: 'Add item' }))
  const sheet = await screen.findByRole('dialog', { name: 'Add item' })
  fireEvent.change(within(sheet).getByLabelText('Item'), { target: { value: 'Soap' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add' }))
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Soap' }))
  await waitFor(async () => expect(await db.queue.count()).toBe(2))
  expect(api.callsTo(LINE_DEL)).toHaveLength(0)
  const queued = await listQueuedBodies('/api/v1/stock')
  const id = (queued[0].body as { id: string }).id
  expect(queued.map((b) => `${b.method} ${b.path}`)).toEqual([
    'POST /api/v1/stock/shopping/lines', `DELETE /api/v1/stock/shopping/lines/${id}`,
  ])
  expect(screen.queryByRole('checkbox', { name: 'Soap' })).toBeNull()
  expect(screen.queryByText('Line not found')).toBeNull()
})

it('review I-3: Add to pantry does not apply when a write it waited for fell into the queue', async () => {
  const data = shoppingOut({ ticked_count: 2 })
  data.items[0] = { ...data.items[0], ticked: true, tick_id: 'tick-8' }
  data.items[1] = { ...data.items[1], ticked: true, tick_id: 'tick-9' }
  const api = fakeApi({ ...shoppingRoutes(data), 'GET /api/v1/auth/me': () => ME })
  // The untick is held, then answered 503: it ends in the offline queue.
  const untick = held(() => reply(503, { detail: 'busy' }))
  api.on(UNTICK, untick.handler as never)
  renderWithProviders(<ShoppingList />)
  await loaded()
  fireEvent.click(row('Milk × 2'))
  await waitFor(() => expect(api.callsTo(UNTICK)).toHaveLength(1))
  const bar = () => screen.getByRole('region', { name: 'Ticked items' })
  fireEvent.click(within(bar()).getByRole('button', { name: 'Add to pantry' }))
  untick.release()
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  await waitFor(() => expect(bar()).toHaveTextContent('Waiting to sync 1 change'))
  expect(within(bar()).getByRole('button', { name: 'Add to pantry' })).toBeDisabled()
  await new Promise((r) => setTimeout(r, 30))
  // The server still has Milk ticked: applying now would add what the user unticked.
  expect(api.callsTo(APPLY)).toHaveLength(0)
})
