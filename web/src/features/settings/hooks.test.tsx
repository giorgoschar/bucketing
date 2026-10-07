import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { db } from '../../offline/db'
import { fakeApi } from '../../test/fakeApi'
import { Providers, resetTestEnv, testQueryClient } from '../../test/render'

vi.mock('../../session/SessionProvider', () => ({
  useSession: () => ({ status: 'signedIn', me: { id: 'u1', household_id: 'h1' } }),
}))

import { useProfile, useSecurity } from './hooks'

const SECURITY = { totp_enabled: true, backup_codes_remaining: 7, passkey_available: true, passkey_linked: false, password_session: true }
const wrapper = ({ children }: { children: ReactNode }) => <Providers client={testQueryClient()}>{children}</Providers>

afterEach(resetTestEnv)

it('reads the security status without writing it to the device cache', async () => {
  fakeApi({
    'GET /api/v1/settings/security': () => SECURITY,
    'GET /api/v1/settings/profile': () => ({ id: 'u1', username: 'g', display_name: 'G' }) as never,
  })
  const sec = renderHook(() => useSecurity(), { wrapper })
  await waitFor(() => expect(sec.result.current.data).toEqual(SECURITY))
  // A cached read in the same test does reach the store, so the store is live.
  const prof = renderHook(() => useProfile(), { wrapper })
  await waitFor(() => expect(prof.result.current.data).toBeDefined())
  await waitFor(async () => expect(await db.cache.count()).toBe(1))
  expect(sec.result.current.fromCache).toBe(false)
})
