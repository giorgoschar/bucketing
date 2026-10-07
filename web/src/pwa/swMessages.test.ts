import { describe, expect, it, vi } from 'vitest'
import { listenForSwNavigation, routerPathFromSwMessage } from './swMessages'

describe('routerPathFromSwMessage', () => {
  it('turns a worker navigate message into a router path under /app', () => {
    expect(routerPathFromSwMessage({ type: 'navigate', url: '/app/plan' })).toBe('/plan')
    expect(routerPathFromSwMessage({ type: 'navigate', url: '/app/' })).toBe('/')
    expect(routerPathFromSwMessage({ type: 'navigate', url: '/app/settings?x=1' })).toBe('/settings?x=1')
  })
  it('ignores anything else, and never leaves /app/', () => {
    expect(routerPathFromSwMessage({ type: 'other', url: '/app/plan' })).toBeNull()
    expect(routerPathFromSwMessage({ type: 'navigate', url: 'https://evil.example/app/plan' })).toBeNull()
    expect(routerPathFromSwMessage({ type: 'navigate', url: '//evil.example/app/' })).toBeNull()
    expect(routerPathFromSwMessage({ type: 'navigate', url: '/dashboard' })).toBeNull()
    expect(routerPathFromSwMessage(null)).toBeNull()
  })
})

describe('listenForSwNavigation', () => {
  it('navigates with the router on a navigate message', () => {
    const target = new EventTarget()
    const navigate = vi.fn()
    const stop = listenForSwNavigation(target, navigate)
    target.dispatchEvent(new MessageEvent('message', { data: { type: 'navigate', url: '/app/activity' } }))
    target.dispatchEvent(new MessageEvent('message', { data: { type: 'SKIP_WAITING' } }))
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith('/activity')
    stop()
    target.dispatchEvent(new MessageEvent('message', { data: { type: 'navigate', url: '/app/plan' } }))
    expect(navigate).toHaveBeenCalledTimes(1)
  })
})
