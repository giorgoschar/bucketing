import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { keys } from '../../../data/keys'
import { fakeApi, reply } from '../../../test/fakeApi'
import { pantryRoutes, stockDetail, stockItem } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { todayISO } from '../../../ui/format'
import { Detail } from './Detail'
import { editBody } from './edit'
import type { StockDetail } from './types'

afterEach(resetTestEnv)

const DETAIL = 'GET /api/v1/stock/{item_id}' as const
const PATCH = 'PATCH /api/v1/stock/{item_id}' as const
const PRICES = 'POST /api/v1/stock/{item_id}/prices' as const
const RETAILERS = 'GET /api/v1/stock/retailers' as const

/** The detail, PATCH (C2) and Log a price (C3) on a small server. */
function routes(detail: StockDetail = stockDetail()) {
  let current = detail
  return {
    ...pantryRoutes({ items: [stockItem({ ...detail })] }),
    [DETAIL]: () => current,
    [PATCH]: (req: { body: unknown }) => {
      current = { ...current, ...(req.body as object) }
      return { ...current }
    },
    // The server may list "other" anywhere, or not at all: the picker puts "Other" last either way.
    [RETAILERS]: () => [{ code: 'other', name: 'Other' }, { code: 'lidl', name: 'Lidl' }, { code: 'ab', name: 'AB' }],
    [PRICES]: (req: { body: unknown }) => {
      const b = req.body as { price: number; retailer: string; date: string }
      const name = b.retailer === 'lidl' ? 'Lidl' : b.retailer
      current = {
        ...current,
        prices_today: [{ retailer: b.retailer, retailer_name: name, price: b.price, unit_price: null, is_discount: false }],
        history: [...current.history, { date: b.date, min_price: b.price }],
      }
      return current
    },
  }
}

async function openEdit() {
  fireEvent.click(await screen.findByRole('button', { name: 'Edit Barilla spaghetti' }))
  return screen.findByRole('dialog', { name: 'Edit product' })
}

async function openPrice() {
  const prices = await screen.findByRole('region', { name: 'Prices today' })
  fireEvent.click(within(prices).getByRole('button', { name: 'Log a price' }))
  return screen.findByRole('dialog', { name: 'Log a price' })
}

