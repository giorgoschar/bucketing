import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi, reply } from '../../../test/fakeApi'
import { barcodeProduct, pantryRoutes, productSummary, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { AddSheet, SEARCH_DELAY_MS } from './AddSheet'

afterEach(resetTestEnv)

const SEARCH = 'GET /api/v1/products/search' as const
const ADD = 'POST /api/v1/stock' as const
const BARCODE = 'GET /api/v1/products/barcode/{code}' as const
const sleep = (ms: number) => act(() => new Promise<void>((r) => setTimeout(r, ms)))
const sheet = () => within(screen.getByRole('dialog', { name: 'Add to pantry' }))

function routes() {
  return {
    ...pantryRoutes(),
    [SEARCH]: () => [productSummary(), productSummary({ id: 'pk-kolios', name: 'Kolios Feta PDO', brand: 'Kolios' })],
    [ADD]: () => Response.json(stockItem({ id: 'new', name: 'Dodoni Feta PDO' }), { status: 201 }),
  }
}

it('search waits 300 ms after typing and needs 2 or more characters', async () => {
  expect(SEARCH_DELAY_MS).toBe(300)
  const fake = fakeApi(routes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  const box = sheet().getByRole('searchbox', { name: 'Search PosoKanei' })
  fireEvent.change(box, { target: { value: 'f' } })
  await sleep(SEARCH_DELAY_MS + 100)
  expect(fake.callsTo(SEARCH)).toHaveLength(0)

  fireEvent.change(box, { target: { value: 'fe' } })
  fireEvent.change(box, { target: { value: 'fet' } })
  await sleep(200)
  expect(fake.callsTo(SEARCH)).toHaveLength(0)
  await waitFor(() => expect(fake.callsTo(SEARCH)).toHaveLength(1))
  expect(fake.callsTo(SEARCH)[0].query.get('q')).toBe('fet')
  const result = await sheet().findByRole('listitem', { name: 'Dodoni Feta PDO' })
  expect(result).toHaveTextContent('Dodoni · 400 g')
  expect(result).toHaveTextContent('€5.29')
  expect(result).toHaveTextContent('Lidl')
  expect(sheet().getByText('Prices from PosoKanei').closest('p')).toHaveTextContent('Prices from PosoKanei · Updated 8 Oct')
})

it('＋ on a result adds it with a minimum of 1 and says so', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.change(sheet().getByRole('searchbox', { name: 'Search PosoKanei' }), { target: { value: 'feta' } })
  const result = await sheet().findByRole('listitem', { name: 'Dodoni Feta PDO' })
  fireEvent.click(within(result).getByRole('button', { name: 'Add Dodoni Feta PDO' }))
  await waitFor(() => expect(fake.callsTo(ADD)).toHaveLength(1))
  expect(fake.callsTo(ADD)[0].body).toMatchObject({
    name: 'Dodoni Feta PDO', brand: 'Dodoni', barcode: '5201004021108', posokanei_id: 'pk-feta', unit: 'g', unit_quantity: 400,
    min_quantity: 1,
  })
  expect(await within(result).findByRole('button', { name: 'Added Dodoni Feta PDO' })).toBeDisabled()
  expect(await screen.findByText('Added Dodoni Feta PDO')).toBeInTheDocument()
})

it('search unavailable (503) says so, and manual add stays', async () => {
  fakeApi({ ...routes(), [SEARCH]: () => reply(503, { detail: 'Prices unavailable' }) })
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.change(sheet().getByRole('searchbox', { name: 'Search PosoKanei' }), { target: { value: 'feta' } })
  expect(await sheet().findByText('Prices unavailable right now')).toBeInTheDocument()
  expect(sheet().getByRole('button', { name: 'Add manually' })).toBeEnabled()
})

it('a manual add posts name, brand, size, in stock and keep at least', async () => {
  const fake = fakeApi(routes())
  const closed: boolean[] = []
  renderWithProviders(<AddSheet open onClose={() => closed.push(true)} />)
  fireEvent.click(sheet().getByRole('button', { name: 'Add manually' }))
  fireEvent.change(sheet().getByLabelText('Name'), { target: { value: 'Olive oil' } })
  fireEvent.change(sheet().getByLabelText('Brand'), { target: { value: 'Gaea' } })
  fireEvent.change(sheet().getByLabelText('Size'), { target: { value: '1' } })
  fireEvent.change(sheet().getByLabelText('Unit'), { target: { value: 'L' } })
  fireEvent.change(sheet().getByLabelText('In stock'), { target: { value: '2' } })
  fireEvent.change(sheet().getByLabelText('Keep at least'), { target: { value: '1,5' } })
  fireEvent.click(sheet().getByRole('button', { name: 'Add to pantry' }))
  await waitFor(() => expect(fake.callsTo(ADD)).toHaveLength(1))
  expect(fake.callsTo(ADD)[0].body).toEqual({
    name: 'Olive oil', brand: 'Gaea', unit_quantity: 1, unit: 'L', quantity: 2, min_quantity: 1.5, barcode: null,
  })
  await waitFor(() => expect(closed).toEqual([true]))
})

it('a manual add needs a name', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.click(sheet().getByRole('button', { name: 'Add manually' }))
  fireEvent.click(sheet().getByRole('button', { name: 'Add to pantry' }))
  expect(await sheet().findByText('Give it a name')).toBeInTheDocument()
  expect(fake.callsTo(ADD)).toHaveLength(0)
})

