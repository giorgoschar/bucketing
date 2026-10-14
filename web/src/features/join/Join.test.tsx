import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { toast, changed } = vi.hoisted(() => ({ toast: vi.fn(), changed: vi.fn() }))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/householdChange', () => ({ afterHouseholdChange: changed }))

import { db } from '../../offline/db'
import { Join } from './Join'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const renderIt = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/join/tok1']}><Routes><Route path="/join/:token" element={<Join />} /></Routes></MemoryRouter>
  </QueryClientProvider>,
)
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); changed.mockClear() })

describe('Join', () => {
  it('shows who invited you to which household, and joins on tap', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const req = input as Request
      return req.method === 'POST' ? json({ household_id: 'h2', household_name: 'Casa' }) : json({ household_name: 'Casa', inviter: 'Maria' })
    })
    renderIt()
    expect(await screen.findByText(/Maria invited you to join/)).toBeInTheDocument()
    expect(screen.getByText('Casa')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Join Casa' }))
    await waitFor(() => expect(changed).toHaveBeenCalled())
    const post = fetch.mock.calls.map((c) => c[0] as Request).find((r) => r.method === 'POST')!
    expect(new URL(post.url).pathname).toBe('/api/v1/invites/tok1/accept')
  })

  it('an expired link says so', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ detail: 'This invite link has expired.' }, 410))
    renderIt()
    expect(await screen.findByText('This invite link has expired.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Join/ })).toBeNull()
  })

  it('an unknown or used link is invalid', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ detail: 'This invite link is not valid.' }, 404))
    renderIt()
    expect(await screen.findByText('This invite link is not valid.')).toBeInTheDocument()
  })

  it('a refused join keeps the screen and toasts the reason', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) =>
      (input as Request).method === 'POST' ? json({ detail: 'You are already in this household.' }, 409) : json({ household_name: 'Casa', inviter: null }))
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Join Casa' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('You are already in this household.', { tone: 'error' }))
    expect(changed).not.toHaveBeenCalled()
  })

  it('does not join while offline writes wait: the join would wipe them', async () => {
    await db.queue.add({ createdAt: 1, attempts: 0, nextAttemptAt: 0, status: 'pending', iv: new Uint8Array(12), data: new ArrayBuffer(1) })
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ household_name: 'Casa', inviter: null }))
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Join Casa' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('You have 1 change waiting to sync. Go online and let them sync first.', { tone: 'error' }))
    expect(fetch.mock.calls.some((c) => (c[0] as Request).method === 'POST')).toBe(false)
    await db.queue.clear()
  })
})
