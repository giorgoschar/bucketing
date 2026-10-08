import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../../test/fakeApi'
import { pantryRoutes } from '../../../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../../../test/render'

const det = vi.hoisted(() => ({
  codes: [] as string[], made: 0, dead: false, wasm: null as null | string, overrides: [] as object[], loadFails: false,
  eager: [] as (boolean | undefined)[],
}))
vi.mock('barcode-detector/ponyfill', () => ({
  prepareZXingModule: async (o: { overrides: { locateFile: (p: string, prefix: string) => string }; fireImmediately?: boolean }) => {
    det.overrides.push(o.overrides)
    det.eager.push(o.fireImmediately)
    det.wasm = o.overrides.locateFile('zxing_reader.wasm', 'https://fastly.jsdelivr.net/npm/zxing-wasm/dist/reader/')
    if (det.loadFails) throw new Error('failed to asynchronously prepare wasm')
    return {}
  },
  BarcodeDetector: class {
    constructor() { det.made += 1 }
    async detect() {
      if (det.dead) throw new DOMException('Barcode detection service unavailable.', 'NotSupportedError')
      return det.codes.map((rawValue) => ({ rawValue, format: 'ean_13' }))
    }
  },
}))

import { AddSheet } from '../AddSheet'
import { makeDetector } from './detector'
import { Scanner } from './Scanner'

const track = { stop: vi.fn() }
const stream = { getTracks: () => [track] } as unknown as MediaStream
const getUserMedia = vi.fn<(c: MediaStreamConstraints) => Promise<MediaStream>>()

beforeEach(() => {
  det.codes = []
  det.made = 0
  det.overrides = []
  det.eager = []
  det.loadFails = false
  det.dead = false
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

it.each([
  ['Close', () => fireEvent.click(screen.getByRole('button', { name: 'Close' }))],
  ['Esc', () => fireEvent.keyDown(document, { key: 'Escape' })],
])('%s leaves and stops the camera at once (still mounted)', async (_how, leave) => {
  getUserMedia.mockResolvedValue(stream)
  const onClose = vi.fn()
  render(<Scanner onDetect={() => {}} onUnavailable={() => {}} onClose={onClose} />)
  const dialog = screen.getByRole('dialog', { name: 'Scan barcode' })
  expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
  expect(dialog).toHaveTextContent('Hold the barcode inside the box')
  // The camera is live and reading.
  await waitFor(() => expect(det.made).toBe(1))
  expect(track.stop).not.toHaveBeenCalled()
  leave()
  expect(onClose).toHaveBeenCalledTimes(1)
  // Not unmounted: the Scanner itself stops the stream on the way out.
  expect(screen.getByRole('dialog', { name: 'Scan barcode' })).toBeInTheDocument()
  expect(track.stop).toHaveBeenCalledTimes(1)
})

it('Close before the camera answers: the stream is stopped as soon as it arrives', async () => {
  let give: (s: MediaStream) => void = () => {}
  getUserMedia.mockReturnValue(new Promise<MediaStream>((r) => { give = r }))
  render(<Scanner onDetect={() => {}} onUnavailable={() => {}} onClose={() => {}} />)
  await waitFor(() => expect(getUserMedia).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  await act(async () => { give(stream) })
  expect(track.stop).toHaveBeenCalledTimes(1)
  expect(det.made).toBe(0)
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

it('a decoder that fails to load stops the camera and falls back to the typed barcode', async () => {
  getUserMedia.mockResolvedValue(stream)
  det.loadFails = true
  fakeApi(pantryRoutes())
  renderWithProviders(<AddSheet open onClose={() => {}} />)
  fireEvent.click(screen.getByRole('button', { name: 'Scan barcode' }))
  expect(await screen.findByText('Type the barcode instead')).toBeInTheDocument()
  expect(screen.queryByRole('dialog', { name: 'Scan barcode' })).not.toBeInTheDocument()
  expect(track.stop).toHaveBeenCalled()
  expect(det.made).toBe(0)
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Type barcode' })).toHaveFocus())
})

it('the decoder is loaded up front, and every Scan reuses the same module settings (no re-instantiation)', async () => {
  await makeDetector()
  await makeDetector()
  expect(det.eager).toEqual([true, true])
  expect(det.overrides).toHaveLength(2)
  expect(det.overrides[0]).toBe(det.overrides[1])
})

it('a decoder that dies mid-scan (NotSupportedError) stops the camera and falls back', async () => {
  getUserMedia.mockResolvedValue(stream)
  det.dead = true
  const onUnavailable = vi.fn()
  render(<Scanner onDetect={() => {}} onUnavailable={onUnavailable} onClose={() => {}} />)
  await waitFor(() => expect(onUnavailable).toHaveBeenCalledTimes(1))
  expect(track.stop).toHaveBeenCalled()
})