it('Type barcode opens the lookup sheet for it', async () => {
  const fake = fakeApi({ ...routes(), [BARCODE]: () => barcodeProduct() })
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.change(sheet().getByRole('textbox', { name: 'Type barcode' }), { target: { value: '5201004021108' } })
  fireEvent.click(sheet().getByRole('button', { name: 'Look up' }))
  const lookup = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  expect(fake.callsTo(BARCODE)[0].path).toBe('/api/v1/products/barcode/5201004021108')
  expect(lookup).toHaveTextContent('Barcode 5201004021108')
})

it('Look up needs 6 to 14 digits', () => {
  fakeApi(routes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.change(sheet().getByRole('textbox', { name: 'Type barcode' }), { target: { value: '12a' } })
  expect(sheet().getByRole('button', { name: 'Look up' })).toBeDisabled()
})

it('404 → Add manually opens the manual form with the barcode filled in', async () => {
  const fake = fakeApi({ ...routes(), [BARCODE]: () => reply(404, { detail: 'Product not found' }) })
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.change(sheet().getByRole('textbox', { name: 'Type barcode' }), { target: { value: '12345678' } })
  fireEvent.click(sheet().getByRole('button', { name: 'Look up' }))
  const lookup = await screen.findByRole('dialog', { name: 'Barcode 12345678' })
  expect(lookup).toHaveTextContent('Not on PosoKanei')
  fireEvent.click(within(lookup).getByRole('button', { name: 'Add manually' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Barcode 12345678' })).not.toBeInTheDocument())
  expect(sheet().getByText('Barcode 12345678')).toBeInTheDocument()
  fireEvent.change(sheet().getByLabelText('Name'), { target: { value: 'Village bread' } })
  fireEvent.click(sheet().getByRole('button', { name: 'Add to pantry' }))
  await waitFor(() => expect(fake.callsTo(ADD)).toHaveLength(1))
  expect(fake.callsTo(ADD)[0].body).toMatchObject({ name: 'Village bread', barcode: '12345678' })
})

it('offline: the add writes are disabled, with the reason', async () => {
  setOnline(false)
  const fake = fakeApi(routes())
  fake.down()
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  expect(sheet().getAllByText('Connect to change the pantry').length).toBeGreaterThan(0)
  expect(sheet().getByRole('searchbox', { name: 'Search PosoKanei' })).toBeDisabled()
  expect(sheet().getByRole('button', { name: 'Look up' })).toBeDisabled()
  expect(sheet().getByRole('button', { name: 'Scan barcode' })).toBeDisabled()
  fireEvent.click(sheet().getByRole('button', { name: 'Add manually' }))
  fireEvent.change(sheet().getByLabelText('Name'), { target: { value: 'Olive oil' } })
  expect(sheet().getByRole('button', { name: 'Add to pantry' })).toBeDisabled()
  expect(fake.callsTo(ADD)).toHaveLength(0)
})
