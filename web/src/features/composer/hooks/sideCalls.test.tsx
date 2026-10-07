import { act, renderHook } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../../../test/render'
import { goOffline, loose } from '../testHelpers'
import { useDuplicateCheck } from './useDuplicateCheck'
import { useReceiptUpload } from './useReceiptUpload'

afterEach(resetTestEnv)

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={testQueryClient()}>{children}</QueryClientProvider>
)
const DUP = { id: 't7', amount: 3, currency: 'EUR', date: '2026-10-06', notes: null, merchant: 'Coffee Island', bucket: 'Day to day', paid_by: 'Maria', same_bucket: true }
const Q = { amount: '3.00', transaction_date: '2026-10-07', bucket_id: 'b-day' }

it('duplicate check returns the server matches and sends the query', async () => {
  const api = fakeApi(loose({ 'GET /api/v1/transactions/check-duplicate': { duplicates: [DUP] } }))
  const { result } = renderHook(() => useDuplicateCheck(), { wrapper })
  expect(await result.current(Q)).toEqual([DUP])
  expect(Object.fromEntries(api.calls[0].query)).toEqual({ amount: '3.00', transaction_date: '2026-10-07', bucket_id: 'b-day' })
})

it('duplicate check gives up after 2 seconds, and ignores errors and offline', async () => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  fakeApi(loose({ 'GET /api/v1/transactions/check-duplicate': () => new Promise<Response>(() => {}) }))
  const { result } = renderHook(() => useDuplicateCheck(), { wrapper })
  const p = result.current(Q)
  await vi.advanceTimersByTimeAsync(2000)
  expect(await p).toEqual([])
  vi.useRealTimers()
  vi.restoreAllMocks()
  fakeApi(loose({ 'GET /api/v1/transactions/check-duplicate': () => new Response('boom', { status: 500 }) }))
  expect(await result.current(Q)).toEqual([])
  vi.restoreAllMocks()
  goOffline()
  expect(await result.current(Q)).toEqual([])
})

it('receipt upload posts the file as multipart and reports failures', async () => {
  let status = 200
  const api = fakeApi(loose({
    'POST /api/v1/transactions/{txn_id}/receipt': () =>
      status === 200 ? Response.json({ receipt_path: 'x.jpg' }) : Response.json({ detail: 'File too large (max 10 MB)' }, { status }),
  }))
  const { result } = renderHook(() => useReceiptUpload(), { wrapper })
  const file = new File(['img'], 'r.jpg', { type: 'image/jpeg' })
  let r!: string
  await act(async () => { r = await result.current('t1', file) })
  expect(r).toBe('ok')
  expect(api.calls[0].path).toBe('/api/v1/transactions/t1/receipt')
  expect((api.calls[0].body as FormData).get('file')).toBeInstanceOf(File)
  status = 413
  await act(async () => { r = await result.current('t1', file) })
  expect(r).toBe('failed')
})
