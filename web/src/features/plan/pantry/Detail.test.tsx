import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi, reply } from '../../../test/fakeApi'
import { pantryRoutes, stockDetail, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { Detail } from './Detail'
import { PriceChart } from './PriceChart'
import { chartGeometry } from './priceScale'

afterEach(resetTestEnv)

const DETAIL = 'GET /api/v1/stock/{item_id}' as const
const PATCH = 'PATCH /api/v1/stock/{item_id}' as const
const REFRESH = 'POST /api/v1/stock/{item_id}/refresh' as const
const ARCHIVE = 'POST /api/v1/stock/{item_id}/archive' as const
const ADJUST = 'POST /api/v1/stock/{item_id}/adjust' as const

function routes(detail = stockDetail()) {
  let current = detail
  return {
    ...pantryRoutes({ items: [stockItem({ ...detail })] }),
    [DETAIL]: () => current,
    [PATCH]: (req: { body: unknown }) => {
      current = { ...current, ...(req.body as object) }
      current.low = current.quantity <= current.min_quantity
      return { ...current }
    },
    [REFRESH]: () => current,
    [ARCHIVE]: () => null,
    [ADJUST]: (req: { body: unknown }) => {
      const quantity = Math.max(0, current.quantity + (req.body as { delta: number }).delta)
      current = { ...current, quantity, low: quantity <= current.min_quantity }
      return { ...current }
    },
  }
}

const card = (name: string) => screen.getByRole('region', { name })

it('the stock stepper, with "N below your minimum" when low, and the − n + adjust', async () => {
  const fake = fakeApi(routes(stockDetail({ quantity: 1, min_quantity: 3, low: true, need_qty: 5 })))
  // The memory router renders <Detail /> for every path; the id comes from the URL.
  renderWithProviders(<Detail id="s1" />)
  const stock = await screen.findByRole('region', { name: 'Stock' })
  expect(screen.getByRole('heading', { level: 1, name: 'Barilla spaghetti' })).toBeInTheDocument()
  expect(stock).toHaveTextContent('2 below your minimum')
  fireEvent.click(within(stock).getByRole('button', { name: 'Increase Barilla spaghetti' }))
  await waitFor(() => expect(fake.callsTo(ADJUST)).toHaveLength(1))
  expect(fake.callsTo(ADJUST)[0].body).toMatchObject({ delta: 1 })
  await waitFor(() => expect(stock).toHaveTextContent('1 below your minimum'))
})

it('not low: no minimum warning', async () => {
  fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const stock = await screen.findByRole('region', { name: 'Stock' })
  expect(stock).not.toHaveTextContent('below your minimum')
})

it('Keep at least sends PATCH min_quantity', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const stock = await screen.findByRole('region', { name: 'Stock' })
  fireEvent.click(within(stock).getByRole('button', { name: 'Increase minimum for Barilla spaghetti' }))
  await waitFor(() => expect(fake.callsTo(PATCH)).toHaveLength(1))
  expect(fake.callsTo(PATCH)[0].path).toBe('/api/v1/stock/s1')
  expect(fake.callsTo(PATCH)[0].body).toEqual({ min_quantity: 2 })
  await waitFor(() => expect(within(within(stock).getByRole('group', { name: 'Keep at least' })).getByTestId('pantry-qty')).toHaveTextContent('2'))
})

it('"Lasts about N days", and nothing when there is no estimate', async () => {
  fakeApi(routes(stockDetail({ runout_days: 12 })))
  const { unmount } = renderWithProviders(<Detail id="s1" />)
  expect(await screen.findByText('Lasts about')).toBeInTheDocument()
  expect(card('Stock')).toHaveTextContent('12 days')
  unmount()
  await resetTestEnv()
  fakeApi(routes(stockDetail({ runout_days: null })))
  renderWithProviders(<Detail id="s1" />)
  await screen.findByRole('region', { name: 'Stock' })
  expect(screen.queryByText('Lasts about')).not.toBeInTheDocument()
})

it('prices today: a bar per store, cheapest first, with the offer marked', async () => {
  const shuffled = stockDetail().prices_today.slice().reverse()
  fakeApi(routes(stockDetail({ prices_today: shuffled })))
  renderWithProviders(<Detail id="s1" />)
  const prices = await screen.findByRole('list', { name: 'Prices today' })
  const rows = within(prices).getAllByRole('listitem')
  expect(rows.map((r) => r.textContent)).toEqual(['Sklavenitis Offer€1.19', 'Lidl€1.29', 'AB€1.45'])
  const widths = rows.map((r) => (r.querySelector('.pantry-cmp__fill') as HTMLElement).style.width)
  expect(widths).toEqual([`${(1.19 / 1.45) * 100}%`, `${(1.29 / 1.45) * 100}%`, '100%'])
})

