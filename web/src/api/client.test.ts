import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, onUnauthorized } from './client'

afterEach(() => { vi.restoreAllMocks(); document.cookie = 'csrf_token=; max-age=0' })

describe('api client', () => {
  it('sends the CSRF cookie as a header on writes, same-origin credentials', async () => {
    document.cookie = 'csrf_token=abc.def'
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    await api.POST('/api/v1/notifications/read-all' as never, {} as never)
    const req = f.mock.calls[0][0] as Request
    expect(req.headers.get('X-CSRF-Token')).toBe('abc.def')
    expect(req.credentials).toBe('same-origin')
  })

  it('does not send the CSRF header on GET', async () => {
    document.cookie = 'csrf_token=abc.def'
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200 }))
    await api.GET('/api/v1/auth/me')
    expect((f.mock.calls[0][0] as Request).headers.get('X-CSRF-Token')).toBeNull()
  })

  it('emits unauthorized on 401', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 401 }))
    const cb = vi.fn()
    const off = onUnauthorized(cb)
    await api.GET('/api/v1/auth/me')
    off()
    expect(cb).toHaveBeenCalledOnce()
  })
})
