import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Keypad } from './Keypad'

afterEach(() => { cleanup(); vi.useRealTimers() })

it('has 12 named keys and reports taps', () => {
  const onKey = vi.fn()
  render(<Keypad onKey={onKey} />)
  expect(screen.getAllByRole('button')).toHaveLength(12)
  fireEvent.click(screen.getByRole('button', { name: '3' }))
  fireEvent.click(screen.getByRole('button', { name: 'Decimal point' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete last digit' }))
  expect(onKey.mock.calls.map((c) => c[0])).toEqual(['3', '.', 'back'])
})

it('a long press on backspace clears once and does not also delete', () => {
  vi.useFakeTimers()
  const onKey = vi.fn()
  render(<Keypad onKey={onKey} />)
  const back = screen.getByRole('button', { name: 'Delete last digit' })
  fireEvent.pointerDown(back)
  act(() => { vi.advanceTimersByTime(500) })
  fireEvent.pointerUp(back)
  fireEvent.click(back)
  expect(onKey.mock.calls.map((c) => c[0])).toEqual(['clear'])
})

it('hidden removes it from the accessibility tree', () => {
  render(<Keypad onKey={() => {}} hidden />)
  expect(screen.queryByRole('button', { name: '3' })).not.toBeInTheDocument()
})
