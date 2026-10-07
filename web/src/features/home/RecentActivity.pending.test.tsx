import { screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { page, readRoutes } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv, TEST_IDENTITY } from '../../test/render'
import { RecentActivity } from './RecentActivity'

beforeEach(() => setIdentity(TEST_IDENTITY))
afterEach(resetTestEnv)

it('a queued save shows at the top of Recent with "Waiting to sync", and is not a link', async () => {
  fakeApi({ ...readRoutes(), 'GET /api/v1/transactions': () => page([]) })
  await enqueue({
    method: 'POST', path: '/api/v1/transactions',
    body: { client_id: 'c-1', type: 'expense', amount: '3.00', currency: 'EUR', bucket_id: 'b1', merchant: 'Coffee Island', transaction_date: '2026-10-07' },
  })
  renderWithProviders(<RecentActivity />)
  expect(await screen.findByText('Coffee Island')).toBeInTheDocument()
  expect(screen.getByText('Waiting to sync')).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Coffee Island/ })).not.toBeInTheDocument()
})
