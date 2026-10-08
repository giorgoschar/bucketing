import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi, reply } from '../../../test/fakeApi'
import { barcodeProduct, pantryRoutes, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { BarcodeSheet } from './BarcodeSheet'

afterEach(resetTestEnv)

const BARCODE = 'GET /api/v1/products/barcode/{code}' as const
const ADD = 'POST /api/v1/stock' as const

const handlers = () => ({ onClose: vi.fn(), onScanAnother: vi.fn(), onAddManually: vi.fn(), onAdded: vi.fn() })

it('found: name and barcode, the best price, the other stores, Scan another and Add to pantry', async () => {
  const fake = fakeApi({ ...pantryRoutes(), [BARCODE]: () => barcodeProduct(), [ADD]: () => Response.json(stockItem(), { status: 201 }) })
  const h = handlers()
  renderWithProviders(<BarcodeSheet code="5201004021108" {...h} />)
  const sheet = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  expect(sheet).toHaveTextContent('Barcode 5201004021108')
  expect(sheet).not.toHaveTextContent('In pantry')
  expect(within(sheet).getByText('Best price').parentElement).toHaveTextContent('€5.29 at Lidl')
  expect(sheet).toHaveTextContent('Sklavenitis €5.89')
  // Checking a price never adds the product.
  expect(fake.callsTo(ADD)).toHaveLength(0)

  fireEvent.click(within(sheet).getByRole('button', { name: 'Scan another' }))
  expect(h.onScanAnother).toHaveBeenCalled()
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add to pantry' }))
  await waitFor(() => expect(fake.callsTo(ADD)).toHaveLength(1))
  expect(fake.callsTo(ADD)[0].body).toMatchObject({
    name: 'Dodoni Feta PDO', barcode: '5201004021108', posokanei_id: 'pk-feta', min_quantity: 1, quantity: 0,
  })
  await waitFor(() => expect(h.onAdded).toHaveBeenCalled())
})

it('in pantry: "In pantry: 3" and Open goes to the item, with no Add', async () => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => barcodeProduct({ in_pantry: { stock_item_id: 's1', quantity: 3 } }) })
  const { router } = renderWithProviders(<BarcodeSheet code="5201004021108" {...handlers()} />)
  const sheet = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  expect(sheet).toHaveTextContent('In pantry: 3')
  expect(within(sheet).queryByRole('button', { name: 'Add to pantry' })).not.toBeInTheDocument()
  fireEvent.click(within(sheet).getByRole('button', { name: 'Open' }))
  expect(router.state.location.pathname).toBe('/plan/pantry/s1')
})

it('404: Not on PosoKanei, and Add manually hands the barcode over', async () => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => reply(404, { detail: 'Product not found' }) })
  const h = handlers()
  renderWithProviders(<BarcodeSheet code="12345678" {...h} />)
  const sheet = await screen.findByRole('dialog', { name: 'Barcode 12345678' })
  expect(await within(sheet).findByText('Not on PosoKanei')).toBeInTheDocument()
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add manually' }))
  expect(h.onAddManually).toHaveBeenCalledWith('12345678')
})

it('503: Prices unavailable right now, and manual add is still offered', async () => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => reply(503, { detail: 'Prices unavailable' }) })
  const h = handlers()
  renderWithProviders(<BarcodeSheet code="12345678" {...h} />)
  const sheet = await screen.findByRole('dialog', { name: 'Barcode 12345678' })
  expect(await within(sheet).findByText('Prices unavailable right now')).toBeInTheDocument()
  fireEvent.click(within(sheet).getByRole('button', { name: 'Add manually' }))
  expect(h.onAddManually).toHaveBeenCalledWith('12345678')
})

it('offline: Add to pantry is disabled with the reason', async () => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => barcodeProduct() })
  renderWithProviders(<BarcodeSheet code="5201004021108" {...handlers()} />)
  const sheet = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  setOnline(false)
  await waitFor(() => expect(within(sheet).getByRole('button', { name: 'Add to pantry' })).toBeDisabled())
  expect(sheet).toHaveTextContent('Connect to change the pantry')
  // A scan needs the lookup, which needs a connection.
  expect(within(sheet).getByRole('button', { name: 'Scan another' })).toBeDisabled()
})

// Pantry fix round 1, I3: a miss (404) or PosoKanei being down (503) still says whether the barcode is in the
// pantry, in a JSON body {detail, in_pantry}.
it.each([
  [404, 'Product not found', 'Not on PosoKanei'],
  [503, 'Prices unavailable', 'Prices unavailable right now'],
])('%i with in_pantry: says "In pantry: 3" and offers Open, not Add manually', async (status, detail, head) => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => reply(status, { detail, in_pantry: { stock_item_id: 's1', quantity: 3 } }) })
  const h = handlers()
  const { router } = renderWithProviders(<BarcodeSheet code="12345678" {...h} />)
  const sheet = await screen.findByRole('dialog', { name: 'Barcode 12345678' })
  expect(await within(sheet).findByText(head)).toBeInTheDocument()
  expect(sheet).toHaveTextContent('In pantry: 3')
  expect(within(sheet).queryByRole('button', { name: 'Add manually' })).not.toBeInTheDocument()
  fireEvent.click(within(sheet).getByRole('button', { name: 'Open' }))
  expect(h.onClose).toHaveBeenCalled()
  expect(router.state.location.pathname).toBe('/plan/pantry/s1')
})

it.each([404, 503])('%i with in_pantry null: no "In pantry", Add manually as before', async (status) => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => reply(status, { detail: 'x', in_pantry: null }) })
  renderWithProviders(<BarcodeSheet code="12345678" {...handlers()} />)
  const sheet = await screen.findByRole('dialog', { name: 'Barcode 12345678' })
  expect(await within(sheet).findByRole('button', { name: 'Add manually' })).toBeInTheDocument()
  expect(sheet).not.toHaveTextContent('In pantry')
  expect(within(sheet).queryByRole('button', { name: 'Open' })).not.toBeInTheDocument()
})
