import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { QueryView, type QueryViewState } from './QueryView'

afterEach(cleanup)

const base: QueryViewState<string> = {
  data: undefined, dataUpdatedAt: 0, isLoading: true, offline: false, stale: false, noData: false, refetch: () => {},
}
const show = (s: Partial<QueryViewState<string>>, showBanner?: boolean) =>
  render(
    <QueryView result={{ ...base, ...s }} noDataText="No saved data yet. Connect once to load Plan." showBanner={showBanner}>
      {(d) => <p>{d}</p>}
    </QueryView>,
  )

it('loading shows a busy skeleton', () => {
  show({})
  expect(screen.getByRole('status', { name: 'Loading' })).toHaveAttribute('aria-busy', 'true')
})

it('data renders children; stale data adds the offline banner unless suppressed', () => {
  const at = new Date(2026, 9, 7, 14, 2).getTime()
  const { unmount } = show({ data: 'plan', isLoading: false, stale: true, dataUpdatedAt: at })
  expect(screen.getByText('plan')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Offline · updated')
  unmount()
  show({ data: 'plan', isLoading: false, stale: true, dataUpdatedAt: at }, false)
  expect(screen.queryByRole('status')).toBeNull()
})

it('offline with nothing saved says so; online failure offers Try again', () => {
  const { unmount } = show({ isLoading: false, noData: true, offline: true })
  expect(screen.getByText('No saved data yet. Connect once to load Plan.')).toBeInTheDocument()
  unmount()
  const refetch = vi.fn()
  show({ isLoading: false, noData: true, offline: false, refetch })
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(refetch).toHaveBeenCalledOnce()
})
