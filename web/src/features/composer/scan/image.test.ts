import { afterEach, expect, it, vi } from 'vitest'
import { fitWithin, jpegName, shrinkImage } from './image'

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('fits the longest side within 2000 px, never enlarging', () => {
  expect(fitWithin(4000, 3000)).toEqual({ w: 2000, h: 1500 })
  expect(fitWithin(1500, 3000)).toEqual({ w: 1000, h: 2000 })
  expect(fitWithin(800, 600)).toEqual({ w: 800, h: 600 })
})

it('names the result .jpg', () => {
  expect(jpegName('IMG_0001.HEIC')).toBe('IMG_0001.jpg')
  expect(jpegName('.png')).toBe('receipt.jpg')
})

it('re-encodes as JPEG 0.85 at the fitted size', async () => {
  const close = vi.fn()
  vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 4000, height: 3000, close })))
  const drawImage = vi.fn()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D)
  const toBlob = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (cb) {
    cb(new Blob(['jpeg'], { type: 'image/jpeg' }))
  })
  const out = await shrinkImage(new File(['big'], 'IMG_0001.HEIC', { type: 'image/heic' }))
  expect(out.name).toBe('IMG_0001.jpg')
  expect(out.type).toBe('image/jpeg')
  expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 2000, 1500)
  expect(toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/jpeg', 0.85)
  expect(close).toHaveBeenCalled()
})

it('falls back to the original file when it cannot decode', async () => {
  vi.stubGlobal('createImageBitmap', vi.fn(async () => { throw new Error('decode') }))
  const f = new File(['x'], 'r.heic')
  expect(await shrinkImage(f)).toBe(f)
})
