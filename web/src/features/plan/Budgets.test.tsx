import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi, reply } from '../../test/fakeApi'
import { budgetRow, pace } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, setOnline } from '../../test/render'
import { Budgets } from './Budgets'

afterEach(resetTestEnv)

const rows = [
  budgetRow(),
  budgetRow({ bucket_id: 'b2', name: 'Kids', budget: 300, spent: 255, pct: 85 }),
  budgetRow({ bucket_id: 'b3', name: 'Fun', budget: 200, spent: 208, pct: 104 }),
  budgetRow({ bucket_id: 'b4', name: 'Gifts', budget: null, spent: 120, pct: null }),
  budgetRow({
    bucket_id: 'b5', name: 'Naxos trip', kind: 'event', budget: 900, spent: 610, pct: 67.8,
    period_start: '2026-10-01', period_end: '2026-10-12', days_left: 5, archive_suggested: true,
  }),
]

it('tints bars at 80% and 100%, with words as well as colour', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => rows, 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  expect(await screen.findByRole('progressbar', { name: 'Day to day' })).toHaveAttribute('data-tone', 'ok')
  expect(screen.getByRole('progressbar', { name: 'Kids' })).toHaveAttribute('data-tone', 'warn')
  expect(screen.getByRole('progressbar', { name: 'Fun' })).toHaveAttribute('data-tone', 'over')
  expect(screen.getByText('Fun').closest('.plan-budget')).toHaveTextContent('over budget')
  expect(screen.getByText('Day to day').closest('.plan-budget')).toHaveTextContent('€904 of €1,200')
})

it('a bucket without a budget shows its spend and no bar', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => rows, 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  const gifts = (await screen.findByText('Gifts')).closest('.plan-budget')!
  expect(gifts).toHaveTextContent('€120 spent')
  expect(screen.queryByRole('progressbar', { name: 'Gifts' })).toBeNull()
  expect(document.body.textContent).not.toContain('NaN')
})

it('pace: "on pace for" and the over-pace marker; nothing before day 7 (pace null)', async () => {
  fakeApi({
    'GET /api/v1/plan/budgets': () => rows,
    'GET /api/v1/plan/pace': () => [pace(), pace({ bucket_id: 'b2', name: 'Kids', pace: null, over_pace: false })],
  })
  renderWithProviders(<Budgets />)
  const day2day = (await screen.findByText('Day to day')).closest('.plan-budget')!
  await screen.findByText(/on pace for/)
  expect(day2day).toHaveTextContent('on pace for €1,310')
  expect(day2day).toHaveTextContent('over pace')
  expect(screen.getByText('Kids').closest('.plan-budget')).not.toHaveTextContent('on pace')
})

it('event buckets show their dates, days left and the Archive? label', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => rows, 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  const trip = (await screen.findByText('Naxos trip')).closest('.plan-budget')!
  expect(trip).toHaveTextContent('1 Oct – 12 Oct')
  expect(trip).toHaveTextContent('5 days left')
  expect(trip).toHaveTextContent('Archive?')
})

const ARCHIVE = 'POST /api/v1/buckets/{bucket_id}/archive' as const
const trip = budgetRow({
  bucket_id: 'trip1', name: 'Crete', kind: 'event', budget: 900, spent: 610, pct: 67.8,
  period_start: '2026-09-01', period_end: '2026-09-12', days_left: 0, archive_suggested: true,
})

it('Archive (2d §5.6): asks first, says there is no undo, then archives online and refreshes', async () => {
  const fake = fakeApi({ 'GET /api/v1/plan/budgets': () => [trip], 'GET /api/v1/plan/pace': () => [], [ARCHIVE]: () => reply(200, {}) })
  renderWithProviders(<Budgets />)
  fireEvent.click(await screen.findByRole('button', { name: 'Archive Crete' }))
  const sheet = screen.getByRole('dialog', { name: 'Archive budget' })
  expect(within(sheet).getByText('Archive Crete? There is no undo: it leaves Plan and the new app.')).toBeInTheDocument()
  const before = fake.callsTo('GET /api/v1/plan/budgets').length
  fireEvent.click(within(sheet).getByRole('button', { name: 'Archive' }))
  await waitFor(() => expect(fake.callsTo(ARCHIVE)).toHaveLength(1))
  expect(fake.callsTo(ARCHIVE)[0].path).toBe('/api/v1/buckets/trip1/archive')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await waitFor(() => expect(fake.callsTo('GET /api/v1/plan/budgets').length).toBeGreaterThan(before))
})

it('Archive (2d §5.6): offline it is refused with the reason and nothing is sent or queued', async () => {
  const fake = fakeApi({ 'GET /api/v1/plan/budgets': () => [trip], 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  fireEvent.click(await screen.findByRole('button', { name: 'Archive Crete' }))
  setOnline(false)
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Archive budget' })).getByRole('button', { name: 'Archive' }))
  expect(await screen.findByRole('alert')).toHaveTextContent("You're offline. This change needs a connection.")
  expect(fake.callsTo(ARCHIVE)).toHaveLength(0)
  expect(screen.getByRole('dialog', { name: 'Archive budget' })).toBeInTheDocument()
})

it('Archive (2d §5.6): rows without the suggestion have no button', async () => {
  fakeApi({ 'GET /api/v1/plan/budgets': () => [{ ...trip, archive_suggested: false }], 'GET /api/v1/plan/pace': () => [] })
  renderWithProviders(<Budgets />)
  await screen.findByText('Crete')
  expect(screen.queryByRole('button', { name: /Archive/ })).toBeNull()
})
