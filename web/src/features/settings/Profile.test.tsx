import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installMemoryStorage } from '../../test/storage'
import { query } from '../insights/fixtures'

const { toast, signOut, security } = vi.hoisted(() => ({ toast: vi.fn(), signOut: vi.fn(async () => {}), security: { current: {} as Record<string, unknown> } }))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' }, signOut }) }))
vi.mock('./hooks', () => ({
  useProfile: () => query({ id: 'me', username: 'g', display_name: 'Giorgos', email: 'g@x.t', avatar_color: '#6366f1', totp_enabled: true, household_id: 'hh1' }),
  useSecurity: () => query(security.current),
}))

import { takeSignInNotice } from '../../session/notice'
import { Profile } from './Profile'
import { groupSecret } from './TwoFactor'

installMemoryStorage()
const ON = { totp_enabled: true, backup_codes_remaining: 6, passkey_available: true, passkey_linked: false, password_session: true }
const ERR = { tone: 'error' }
let qc: QueryClient

function Loc() { return <p data-testid="loc">{useLocation().search}</p> }
function renderAt(url = '/settings/profile') {
  qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}><Routes><Route path="/settings/profile" element={<><Profile /><Loc /></>} /></Routes></MemoryRouter>
    </QueryClientProvider>,
  )
}
function answer(routes: Record<string, () => Response>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = new URL(input instanceof Request ? input.url : String(input))
    const hit = routes[url.pathname]
    return hit ? hit() : new Response('{}', { status: 404 })
  })
}
const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => { security.current = ON; document.cookie = 'csrf_token=tok' })
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); signOut.mockClear(); sessionStorage.clear() })

