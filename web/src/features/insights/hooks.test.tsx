import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { Providers, resetTestEnv, testQueryClient } from '../../test/render'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }),
}))

import { useInsights, usePersonShare } from './hooks'
import { NO_FILTERS } from './types'

const client = testQueryClient()
const wrapper = ({ children }: { children: ReactNode }) => <Providers client={client}>{children}</Providers>

afterEach(async () => {
  client.clear()
  await resetTestEnv()
})

describe('insights hooks', () => {
  it('sends the period, lens and filters', async () => {
    const fake = fakeApi({ 'GET /api/v1/insights': () => ({ total_spent: 1 }) })
    const { result } = renderHook(
      () => useInsights({ preset: 'custom', from: '2026-09-01', to: '2026-09-30' }, 'm', { bucketIds: ['b1'], categoryIds: [] }),
      { wrapper },
    )
    await waitFor(() => expect(result.current.data).toBeDefined())
    const [call] = fake.callsTo('GET /api/v1/insights')
    expect(Object.fromEntries(call.query)).toEqual({
      preset: 'custom', start_date: '2026-09-01', end_date: '2026-09-30', paid_by: 'm', bucket_ids: 'b1',
    })
  })

  it('sends no lens or filter params for the Household lens without filters', async () => {
    const fake = fakeApi({ 'GET /api/v1/insights': () => ({ total_spent: 1 }) })
    const { result } = renderHook(() => useInsights({ preset: 'this_month' }, 'household', NO_FILTERS), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(Object.fromEntries(fake.callsTo('GET /api/v1/insights')[0].query)).toEqual({ preset: 'this_month' })
  })

  it('does not call /insights/person for the Household lens', async () => {
    const fake = fakeApi()
    const { result } = renderHook(() => usePersonShare({ preset: 'this_month' }, null), { wrapper })
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current.data).toBeUndefined()
    expect(fake.calls).toHaveLength(0)
  })
})