it('the chart: every point lies on its time and price scale', () => {
  const g = chartGeometry(
    [{ date: '2026-05-01', min_price: 2 }, { date: '2026-05-11', min_price: 1 }, { date: '2026-05-31', min_price: 3 }],
    { width: 300, height: 100, padX: 10, padTop: 20, padBottom: 10 },
  )
  // The price axis runs from 1 − 0.10 to 3 + 0.10 (the larger of ±5 % of the mid price, 2, and ±€0.10).
  expect(g.lo).toBeCloseTo(0.9)
  expect(g.hi).toBeCloseTo(3.1)
  // x: 10 + days/30 * 280; y: 20 + (3.1 − price) / 2.2 * 70.
  const y = (p: number) => 20 + ((3.1 - p) / 2.2) * 70
  const expected = [[10, y(2)], [10 + (10 / 30) * 280, y(1)], [290, y(3)]]
  g.points.forEach((p, i) => {
    expect(p.x).toBeCloseTo(expected[i][0], 6)
    expect(p.y).toBeCloseTo(expected[i][1], 6)
  })
  expect(g.low).toBe(1)
  expect(g.path).toBe(`M10.0 ${y(2).toFixed(1)} L103.3 ${y(1).toFixed(1)} L290.0 ${y(3).toFixed(1)}`)
})

it('the chart: a 1-cent wiggle stays small (the y-range is padded, never just min to max)', () => {
  const box = { width: 300, height: 100, padX: 10, padTop: 20, padBottom: 10 }
  const g = chartGeometry(
    [{ date: '2026-05-01', min_price: 1.19 }, { date: '2026-05-02', min_price: 1.2 }, { date: '2026-05-03', min_price: 1.19 }], box,
  )
  // ±€0.10 beats ±5 % of €1.195: the range is 1.09–1.30, so a cent is under a tenth of the 70 px plot.
  expect(g.lo).toBeCloseTo(1.09)
  expect(g.hi).toBeCloseTo(1.3)
  expect(Math.abs(g.points[1].y - g.points[0].y)).toBeLessThan(7)
  // At higher prices, 5 % wins: €20–€21 pads by €1.025.
  const big = chartGeometry([{ date: '2026-05-01', min_price: 20 }, { date: '2026-05-02', min_price: 21 }], box)
  expect(big.lo).toBeCloseTo(18.975)
  expect(big.hi).toBeCloseTo(22.025)
})

it('the chart draws the history with its low, first and last labels and a table', () => {
  const { container } = render(<PriceChart history={stockDetail().history} title="Lowest price, 6 months" />)
  expect(container.querySelectorAll('svg circle')).toHaveLength(2) // the low and the latest
  expect(screen.getByText('Low €1.09 in Aug')).toBeInTheDocument()
  expect(screen.getByText('May €1.49')).toBeInTheDocument()
  expect(screen.getByText('Oct €1.19')).toBeInTheDocument()
  const table = screen.getByRole('table', { name: 'Lowest price by day' })
  expect(within(table).getAllByRole('row')).toHaveLength(3)
})

it('fewer than 2 points: "Not enough price history yet"', () => {
  const { container } = render(<PriceChart history={[{ date: '2026-10-08', min_price: 1.19 }]} title="Lowest price, 6 months" />)
  expect(screen.getByText('Not enough price history yet')).toBeInTheDocument()
  expect(container.querySelector('svg')).toBeNull()
})

it('Track price sends PATCH track_price', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const toggle = await screen.findByRole('switch', { name: 'Track price' })
  expect(toggle).toHaveAttribute('aria-checked', 'false')
  expect(screen.getByText('Get a notification when it drops')).toBeInTheDocument()
  fireEvent.click(toggle)
  await waitFor(() => expect(fake.callsTo(PATCH)).toHaveLength(1))
  expect(fake.callsTo(PATCH)[0].body).toEqual({ track_price: true })
  await waitFor(() => expect(screen.getByRole('switch', { name: 'Track price' })).toHaveAttribute('aria-checked', 'true'))
})