describe('Profile', () => {
  it('blocks a save offline, sends nothing and says why', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection.", ERR))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('saves the profile with the picked colour', async () => {
    const fetch = answer({ '/api/v1/settings/profile': json({ ok: true }) })
    renderAt()
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: '  Giorgos C ' } })
    fireEvent.click(screen.getByRole('radio', { name: 'Green' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Profile saved'))
    const req = fetch.mock.calls[0][0] as Request
    expect(req.method).toBe('PUT')
    expect(await req.json()).toEqual({ display_name: 'Giorgos C', email: 'g@x.t', avatar_color: '#10b981' })
  })

  it('a 409 keeps what was typed and toasts the server message', async () => {
    answer({ '/api/v1/settings/profile': json({ detail: 'Email already registered to another account' }, 409) })
    renderAt()
    fireEvent.change(screen.getByLabelText('Email (optional)'), { target: { value: 'taken@x.t' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Email already registered to another account', ERR))
    expect(screen.getByLabelText('Email (optional)')).toHaveValue('taken@x.t')
  })

  it('checks the new password length before sending', () => {
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    const sheet = screen.getByRole('dialog', { name: 'Change password', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Current password'), { target: { value: 'old-password-123' } })
    fireEvent.change(within(sheet).getByLabelText('New password'), { target: { value: 'short' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Change and sign out', hidden: true }))
    expect(within(sheet).getByText('Use at least 12 characters.')).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('a password change ends signed out with a notice', async () => {
    answer({ '/api/v1/settings/profile/password': () => new Response(null, { status: 204 }) })
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
    const sheet = screen.getByRole('dialog', { name: 'Change password', hidden: true })
    expect(within(sheet).getByText(/You'll be signed out everywhere and your Apple Pay tokens will stop working/)).toBeInTheDocument()
    expect(within(sheet).getByLabelText('New password')).toHaveAttribute('autocomplete', 'new-password')
    fireEvent.change(within(sheet).getByLabelText('Current password'), { target: { value: 'old-password-123' } })
    fireEvent.change(within(sheet).getByLabelText('New password'), { target: { value: 'a-long-new-password' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Change and sign out', hidden: true }))
    await waitFor(() => expect(signOut).toHaveBeenCalled())
    expect(takeSignInNotice()).toBe('Password changed. Sign in again.')
  })

  it('sets up 2FA: grouped secret, otpauth link, then backup codes that ignore the backdrop', async () => {
    security.current = { ...ON, totp_enabled: false, backup_codes_remaining: 0 }
    answer({
      '/api/v1/settings/security/totp/setup': json({ secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Tameio:g?secret=JBSWY3DPEHPK3PXP' }),
      '/api/v1/settings/security/totp/enable': json({ backup_codes: ['AAAA1', 'BBBB2', 'CCCC3', 'DDDD4', 'EEEE5', 'FFFF6', 'GGGG7', 'HHHH8'] }),
    })
    renderAt()
    fireEvent.click(screen.getByRole('button', { name: 'Set up' }))
    expect(await screen.findByText('JBSW Y3DP EHPK 3PXP')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open in authenticator' })).toHaveAttribute('href', expect.stringMatching(/^otpauth:\/\//))
    const code = screen.getByLabelText('6-digit code')
    expect(code).toHaveAttribute('autocomplete', 'one-time-code')
    expect(code).toHaveAttribute('inputmode', 'numeric')
    fireEvent.change(code, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    const sheet = await screen.findByRole('dialog', { name: 'Backup codes', hidden: true })
    expect(within(sheet).getByText('AAAA1')).toBeInTheDocument()
    fireEvent.click(screen.getAllByTestId('sheet-backdrop').at(-1)!) // 2a's backdrop element
    expect(screen.getByRole('dialog', { name: 'Backup codes', hidden: true })).toBeInTheDocument()
    // Never cached, never stored.
    const cached = JSON.stringify(qc.getQueryCache().getAll().map((q) => q.state.data))
    expect(cached).not.toContain('AAAA1')
    expect(cached).not.toContain('JBSWY3DPEHPK3PXP')
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('AAAA1')
    fireEvent.click(within(sheet).getByRole('button', { name: "I've saved these" }))
    await waitFor(() => expect(screen.queryByText('AAAA1')).toBeNull())
  })

  it('after Turn off on a password session the Set up sheet opens', async () => {
    answer({
      '/api/v1/settings/security/totp/disable': () => new Response(null, { status: 204 }),
      '/api/v1/settings/security/totp/setup': json({ secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/x' }),
    })
    renderAt()
    expect(screen.getByText(/6 backup codes left/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    const sheet = screen.getByRole('dialog', { name: 'Turn off 2FA', hidden: true })
    fireEvent.change(within(sheet).getByLabelText('Password'), { target: { value: 'pw-123456789012' } })
    fireEvent.change(within(sheet).getByLabelText('Authenticator code'), { target: { value: '123456' } })
    fireEvent.click(within(sheet).getByRole('button', { name: 'Turn off 2FA', hidden: true }))
    expect(await screen.findByText('Password sign-in needs 2FA. Set it up again to keep using Tameio.')).toBeInTheDocument()
  })

  it('links a passkey with a native form carrying CSRF and return_to', () => {
    renderAt()
    const form = screen.getByRole('button', { name: 'Link passkey' }).closest('form')!
    expect(form).toHaveAttribute('action', '/app/auth/link')
    expect(form).toHaveAttribute('method', 'post')
    const data = new FormData(form)
    expect(data.get('_csrf_token')).toBe('tok')
    expect(data.get('return_to')).toBe('app')
    expect(within(form).getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password')
  })

  it('unlinks with the same hidden fields', () => {
    security.current = { ...ON, passkey_linked: true }
    renderAt()
    const form = screen.getByRole('button', { name: 'Unlink' }).closest('form')!
    expect(form).toHaveAttribute('action', '/app/auth/unlink')
    expect(new FormData(form).get('return_to')).toBe('app')
    expect(new FormData(form).get('_csrf_token')).toBe('tok')
  })

  it('a passkey-only session cannot change the passkey', () => {
    security.current = { ...ON, password_session: false, passkey_linked: true }
    renderAt()
    expect(screen.getByText('Sign in with your password and 2FA to change this.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Unlink' })).toBeNull()
  })

  it('toasts ?passkey= once and drops it from the URL', async () => {
    renderAt('/settings/profile?passkey=error')
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Couldn't link the passkey. Check your password and code.", ERR))
    expect(toast).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('loc')).toHaveTextContent('')
  })
})

describe('groupSecret', () => {
  it('groups in fours', () => {
    expect(groupSecret('JBSWY3DPEHPK3PXP')).toBe('JBSW Y3DP EHPK 3PXP')
  })
})
