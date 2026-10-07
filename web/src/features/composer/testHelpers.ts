import { vi } from 'vitest'
import type { FakeApi, FakeCall, Routes } from '../../test/fakeApi'
import { setOnline } from '../../test/render'

/**
 * Composer tests describe routes as plain values or handlers. Plain values become handlers; concrete
 * paths ("GET /api/v1/transactions/t9") match literally; paths not yet in the schema (2d's rules) are fine.
 */
export function loose(routes: Record<string, unknown>): Routes {
  return Object.fromEntries(Object.entries(routes).map(([k, v]) => [k, typeof v === 'function' ? v : () => v])) as Routes
}

/** The writes a test made, in order. */
export const writes = (api: FakeApi): FakeCall[] =>
  api.calls.filter((c) => c.method !== 'GET' && c.path !== '/api/v1/auth/me')

/** No connection: navigator.onLine false and every request fails at the network level. */
export function goOffline(): void {
  setOnline(false)
  vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
}
