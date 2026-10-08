import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../../test/storage'
import { query } from '../insights/fixtures'

const toast = vi.hoisted(() => vi.fn())
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({
  useTokens: () => query([{ id: 't1', name: 'iPhone', prefix: 'pat_ab12', scopes: ['ingest'], default_bucket_id: 'b1', last_used_at: new Date(Date.now() - 2 * 3600_000).toISOString(), created_at: null }]),
  useBuckets: () => query([{ id: 'b1', name: 'Daily' }]),
}))

import { Automations } from './Automations'
import { lastUsed } from './tokenHooks'

installMemoryStorage()
let qc: QueryClient
function Loc() { return <p data-testid="loc">{useLocation().search}{useLocation().hash}</p> }
const renderIt = () => { qc = new QueryClient(); return render(<QueryClientProvider client={qc}><MemoryRouter><Automations /><Loc /></MemoryRouter></QueryClientProvider>) }
afterEach(() => { vi.restoreAllMocks(); toast.mockClear() })

describe('Automations', () => {
  it('lists tokens with prefix, bucket and last use, in setup order', () => {
    renderIt()
    expect(screen.getByText('iPhone')).toBeInTheDocument()
    expect(screen.getByText(/pat_ab12 · Daily · Last used 2h ago/)).toBeInTheDocument()
    expect(screen.getByText('Purchases arrive tagged Apple Pay with no payer. You pick who paid from Home.')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem', { name: /^Step/ })).toHaveLength(3)
  })

  it('shows a new token once and never caches or stores it', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 't2', name: 'Watch', prefix: 'pat_cd34', scopes: ['ingest'], default_bucket_id: null, last_used_at: null, created_at: null, token: 'pat_cd34SECRETSECRET' }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'Watch' } })
    fireEvent.change(screen.getByLabelText('Default budget'), { target: { value: 'b1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create token' }))
    const card = await screen.findByRole('alert')
    expect(within(card).getByText('pat_cd34SECRETSECRET')).toBeInTheDocument()
    expect(await (fetch.mock.calls[0][0] as Request).json()).toEqual({ name: 'Watch', default_bucket_id: 'b1' })
    expect(JSON.stringify(qc.getQueryCache().getAll().map((q) => q.state.data))).not.toContain('SECRET')
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('SECRET')
    expect(screen.getByTestId('loc').textContent).not.toContain('SECRET')
  })

  it('validates the name length before sending', () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'x'.repeat(61) } })
    fireEvent.click(screen.getByRole('button', { name: 'Create token' }))
    expect(screen.getByText('Use 1 to 60 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('revoke asks first', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Revoke iPhone' }))
    fireEvent.click(screen.getByRole('button', { name: 'Revoke token' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect((fetch.mock.calls[0][0] as Request).method).toBe('DELETE')
  })

  it('formats last use', () => {
    const now = Date.parse('2026-10-07T12:00:00Z')
    expect(lastUsed(null, now)).toBe('Never used')
    expect(lastUsed('2026-10-07T11:59:30Z', now)).toBe('Last used just now')
    expect(lastUsed('2026-10-07T10:00:00Z', now)).toBe('Last used 2h ago')
    expect(lastUsed('2026-10-07T10:00:00', now)).toBe('Last used 2h ago') // naive UTC from the server
    expect(lastUsed('2026-10-04T12:00:00Z', now)).toBe('Last used 3d ago')
  })
})
