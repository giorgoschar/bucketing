import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { categoryUsual, monthPicture } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Month } from './Month'

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12)) // Wed 7 Oct 2026
})
afterEach(resetTestEnv)

const routes = () => ({
  'GET /api/v1/plan/month': () => monthPicture(),
  'GET /api/v1/insights/categories-vs-usual': () => [
    categoryUsual(),
    categoryUsual({ category_id: 'c2', name: 'Fuel', this_month: 80, usual: null, flagged: false }),
  ],
})

it('shows Net (projected), the in/out table and the lines kept out of Net', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />, { route: '/plan?view=month' })
  expect(await screen.findByText('+€2,311.10')).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 3, name: 'Oct 2026' })).toBeInTheDocument()
  const fixed = screen.getByRole('rowheader', { name: 'Out · Fixed' }).closest('tr')!
  expect(fixed).toHaveTextContent('Out · Fixed€600€239€839')
  expect(screen.getByRole('rowheader', { name: 'In' }).closest('tr')).toHaveTextContent('In€3,150€1,500€4,650')
  expect(screen.getByText(/Trips & events/)).toHaveTextContent('Trips & events: €410.00')
  expect(screen.getByText(/Cash not yet logged/)).toHaveTextContent('Cash not yet logged: €45.00')
})

it('bucket rows expand to budget, so far and projected; a missing budget says so', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />)
  const kids = await screen.findByRole('button', { name: /Kids/ })
  expect(kids).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(kids)
  expect(kids).toHaveAttribute('aria-expanded', 'true')
  expect(kids.parentElement).toHaveTextContent('No budget')
  fireEvent.click(screen.getByRole('button', { name: /Day to day/ }))
  expect(screen.getByRole('button', { name: /Day to day/ }).parentElement).toHaveTextContent('Budget€1,200')
})

it('categories vs usual: flagged rows say "above usual"; no usual shows —', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />)
  const list = await screen.findByRole('region', { name: 'Categories vs usual' })
  expect(within(list).getByText('Groceries').closest('.ui-row')).toHaveTextContent('above usual')
  expect(within(list).getByText('Fuel').closest('.ui-row')).toHaveTextContent('Usual —')
  expect(within(list).getByText('Fuel').closest('.ui-row')).not.toHaveTextContent('above usual')
})

it('estimates show ≈', async () => {
  fakeApi({ ...routes(), 'GET /api/v1/plan/month': () => monthPicture({ estimated: true }) })
  renderWithProviders(<Month />)
  expect(await screen.findByText('≈ +€2,311.10')).toBeInTheDocument()
})

it('the switcher crosses the year end and asks for the new month', async () => {
  const fake = fakeApi(routes())
  const { router } = renderWithProviders(<Month />, { route: '/plan?view=month&month=2026-12' })
  expect(await screen.findByRole('heading', { level: 3, name: 'Dec 2026' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next month' }))
  expect(screen.getByRole('heading', { level: 3, name: 'Jan 2027' })).toBeInTheDocument()
  expect(router.state.location.search).toBe('?view=month&month=2027-01')
  await waitFor(() =>
    expect(fake.callsTo('GET /api/v1/plan/month').map((c) => c.query.get('month'))).toContain('2027-01'))
})

it('stops 11 months either side and ignores an out-of-range month in the URL', async () => {
  fakeApi(routes())
  const { unmount } = renderWithProviders(<Month />, { route: '/plan?month=2027-09' })
  expect(await screen.findByRole('button', { name: 'Next month' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Previous month' })).toBeEnabled()
  unmount()
  const second = renderWithProviders(<Month />, { route: '/plan?month=2025-11' })
  expect(await screen.findByRole('button', { name: 'Previous month' })).toBeDisabled()
  second.unmount()
  renderWithProviders(<Month />, { route: '/plan?month=2030-01' })
  expect(await screen.findByRole('heading', { level: 3, name: 'Oct 2026' })).toBeInTheDocument()
})

it('the table header row starts with a real header cell, labelled for screen readers', async () => {
  fakeApi(routes())
  renderWithProviders(<Month />)
  await screen.findByText('+€2,311.10')
  const head = screen.getAllByRole('row')[0]
  expect(within(head).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Line', 'So far', 'To come', 'Projected'])
  expect(within(head).queryAllByRole('cell')).toHaveLength(0)
})
