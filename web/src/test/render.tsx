import { cleanup, render, type RenderResult } from '@testing-library/react'
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement, ReactNode } from 'react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { clearPending } from '../data/pending'
import { wipe } from '../offline/db'
import { cancelKick } from '../offline/queue'
import { setIdentity, type Identity } from '../offline/identity'
import { dismissToast, Toaster } from '../ui/Toast'

export const TEST_IDENTITY: Identity = { user_id: 'u1', household_id: 'h1' }

/** No retries (a failure shows at once), nothing garbage-collected mid-test, offline-first like the app. */
export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: 30_000, networkMode: 'offlineFirst' },
      mutations: { retry: false },
    },
  })
}

export function Providers({ client, children }: { client: QueryClient; children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

export type Rendered = RenderResult & { client: QueryClient; router: ReturnType<typeof createMemoryRouter> }

/**
 * Renders `ui` at `route` inside a fresh query client, a memory router (every path renders `ui`, so links
 * only change router.state.location) and the Toaster, signed in as TEST_IDENTITY.
 */
export function renderWithProviders(ui: ReactElement, opts: { route?: string; client?: QueryClient } = {}): Rendered {
  setIdentity(TEST_IDENTITY)
  const client = opts.client ?? testQueryClient()
  const router = createMemoryRouter([{ path: '*', element: <>{ui}<Toaster /></> }], {
    initialEntries: [opts.route ?? '/'],
  })
  const result = render(<Providers client={client}><RouterProvider router={router} /></Providers>)
  return { ...result, client, router }
}

/** Flip the online state for useOnline(), useAction and TanStack's onlineManager together. */
export function setOnline(online: boolean): void {
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => online })
  onlineManager.setOnline(online)
  window.dispatchEvent(new Event(online ? 'online' : 'offline'))
}

/** afterEach: unmount, restore spies and timers, back online, and clear toasts, pending ids, identity and the store. */
export async function resetTestEnv(): Promise<void> {
  cleanup()
  vi.restoreAllMocks()
  vi.useRealTimers()
  cancelKick()
  Reflect.deleteProperty(navigator, 'onLine') // falls back to Navigator.prototype.onLine
  onlineManager.setOnline(true)
  dismissToast()
  clearPending()
  setIdentity(null)
  await wipe()
}
