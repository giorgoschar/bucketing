import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv, setOnline } from '../../test/render'
import { writes } from './testHelpers'
import { renderComposer } from './testing'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({
    status: 'signedIn', logoutFailed: false, signOut: async () => {}, retryLogout: async () => {},
    me: { id: 'u1', household_id: 'h1', username: 'giorgos', display_name: 'Giorgos', email: null, avatar_color: null },
  }),
}))
const cam = vi.hoisted(() => ({ decode: null as null | ((t: string) => void) }))
vi.mock('./scan/qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./scan/qr')>()),
  startQr: vi.fn(async (_v: HTMLVideoElement, onDecode: (t: string) => void) => {
    cam.decode = onDecode
    return { stop: () => {} }
  }),
}))
vi.mock('./scan/image', () => ({ shrinkImage: vi.fn(async () => new File(['small'], 'shrunk.jpg', { type: 'image/jpeg' })) }))

afterEach(async () => {
  await resetTestEnv()
  cam.decode = null
})

const AADE = 'https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc'
const RESULT = { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' }

async function scan(result: object) {
  const r = await renderComposer('/new', { routes: { 'POST /api/v1/transactions/scan/qr': result } })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!(AADE))
  await screen.findByText('Read from myDATA QR')
  return r
}

it('a QR success fills the form, tags the fields, and saves after the duplicate check', async () => {
  const { api, router } = await scan(RESULT)
  expect(router.state.location.search).toBe('')
  expect(screen.queryByRole('dialog', { name: 'Scan receipt' })).not.toBeInTheDocument()
  expect(screen.getByText('Amount 12.50 euro')).toBeInTheDocument()
  expect(screen.getByPlaceholderText('Where? (optional)')).toHaveValue('Test Taverna')
  expect(screen.getByRole('button', { name: 'Category: Eating out, from receipt. Change' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /^Save 12 euro 50/ }))
  await screen.findByText('home screen')
  expect(api.calls.some((c) => c.path === '/api/v1/transactions/check-duplicate')).toBe(true)
  expect(writes(api).map((c) => c.path)).toEqual(['/api/v1/transactions/scan/qr', '/api/v1/transactions'])
  expect(writes(api)[1].body).toMatchObject({ amount: '12.50', merchant: 'Test Taverna', category_id: 'c-eat', transaction_date: '2026-10-05' })
})

it('no total: the amount stays empty with "Couldn\'t find the total"', async () => {
  await scan({ ...RESULT, amount: null })
  expect(screen.getByText("Couldn't find the total")).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Save/ })).toBeDisabled()
})

it('with the rules API present, changing the scanned category offers Remember; changing it back withdraws it', async () => {
  await scan(RESULT)
  expect(screen.queryByRole('switch', { name: /^Remember/ })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Category: Eating out, from receipt. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Coffee/ }))
  expect(screen.getByRole('switch', { name: 'Remember "Test Taverna" → "Coffee"' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Category: Coffee. Change' }))
  fireEvent.click(await screen.findByRole('button', { name: /^Eating out/ }))
  expect(screen.queryByRole('switch', { name: /^Remember/ })).not.toBeInTheDocument()
})

it('Photo attaches the shrunk image, opens an empty composer, and never calls /scan/parse', async () => {
  const { api } = await renderComposer('/new', { routes: { 'POST /api/v1/transactions/t1/receipt': { receipt_path: 'x.jpg' } } })
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Photo' }))
  fireEvent.change(screen.getByLabelText('Take photo'), { target: { files: [new File(['big'], 'IMG.HEIC')] } })
  expect(await screen.findByText('Receipt attached. Type the details.')).toBeInTheDocument()
  expect(screen.getByText('Amount 0.00 euro')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '8' }))
  fireEvent.click(screen.getByRole('button', { name: /^Save 8 euro/ }))
  await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/transactions/t1/receipt')).toBe(true))
  const upload = api.calls.find((c) => c.path === '/api/v1/transactions/t1/receipt')!
  expect(((upload.body as FormData).get('file') as File).name).toBe('shrunk.jpg')
  expect(api.calls.some((c) => c.path.endsWith('/scan/parse'))).toBe(false)
})

it('offline: the scan screen says it needs a connection', async () => {
  await renderComposer('/new')
  await screen.findByRole('button', { name: 'Budget: Day to day. Change' })
  act(() => setOnline(false))
  fireEvent.click(screen.getByRole('button', { name: 'Scan receipt' }))
  expect(await screen.findByText('Scanning needs a connection. Type it instead')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Type it instead' }))
  expect(screen.queryByRole('dialog', { name: 'Scan receipt' })).not.toBeInTheDocument()
})
