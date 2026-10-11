import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { markPending } from '../../data/pending'
import { fakeApi, hang, reply } from '../../test/fakeApi'
import { day, entry, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { Upcoming } from './Upcoming'

// Wednesday 7 Oct 2026: 9 Oct is this week, 26 Oct starts the week of 26 Oct - 1 Nov, 2 Nov the week after.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 7, 12))
})
afterEach(resetTestEnv)

const days = [
  day('2026-10-09', [entry()], 1161.1),
  day('2026-10-20', [], 1161.1),
  day('2026-10-26', [entry({ id: 'e2', item_id: 'i2', name: 'Salary', direction: 'in', due_date: '2026-10-26', amount: 1500, estimated: true })], 2661.1),
  day('2026-11-02', [entry({ id: 'e3', item_id: 'i3', name: 'Electricity', due_date: '2026-11-02', amount: null })], 0),
]

it('groups entries into one card per week with the week\'s net, marking estimates and missing amounts', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  const nov = await screen.findByRole('region', { name: '2–8 Nov' })
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['This week', '26 Oct – 1 Nov', '2–8 Nov'])
  const oct26 = screen.getByRole('region', { name: '26 Oct – 1 Nov' })
  expect(oct26).toHaveTextContent('Net this month +€2,661.10')
  expect(within(oct26).getByRole('button', { name: /Salary/ })).toHaveTextContent('Mon 26')
  expect(within(oct26).getByRole('button', { name: /Salary/ })).toHaveTextContent('≈ +€1,500.00')
  expect(nov).toHaveTextContent('Mon 2')
  expect(nov).toHaveTextContent('No amount yet')
  expect(document.body.textContent).not.toContain('NaN')
})

it('no "Out" label; income rows keep "In" and the positive tone', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => days })
  renderWithProviders(<Upcoming />)
  const salary = await screen.findByRole('button', { name: /Salary/ })
  expect(salary).toHaveTextContent('In')
  expect(salary.querySelector('.ui-money')).toHaveClass('ui-pos')
  expect(screen.getByRole('button', { name: /Cosmote/ })).toHaveTextContent('Fri 9')
  expect(document.body).not.toHaveTextContent('Out')
})

it('a week crossing a month shows the net per month; one card holds both months\' rows', async () => {
  const crossing = [
    day('2026-10-30', [entry({ id: 'a', name: 'Gym', due_date: '2026-10-30' })], 300),
    day('2026-11-01', [entry({ id: 'b', item_id: 'i2', name: 'Rent', due_date: '2026-11-01' })], 40),
  ]
  fakeApi({ ...readRoutes(), 'GET /api/v1/plan/upcoming': () => crossing })
  renderWithProviders(<Upcoming />)
  const week = await screen.findByRole('region', { name: '26 Oct – 1 Nov' })
  expect(within(week).getAllByRole('button')).toHaveLength(2)
  expect(week).toHaveTextContent('Net Oct +€300.00')
  expect(week).toHaveTextContent('Net Nov +€40.00')
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

it('Skip in the Entry sheet updates the row and the net at once, then rolls both back on a 409', async () => {
  let answer!: (r: Response) => void
  let reads = 0
  fakeApi({
    ...readRoutes(),
    // Later reads (the invalidation after the 409) never answer: what the screen shows is the rollback.
    'GET /api/v1/plan/upcoming': () => (++reads === 1 ? days : hang()),
    'POST /api/v1/recurring/entries/{entry_id}/skip': () => new Promise<Response>((r) => { answer = r }),
  })
  renderWithProviders(<Upcoming />)
  const oct9 = await screen.findByRole('region', { name: 'This week' })
  expect(oct9).toHaveTextContent('Net this month +€1,161.10')
  fireEvent.click(within(oct9).getByRole('button', { name: /Cosmote/ }))
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Cosmote' })).getByRole('button', { name: 'Skip' }))

  // Optimistic, before the server answers: the row is Skipped and its €38.90 is out of the net.
  await waitFor(() => expect(within(oct9).getByRole('button', { name: /Cosmote/ })).toHaveTextContent('Skipped'))
  expect(oct9).toHaveTextContent('Net this month +€1,200.00')
  expect(screen.getByRole('region', { name: '26 Oct – 1 Nov' })).toHaveTextContent('Net this month +€2,700.00')

  act(() => answer(reply(409, { detail: 'This entry is already done.' })))
  expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('This entry is already done.')
  expect(within(oct9).getByRole('button', { name: /Cosmote/ })).not.toHaveTextContent('Skipped')
  expect(oct9).toHaveTextContent('Net this month +€1,161.10')
  expect(screen.getByRole('region', { name: '26 Oct – 1 Nov' })).toHaveTextContent('Net this month +€2,661.10')
})
