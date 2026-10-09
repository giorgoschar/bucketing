import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv } from '../../test/render'
import { Activity } from './Activity'
import { HOLD_MS, _resetHeldForTests } from './heldDeletes'
import { makeTxn, pageOf, refRoutes, renderActivity } from './testing'

// P3 final review M5: the toast pauses while a finger or focus is on it, but the 5 s hold did not, so an Undo
// tapped at the very end found the delete already sent and silently did nothing.
afterEach(async () => {
  _resetHeldForTests()
  await resetTestEnv()
})

const DELETE = 'DELETE /api/v1/transactions/{txn_id}' as const

function setup() {
  const row = makeTxn({ merchant: 'Cosmote' })
  const fake = fakeApi({ ...refRoutes(), 'GET /api/v1/transactions': () => pageOf([row]), [DELETE]: () => null })
  renderActivity(<Activity />)
  return fake
}

describe('swipe-delete Undo at the 5 s edge', () => {
  it('while the Undo toast is held open past 5 s, the delete waits and Undo still works', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const fake = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    act(() => vi.advanceTimersByTime(HOLD_MS - 100))
    const undo = screen.getByRole('button', { name: 'Undo' })
    fireEvent.pointerEnter(undo.closest('.ui-toast')!) // the finger lands on the toast: it pauses
    await act(async () => { vi.advanceTimersByTime(2000) }) // well past the 5 s hold
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(fake.callsTo(DELETE)).toHaveLength(0)
    fireEvent.click(undo)
    expect(await screen.findByText('Cosmote')).toBeInTheDocument()
    await act(async () => { vi.advanceTimersByTime(HOLD_MS * 2) })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(fake.callsTo(DELETE)).toHaveLength(0)
  })

  it('once the held toast goes, the delete is sent', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const fake = setup()
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    const toastEl = screen.getByRole('button', { name: 'Undo' }).closest('.ui-toast')!
    fireEvent.pointerEnter(toastEl)
    await act(async () => { vi.advanceTimersByTime(HOLD_MS + 2000) })
    await act(async () => { await new Promise((r) => setTimeout(r, 20)) })
    expect(fake.callsTo(DELETE)).toHaveLength(0)
    fireEvent.pointerLeave(toastEl) // resumes with the time it had left, then goes
    act(() => vi.advanceTimersByTime(HOLD_MS))
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
    await waitFor(() => expect(fake.callsTo(DELETE)).toHaveLength(1))
  })

  it('a second delete replacing the toast does not keep the first one waiting', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const a = makeTxn({ merchant: 'A shop' })
    const b = makeTxn({ merchant: 'B shop' })
    const fake = fakeApi({ ...refRoutes(), 'GET /api/v1/transactions': () => pageOf([a, b]), [DELETE]: () => null })
    renderActivity(<Activity />)
    const [delA] = await screen.findAllByRole('button', { name: 'Delete' })
    fireEvent.click(delA)
    act(() => vi.advanceTimersByTime(1000))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' })) // B's toast replaces A's
    act(() => vi.advanceTimersByTime(HOLD_MS - 1000))
    await waitFor(() => expect(fake.callsTo(DELETE).map((c) => c.path)).toEqual([`/api/v1/transactions/${a.id}`]))
    act(() => vi.advanceTimersByTime(1000))
    await waitFor(() => expect(fake.callsTo(DELETE)).toHaveLength(2))
  })
})
