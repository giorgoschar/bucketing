import { describe, expect, it, vi } from 'vitest'
import { INITIAL_WINDOW_MS, UPDATE_CHECK_INTERVAL_MS, setupPwaUpdates } from './update'

function setup() {
  let t = 1_000_000
  const updateSW = vi.fn().mockResolvedValue(undefined)
  const registration = { update: vi.fn().mockResolvedValue(undefined) }
  let cbs: { onNeedRefresh: () => void; onRegisteredSW: (u: string, r: unknown) => void }
  const listeners: Array<() => void> = []
  const doc = {
    visibilityState: 'visible' as DocumentVisibilityState,
    addEventListener: (_: string, fn: () => void) => void listeners.push(fn),
  }
  setupPwaUpdates({
    register: (c) => {
      cbs = c as typeof cbs
      return updateSW
    },
    doc: doc as unknown as Document,
    now: () => t,
  })
  cbs!.onRegisteredSW('/app/sw.js', registration)
  return {
    updateSW, registration, cbs: cbs!,
    advance: (ms: number) => { t += ms },
    setVis(v: DocumentVisibilityState) { doc.visibilityState = v; listeners.forEach((l) => l()) },
  }
}

describe('setupPwaUpdates', () => {
  it('applies an update that arrives in the initial window', () => {
    const s = setup()
    s.advance(INITIAL_WINDOW_MS - 1)
    s.cbs.onNeedRefresh()
    expect(s.updateSW).toHaveBeenCalledOnce()
    expect(s.updateSW).toHaveBeenCalledWith(true)
  })
  it('does not apply a late update while visible', () => {
    const s = setup()
    s.advance(INITIAL_WINDOW_MS + 1)
    s.cbs.onNeedRefresh()
    expect(s.updateSW).not.toHaveBeenCalled()
  })
  it('applies a waiting update once when the app is hidden', () => {
    const s = setup()
    s.advance(INITIAL_WINDOW_MS + 1)
    s.cbs.onNeedRefresh()
    s.setVis('hidden')
    s.setVis('visible')
    s.setVis('hidden')
    expect(s.updateSW).toHaveBeenCalledOnce()
    expect(s.updateSW).toHaveBeenCalledWith(true)
  })
  it('does nothing on hidden when no update is waiting', () => {
    const s = setup()
    s.setVis('hidden')
    expect(s.updateSW).not.toHaveBeenCalled()
  })
  it('throttles registration.update() to once per 30 minutes', () => {
    const s = setup()
    s.setVis('visible')
    expect(s.registration.update).not.toHaveBeenCalled()
    s.advance(UPDATE_CHECK_INTERVAL_MS)
    s.setVis('visible')
    expect(s.registration.update).toHaveBeenCalledOnce()
    s.advance(60_000)
    s.setVis('visible')
    expect(s.registration.update).toHaveBeenCalledOnce()
    s.advance(UPDATE_CHECK_INTERVAL_MS)
    s.setVis('visible')
    expect(s.registration.update).toHaveBeenCalledTimes(2)
  })
})
