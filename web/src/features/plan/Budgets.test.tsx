import { screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { budgetRow, pace } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
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
