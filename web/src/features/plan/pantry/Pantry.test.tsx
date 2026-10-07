import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { db } from '../../../offline/db'
import { open } from '../../../offline/crypto'
import { fakeApi, hang, reply } from '../../../test/fakeApi'
import { lowMilk, pantryRoutes, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { Pantry } from './Pantry'
import type { StockItem } from './types'

afterEach(resetTestEnv)

const ADJUST = 'POST /api/v1/stock/{item_id}/adjust' as const
const row = (name: string) => screen.getByRole('listitem', { name })
const names = () => screen.getAllByRole('listitem').map((li) => li.getAttribute('aria-label'))

it('rows: name and size, "N left", the low tint with "need N", and the cheapest price chip', async () => {
  fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  const pasta = await screen.findByRole('listitem', { name: 'Barilla spaghetti' })
  expect(pasta).toHaveTextContent('Barilla spaghetti · 500 g')
  expect(pasta).toHaveTextContent('3 left')
  expect(pasta).not.toHaveTextContent('need')
  expect(pasta).not.toHaveClass('pantry-row--low')
  expect(within(pasta).getByText('€1.19 · Sklavenitis')).not.toHaveClass('pantry-price--buy')

  const milk = row('Milk')
  expect(milk).toHaveTextContent('Milk · 1 L')
  expect(milk).toHaveTextContent('0 left · need 2')
  expect(milk).toHaveClass('pantry-row--low')
  expect(within(milk).queryByText(/€/)).not.toBeInTheDocument()
})

it('the price chip is green (and says so) when the advice is buy_now', async () => {
  fakeApi(pantryRoutes({ items: [stockItem({ advice: 'buy_now' })] }))
  renderWithProviders(<Pantry />)
  const chip = await screen.findByText('€1.19 · Sklavenitis')
  expect(chip.closest('.pantry-price')).toHaveClass('pantry-price--buy')
  expect(chip.closest('.pantry-price')).toHaveTextContent(/good time to buy/i)
})

it('chips: All, Running low and Price tracked filter the list, with counts', async () => {
  const tracked = stockItem({ id: 's3', name: 'Loumidis coffee', brand: 'Loumidis', track_price: true })
  fakeApi(pantryRoutes({ items: [stockItem(), lowMilk(), tracked] }))
  renderWithProviders(<Pantry />)
  await screen.findByRole('listitem', { name: 'Milk' })
  const chips = within(screen.getByRole('group', { name: 'Show' }))
  expect(chips.getAllByRole('button').map((b) => b.textContent)).toEqual(['All 3', 'Running low 1', 'Price tracked 1'])
  expect(chips.getByRole('button', { name: /All/ })).toHaveAttribute('aria-pressed', 'true')

  fireEvent.click(chips.getByRole('button', { name: /Running low/ }))
  expect(names()).toEqual(['Milk'])
  fireEvent.click(chips.getByRole('button', { name: /Price tracked/ }))
  expect(names()).toEqual(['Loumidis coffee'])
  fireEvent.click(chips.getByRole('button', { name: /All/ }))
  expect(names()).toHaveLength(3)
})

it('search filters by name and by brand, ignoring case', async () => {
  fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  await screen.findByRole('listitem', { name: 'Milk' })
  const search = screen.getByRole('searchbox', { name: 'Search pantry' })
  fireEvent.change(search, { target: { value: 'spag' } })
  expect(names()).toEqual(['Barilla spaghetti'])
  fireEvent.change(search, { target: { value: 'DELTA' } })
  expect(names()).toEqual(['Milk'])
  fireEvent.change(search, { target: { value: 'zzz' } })
  expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  expect(screen.getByText('Nothing matches “zzz”')).toBeInTheDocument()
})

it('the stepper sends {delta, client_id} and shows the new count at once', async () => {
  let answer!: (r: Response) => void
  const fake = fakeApi(pantryRoutes())
  fake.on(ADJUST, () => new Promise<Response>((r) => { answer = r }))
  renderWithProviders(<Pantry />)
  const pasta = await screen.findByRole('listitem', { name: 'Barilla spaghetti' })
  fireEvent.click(within(pasta).getByRole('button', { name: 'Increase Barilla spaghetti' }))
  // Optimistic: before the server answers.
  await waitFor(() => expect(within(pasta).getByTestId('pantry-qty')).toHaveTextContent('4'))
  expect(pasta).toHaveTextContent('4 left')
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(1))
  const sent = fake.callsTo(ADJUST)[0]
  expect(sent.path).toBe('/api/v1/stock/s1/adjust')
  expect(sent.body).toMatchObject({ delta: 1 })
  expect((sent.body as { client_id: string }).client_id).toMatch(/^[0-9a-f-]{36}$/)
  answer(Response.json(stockItem({ quantity: 4 })))

  fireEvent.click(within(pasta).getByRole('button', { name: 'Decrease Barilla spaghetti' }))
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(2))
  const second = fake.callsTo(ADJUST)[1].body as { delta: number; client_id: string }
  expect(second.delta).toBe(-1)
  expect(second.client_id).not.toBe((sent.body as { client_id: string }).client_id)
})

it('going low turns the row warm, and minus is disabled at 0', async () => {
  fakeApi(pantryRoutes({ items: [stockItem({ quantity: 2, min_quantity: 1, need_qty: 1 })] }))
  renderWithProviders(<Pantry />)
  const pasta = await screen.findByRole('listitem', { name: 'Barilla spaghetti' })
  const minus = within(pasta).getByRole('button', { name: 'Decrease Barilla spaghetti' })
  fireEvent.click(minus)
  await waitFor(() => expect(pasta).toHaveClass('pantry-row--low'))
  fireEvent.click(minus)
  await waitFor(() => expect(within(pasta).getByTestId('pantry-qty')).toHaveTextContent('0'))
  expect(minus).toBeDisabled()
})

