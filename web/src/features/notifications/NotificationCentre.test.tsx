import 'fake-indexeddb/auto'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { installMemoryStorage } from '../../test/storage'
import { NotificationBell } from './NotificationBell'
import { NotificationCentre } from './NotificationCentre'

installMemoryStorage()
afterEach(resetTestEnv)

const LIST = 'GET /api/v1/notifications' as const
const mins = (m: number) => new Date(Date.now() - m * 60_000).toISOString()
const n = (id: string, over: Record<string, unknown> = {}) =>
  ({ id, type: 'bill_due', title: `T${id}`, body: 'b', link: '/bills', is_read: false, created_at: mins(5), ...over })
const body = () => ({ unread: 2, has_more: false, offset: 0, items: [n('1'), n('2', { link: '/transactions/x', created_at: mins(90) }), n('3', { is_read: true })] })

describe('Notification centre', () => {
  it('lists newest first, marks unread, and a tap opens the target and marks it read', async () => {
    const api = fakeApi({
      [LIST]: () => body(),
      'POST /api/v1/notifications/{notification_id}/read': () => ({ ok: true }),
    })
    const { router } = renderWithProviders(<NotificationCentre />, { route: '/notifications' })
    const rows = await screen.findAllByRole('button', { name: /^T\d/ })
    expect(rows.map((r) => r.textContent)).toEqual([expect.stringContaining('T1'), expect.stringContaining('T2'), expect.stringContaining('T3')])
    expect(screen.getAllByRole('img', { name: 'Unread' })).toHaveLength(2)
    fireEvent.click(rows[1])
    await waitFor(() => expect(router.state.location.pathname).toBe('/activity'))
    await waitFor(() => expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/notifications/2/read')).toBe(true))
  })

  it('Mark all read posts read-all', async () => {
    let read = false
    const api = fakeApi({
      [LIST]: () => (read ? { ...body(), unread: 0 } : body()),
      'POST /api/v1/notifications/read-all': () => { read = true; return { unread: 0 } },
    })
    renderWithProviders(<NotificationCentre />, { route: '/notifications' })
    fireEvent.click(await screen.findByRole('button', { name: 'Mark all read' }))
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/notifications/read-all')).toBe(true))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Mark all read' })).toBeNull())
  })

  it('says so when there is nothing', async () => {
    fakeApi({ [LIST]: () => ({ unread: 0, has_more: false, offset: 0, items: [] }) })
    renderWithProviders(<NotificationCentre />, { route: '/notifications' })
    expect(await screen.findByText('No notifications yet')).toBeInTheDocument()
  })

  it('offline: shows the saved list, taps still navigate, nothing is posted', async () => {
    const api = fakeApi({ [LIST]: () => body() })
    const { router, unmount, client } = renderWithProviders(<NotificationCentre />, { route: '/notifications' })
    await screen.findByText('T1')
    unmount()
    setOnline(false)
    renderWithProviders(<NotificationCentre />, { route: '/notifications', client })
    fireEvent.click(await screen.findByRole('button', { name: /T1/ }))
    expect(api.calls.filter((c) => c.method === 'POST')).toHaveLength(0)
    expect(router.state.location.pathname).toBe('/notifications')
  })
})

describe('Notification bell', () => {
  it('shows the unread count in its name', async () => {
    fakeApi({ [LIST]: () => body() })
    renderWithProviders(<NotificationBell />)
    expect(await screen.findByRole('link', { name: 'Notifications, 2 unread' })).toHaveAttribute('href', '/notifications')
  })
})