it('Edit sends only what changed: name, brand, size with its unit, and the barcode', async () => {
  const fake = fakeApi(routes())
  const { client } = renderWithProviders(<Detail id="s1" />)
  client.setQueryData(keys.stockList(), [stockItem()])
  const sheet = await openEdit()
  expect(within(sheet).getByLabelText('Name')).toHaveValue('Barilla spaghetti')
  expect(within(sheet).getByLabelText('Size')).toHaveValue('500')
  expect(within(sheet).getByLabelText('Unit')).toHaveValue('g')
  expect(within(sheet).getByLabelText('Barcode')).toHaveValue('8076802085738')
  fireEvent.change(within(sheet).getByLabelText('Name'), { target: { value: '  Spaghetti n.5 ' } })
  fireEvent.change(within(sheet).getByLabelText('Size'), { target: { value: '1' } })
  fireEvent.change(within(sheet).getByLabelText('Unit'), { target: { value: 'kg' } })
  fireEvent.change(within(sheet).getByLabelText('Barcode'), { target: { value: '8076 8020 85745' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(fake.callsTo(PATCH)).toHaveLength(1))
  expect(fake.callsTo(PATCH)[0].body).toEqual({ name: 'Spaghetti n.5', unit_quantity: 1, unit: 'kg', barcode: '8076802085745' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(await screen.findByRole('heading', { level: 1, name: 'Spaghetti n.5' })).toBeInTheDocument()
  // The stock keys are refreshed: the list refetches.
  expect(client.getQueryState(keys.stockList())?.isInvalidated).toBe(true)
})

it('Edit: a free-text unit, a comma size, and clearing the brand', () => {
  const d = stockDetail()
  const f = { name: 'Barilla spaghetti', brand: ' ', size: '1,5', unit: 'other', otherUnit: ' packs ', barcode: '8076802085738' }
  expect(editBody(d, f)).toEqual({ body: { brand: null, unit_quantity: 1.5, unit: 'packs' } })
  expect(editBody(d, { ...f, size: '' })).toEqual({ body: { brand: null, unit_quantity: null, unit: null } })
  expect(editBody(d, { ...f, name: '  ' })).toEqual({ error: 'Give it a name', field: 'name' })
  expect(editBody(d, { ...f, barcode: '12ab' })).toEqual({ error: 'A barcode is 6 to 14 digits', field: 'barcode' })
  expect(editBody(d, { ...f, size: '2', otherUnit: '' })).toEqual({ error: 'Give the size a unit', field: 'unit' })
})

// Fix round 1 (review M-4): each validation error is tied to its field.
it.each<[string, string, string, string]>([
  ['Name', '  ', 'Name', 'Give it a name'],
  ['Size', 'abc', 'Size', 'Size must be a number above 0'],
  ['Barcode', '12', 'Barcode', 'A barcode is 6 to 14 digits'],
])('Edit: a bad %s marks that field invalid and describes it with the error', async (label, value, field, message) => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openEdit()
  fireEvent.change(within(sheet).getByLabelText(label), { target: { value } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save changes' }))
  expect(await within(sheet).findByRole('alert')).toHaveTextContent(message)
  expect(within(sheet).getByLabelText(field)).toHaveAttribute('aria-invalid', 'true')
  expect(within(sheet).getByLabelText(field)).toHaveAccessibleDescription(message)
  expect(fake.callsTo(PATCH)).toHaveLength(0)
})

it('Edit: a size with no unit name marks the unit name field', async () => {
  fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openEdit()
  fireEvent.change(within(sheet).getByLabelText('Unit'), { target: { value: 'other' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save changes' }))
  await within(sheet).findByRole('alert')
  expect(within(sheet).getByLabelText('Unit name')).toHaveAttribute('aria-invalid', 'true')
  expect(within(sheet).getByLabelText('Unit name')).toHaveAccessibleDescription('Give the size a unit')
  expect(within(sheet).getByLabelText('Name')).not.toHaveAttribute('aria-invalid')
})

it('Edit: a barcode another product has is said inline, and the sheet stays open', async () => {
  const fake = fakeApi(routes())
  fake.on(PATCH, () => reply(409, { detail: 'Another product already has this barcode' }))
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openEdit()
  fireEvent.change(within(sheet).getByLabelText('Barcode'), { target: { value: '5201004021108' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Save changes' }))
  const alert = await within(sheet).findByRole('alert')
  expect(alert).toHaveTextContent('Another product already has this barcode')
  expect(within(sheet).getByLabelText('Barcode')).toHaveAttribute('aria-invalid', 'true')
  expect(within(sheet).getByLabelText('Barcode')).toHaveAccessibleDescription('Another product already has this barcode')
  expect(screen.getByRole('dialog', { name: 'Edit product' })).toBeInTheDocument()
})

it('Log a price: the store picker ends with Other; the body has the price, store and date', async () => {
  const fake = fakeApi(routes(stockDetail({ prices_today: [], prices_as_of: null })))
  renderWithProviders(<Detail id="s1" />)
  expect(await screen.findByText('Prices you log appear here')).toBeInTheDocument()
  const sheet = await openPrice()
  const store = within(sheet).getByLabelText('Store')
  await waitFor(() => expect(store).toBeEnabled())
  expect(within(store).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose a store', 'Lidl', 'AB', 'Other'])
  expect(within(sheet).getByLabelText('Date')).toHaveValue(todayISO())
  const save = within(sheet).getByRole('button', { name: 'Log price' })
  expect(save).toBeDisabled()
  fireEvent.change(within(sheet).getByLabelText('Price'), { target: { value: '1,29' } })
  fireEvent.change(store, { target: { value: 'lidl' } })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Log €1.29' }))
  await waitFor(() => expect(fake.callsTo(PRICES)).toHaveLength(1))
  expect(fake.callsTo(PRICES)[0].path).toBe('/api/v1/stock/s1/prices')
  expect(fake.callsTo(PRICES)[0].body).toEqual({ price: 1.29, retailer: 'lidl', date: todayISO() })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  // The detail shows the logged price at once (the reply is the detail).
  const list = await screen.findByRole('list', { name: 'Prices today' })
  expect(within(list).getAllByRole('listitem').map((r) => r.textContent)).toEqual(['Lidl€1.29'])
})

it.each([
  ['1,29', 1.29], ['1.5', 1.5], ['2', 2], [' 0,99 ', 0.99],
])('Log a price reads %s as %s', async (typed, sent) => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openPrice()
  await waitFor(() => expect(within(sheet).getByLabelText('Store')).toBeEnabled())
  fireEvent.change(within(sheet).getByLabelText('Price'), { target: { value: typed } })
  fireEvent.change(within(sheet).getByLabelText('Store'), { target: { value: 'other' } })
  fireEvent.submit(within(sheet).getByLabelText('Price').closest('form')!)
  await waitFor(() => expect(fake.callsTo(PRICES)).toHaveLength(1))
  expect((fake.callsTo(PRICES)[0].body as { price: number }).price).toBe(sent)
})

it.each(['0', '1,2,3', 'abc', '1.234'])('Log a price refuses %s', async (typed) => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openPrice()
  await waitFor(() => expect(within(sheet).getByLabelText('Store')).toBeEnabled())
  fireEvent.change(within(sheet).getByLabelText('Price'), { target: { value: typed } })
  fireEvent.change(within(sheet).getByLabelText('Store'), { target: { value: 'lidl' } })
  expect(within(sheet).getByRole('button', { name: 'Log price' })).toBeDisabled()
  fireEvent.submit(within(sheet).getByLabelText('Price').closest('form')!)
  expect(fake.callsTo(PRICES)).toHaveLength(0)
})

it('Log a price: a future date is blocked', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openPrice()
  await waitFor(() => expect(within(sheet).getByLabelText('Store')).toBeEnabled())
  const tomorrow = new Date()
  tomorrow.setDate(tomorrow.getDate() + 1)
  fireEvent.change(within(sheet).getByLabelText('Price'), { target: { value: '1,29' } })
  fireEvent.change(within(sheet).getByLabelText('Store'), { target: { value: 'lidl' } })
  fireEvent.change(within(sheet).getByLabelText('Date'), { target: { value: todayISO(tomorrow) } })
  expect(within(sheet).getByLabelText('Date')).toHaveAccessibleDescription('Pick today or an earlier day')
  expect(within(sheet).getByRole('button', { name: 'Log €1.29' })).toBeDisabled()
  fireEvent.submit(within(sheet).getByLabelText('Price').closest('form')!)
  expect(fake.callsTo(PRICES)).toHaveLength(0)
})

it('offline: Edit and Log a price are disabled; a sheet open when the connection drops cannot save', async () => {
  const fake = fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openPrice()
  await waitFor(() => expect(within(sheet).getByLabelText('Store')).toBeEnabled())
  fireEvent.change(within(sheet).getByLabelText('Price'), { target: { value: '1,29' } })
  fireEvent.change(within(sheet).getByLabelText('Store'), { target: { value: 'lidl' } })
  setOnline(false)
  await waitFor(() => expect(within(sheet).getByRole('button', { name: 'Log €1.29' })).toBeDisabled())
  expect(sheet).toHaveTextContent('Connect to change the pantry')
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(screen.getByRole('button', { name: 'Edit Barilla spaghetti' })).toBeDisabled()
  expect(within(screen.getByRole('region', { name: 'Prices today' })).getByRole('button', { name: 'Log a price' })).toBeDisabled()
  expect(fake.callsTo(PRICES)).toHaveLength(0)
  expect(fake.callsTo(PATCH)).toHaveLength(0)
})

it('Edit offline after opening: Save is disabled', async () => {
  fakeApi(routes())
  renderWithProviders(<Detail id="s1" />)
  const sheet = await openEdit()
  setOnline(false)
  await waitFor(() => expect(within(sheet).getByRole('button', { name: 'Save changes' })).toBeDisabled())
  expect(sheet).toHaveTextContent('Connect to change the pantry')
})
