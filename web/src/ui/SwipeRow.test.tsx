import { cleanup, act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { LONG_PRESS_MS, SwipeRow } from './SwipeRow'

beforeAll(() => {
  // jsdom: no PointerEvent, no layout. Give rows a 300 px width.
  if (!('PointerEvent' in window)) {
    class PE extends MouseEvent {
      pointerId: number
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init)
        this.pointerId = init.pointerId ?? 1
      }
    }
    Object.assign(window, { PointerEvent: PE })
  }
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 300 })
})
afterEach(() => { cleanup(); vi.useRealTimers() })

function drag(el: HTMLElement, fromX: number, toX: number) {
  fireEvent.pointerDown(el, { clientX: fromX, clientY: 10, pointerId: 1 })
  fireEvent.pointerMove(el, { clientX: toX, clientY: 12, pointerId: 1 })
  fireEvent.pointerUp(el, { clientX: toX, clientY: 12, pointerId: 1 })
}

function setup(extra = {}) {
  const props = { onDelete: vi.fn(), onCopy: vi.fn(), onLongPress: vi.fn(), ...extra }
  render(<SwipeRow {...props}><span>Cosmote</span></SwipeRow>)
  return { props, row: screen.getByText('Cosmote').parentElement as HTMLElement }
}

describe('SwipeRow', () => {
  it('deletes past 40% to the left, copies past 40% to the right', () => {
    const { props, row } = setup()
    drag(row, 250, 100) // -150 px = 50%
    expect(props.onDelete).toHaveBeenCalledOnce()
    drag(row, 50, 200)
    expect(props.onCopy).toHaveBeenCalledOnce()
  })

  it('does nothing under the threshold', () => {
    const { props, row } = setup()
    drag(row, 250, 160) // -90 px = 30%
    expect(props.onDelete).not.toHaveBeenCalled()
  })

  it('is never the only path: Delete and Copy are real buttons', () => {
    const { props } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(props.onDelete).toHaveBeenCalledOnce()
    expect(props.onCopy).toHaveBeenCalledOnce()
  })

  it('long-press of 500 ms enters selection; moving cancels it', () => {
    vi.useFakeTimers()
    const { props, row } = setup()
    fireEvent.pointerDown(row, { clientX: 10, clientY: 10, pointerId: 1 })
    act(() => vi.advanceTimersByTime(LONG_PRESS_MS))
    expect(props.onLongPress).toHaveBeenCalledOnce()
    fireEvent.pointerUp(row)
    fireEvent.pointerDown(row, { clientX: 10, clientY: 10, pointerId: 2 })
    fireEvent.pointerMove(row, { clientX: 40, clientY: 10, pointerId: 2 })
    act(() => vi.advanceTimersByTime(LONG_PRESS_MS))
    expect(props.onLongPress).toHaveBeenCalledOnce()
  })

  it('a disabled row (queued create) has no actions', () => {
    setup({ disabled: true })
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
  })
})
