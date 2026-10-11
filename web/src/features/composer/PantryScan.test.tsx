import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { barcodeProduct, pantryRoutes } from '../../test/fixtures'
import { reply } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import type { ScannerProps } from '../plan/pantry/scan/Scanner'
import { renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))
// The camera module is replaced; the factory runs only when something imports it, so `loads` counts imports.
const loads = vi.hoisted(() => ({ n: 0 }))
vi.mock('../plan/pantry/scan/Scanner', () => {
  loads.n += 1
  return {
    Scanner: ({ onDetect, onUnavailable, onClose }: ScannerProps) => (
      <div role="dialog" aria-label="Scan barcode">
        <button type="button" onClick={() => onDetect('5201004021108')}>Read a code</button>
        <button type="button" onClick={() => onDetect('12345678')}>Read an unknown code</button>
        <button type="button" onClick={() => onUnavailable()}>Deny</button>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    ),
  }
})

vi.mock('./scan/qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./scan/qr')>()),
  startQr: vi.fn(async () => ({ stop: () => {} })),
}))

afterEach(resetTestEnv)

const BARCODE = (code: string) => `GET /api/v1/products/barcode/${code}`
const routes = (extra: Record<string, unknown> = {}) => ({
  // Only the pantry's own routes: the household, buckets and the rest stay the composer's.
  ...Object.fromEntries(Object.entries(pantryRoutes() as Record<string, unknown>).filter(([k]) => k.includes('/stock'))),
  [BARCODE('5201004021108')]: () => barcodeProduct(),
  ...extra,
})

async function openPantryScan(extra: Record<string, unknown> = {}) {
  const r = await renderComposer('/new', { routes: routes(extra) })
  await screen.findByRole('button', { name: /^Budget:/ })
  fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Scan' })).getByRole('button', { name: /^Pantry barcode/ }))
  return r
}

it('the pantry camera is only imported when Pantry barcode is chosen', async () => {
  await renderComposer('/new', { routes: routes() })
  await screen.findByRole('button', { name: /^Budget:/ })
  fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Scan' })).getByRole('button', { name: /^Receipt QR/ }))
  await new Promise((r) => setTimeout(r, 20))
  expect(loads.n).toBe(0)
})

it('Pantry barcode opens the scanner, then the barcode sheet with the add button', async () => {
  await openPantryScan()
  fireEvent.click(await screen.findByRole('button', { name: 'Read a code' }))
  const sheet = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  expect(within(sheet).getByRole('button', { name: 'Add to pantry' })).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Scan barcode' })).not.toBeInTheDocument()
})

it('an item already in the pantry shows its stepper', async () => {
  await openPantryScan({ [BARCODE('5201004021108')]: () => barcodeProduct({ in_pantry: { stock_item_id: 's1', quantity: 3 } }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Read a code' }))
  const sheet = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  expect(await within(sheet).findByText('In your pantry')).toBeInTheDocument()
})

it('Scan another goes back to the camera', async () => {
  await openPantryScan()
  fireEvent.click(await screen.findByRole('button', { name: 'Read a code' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Scan another' }))
  expect(await screen.findByRole('dialog', { name: 'Scan barcode' })).toBeInTheDocument()
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Dodoni Feta PDO' })).not.toBeInTheDocument())
})

it('closing at the camera and at the sheet returns to the form with the typed amount, place and budget intact', async () => {
  await renderComposer('/new', { routes: routes() })
  await screen.findByRole('button', { name: /^Budget:/ })
  fireEvent.click(screen.getByRole('button', { name: '7' }))
  fireEvent.change(screen.getByPlaceholderText('Where? (optional)'), { target: { value: 'Bakery' } })
  const intact = () => {
    expect(screen.getByText('Amount 7.00 euro')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Where? (optional)')).toHaveValue('Bakery')
    expect(screen.getByRole('button', { name: /^Budget: Day to day/ })).toBeInTheDocument()
  }
  const open = async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
    fireEvent.click(within(await screen.findByRole('dialog', { name: 'Scan' })).getByRole('button', { name: /^Pantry barcode/ }))
  }
  await open()
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Scan barcode' })).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Scan barcode' })).not.toBeInTheDocument())
  await waitFor(intact)
  await open()
  fireEvent.click(await screen.findByRole('button', { name: 'Read a code' }))
  const sheet = await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })
  fireEvent.click(within(sheet).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Dodoni Feta PDO' })).not.toBeInTheDocument())
  await waitFor(intact)
})

it('no camera: type the digits, then look them up', async () => {
  await openPantryScan()
  fireEvent.click(await screen.findByRole('button', { name: 'Deny' }))
  const typed = await screen.findByRole('textbox', { name: 'Type barcode' })
  expect(typed).toHaveFocus()
  expect(screen.getByRole('button', { name: 'Look up' })).toBeDisabled()
  fireEvent.change(typed, { target: { value: '5201004021108' } })
  fireEvent.click(screen.getByRole('button', { name: 'Look up' }))
  expect(await screen.findByRole('dialog', { name: 'Dodoni Feta PDO' })).toBeInTheDocument()
})

it('an unknown code offers Add manually inside the flow', async () => {
  await openPantryScan({ [BARCODE('12345678')]: () => reply(404, { detail: 'Product not found' }) })
  fireEvent.click(await screen.findByRole('button', { name: 'Read an unknown code' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Add manually' }))
  expect(await screen.findByRole('dialog', { name: 'Add to pantry' })).toHaveTextContent('Barcode 12345678')
})
