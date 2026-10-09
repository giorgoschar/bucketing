import { screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi, hang } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { BillsList } from './BillsList'
import { billRow, billsRoutes, change } from './fixtures'
import type { Routes } from '../../../test/fakeApi'

afterEach(resetTestEnv)

it('empty: says so and links to Plan › Items', async () => {
  fakeApi(billsRoutes([]))
  renderWithProviders(<BillsList />, { route: '/insights/bills' })
  expect(await screen.findByText('No recurring bills yet')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open items' })).toHaveAttribute('href', '/plan/items')
})

it('a row: name, last amount and date, the 12-month total, a sparkline, and a link to its history', async () => {
  fakeApi(billsRoutes([billRow()]))
  renderWithProviders(<BillsList />, { route: '/insights/bills' })
  const row = (await screen.findByRole('link', { name: /Electricity/ }))
  expect(row).toHaveAttribute('href', '/insights/bills/i1')
  expect(row).toHaveTextContent('€84.00')
  expect(row).toHaveTextContent('14 Sep')
  expect(row).toHaveTextContent('€790.40')
  expect(within(row).getByRole('img', { name: /Electricity.*last 4 payments/ })).toBeInTheDocument()
  expect(row).not.toHaveTextContent('vs usual')
})

it('a changed bill says so in an arrow and words, up and down', async () => {
  fakeApi(billsRoutes([
    billRow({ change: change({ pct: 37.7 }) }),
    billRow({ item_id: 'i2', name: 'Water', change: change({ pct: -22.2, direction: 'down' }) }),
  ]))
  renderWithProviders(<BillsList />, { route: '/insights/bills' })
  expect(await screen.findByText('↑ 38% vs usual')).toBeInTheDocument()
  expect(screen.getByText('↓ 22% vs usual')).toBeInTheDocument()
})

it('paused bills are listed last under "Paused"', async () => {
  fakeApi(billsRoutes([billRow(), billRow({ item_id: 'i3', name: 'Old gym', is_active: false })]))
  renderWithProviders(<BillsList />, { route: '/insights/bills' })
  const heading = await screen.findByRole('heading', { name: 'Paused' })
  const links = screen.getAllByRole('link', { name: /Electricity|Old gym/ })
  expect(links.map((l) => l.textContent)).toEqual([expect.stringContaining('Electricity'), expect.stringContaining('Old gym')])
  expect(heading.compareDocumentPosition(links[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(heading.compareDocumentPosition(links[0]) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
})

it('says in one line that the lens and period do not apply', async () => {
  fakeApi(billsRoutes([billRow()]))
  renderWithProviders(<BillsList />, { route: '/insights/bills?p=last_month' })
  expect(await screen.findByText('Bills cover all time. The lens and period above do not apply.')).toBeInTheDocument()
})

it('offline with a saved copy: the rows and "Offline · showing saved history"', async () => {
  const fake = fakeApi(billsRoutes([billRow()]))
  const { unmount, client } = renderWithProviders(<BillsList />)
  await screen.findByText('Electricity')
  unmount()
  setOnline(false)
  fake.down()
  renderWithProviders(<BillsList />, { client })
  expect(await screen.findByText('Offline · showing saved history')).toBeInTheDocument()
  expect(screen.getByText('Electricity')).toBeInTheDocument()
})

it('offline with nothing saved: an empty state, not a spinner', async () => {
  setOnline(false)
  fakeApi(billsRoutes([])).down()
  renderWithProviders(<BillsList />)
  expect(await screen.findByText('No saved bills yet. Connect once to load Bills.')).toBeInTheDocument()
})

it('loading shows the skeleton', () => {
  fakeApi({ 'GET /api/v1/insights/bills': () => hang() } as unknown as Routes)
  renderWithProviders(<BillsList />)
  expect(screen.getByRole('status', { name: 'Loading' })).toBeInTheDocument()
})
