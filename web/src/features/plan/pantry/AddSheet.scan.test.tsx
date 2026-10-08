import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { barcodeProduct, pantryRoutes } from '../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import type { ScannerProps } from './scan/Scanner'

// The camera module is replaced; the factory runs only when something imports it, so `loads` counts imports.
const loads = vi.hoisted(() => ({ n: 0 }))
vi.mock('./scan/Scanner', () => {
  loads.n += 1
  return {
    Scanner: ({ onDetect, onUnavailable, onClose }: ScannerProps) => (
      <div role="dialog" aria-label="Scan barcode">
        <button type="button" onClick={() => onDetect('5201004021108')}>Read a code</button>
        <button type="button" onClick={() => onUnavailable()}>Deny</button>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    ),
  }
})

import { AddSheet } from './AddSheet'

afterEach(resetTestEnv)

const BARCODE = 'GET /api/v1/products/barcode/{code}' as const
const sheet = () => within(screen.getByRole('dialog', { name: 'Add to pantry' }))

it('the scanner module is only imported when Scan is tapped', async () => {
  fakeApi({ ...pantryRoutes(), [BARCODE]: () => barcodeProduct() })
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  await new Promise((r) => setTimeout(r, 20))
  expect(loads.n).toBe(0)
  fireEvent.click(sheet().getByRole('button', { name: 'Scan barcode' }))
  expect(await screen.findByRole('dialog', { name: 'Scan barcode' })).toBeInTheDocument()
  expect(loads.n).toBe(1)
})

it('a read code closes the camera and opens the lookup sheet', async () => {
  const fake = fakeApi({ ...pantryRoutes(), [BARCODE]: () => barcodeProduct() })
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.click(sheet().getByRole('button', { name: 'Scan barcode' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Read a code' }))
  expect(await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Scan barcode' })).not.toBeInTheDocument()
  expect(fake.callsTo(BARCODE)[0].path).toBe('/api/v1/products/barcode/5201004021108')

  // Scan another: back to the camera.
  fireEvent.click(screen.getByRole('button', { name: 'Scan another' }))
  expect(await screen.findByRole('dialog', { name: 'Scan barcode' })).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Dodoni Feta PDO' })).not.toBeInTheDocument())
})

it('no camera: "Type the barcode instead" with the barcode field focused', async () => {
  fakeApi(pantryRoutes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.click(sheet().getByRole('button', { name: 'Scan barcode' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Deny' }))
  expect(await sheet().findByText('Type the barcode instead')).toBeInTheDocument()
  await waitFor(() => expect(sheet().getByRole('textbox', { name: 'Type barcode' })).toHaveFocus())
})
