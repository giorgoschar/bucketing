import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import type { Session } from '../session/SessionProvider'
import { offerTickedPrompt, resetTickedPrompt } from '../features/plan/pantry/tickedOffer'
import { fakeApi } from '../test/fakeApi'
import { resetTestEnv, testQueryClient } from '../test/render'
import { AppShell } from './AppShell'

vi.mock('../offline/queue', async (orig) => ({ ...(await orig<typeof import('../offline/queue')>()), startReplayTriggers: () => () => {} }))
const session: Session = {
  status: 'signedIn', signOut: async () => {}, logoutFailed: false, retryLogout: async () => {},
  me: { id: 'u1', username: 'g', household_id: 'h1', display_name: 'G', email: null, avatar_color: null },
}
vi.mock('../session/SessionProvider', () => ({ useSession: () => session }))

afterEach(async () => {
  resetTickedPrompt()
  await resetTestEnv()
})

// Pantry spec §4.6: the composer leaves before the summary answers; AppShell is where the offer shows.
it('AppShell shows the post-save pantry offer', async () => {
  fakeApi({ 'GET /api/v1/stock/summary': () => ({ low_count: 1, ticked_count: 3 }) })
  const client = testQueryClient()
  const router = createMemoryRouter(
    [{ path: '/', element: <AppShell />, children: [{ index: true, element: <p>home screen</p> }] }],
  )
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>)
  expect(screen.queryByRole('dialog')).toBeNull()
  await act(() => offerTickedPrompt(client))
  expect(await screen.findByRole('dialog', { name: '3 ticked pantry items' })).toBeInTheDocument()
})
