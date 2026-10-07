import { afterEach, describe, expect, it, vi } from 'vitest'
import { enablePush, pushState, urlBase64ToUint8Array, type PushEnv } from './pushClient'

const unsubscribe = vi.fn(async () => true)
function env(over: Partial<PushEnv> & { sub?: PushSubscription | null } = {}): PushEnv {
  const subscribe = vi.fn(async () => ({ endpoint: 'https://web.push.apple.com/x', unsubscribe, toJSON: () => ({ endpoint: 'https://web.push.apple.com/x', keys: { p256dh: 'p', auth: 'a' } }) }))
  const registration = { pushManager: { getSubscription: vi.fn(async () => over.sub ?? null), subscribe } } as unknown as ServiceWorkerRegistration
  return {
    standalone: true,
    supported: true,
    permission: () => 'default',
    requestPermission: vi.fn(async () => 'granted' as NotificationPermission),
    registration: async () => registration,
    ...over,
  }
}

afterEach(() => { vi.restoreAllMocks(); unsubscribe.mockClear() })

describe('pushState', () => {
  it('names each state', async () => {
    expect(await pushState(env({ supported: false }))).toBe('unsupported')
    expect(await pushState(env({ standalone: false }))).toBe('not-installed')
    expect(await pushState(env({ permission: () => 'denied' }))).toBe('denied')
    expect(await pushState(env())).toBe('off')
    expect(await pushState(env({ permission: () => 'granted', sub: {} as PushSubscription }))).toBe('on')
  })
})

describe('enablePush', () => {
  it('asks permission, subscribes with the server key and posts it with the CSRF header', async () => {
    document.cookie = 'csrf_token=tok'
    const fetch = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ public_key: 'BEl6' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    const res = await enablePush(env())
    expect(res.response.ok).toBe(true)
    const [, post] = fetch.mock.calls
    expect(String(post[0])).toContain('/push/subscribe')
    expect((post[1] as RequestInit).headers).toMatchObject({ 'X-CSRF-Token': 'tok' })
    expect(JSON.parse((post[1] as RequestInit).body as string)).toEqual({ endpoint: 'https://web.push.apple.com/x', keys: { p256dh: 'p', auth: 'a' } })
  })

  it('a refused POST /push/subscribe drops the browser subscription again', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ public_key: 'BEl6' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'nope' }), { status: 400 }))
    const res = await enablePush(env())
    expect(res.response.status).toBe(400)
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })

  it('a network failure on POST /push/subscribe unsubscribes, then rethrows', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ public_key: 'BEl6' }), { status: 200 }))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(enablePush(env())).rejects.toThrow('Failed to fetch')
    expect(unsubscribe).toHaveBeenCalledTimes(1)
  })

  it('a successful subscribe keeps the browser subscription', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ public_key: 'BEl6' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    await enablePush(env())
    expect(unsubscribe).not.toHaveBeenCalled()
  })

  it('stops at a refused permission without calling the server', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    const res = await enablePush(env({ requestPermission: async () => 'denied' }))
    expect(res.response.status).toBe(403)
    expect(fetch).not.toHaveBeenCalled()
  })
})

it('decodes a VAPID key', () => {
  expect([...urlBase64ToUint8Array('AQID')]).toEqual([1, 2, 3])
})
