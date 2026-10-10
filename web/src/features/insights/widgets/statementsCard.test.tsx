import { screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import { listMonth, listRoutes, statementList } from '../statements/fixtures'
import { StatementsCard } from './cards'

afterEach(resetTestEnv)

const months = [
  listMonth(),
  listMonth({ month: '2026-08', label: 'August 2026', net: -200, reviewed_at: '2026-09-03T09:00:00', closed: true }),
  listMonth({ month: '2026-07', label: 'July 2026', net: 0, closed: true }),
  listMonth({ month: '2026-06', label: 'June 2026', net: 90, closed: true }),
]

it('the last three months with their net as signed text, and "All statements"', async () => {
  fakeApi(listRoutes(statementList({ months })))
  renderWithProviders(<StatementsCard />)
  const card = await screen.findByRole('region', { name: 'Statements' })
  const links = within(card).getAllByRole('link')
  expect(links.map((l) => l.textContent)).toEqual([
    'All statements',
    expect.stringContaining('September 2026'), expect.stringContaining('August 2026'), expect.stringContaining('July 2026'),
  ])
  expect(links[1]).toHaveTextContent('+€760.00')
  expect(links[2]).toHaveTextContent('−€200.00')
  expect(links[3]).toHaveTextContent('€0.00')
  expect(within(card).queryByText(/June/)).toBeNull()
  expect(links[0]).toHaveAttribute('href', '/insights/statements')
  expect(links[1]).toHaveAttribute('href', '/insights/statements/2026-09')
})

it('the month in review says "Review"', async () => {
  fakeApi(listRoutes(statementList({ review: { month: '2026-09', label: 'September 2026', days_left: 3 }, months })))
  renderWithProviders(<StatementsCard />)
  const card = await screen.findByRole('region', { name: 'Statements' })
  expect(within(card).getByRole('link', { name: /September 2026/ })).toHaveTextContent('Review')
})

it('no past months: a quiet line and no link', async () => {
  fakeApi(listRoutes(statementList()))
  renderWithProviders(<StatementsCard />)
  expect(await screen.findByText('No past months yet.')).toBeInTheDocument()
  expect(screen.queryByRole('link')).toBeNull()
})

it('renders nothing while loading or when nothing is saved', () => {
  fakeApi(listRoutes(statementList({ months })))
  const { container } = renderWithProviders(<StatementsCard />)
  expect(container.querySelector('.insights__card')).toBeNull()
})