it('Refresh prices: a 503 shows an inline message', async () => {
  const fake = fakeApi({ ...routes(), [REFRESH]: () => reply(503, { detail: 'Prices unavailable' }) })
  renderWithProviders(<Detail id="s1" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Refresh prices' }))
  expect(await screen.findByText('Prices unavailable right now. Try again later.')).toBeInTheDocument()
  expect(fake.callsTo(REFRESH)[0].path).toBe('/api/v1/stock/s1/refresh')
})

it('Refresh prices shows the fresh prices', async () => {
  const fresh = stockDetail({ prices_today: [{ retailer: 'lidl', retailer_name: 'Lidl', price: 0.99, unit_price: 1.98, is_discount: false }] })
  const fake = fakeApi(routes())
  fake.on(REFRESH, () => fresh)
  fake.on(DETAIL, () => (fake.callsTo(REFRESH).length ? fresh : stockDetail()))
  renderWithProviders(<Detail id="s1" />)
  fireEvent.click(await screen.findByRole('button', { name: 'Refresh prices' }))
  await waitFor(() => expect(screen.getByRole('list', { name: 'Prices today' })).toHaveTextContent('€0.99'))
})

it('Archive asks first in the sheet, then archives and goes back to the list', async () => {
  const fake = fakeApi(routes())
  const { router } = renderWithProviders(<Detail id="s1" />, { route: '/plan/pantry/s1' })
  fireEvent.click(await screen.findByRole('button', { name: 'Archive product' }))
  const confirm = screen.getByRole('dialog', { name: 'Archive Barilla spaghetti?' })
  expect(fake.callsTo(ARCHIVE)).toHaveLength(0)
  fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Archive product' }))
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Archive' }))
  await waitFor(() => expect(fake.callsTo(ARCHIVE)).toHaveLength(1))
  expect(fake.callsTo(ARCHIVE)[0].path).toBe('/api/v1/stock/s1/archive')
  await waitFor(() => expect(router.state.location.pathname).toBe('/plan'))
  expect(router.state.location.search).toBe('?view=pantry')
})

it('Back returns to the Pantry list', async () => {
  fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  await screen.findByRole('region', { name: 'Stock' })
  expect(screen.getByRole('link', { name: 'Back' })).toHaveAttribute('href', '/plan?view=pantry')
})

it('offline: the online-only writes are disabled with the reason; the stepper still works', async () => {
  fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const stock = await screen.findByRole('region', { name: 'Stock' })
  setOnline(false)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh prices' })).toBeDisabled())
  expect(screen.getByRole('button', { name: 'Archive product' })).toBeDisabled()
  expect(screen.getByRole('switch', { name: 'Track price' })).toBeDisabled()
  expect(within(stock).getByRole('button', { name: 'Increase minimum for Barilla spaghetti' })).toBeDisabled()
  expect(within(stock).getByRole('button', { name: 'Increase Barilla spaghetti' })).toBeEnabled()
  expect(screen.getAllByText('Connect to change the pantry').length).toBeGreaterThan(0)
})

it('a missing (archived or foreign) item says so, with a way back to the list', async () => {
  fakeApi({ ...routes(), [DETAIL]: () => reply(404, { detail: 'Stock item not found' }) })
  renderWithProviders(<Detail id="nope" />)
  expect(await screen.findByText('This item isn’t in your pantry any more')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Back to Pantry' })).toHaveAttribute('href', '/plan?view=pantry')
  expect(screen.queryByText('Couldn’t load this.')).not.toBeInTheDocument()
})

it('another failure keeps the generic retry', async () => {
  fakeApi({ ...routes(), [DETAIL]: () => reply(500) })
  renderWithProviders(<Detail id="s1" />)
  expect(await screen.findByText('Couldn’t load this.')).toBeInTheDocument()
})

it('offline, the stock stepper is queued and says it is waiting to sync', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const stock = await screen.findByRole('region', { name: 'Stock' })
  expect(stock).not.toHaveTextContent('Waiting to sync')
  setOnline(false)
  fake.down()
  fireEvent.click(within(stock).getByRole('button', { name: 'Increase Barilla spaghetti' }))
  expect(await within(stock).findByText('Waiting to sync')).toBeInTheDocument()
  expect(within(within(stock).getByRole('group', { name: 'Barilla spaghetti in stock' })).getByTestId('pantry-qty')).toHaveTextContent('4')
})
