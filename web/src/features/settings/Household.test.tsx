import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const { toast, me } = vi.hoisted(() => ({ toast: vi.fn(), me: { current: 'me' } }))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: me.current, household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({
  useHousehold: () => query({ id: 'hh1', name: 'Home', default_currency: 'EUR', members: [
    { user_id: 'me', role: 'owner', display_name: 'Giorgos', username: 'g', avatar_color: null },
    { user_id: 'm', role: 'member', display_name: 'Maria', username: 'maria', avatar_color: null },
  ] }),
}))

import { Household } from './Household'

const renderIt = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Household /></MemoryRouter></QueryClientProvider>)
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); me.current = 'me' })

describe('Household', () => {
  it('owner: members with you and roles, currency fixed, remove with confirm', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))
    renderIt()
    expect(screen.getByText('Giorgos (you)')).toBeInTheDocument()
    expect(screen.getByText('EUR · Fixed')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Maria' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove from household' }))
    fireEvent.click(screen.getByRole('button', { name: 'Remove Maria' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect([req.method, new URL(req.url).pathname]).toEqual(['DELETE', '/api/v1/settings/household/members/m'])
  })

  it('owner: renames with the currency unchanged', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 'hh1', name: 'Casa', default_currency: 'EUR' }), { status: 200 }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Edit name' }))
    fireEvent.change(screen.getByLabelText('Household name'), { target: { value: ' Casa ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect(req.method).toBe('PUT')
    expect(await req.json()).toEqual({ name: 'Casa', default_currency: 'EUR' })
  })

  it('owner: a new invite link is shown once', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ token: 'tok123', expires_at: '2026-10-14T00:00:00' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'New link' }))
    expect(await screen.findByText(`${location.origin}/join/tok123`)).toBeInTheDocument()
    expect(screen.getByText('Expires in 7 days · single use')).toBeInTheDocument()
  })

  it('invite 429 says to wait', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 429 }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'New link' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Too many links, wait a minute.', { tone: 'error' }))
  })

  it('a member sees no edit, menu or invite', () => {
    me.current = 'm'
    renderIt()
    expect(screen.queryByRole('button', { name: /Actions for/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'New link' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Edit name' })).toBeNull()
  })
})
