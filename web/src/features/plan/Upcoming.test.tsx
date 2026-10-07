import { act, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { markPending } from '../../data/pending'
import { fakeApi } from '../../test/fakeApi'
import { day, entry, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { Upcoming } from './Upcoming'

afterEach(resetTestEnv)

const days = [
  day('2026-10-09', [entry()], 1161.1),
  day('2026-10-20', [], 1161.1),
  day('2026-10-26', [entry({ id: 'e2', item_id: 'i2', name: 'Salary', direction: 'in', due_date: '2026-10-26', amount: 1500, estimated: true })], 2661.1),
  day('2026-11-02', [entry({ id: 'e3', item_id: 'i3', name: 'Electricity', due_date: '2026-11-02', amount: null })], 0),
]

it('groups entries under day headings with the running net, marking estimates and missing amounts', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  const oct26 = await screen.findByRole('region', { name: 'Mon 26 Oct' })
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Fri 9 Oct', 'Mon 26 Oct', 'Mon 2 Nov'])
  expect(oct26).toHaveTextContent('Net this month +€2,661.10')
  expect(within(oct26).getByRole('button', { name: /Salary/ })).toHaveTextContent('≈ +€1,500.00')
  expect(screen.getByRole('region', { name: 'Mon 2 Nov' })).toHaveTextContent('No amount yet')
  expect(document.body.textContent).not.toContain('NaN')
})

it('tapping a row opens the Entry sheet', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  fireEvent.click(await screen.findByRole('button', { name: /Cosmote/ }))
  expect(screen.getByRole('dialog', { name: 'Cosmote' })).toBeInTheDocument()
})

it('marks rows whose change is waiting to sync', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  act(() => markPending('e1'))
  expect(await screen.findByRole('button', { name: /Cosmote/ })).toHaveTextContent('Waiting to sync')
})

it('empty: says nothing is due and links to a new item', async () => {
  fakeApi({ 'GET /api/v1/plan/upcoming': () => [day('2026-10-09', [], 0)] })
  renderWithProviders(<Upcoming />)
  expect(await screen.findByText('Nothing due in the next 30 days')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Add a recurring item' })).toHaveAttribute('href', '/plan/items?new=1')
})

it('offline with nothing saved', async () => {
  fakeApi({}).down()
  setOnline(false)
  renderWithProviders(<Upcoming />)
  expect(await screen.findByText('No saved data yet. Connect once to load Plan.')).toBeInTheDocument()
})
