import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HOLD_MS, _resetHeldForTests, holdDelete, undoDelete } from './heldDeletes'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  _resetHeldForTests()
  vi.useRealTimers()
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
})

describe('held deletes', () => {
  it('Undo sends nothing', () => {
    const send = vi.fn()
    holdDelete('a', send)
    vi.advanceTimersByTime(HOLD_MS - 1)
    expect(undoDelete('a')).toBe(true)
    vi.advanceTimersByTime(HOLD_MS * 2)
    expect(send).not.toHaveBeenCalled()
  })

  it('sends the DELETE when the 5 s toast ends', () => {
    const send = vi.fn()
    holdDelete('a', send)
    vi.advanceTimersByTime(HOLD_MS)
    expect(send).toHaveBeenCalledOnce()
  })

  it('sends at once when the page is hidden', () => {
    const send = vi.fn()
    holdDelete('a', send)
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(send).toHaveBeenCalledOnce()
    const other = vi.fn()
    holdDelete('b', other)
    window.dispatchEvent(new Event('pagehide'))
    expect(other).toHaveBeenCalledOnce()
  })
})
