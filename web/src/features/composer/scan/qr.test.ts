import { afterEach, expect, it, vi } from 'vitest'

const scanner = vi.hoisted(() => ({ start: vi.fn(async () => {}), stop: vi.fn(), destroy: vi.fn(), cb: null as null | ((r: { data: string }) => void) }))
vi.mock('qr-scanner', () => ({
  default: class {
    constructor(_video: HTMLVideoElement, cb: (r: { data: string }) => void) { scanner.cb = cb }
    start = scanner.start
    stop = scanner.stop
    destroy = scanner.destroy
  },
}))

import { isReceiptUrl, startQr } from './qr'

afterEach(() => vi.clearAllMocks())

it('only https URLs count as receipt QRs', () => {
  expect(isReceiptUrl(' https://www1.aade.gr/tameiakes/myweb/q1.php?SIG=x ')).toBe(true)
  expect(isReceiptUrl('http://www1.aade.gr/x')).toBe(false)
  expect(isReceiptUrl('WIFI:S:home;P:secret;;')).toBe(false)
})

it('decodes continuously and stops cleanly', async () => {
  const onDecode = vi.fn()
  const session = await startQr(document.createElement('video'), onDecode)
  scanner.cb!({ data: 'https://example.gr/r' })
  expect(onDecode).toHaveBeenCalledWith('https://example.gr/r')
  session.stop()
  expect(scanner.stop).toHaveBeenCalled()
  expect(scanner.destroy).toHaveBeenCalled()
})

it('a denied camera rejects and releases the scanner', async () => {
  scanner.start.mockRejectedValueOnce(new Error('NotAllowedError'))
  await expect(startQr(document.createElement('video'), () => {})).rejects.toThrow('NotAllowedError')
  expect(scanner.destroy).toHaveBeenCalled()
})
