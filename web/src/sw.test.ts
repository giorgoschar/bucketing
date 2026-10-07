// Pins the /app/ worker's behaviour (Phase 1 + 2d push) by running src/sw.ts against fake
// service-worker globals and a mocked Workbox. Built-output checks live in scripts/check-sw.mjs.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const wb = vi.hoisted(() => ({
  precacheAndRoute: vi.fn(),
  cleanupOutdatedCaches: vi.fn(),
  createHandlerBoundToURL: vi.fn((url: string) => ({ boundTo: url })),
  registerRoute: vi.fn(),
  NavigationRoute: vi.fn(function (this: Record<string, unknown>, handler: unknown, opts: unknown) {
    this.handler = handler
    this.opts = opts
  }),
}))
vi.mock('workbox-precaching', () => ({
  precacheAndRoute: wb.precacheAndRoute, cleanupOutdatedCaches: wb.cleanupOutdatedCaches, createHandlerBoundToURL: wb.createHandlerBoundToURL,
}))
vi.mock('workbox-routing', () => ({ registerRoute: wb.registerRoute, NavigationRoute: wb.NavigationRoute }))

type Listener = (event: Record<string, unknown>) => void
const MANIFEST = [{ url: 'index.html', revision: 'abc' }]

function fakeScope() {
  const listeners = new Map<string, Listener[]>()
  const scope = {
    __WB_MANIFEST: MANIFEST,
    location: new URL('https://tameio.test/app/sw.js'),
    addEventListener: (type: string, fn: Listener) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    skipWaiting: vi.fn(async () => {}),
    registration: { showNotification: vi.fn(async () => {}) },
    clients: { matchAll: vi.fn(async () => [] as unknown[]), openWindow: vi.fn(async () => null), claim: vi.fn() },
  }
  const fire = async (type: string, event: Record<string, unknown>) => {
    const waits: Promise<unknown>[] = []
    for (const fn of listeners.get(type) ?? []) fn({ ...event, waitUntil: (p: Promise<unknown>) => waits.push(p) })
    await Promise.all(waits)
  }
  return { scope, listeners, fire }
}

let sw: ReturnType<typeof fakeScope>
beforeEach(async () => {
  vi.resetModules()
  Object.values(wb).forEach((f) => f.mockClear())
  sw = fakeScope()
  vi.stubGlobal('self', sw.scope)
  await import('./sw')
})
afterEach(() => { vi.unstubAllGlobals() })

describe('the /app/ service worker', () => {
  it('precaches the injected manifest and drops old caches', () => {
    expect(wb.precacheAndRoute).toHaveBeenCalledWith(MANIFEST)
    expect(wb.cleanupOutdatedCaches).toHaveBeenCalled()
  })

  it('answers navigations with /app/index.html except /app/auth/ and /api/', () => {
    expect(wb.createHandlerBoundToURL).toHaveBeenCalledWith('/app/index.html')
    const route = wb.registerRoute.mock.calls[0][0] as { opts: { denylist: RegExp[] } }
    const denied = (p: string) => route.opts.denylist.some((re) => re.test(p))
    expect(denied('/app/auth/link')).toBe(true)
    expect(denied('/api/v1/insights')).toBe(true)
    expect(denied('/app/plan')).toBe(false)
    expect(denied('/app/settings/profile')).toBe(false)
  })

  it('registers no runtime caching: the navigation route is the only route', () => {
    expect(wb.registerRoute).toHaveBeenCalledTimes(1)
    expect(wb.NavigationRoute).toHaveBeenCalledTimes(1)
  })

  it('waits for SKIP_WAITING: no skipWaiting on install, no clients.claim', async () => {
    expect(sw.listeners.has('install')).toBe(false)
    expect(sw.listeners.has('activate')).toBe(false)
    await sw.fire('message', { data: { type: 'OTHER' } })
    expect(sw.scope.skipWaiting).not.toHaveBeenCalled()
    await sw.fire('message', { data: { type: 'SKIP_WAITING' } })
    expect(sw.scope.skipWaiting).toHaveBeenCalledTimes(1)
    expect(sw.scope.clients.claim).not.toHaveBeenCalled()
  })

  it('shows a push as a notification that opens the mapped app route', async () => {
    await sw.fire('push', { data: { text: () => JSON.stringify({ title: 'Overdue: Rent', body: '€900', link: '/bills' }) } })
    expect(sw.scope.registration.showNotification).toHaveBeenCalledWith('Overdue: Rent',
      expect.objectContaining({ body: '€900', data: { url: '/app/plan' } }))
  })

  it('a click focuses an open app window and navigates it', async () => {
    const navigate = vi.fn(async () => null)
    const client = { url: 'https://tameio.test/app/', focus: vi.fn(async () => ({ navigate })) }
    sw.scope.clients.matchAll.mockResolvedValue([{ url: 'https://tameio.test/dashboard', focus: vi.fn() }, client])
    const close = vi.fn()
    await sw.fire('notificationclick', { notification: { close, data: { url: '/app/plan' } } })
    expect(close).toHaveBeenCalled()
    expect(navigate).toHaveBeenCalledWith('https://tameio.test/app/plan')
    expect(sw.scope.clients.openWindow).not.toHaveBeenCalled()
  })

  it('a click with no app window opens one, and never leaves the /app/ scope', async () => {
    await sw.fire('notificationclick', { notification: { close: vi.fn(), data: { url: 'https://evil.example/x' } } })
    expect(sw.scope.clients.openWindow).toHaveBeenCalledWith('https://tameio.test/app/')
  })
})
