import { cleanup, act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SEARCH_DEBOUNCE_MS, SearchField } from './SearchField'

beforeEach(() => vi.useFakeTimers())
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('SearchField', () => {
  it('debounces typing by 250 ms', () => {
    const onChange = vi.fn()
    render(<SearchField value="" onChange={onChange} />)
    const input = screen.getByRole('searchbox', { name: 'Search transactions' })
    fireEvent.change(input, { target: { value: 'cosm' } })
    fireEvent.change(input, { target: { value: 'cosmote' } })
    act(() => vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS - 1))
    expect(onChange).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(1))
    expect(onChange).toHaveBeenCalledExactlyOnceWith('cosmote')
  })

  it('clears at once', () => {
    const onChange = vi.fn()
    render(<SearchField value="lidl" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }))
    expect(onChange).toHaveBeenCalledWith('')
  })
})
