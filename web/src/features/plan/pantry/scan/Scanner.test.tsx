import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../../test/fakeApi'
import { pantryRoutes } from '../../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../../test/render'

const det = vi.hoisted(() => ({ codes: [] as string[], made: 0, wasm: null as null | string }))
vi.mock('barcode-detector/ponyfill', () => ({
  prepareZXingModule: (o: { overrides: { locateFile: (p: string, prefix: string) => string } }) => {
    det.wasm = o.overrides.locateFile('zxing_reader.wasm', 'https://fastly.jsdelivr.net/npm/zxing-wasm/dist/reader/')
  },
  BarcodeDetector: class {
    constructor() { det.made += 1 }
    async detect() { return det.codes.map((rawValue) => ({ rawValue, format: 'ean_13' })) }
  },
}))

import { AddSheet } from '../AddSheet'
import { Scanner } from './Scanner'

const track = { stop: vi.fn() }
const stream = { getTracks: () => [track] } as unknown as MediaStream
const getUserMedia = vi.fn<(c: MediaStreamConstraints) => Promise<MediaStream>>()

beforeEach(() => {
  det.codes = []
  det.made = 0
  getUserMedia.mockReset()
  track.stop.mockReset()
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
  vi.spyOn(HTMLMediaElement.prototype, 'readyState', 'get').mockReturnValue(4) // HAVE_ENOUGH_DATA
})
afterEach(async () => {
  Reflect.deleteProperty(navigator, 'mediaDevices')
  await resetTestEnv()
})

const denied = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'))

it('uses the rear camera, reads EAN/UPC through the self-hosted decoder, and stops the camera on a read', async () => {
  getUserMedia.mockResolvedValue(stream)
  const onDetect = vi.fn()
  render(<Scanner onDetect={onDetect} onUnavailable={() => {}} onClose={() => {}} />)
  await waitFor(() => expect(det.made).toBe(1))
  expect(getUserMedia.mock.calls[0][0]).toMatchObject({ video: { facingMode: { ideal: 'environment' } }, audio: false })
  // The wasm comes from our own build, never the package's CDN default.
  expect(det.wasm).not.toMatch(/jsdelivr|^https?:/)
  expect(det.wasm).toMatch(/zxing_reader.*\.wasm/)
  act(() => { det.codes = ['5201004021108'] })
  await waitFor(() => expect(onDetect).toHaveBeenCalledWith('5201004021108'))
  expect(onDetect).toHaveBeenCalledTimes(1)
  expect(track.stop).toHaveBeenCalled()
})

it('Close and Esc leave, and the camera stops', async () => {
  getUserMedia.mockResolvedValue(stream)
  const onClose = vi.fn()
  const { unmount } = render(<Scanner onDetect={() => {}} onUnavailable={() => {}} onClose={onClose} />)
  const dialog = screen.getByRole('dialog', { name: 'Scan barcode' })
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
  expect(dialog).toHaveTextContent('Hold the barcode inside the box')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(onClose).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(onClose).toHaveBeenCalledTimes(2)
  await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
  await act(async () => {})
  unmount()
  expect(track.stop).toHaveBeenCalled()
})

it('a denied camera falls back to the typed barcode, focused', async () => {
  getUserMedia.mockImplementation(denied)
  fakeApi(pantryRoutes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Scan barcode' }))
  expect(await screen.findByText('Type the barcode instead')).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Scan barcode' })).not.toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Type barcode' })).toHaveFocus())
})

it('a browser without the camera API (old iOS Safari) falls back the same way', async () => {
  Reflect.deleteProperty(navigator, 'mediaDevices')
  fakeApi(pantryRoutes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Scan barcode' }))
  expect(await screen.findByText('Type the barcode instead')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Type barcode' })).toHaveFocus())
})

it('Esc on the camera closes only the camera, not the Add sheet under it', async () => {
  getUserMedia.mockResolvedValue(stream)
  fakeApi(pantryRoutes())
  const onClose = vi.fn()
  renderWithProviders(<AddSheet open onClose={onClose} />)
  fireEvent.click(screen.getByRole('button', { name: 'Scan barcode' }))
  await screen.findByRole('dialog', { name: 'Scan barcode' })
  fireEvent.keyDown(document.activeElement ?? document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Scan barcode' })).not.toBeInTheDocument())
  expect(onClose).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog', { name: 'Add to pantry' })).toBeInTheDocument()
})
