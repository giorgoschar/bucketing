import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { clearPending, isPending, markPending, usePendingIds } from './pending'

afterEach(() => clearPending())

it('tracks queued row ids and re-renders subscribers', () => {
  const { result } = renderHook(() => usePendingIds())
  expect(result.current.size).toBe(0)
  act(() => markPending('e1'))
  expect(result.current.has('e1')).toBe(true)
  expect(isPending('e1')).toBe(true)
  act(() => clearPending())
  expect(result.current.has('e1')).toBe(false)
})
