import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { ShareCard } from './widgets/summary'

afterEach(cleanup)

const who = { me: true, name: 'Giorgos' }

// P3 final review M3: offline, a person share never fetched paused instead of failing, so it spun forever.
it('"Paid out vs share" offline with nothing saved says so instead of spinning', () => {
  render(<ShareCard who={who} period={{ preset: 'this_month' }}
    query={{ data: undefined, isError: false, noData: true, refetch: () => {} }} />)
  expect(screen.getByText('No saved data for this view. Connect once to load it.')).toBeInTheDocument()
  expect(screen.queryByRole('status', { name: 'Loading' })).toBeNull()
})

it('online and still loading it keeps the skeleton', () => {
  render(<ShareCard who={who} period={{ preset: 'this_month' }}
    query={{ data: undefined, isError: false, noData: false, refetch: () => {} }} />)
  expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
})
