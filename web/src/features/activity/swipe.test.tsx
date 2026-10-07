import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, setOnline } from '../../test/render'
import { Activity } from './Activity'
import { HOLD_MS, _resetHeldForTests } from './heldDeletes'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

const hide = () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
  document.dispatchEvent(new Event('visibilitychange'))
}

afterEach(async () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  _resetHeldForTests()
  await resetTestEnv()
})

const DELETE = 'DELETE /api/v1/transactions/{txn_id}' as const

function setup() {
  const row = makeTxn({ merchant: 'Cosmote', recurring_bill_id: 'r1', bucket_id: 'b-bills' })
  let deleted = false
  const fake = fakeApi({
    ...refRoutes(),
    'GET /api/v1/recurring': () => [{ id: 'r1', name: 'Cosmote', direction: 'out' }] as never,
    // The fake server forgets the row once it is deleted, like the real one.
    'GET /api/v1/transactions': () => pageOf(deleted ? [] : [row]),
    [DELETE]: () => {
      deleted = true
      return null
    },
  })
  renderActivity(<Activity />)
  return { row, fake }
}

describe('swipe delete', () => {
  it('hides the row, offers Undo, and Undo sends nothing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { fake } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(screen.queryByText('Cosmote')).toBeNull()
    expect(screen.getByText(/Cosmote .* is expected again/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
    expect(await screen.findByText('Cosmote')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(HOLD_MS * 2))
    expect(fake.callsTo(DELETE)).toHaveLength(0)
  })

  it('sends the DELETE after 5 s', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { fake, row } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    act(() => vi.advanceTimersByTime(HOLD_MS))
    await waitFor(() => expect(fake.callsTo(DELETE).map((c) => c.path)).toEqual([`/api/v1/transactions/${row.id}`]))
  })

  it('Copy opens the composer with ?from=', async () => {
    const { row } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Copy' }))
    expect(screen.getByTestId('location').textContent).toBe(`/new?from=${row.id}`)
  })

  it('hiding the page sends the delete at once and takes the Undo toast away', async () => {
    const { fake } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
    act(() => hide())
    await waitFor(() => expect(fake.callsTo(DELETE)).toHaveLength(1))
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  })

  it('the delete sent on page hide uses fetch keepalive with the CSRF header, so it survives teardown', async () => {
    document.cookie = 'csrf_token=tok1'
    const { fake, row } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    act(() => hide())
    await waitFor(() => expect(fake.callsTo(DELETE)).toHaveLength(1))
    const [url, init] = vi.mocked(globalThis.fetch).mock.calls.find(([, i]) => i?.method === 'DELETE') ?? []
    expect(String(url)).toBe(`/api/v1/transactions/${row.id}`)
    expect(init?.keepalive).toBe(true)
    expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('tok1')
    expect(screen.queryByText('Cosmote')).toBeNull()
  })

  it('offline, the delete flushed on page hide goes to the queue instead', async () => {
    const { fake } = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    act(() => setOnline(false))
    act(() => hide())
    await waitFor(() => expect(screen.queryByText('Cosmote')).toBeNull())
    expect(fake.callsTo(DELETE)).toHaveLength(0)
    expect(vi.mocked(globalThis.fetch).mock.calls.some(([, i]) => i?.keepalive)).toBe(false)
  })
})
