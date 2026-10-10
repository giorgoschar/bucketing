import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi, type Routes } from '../../../test/fakeApi'
import { bucket, item, page, readRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import type { ItemWithUsage } from '../../insights/bills/types'
import { emptyItemForm, formToBody, itemToForm } from './form'
import { ItemSheet } from './ItemSheet'

afterEach(resetTestEnv)

const PUT = 'PUT /api/v1/recurring/{item_id}' as const
const routes = (over: Routes = {}): Routes => ({
  ...readRoutes(),
  'GET /api/v1/buckets': () => [bucket()],
  'GET /api/v1/transactions': () => page([]),
  'POST /api/v1/recurring/preview': () => ({ dates: ['2026-10-26'] }),
  ...over,
})
const withUnit = (usage_unit: string | null): ItemWithUsage => ({ ...item(), usage_unit })

async function save(unit: string | null) {
  const fake = fakeApi(routes({ [PUT]: () => item() }))
  const onClose = vi.fn()
  renderWithProviders(<ItemSheet open item={withUnit(unit)} onClose={onClose} />)
  return { fake, onClose }
}

it('Track usage defaults to Off for an item with no unit, and Off sends usage_unit null', async () => {
  const { fake, onClose } = await save(null)
  expect(screen.getByLabelText('Track usage')).toHaveValue('off')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(PUT)[0].body).toMatchObject({ usage_unit: null })
})

it.each(['kWh', 'm³', 'L', 'GB'])('choosing %s sends it as usage_unit', async (unit) => {
  const { fake, onClose } = await save(null)
  fireEvent.change(screen.getByLabelText('Track usage'), { target: { value: unit } })
  expect(screen.queryByLabelText('Usage unit')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(PUT)[0].body).toMatchObject({ usage_unit: unit })
})

it('Other sends the typed text, trimmed, and the field takes 12 characters at most', async () => {
  const { fake, onClose } = await save(null)
  fireEvent.change(screen.getByLabelText('Track usage'), { target: { value: 'other' } })
  const text = screen.getByLabelText('Usage unit')
  expect(text).toHaveAttribute('maxlength', '12')
  fireEvent.change(text, { target: { value: '  therms ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(onClose).toHaveBeenCalled())
  expect(fake.callsTo(PUT)[0].body).toMatchObject({ usage_unit: 'therms' })
})

it('Other with nothing typed, or more than 12 characters, is refused before sending', async () => {
  const { fake, onClose } = await save(null)
  fireEvent.change(screen.getByLabelText('Track usage'), { target: { value: 'other' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Name the usage unit')
  fireEvent.change(screen.getByLabelText('Usage unit'), { target: { value: 'x'.repeat(13) } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByRole('alert')).toHaveTextContent('12 characters')
  expect(onClose).not.toHaveBeenCalled()
  expect(fake.callsTo(PUT)).toHaveLength(0)
})

it('an item with a known unit opens on it; an unknown unit opens on Other with its text', () => {
  expect(itemToForm(withUnit('kWh'))).toMatchObject({ usageChoice: 'kWh', usageOther: '' })
  expect(itemToForm(withUnit('MWh'))).toMatchObject({ usageChoice: 'other', usageOther: 'MWh' })
  expect(itemToForm(withUnit(null))).toMatchObject({ usageChoice: 'off' })
  expect(formToBody(itemToForm(withUnit('MWh')))).toMatchObject({ usage_unit: 'MWh' })
  expect(formToBody(emptyItemForm('2026-10-07', 'u1'))).toMatchObject({ usage_unit: null })
})
