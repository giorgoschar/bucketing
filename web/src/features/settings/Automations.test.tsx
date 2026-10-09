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
  useTokens: () => query([{ id: 't1', name: 'iPhone', prefix: 'pat_ab12', scopes: ['ingest'], default_bucket_id: 'b1', last_used_at: new Date(Date.now() - 2 * 3600_000).toISOString(), created_at: null, can_classify: false },
    { id: 't9', name: 'Asker', prefix: 'pat_zz99', scopes: ['ingest', 'classify'], default_bucket_id: null, last_used_at: null, created_at: null, can_classify: true }]),
  useBuckets: () => query([{ id: 'b1', name: 'Daily' }]),
}))
// The Recent attempts section (polish A5) fetches on mount; these cases count this screen's own fetch calls.
vi.mock('./attemptHooks', () => ({
  useAttempts: () => query({ items: [] }),
  ago: () => '', exactTime: () => '',
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

  it('has the Recent attempts section below Tokens', () => {
    renderIt()
    const tokens = screen.getByRole('heading', { name: 'Tokens' })
    const attempts = screen.getByRole('heading', { name: 'Recent attempts' })
    expect(tokens.compareDocumentPosition(attempts) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(attempts.compareDocumentPosition(screen.getByRole('heading', { name: 'New token' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('the token form has the classify checkbox, off by default, and does not send it when off', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 't2', name: 'Watch', prefix: 'pat_cd34', scopes: ['ingest'], default_bucket_id: null, last_used_at: null, created_at: null, token: 'pat_x' }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    const box = screen.getByRole('checkbox', { name: 'Let the Shortcut ask for a category (shares your category and budget names with the Shortcut)' })
    expect(box).not.toBeChecked()
    fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'Watch' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create token' }))
    await screen.findByRole('alert')
    expect(await (fetch.mock.calls[0][0] as Request).json()).toEqual({ name: 'Watch', default_bucket_id: null })
  })

  it('a checked box sends allow_classify, and the box clears after creating', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ id: 't2', name: 'Watch', prefix: 'pat_cd34', scopes: ['ingest', 'classify'], default_bucket_id: null, last_used_at: null, created_at: null, can_classify: true, token: 'pat_x' }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    const box = screen.getByRole('checkbox', { name: /Let the Shortcut ask for a category/ })
    fireEvent.click(box)
    expect(box).toBeChecked()
    fireEvent.change(screen.getByLabelText('Token name'), { target: { value: 'Watch' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create token' }))
    await screen.findByRole('alert')
    expect(await (fetch.mock.calls[0][0] as Request).json()).toEqual({ name: 'Watch', default_bucket_id: null, allow_classify: true })
    expect(box).not.toBeChecked()
  })

  it('a token that can ask for a category wears a badge; one that cannot does not', () => {
    renderIt()
    const rows = within(screen.getByRole('list', { name: 'Tokens' })).getAllByRole('listitem')
    expect(within(rows[0]).queryByText('Can ask for a category')).toBeNull()
    expect(within(rows[1]).getByText('Can ask for a category')).toBeInTheDocument()
  })

  it('explains asking for a category in three Shortcut steps, and how to stop being asked', () => {
    renderIt()
    const block = screen.getByRole('region', { name: 'Ask for a category' })
    const steps = within(block).getAllByRole('listitem')
    expect(steps).toHaveLength(3)
    expect(steps[0]).toHaveTextContent('If needs_category')
    expect(steps[1]).toHaveTextContent('Choose from List over category_names')
    expect(steps[2]).toHaveTextContent('Get Contents of URL')
    expect(steps[2]).toHaveTextContent('/ingest/apple-pay/<id>/classify')
    expect(steps[2]).toHaveTextContent('{"category": <Chosen Item>}')
    expect(block).toHaveTextContent('To stop being asked about a merchant, add a rule in Settings › Categories & rules.')
  })
})
