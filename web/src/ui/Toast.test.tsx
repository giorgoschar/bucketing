import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { dismissToast, toast, Toaster } from './Toast'

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
