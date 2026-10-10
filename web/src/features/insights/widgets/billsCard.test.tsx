import { screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv } from '../../../test/render'
import { billRow, billsRoutes, change } from '../bills/fixtures'
import { BillsCard } from './cards'

afterEach(resetTestEnv)

const rows = [
  billRow({ item_id: 'a', name: 'Electricity', total_12m: 790 }),
  billRow({ item_id: 'b', name: 'Water', total_12m: 300, last: { entry_id: 'x', due_date: '2026-09-01', amount: 25 } }),
  billRow({ item_id: 'c', name: 'Internet', total_12m: 280, change: change({ pct: 25 }) }),
  billRow({ item_id: 'd', name: 'Gym', total_12m: 100 }),
]

it('shows the three items with the highest 12-month total, each with its last amount, and "All bills"', async () => {
  fakeApi(billsRoutes(rows))
  renderWithProviders(<BillsCard />)
  const card = await screen.findByRole('region', { name: 'Bills' })
  expect(within(card).getAllByRole('link').map((l) => l.textContent)).toEqual([
    'All bills',
    expect.stringContaining('Electricity'), expect.stringContaining('Water'), expect.stringContaining('Internet'),
  ])
  expect(within(card).queryByText('Gym')).toBeNull()
  expect(within(card).getByText('€25.00')).toBeInTheDocument()
  expect(within(card).getByRole('link', { name: 'All bills' })).toHaveAttribute('href', '/insights/bills')
  expect(within(card).getByText('↑ 25% vs usual')).toBeInTheDocument()
})

it('says in one line that the lens and period do not apply', async () => {
  fakeApi(billsRoutes(rows))
  renderWithProviders(<BillsCard />)
  expect(await screen.findByText('Bills cover all time. The lens and period do not apply.')).toBeInTheDocument()
})

it('no bills: the card points to Plan › Items', async () => {
  fakeApi(billsRoutes([]))
  renderWithProviders(<BillsCard />)
  expect(await screen.findByText(/No recurring bills yet/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open items' })).toHaveAttribute('href', '/plan/items')
})

it('renders nothing while loading or when nothing is saved', () => {
  fakeApi(billsRoutes(rows))
  const { container } = renderWithProviders(<BillsCard />)
  expect(container.querySelector('.insights__card')).toBeNull()
})
