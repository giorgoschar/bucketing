import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { query } from '../insights/fixtures'

const { toast, push, prefs } = vi.hoisted(() => ({
  toast: vi.fn(),
  push: { state: 'off' as string, enablePush: vi.fn(), disablePush: vi.fn(), sendTestPush: vi.fn() },
  prefs: { current: null as unknown },
}))
vi.mock('../../ui/Toast', () => ({ useToast: () => ({ show: toast }) }))
vi.mock('../../session/SessionProvider', () => ({ useSession: () => ({ status: 'signedIn', me: { id: 'me', household_id: 'hh1' } }) }))
vi.mock('../../pwa/pushClient', () => ({
  usePushState: () => ({ state: push.state, refresh: vi.fn() }),
  enablePush: push.enablePush, disablePush: push.disablePush, sendTestPush: push.sendTestPush,
}))
vi.mock('./hooks', () => ({ useNotificationPrefs: () => query(prefs.current) }))

import { disabledAfter } from './notificationHooks'
import { Notifications } from './Notifications'

const PREFS = { push_devices: 1, types: [
  { type: 'bill_due', group: 'Bills', label: 'Due in 3 days', enabled: true },
  { type: 'bill_overdue', group: 'Bills', label: 'Overdue', enabled: false },
  { type: 'ingest_created', group: 'Apple Pay', label: 'Each new purchase', enabled: true },
] }
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) })
const renderIt = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><Notifications /></MemoryRouter></QueryClientProvider>)

beforeEach(() => { push.state = 'off'; prefs.current = PREFS })
afterEach(() => { vi.restoreAllMocks(); toast.mockClear(); push.enablePush.mockReset(); push.disablePush.mockReset(); push.sendTestPush.mockReset() })

describe('Notifications', () => {
  it('push off → on subscribes through the client', async () => {
    push.enablePush.mockResolvedValue(ok({ ok: true }))
    renderIt()
    fireEvent.click(screen.getByRole('switch', { name: 'Push on this device' }))
    await waitFor(() => expect(push.enablePush).toHaveBeenCalled())
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Push is on for this device'))
  })

  it('push on → off unsubscribes, and Send test reports the result', async () => {
    push.state = 'on'
    push.disablePush.mockResolvedValue(ok({ ok: true }))
    push.sendTestPush.mockResolvedValue(ok({ sent: false, error: 'VAPID keys are not configured on the server.' }))
    renderIt()
    fireEvent.click(screen.getByRole('button', { name: 'Send test' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('VAPID keys are not configured on the server.', { tone: 'error' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Push on this device' }))
    await waitFor(() => expect(push.disablePush).toHaveBeenCalled())
  })

  it('a refused permission says where to allow it', async () => {
    push.enablePush.mockResolvedValue({ response: new Response(null, { status: 403 }), error: { detail: 'Notifications are turned off for Tameio. Allow them in iOS Settings.' } })
    renderIt()
    fireEvent.click(screen.getByRole('switch', { name: 'Push on this device' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Notifications are turned off for Tameio. Allow them in iOS Settings.', { tone: 'error' }))
  })

  it('denied is disabled and says where to allow it', () => {
    push.state = 'denied'
    renderIt()
    expect(screen.getByRole('switch', { name: 'Push on this device' })).toBeDisabled()
    expect(screen.getByText('Allowed in iOS Settings')).toBeInTheDocument()
  })

  it('in a browser tab it asks to install first', () => {
    push.state = 'not-installed'
    renderIt()
    expect(screen.getByText('Add Tameio to your Home Screen to get push alerts.')).toBeInTheDocument()
  })

  it('alert toggles are grouped and PUT the whole disabled set', async () => {
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(PREFS), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderIt()
    expect(screen.getByRole('heading', { name: 'Bills' })).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Overdue' })).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(screen.getByRole('switch', { name: 'Due in 3 days' }))
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const req = fetch.mock.calls[0][0] as Request
    expect(new URL(req.url).pathname).toBe('/api/v1/settings/notifications')
    expect(req.method).toBe('PUT')
    expect(await req.json()).toEqual({ disabled: ['bill_due', 'bill_overdue'] })
  })

  it('without the mutes API there are no alert toggles', () => {
    prefs.current = null
    renderIt()
    expect(screen.getAllByRole('switch')).toHaveLength(1)
  })

  it('offline changes nothing', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    const fetch = vi.spyOn(globalThis, 'fetch')
    renderIt()
    fireEvent.click(screen.getByRole('switch', { name: 'Due in 3 days' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith("You're offline. This change needs a connection.", { tone: 'error' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Push on this device' }))
    await waitFor(() => expect(toast).toHaveBeenCalledTimes(2))
    expect(fetch).not.toHaveBeenCalled()
    expect(push.enablePush).not.toHaveBeenCalled()
  })

  it('computes the next disabled set', () => {
    expect(disabledAfter(PREFS, 'bill_overdue', true)).toEqual([])
    expect(disabledAfter(PREFS, 'ingest_created', false)).toEqual(['bill_overdue', 'ingest_created'])
  })
})
