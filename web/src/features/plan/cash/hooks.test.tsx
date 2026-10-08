import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { onUnauthorized } from '../../../api/client'
import { fakeApi, reply } from '../../../test/fakeApi'
import { Providers, resetTestEnv, testQueryClient } from '../../../test/render'
import { useCashWallets, useCashWrite } from './hooks'

afterEach(resetTestEnv)

const wrapper = ({ children }: { children: ReactNode }) => <Providers client={testQueryClient()}>{children}</Providers>

// Both calls go through the typed client, so an expired session reaches the 401 listener (sign-out).
it('a 401 on GET /cash/wallets reaches the unauthorized listener', async () => {
  const fake = fakeApi({ 'GET /api/v1/cash/wallets': () => reply(401, { detail: 'Not signed in.' }) })
  const cb = vi.fn()
  const off = onUnauthorized(cb)
  renderHook(() => useCashWallets('2026-10'), { wrapper })
  await waitFor(() => expect(cb).toHaveBeenCalled())
  off()
  expect(fake.callsTo('GET /api/v1/cash/wallets')[0].query.get('month')).toBe('2026-10')
})

it('a 401 on a stash_count POST reaches the unauthorized listener', async () => {
  const fake = fakeApi({ 'POST /api/v1/cash/movements': () => reply(401, { detail: 'Not signed in.' }) })
  const cb = vi.fn()
  const off = onUnauthorized(cb)
  const { result } = renderHook(() => useCashWrite(), { wrapper })
  await result.current.run({ kind: 'stash_count', amount: '120.00' })
  off()
  expect(cb).toHaveBeenCalledOnce()
  expect(fake.callsTo('POST /api/v1/cash/movements')[0].body).toEqual({ kind: 'stash_count', amount: '120.00' })
})
