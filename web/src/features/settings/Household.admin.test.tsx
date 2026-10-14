import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const { toast, me, changed, members } = vi.hoisted(() => ({
  toast: vi.fn(), changed: vi.fn(), me: { current: 'me' },
  members: { current: [] as unknown[] },
}))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/householdChange', () => ({ afterHouseholdChange: changed }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: me.current, household_id: 'hh1' } }) }))
vi.mock('./hooks', () => ({ useHousehold: () => query({ id: 'hh1', name: 'Home', default_currency: 'EUR', members: members.current }) }))

import { db } from '../../offline/db'
import { Household } from './Household'

const two = [
  { user_id: 'me', role: 'owner', display_name: 'Giorgos', username: 'g', avatar_color: null },
  { user_id: 'm', role: 'member', display_name: 'Maria', username: 'maria', avatar_color: null },
]
const solo = [two[0]]
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const rows = (n: number) => [{ id: 'hh1', name: 'Home', role: 'owner', active: true }, ...(n > 1 ? [{ id: 'hh2', name: 'Cabin', role: 'member', active: false }] : [])]

/** The households list answers GET; everything else is the real call under test. */
function serve(list: unknown, reply: Response = new Response(null, { status: 204 })) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const req = input as Request
    return req.method === 'GET' ? json(list) : reply.clone()
  })
}
const posts = (f: ReturnType<typeof serve>) => f.mock.calls.map((c) => c[0] as Request).filter((r) => r.method === 'POST')
const renderIt = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><Household /></MemoryRouter></QueryClientProvider>)
beforeEach(() => { members.current = two })
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); changed.mockClear(); me.current = 'me' })

describe('Household admin', () => {
  it('one household: no switcher, but you can start another', async () => {
    members.current = solo
    const f = serve(rows(1), json({ household_id: 'new' }, 201))
    renderIt()
    expect(screen.queryByRole('button', { name: 'Switch to Cabin' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'New household' }))
    fireEvent.change(screen.getByLabelText('Household name'), { target: { value: ' Cabin ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create household' }))
    await waitFor(() => expect(changed).toHaveBeenCalled())
    const req = posts(f)[0]
    expect(new URL(req.url).pathname).toBe('/api/v1/settings/households')
    expect(await req.json()).toEqual({ name: 'Cabin', default_currency: 'EUR' })
  })

  it('several households: pick one and the app reloads on it', async () => {
    members.current = solo
    const f = serve(rows(2), json({ household_id: 'hh2' }))
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Switch to Cabin' }))
    await waitFor(() => expect(changed).toHaveBeenCalled())
    expect(await posts(f)[0].json()).toEqual({ household_id: 'hh2' })
    expect(screen.queryByRole('button', { name: 'Switch to Home' })).toBeNull() // the active one is not a button
  })

  it('switching is refused while offline writes wait, since the reload would wipe them', async () => {
    members.current = solo
    await db.queue.bulkAdd([1, 2].map((n) => ({ createdAt: n, attempts: 0, nextAttemptAt: 0, status: 'pending' as const, iv: new Uint8Array(12), data: new ArrayBuffer(1) })))
    const f = serve(rows(2), json({ household_id: 'hh2' }))
    renderIt()
    fireEvent.click(await screen.findByRole('button', { name: 'Switch to Cabin' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('You have 2 changes waiting to sync. Go online and let them sync first.', { tone: 'error' }))
    expect(posts(f)).toHaveLength(0)
    expect(changed).not.toHaveBeenCalled()
    await db.queue.clear()
  })

  it('transfer ownership asks in the page first, never with window.confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const f = serve(rows(1))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Maria' }))
    fireEvent.click(screen.getByRole('button', { name: 'Make owner' }))
    expect(posts(f)).toHaveLength(0)
    expect(screen.getByText(/become the owner/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Make Maria the owner' }))
    await waitFor(() => expect(posts(f)).toHaveLength(1))
    expect(new URL(posts(f)[0].url).pathname).toBe('/api/v1/settings/household/transfer-ownership/m')
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('reset 2FA needs the owner code and sends it', async () => {
    const f = serve(rows(1))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Maria' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reset 2FA' }))
    const go = screen.getByRole('button', { name: 'Reset Maria’s 2FA' })
    expect(go).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Your authenticator code'), { target: { value: '123456' } })
    fireEvent.click(go)
    await waitFor(() => expect(posts(f)).toHaveLength(1))
    expect(new URL(posts(f)[0].url).pathname).toBe('/api/v1/settings/household/members/m/reset-2fa')
    expect(await posts(f)[0].json()).toEqual({ owner_code: '123456' })
    await waitFor(() => expect(toast).toHaveBeenCalledWith('2FA reset. They sign in again.'))
  })

  it('a rejected code shows the reason and keeps the step open', async () => {
    serve(rows(1), json({ detail: 'Invalid authenticator code.' }, 400))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Maria' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reset 2FA' }))
    fireEvent.change(screen.getByLabelText('Your authenticator code'), { target: { value: '000000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Reset Maria’s 2FA' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Invalid authenticator code.', { tone: 'error' }))
    expect(screen.getByLabelText('Your authenticator code')).toBeInTheDocument()
  })

  it('a member leaves after one in-page confirmation', async () => {
    me.current = 'm'
    const f = serve(rows(2), json({ household_id: 'hh2' }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Leave household' }))
    expect(posts(f)).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Leave Home' }))
    await waitFor(() => expect(changed).toHaveBeenCalledWith('/app/'))
    expect(await posts(f)[0].json()).toEqual({ confirm_name: '' })
  })

  it('the last member must type the name; leaving the last household goes to setup', async () => {
    members.current = solo
    const f = serve(rows(1), json({ household_id: null }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Leave household' }))
    const go = screen.getByRole('button', { name: 'Leave Home' })
    expect(go).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Type the household name'), { target: { value: 'Home' } })
    fireEvent.click(go)
    await waitFor(() => expect(changed).toHaveBeenCalledWith('/setup'))
    expect(await posts(f)[0].json()).toEqual({ confirm_name: 'Home' })
  })

  it('an owner with other members is told to hand over first, with no leave button', () => {
    serve(rows(1))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Leave household' }))
    expect(screen.getByText(/Make someone else the owner/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Leave Home' })).toBeNull()
  })

  it('a member sees no owner actions in the member menu', () => {
    me.current = 'm'
    serve(rows(1))
    renderIt()
    expect(screen.queryByRole('button', { name: /Actions for/ })).toBeNull()
  })
})
