import { act, renderHook, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { resetTestEnv, setOnline, testQueryClient } from '../test/render'
import { Toaster } from '../ui/Toast'
import { OFFLINE_MESSAGE, RATE_MESSAGE, runOnline, useOnlineAction } from './onlineAction'

afterEach(resetTestEnv)

const res = (status: number, data?: unknown, error?: unknown) =>
  Promise.resolve({ data, error, response: new Response(null, { status }) })

describe('runOnline', () => {
  it('sends nothing while offline', async () => {
    const call = vi.fn(() => res(200, {}))
    const out = await runOnline(call, () => false)
    expect(call).not.toHaveBeenCalled()
    expect(out).toEqual({ ok: false, status: null, kind: 'offline', message: OFFLINE_MESSAGE })
  })
  it('treats a network failure and a 5xx as offline', async () => {
    expect(await runOnline(() => Promise.reject(new TypeError('Failed to fetch')), () => true)).toMatchObject({ message: OFFLINE_MESSAGE })
    expect(await runOnline(() => res(502), () => true)).toMatchObject({ message: OFFLINE_MESSAGE })
  })
  it('maps 429 and passes the server detail for 4xx', async () => {
    expect(await runOnline(() => res(429), () => true)).toMatchObject({ message: RATE_MESSAGE })
    const out = await runOnline(() => res(409, undefined, { detail: 'Email already registered to another account' }), () => true)
    expect(out).toMatchObject({ ok: false, status: 409, kind: 'rejected', message: 'Email already registered to another account' })
  })
  it('leaves 401 to the session', async () => {
    expect(await runOnline(() => res(401), () => true)).toMatchObject({ ok: false, kind: 'auth' })
  })
  it('returns data on success', async () => {
    expect(await runOnline(() => res(201, { id: 'x' }), () => true)).toEqual({ ok: true, status: 201, data: { id: 'x' } })
  })
})

describe('useOnlineAction', () => {
  const client = testQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}<Toaster /></QueryClientProvider>
  )

  it('toasts a failure as an alert and changes nothing', async () => {
    setOnline(false)
    const call = vi.fn(() => res(200, {}))
    const { result } = renderHook(() => useOnlineAction(), { wrapper })
    let out: Awaited<ReturnType<ReturnType<typeof useOnlineAction>>> | undefined
    await act(async () => { out = await result.current(call) })
    expect(out?.ok).toBe(false)
    expect(call).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(OFFLINE_MESSAGE)
  })

  it('invalidates the given keys and shows the success text', async () => {
    const spy = vi.spyOn(client, 'invalidateQueries')
    const { result } = renderHook(() => useOnlineAction(), { wrapper })
    await act(async () => { await result.current(() => res(200, { ok: true }), { invalidates: [['settings']], success: 'Saved' }) })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['settings'] })
    expect(screen.getByRole('status')).toHaveTextContent('Saved')
  })

  it('stays quiet on 401', async () => {
    const { result } = renderHook(() => useOnlineAction(), { wrapper })
    await act(async () => { await result.current(() => res(401)) })
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
