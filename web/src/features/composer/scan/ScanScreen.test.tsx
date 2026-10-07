import { QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../../../test/render'
import { loose, writes } from '../testHelpers'
import { ScanScreen } from './ScanScreen'

const cam = vi.hoisted(() => ({ decode: null as null | ((t: string) => void), stop: vi.fn(), fail: false, started: 0 }))
vi.mock('./qr', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./qr')>()),
  startQr: vi.fn(async (_video: HTMLVideoElement, onDecode: (t: string) => void) => {
    cam.started++
    if (cam.fail) throw new Error('NotAllowedError')
    cam.decode = onDecode
    return { stop: cam.stop }
  }),
}))
vi.mock('./image', () => ({ shrinkImage: vi.fn(async () => new File(['small'], 'shrunk.jpg', { type: 'image/jpeg' })) }))

afterEach(async () => {
  await resetTestEnv()
  Object.assign(cam, { decode: null, fail: false, started: 0 })
  cam.stop.mockClear() // vi.restoreAllMocks no longer resets vi.fn() call history (Vitest 3+)
})

const AADE = 'https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=abc'
const RESULT = { amount: 12.5, currency: 'EUR', date: '2026-10-05', merchant: 'Test Taverna', category_hint: null, category_id: 'c-eat' }

function show(over: Partial<Parameters<typeof ScanScreen>[0]> = {}) {
  const props = { online: true, onResult: vi.fn(), onPhoto: vi.fn(), onClose: vi.fn(), ...over }
  render(<QueryClientProvider client={testQueryClient()}><ScanScreen {...props} /></QueryClientProvider>)
  return props
}

it('a QR receipt URL is looked up and fills the result', async () => {
  const api = fakeApi(loose({ 'POST /api/v1/transactions/scan/qr': RESULT }))
  const p = show()
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!(AADE))
  await waitFor(() => expect(p.onResult).toHaveBeenCalledWith(RESULT))
  expect(writes(api)).toEqual([expect.objectContaining({ path: '/api/v1/transactions/scan/qr', body: { url: AADE } })])
})

it('another kind of QR says so and keeps scanning, with no request', async () => {
  const api = fakeApi({})
  show()
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!('WIFI:S:home;;'))
  expect(await screen.findByText('That is not a receipt QR')).toBeInTheDocument()
  expect(api.calls).toHaveLength(0)
  expect(cam.stop).not.toHaveBeenCalled()
})

it('a 502 shows the server message and the Photo hint, and the camera stays on', async () => {
  fakeApi(loose({ 'POST /api/v1/transactions/scan/qr': () => Response.json({ detail: 'Could not read the receipt from AADE' }, { status: 502 }) }))
  show()
  await waitFor(() => expect(cam.decode).not.toBeNull())
  act(() => cam.decode!(AADE))
  expect(await screen.findByText('Could not read the receipt from AADE')).toBeInTheDocument()
  expect(screen.getByText('No QR? Use Photo to attach the receipt')).toBeInTheDocument()
  expect(cam.stop).not.toHaveBeenCalled()
})

it('camera denied: "Camera not available", Photo and Type it instead remain', async () => {
  cam.fail = true
  const p = show()
  expect(await screen.findByText('Camera not available')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Type it instead' }))
  expect(p.onClose).toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Photo' }))
  expect(screen.getByLabelText('Take photo')).toBeEnabled()
})

it('Photo attaches the shrunk image and calls nothing on the server', async () => {
  const api = fakeApi({})
  const p = show()
  fireEvent.click(screen.getByRole('button', { name: 'Photo' }))
  fireEvent.change(screen.getByLabelText('Take photo'), { target: { files: [new File(['big'], 'IMG.HEIC')] } })
  await waitFor(() => expect(p.onPhoto).toHaveBeenCalledWith(expect.objectContaining({ name: 'shrunk.jpg' })))
  expect(api.calls).toHaveLength(0)
})

it('Upload file takes a PDF as it is and refuses other types', async () => {
  const p = show()
  const upload = screen.getByLabelText('Upload file')
  fireEvent.change(upload, { target: { files: [new File(['x'], 'notes.txt')] } })
  expect(await screen.findByText('Unsupported file type')).toBeInTheDocument()
  const pdf = new File(['%PDF'], 'r.pdf', { type: 'application/pdf' })
  fireEvent.change(upload, { target: { files: [pdf] } })
  await waitFor(() => expect(p.onPhoto).toHaveBeenCalledWith(pdf))
})

it('offline: no camera, Photo and Upload disabled', async () => {
  show({ online: false })
  expect(screen.getByText('Scanning needs a connection. Type it instead')).toBeInTheDocument()
  expect(cam.started).toBe(0)
  expect(screen.getByLabelText('Upload file')).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Photo' }))
  expect(screen.getByLabelText('Take photo')).toBeDisabled()
})
