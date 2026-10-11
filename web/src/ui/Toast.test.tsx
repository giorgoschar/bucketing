import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { amendToast, dismissToast, toast, Toaster } from './Toast'

afterEach(() => { cleanup(); dismissToast(); vi.useRealTimers() })

it('shows a toast in a polite live region; a new one replaces it', () => {
  render(<Toaster />)
  act(() => toast('Saved'))
  expect(screen.getByRole('status')).toHaveTextContent('Saved')
  act(() => toast('Skipped'))
  expect(screen.getByRole('status')).toHaveTextContent('Skipped')
  expect(screen.getByRole('status')).not.toHaveTextContent('Saved')
})

it('runs the action and dismisses', () => {
  const onClick = vi.fn()
  render(<Toaster />)
  act(() => toast('Deleted', { action: { label: 'Undo', onClick } }))
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  expect(onClick).toHaveBeenCalledOnce()
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('dismisses itself after durationMs', () => {
  vi.useFakeTimers()
  render(<Toaster />)
  act(() => toast('Moved 3 payments', { durationMs: 10_000 }))
  act(() => { vi.advanceTimersByTime(9_999) })
  expect(screen.getByRole('status')).toHaveTextContent('Moved 3 payments')
  act(() => { vi.advanceTimersByTime(1) })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('an error toast is an assertive alert, not a polite status', () => {
  render(<Toaster />)
  act(() => toast('Couldn’t save.', { tone: 'error' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Couldn’t save.')
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
  act(() => dismissToast())
  expect(screen.queryByRole('alert')).toBeNull()
})

it('a toast with an action holds while focused or hovered, then finishes its time', () => {
  vi.useFakeTimers()
  render(<Toaster />)
  act(() => toast('Deleted', { action: { label: 'Undo', onClick: () => {} }, durationMs: 4000 }))
  act(() => { vi.advanceTimersByTime(1000) })
  const undo = screen.getByRole('button', { name: 'Undo' })
  act(() => undo.focus())
  act(() => { vi.advanceTimersByTime(10_000) })
  expect(screen.getByRole('status')).toHaveTextContent('Deleted')
  act(() => undo.blur())
  act(() => { vi.advanceTimersByTime(2_999) })
  expect(screen.getByRole('status')).toHaveTextContent('Deleted')
  act(() => { vi.advanceTimersByTime(1) })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('hovering pauses it too', () => {
  vi.useFakeTimers()
  render(<Toaster />)
  act(() => toast('Deleted', { action: { label: 'Undo', onClick: () => {} } }))
  fireEvent.pointerEnter(screen.getByText('Deleted'))
  act(() => { vi.advanceTimersByTime(10_000) })
  expect(screen.getByRole('status')).toHaveTextContent('Deleted')
  fireEvent.pointerLeave(screen.getByText('Deleted'))
  act(() => { vi.advanceTimersByTime(4_000) })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('several actions: each runs its own callback, and one that shows another toast keeps it', () => {
  const always = vi.fn(() => toast('Rule saved'))
  const notNow = vi.fn()
  render(<Toaster />)
  act(() => toast('Always use Groceries for Lidl?', { actions: [{ label: 'Always', onClick: always }, { label: 'Not now', onClick: notNow }] }))
  expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Always', 'Not now'])
  fireEvent.click(screen.getByRole('button', { name: 'Always' }))
  expect(always).toHaveBeenCalledOnce()
  expect(notNow).not.toHaveBeenCalled()
  expect(screen.getByRole('status')).toHaveTextContent('Rule saved')
})

it('a toast with the single action looks and behaves as before', () => {
  render(<Toaster />)
  act(() => toast('Deleted', { action: { label: 'Undo', onClick: () => {} } }))
  expect(screen.getAllByRole('button')).toHaveLength(1)
})

// Fix round 1, finding 4: a toast can be amended in place, but only while it is still the one on screen.
it('toast() returns an id; amendToast changes that toast in place, keeping its DOM node and not closing it', () => {
  const onClose = vi.fn()
  render(<Toaster />)
  let id = 0
  act(() => { id = toast('Saved €5.00', { actions: [{ label: 'Undo', onClick: () => {} }], onClose }) })
  const node = screen.getByText('Saved €5.00').parentElement
  let ok = false
  act(() => { ok = amendToast(id, { message: 'Saved €5.00 · Always?', durationMs: 8000, actions: [{ label: 'Undo', onClick: () => {} }, { label: 'Always', onClick: () => {} }] }) })
  expect(ok).toBe(true)
  expect(screen.getByText('Saved €5.00 · Always?').parentElement).toBe(node)
  expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Undo', 'Always'])
  expect(onClose).not.toHaveBeenCalled()
})

it('amendToast restarts the timer with the new duration', () => {
  vi.useFakeTimers()
  render(<Toaster />)
  let id = 0
  act(() => { id = toast('Saved', { durationMs: 5000 }) })
  act(() => { vi.advanceTimersByTime(4000) })
  act(() => { amendToast(id, { message: 'Saved · Q?', durationMs: 8000 }) })
  act(() => { vi.advanceTimersByTime(7999) })
  expect(screen.getByRole('status')).toHaveTextContent('Saved · Q?')
  act(() => { vi.advanceTimersByTime(2) })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('amendToast does nothing for a toast that is gone, replaced or dismissed', () => {
  render(<Toaster />)
  let first = 0
  act(() => { first = toast('Saved') })
  act(() => { toast('Receipt didn’t upload', { actions: [{ label: 'Retry', onClick: () => {} }] }) })
  let ok = true
  act(() => { ok = amendToast(first, { message: 'Question?' }) })
  expect(ok).toBe(false)
  expect(screen.getByRole('status')).toHaveTextContent('Receipt didn’t upload')
  expect(screen.getByRole('status')).not.toHaveTextContent('Question?')
  act(() => dismissToast())
  act(() => { ok = amendToast(first, { message: 'Question?' }) })
  expect(ok).toBe(false)
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})

it('a toast with more than one action puts its buttons on their own row; one action is unchanged', () => {
  render(<Toaster />)
  act(() => { toast('Deleted', { action: { label: 'Undo', onClick: () => {} } }) })
  expect(document.querySelector('.ui-toast')).not.toHaveClass('ui-toast--multi')
  act(() => { toast('Q?', { actions: [{ label: 'A', onClick: () => {} }, { label: 'B', onClick: () => {} }] }) })
  expect(document.querySelector('.ui-toast')).toHaveClass('ui-toast--multi')
})

it('amendToast keeps a hover/focus pause: the new time starts when the pointer leaves', () => {
  vi.useFakeTimers()
  render(<Toaster />)
  let id = 0
  act(() => { id = toast('Saved', { action: { label: 'Undo', onClick: () => {} }, durationMs: 5000 }) })
  const undo = screen.getByRole('button', { name: 'Undo' })
  act(() => undo.focus())
  act(() => { amendToast(id, { message: 'Saved · Q?', durationMs: 8000 }) })
  act(() => { vi.advanceTimersByTime(20_000) })
  expect(screen.getByRole('status')).toHaveTextContent('Saved · Q?')
  act(() => screen.getByRole('button', { name: 'Undo' }).blur())
  act(() => { vi.advanceTimersByTime(8001) })
  expect(screen.getByRole('status')).toBeEmptyDOMElement()
})