it('offline, the stepper is queued with its client_id and the row says it is waiting to sync', async () => {
  const fake = fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  const milk = await screen.findByRole('listitem', { name: 'Milk' })
  setOnline(false)
  fake.down()
  fireEvent.click(within(milk).getByRole('button', { name: 'Increase Milk' }))
  await waitFor(() => expect(within(milk).getByTestId('pantry-qty')).toHaveTextContent('1'))
  expect(await within(milk).findByText('Waiting to sync')).toBeInTheDocument()
  expect(fake.callsTo(ADJUST)).toHaveLength(0)
  const rows = await db.queue.toArray()
  expect(rows).toHaveLength(1)
  const queued = await open<{ method: string; path: string; body: { delta: number; client_id: string } }>(rows[0])
  expect(queued).toMatchObject({ method: 'POST', path: '/api/v1/stock/s2/adjust', body: { delta: 1 } })
  expect(queued.body.client_id).toMatch(/^[0-9a-f-]{36}$/)
})

it('tapping a row opens its detail', async () => {
  fakeApi(pantryRoutes())
  const { router } = renderWithProviders(<Pantry />)
  const milk = await screen.findByRole('listitem', { name: 'Milk' })
  fireEvent.click(within(milk).getByRole('link', { name: /Milk/ }))
  expect(router.state.location.pathname).toBe('/plan/pantry/s2')
})

it('"Shopping list (N)" counts the shopping list and links to it', async () => {
  fakeApi(pantryRoutes({ shopping: [{ id: 's2' }, { id: 's9' }, { id: 's7' }] }))
  renderWithProviders(<Pantry />)
  const link = await screen.findByRole('link', { name: 'Shopping list (3)' })
  expect(link).toHaveAttribute('href', '/plan/pantry/list')
})

it('"Shopping list" without a count while the list is loading', async () => {
  const routes = pantryRoutes()
  fakeApi({ ...routes, 'GET /api/v1/stock/shopping': () => hang() })
  renderWithProviders(<Pantry />)
  await screen.findByRole('listitem', { name: 'Milk' })
  expect(screen.getByRole('link', { name: 'Shopping list' })).toHaveAttribute('href', '/plan/pantry/list')
})

it('empty: "Nothing in your pantry yet" with Add', async () => {
  fakeApi(pantryRoutes({ items: [], shopping: [] }))
  renderWithProviders(<Pantry />)
  expect(await screen.findByText('Nothing in your pantry yet')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Add a product' })).toBeEnabled()
})

it('offline with nothing saved says how to load it', async () => {
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<Pantry />)
  expect(await screen.findByText('No saved pantry yet. Connect once to load Pantry.')).toBeInTheDocument()
})

it('＋ opens Add to pantry', async () => {
  fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  await screen.findByRole('listitem', { name: 'Milk' })
  fireEvent.click(screen.getByRole('button', { name: 'Add to pantry' }))
  expect(screen.getByRole('dialog', { name: 'Add to pantry' })).toBeInTheDocument()
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Add to pantry' })).getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('dialog', { name: 'Add to pantry' })).not.toBeInTheDocument()
})

it('the empty state’s Add opens Add to pantry', async () => {
  fakeApi(pantryRoutes({ items: [] }))
  renderWithProviders(<Pantry />)
  fireEvent.click(await screen.findByRole('button', { name: 'Add a product' }))
  expect(screen.getByRole('dialog', { name: 'Add to pantry' })).toBeInTheDocument()
})

it('a rejected adjust (the item was archived meanwhile) rolls the count back and says why', async () => {
  let reads = 0
  const routes = pantryRoutes()
  const fake = fakeApi({
    ...routes,
    // Only the first read answers: the refetch after the rejection fails, so what shows is the rollback itself.
    'GET /api/v1/stock': (req) => (++reads === 1 ? (routes['GET /api/v1/stock']!(req) as StockItem[]) : reply(500)),
    [ADJUST]: () => reply(404, { detail: 'Stock item not found' }),
  })
  renderWithProviders(<Pantry />)
  const pasta = await screen.findByRole('listitem', { name: 'Barilla spaghetti' })
  fireEvent.click(within(pasta).getByRole('button', { name: 'Increase Barilla spaghetti' }))
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(1))
  expect(await screen.findByText('Stock item not found')).toBeInTheDocument()
  await waitFor(() => expect(fake.callsTo('GET /api/v1/stock').length).toBeGreaterThan(1))
  expect(within(pasta).getByTestId('pantry-qty')).toHaveTextContent('3')
  expect(pasta).toHaveTextContent('3 left')
  expect(await db.queue.count()).toBe(0)
})

it('a network failure while online queues the very client_id that was sent (a lost reply replays once)', async () => {
  const fake = fakeApi(pantryRoutes())
  renderWithProviders(<Pantry />)
  const milk = await screen.findByRole('listitem', { name: 'Milk' })
  fake.down() // still "online": the send itself fails
  fireEvent.click(within(milk).getByRole('button', { name: 'Increase Milk' }))
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(1))
  const sent = fake.callsTo(ADJUST)[0].body as { delta: number; client_id: string }
  await waitFor(async () => expect(await db.queue.count()).toBe(1))
  const [row] = await db.queue.toArray()
  const queued = await open<{ path: string; body: { delta: number; client_id: string } }>(row)
  expect(queued.path).toBe('/api/v1/stock/s2/adjust')
  expect(queued.body).toEqual({ delta: 1, client_id: sent.client_id })
  expect(await within(milk).findByText('Waiting to sync')).toBeInTheDocument()
})
