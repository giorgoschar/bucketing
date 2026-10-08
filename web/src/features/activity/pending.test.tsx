import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { setIdentity } from '../../offline/identity'
import { enqueue } from '../../offline/queue'
import { fakeApi } from '../../test/fakeApi'
import { resetTestEnv, TEST_IDENTITY } from '../../test/render'
import { pendingStore } from '../composer/hooks/pendingStore'
import { Activity } from './Activity'
import { toPendingTxn } from './pending'
import { TODAY, makeTxn, pageOf, refRoutes, renderActivity } from './testing'

afterEach(async () => {
  pendingStore.reset()
  await resetTestEnv()
})

const ROW = {
  key: 'c-1', id: null, client_id: 'c-1', type: 'expense' as const, amount: '3.50', currency: 'EUR',
  bucket_id: 'b-day', category_id: null, merchant: 'Coffee Island', transaction_date: TODAY, state: 'waiting' as const,
}

describe('pending adapter', () => {
  it('a create becomes a read-only Txn keyed by its client id', () => {
    const t = toPendingTxn(ROW)
    expect(t).toMatchObject({ id: 'c-1', amount: 3.5, merchant: 'Coffee Island', splits: [], pending: true })
  })

  it('a queued edit overlays the server row and keeps its other fields', () => {
    const base = makeTxn({ id: 't8', paid_by: 'u-maria', notes: 'n' })
    const t = toPendingTxn({ ...ROW, key: 't8', id: 't8', amount: '9.00' }, base)
    expect(t).toMatchObject({ id: 't8', amount: 9, paid_by: 'u-maria', notes: 'n', pending: true })
  })

  it('the feed shows queued creates and edits as waiting, and hides queued deletes', async () => {
    setIdentity(TEST_IDENTITY)
    const kept = makeTxn({ id: 'k1', merchant: 'Lidl' })
    const edited = makeTxn({ id: 'e1', merchant: 'Bakery' })
    const gone = makeTxn({ id: 'g1', merchant: 'Kiosk' })
    await enqueue({ method: 'POST', path: '/api/v1/transactions', body: { client_id: 'c-1', type: 'expense', amount: '3.50', currency: 'EUR', merchant: 'Coffee Island', transaction_date: TODAY } })
    await enqueue({ method: 'PUT', path: '/api/v1/transactions/e1', body: { type: 'expense', amount: '7.00', currency: 'EUR', merchant: 'Bakery', transaction_date: TODAY } })
    await enqueue({ method: 'DELETE', path: '/api/v1/transactions/g1' })
    fakeApi({ ...refRoutes(), 'GET /api/v1/transactions': () => pageOf([kept, edited, gone]) })
    renderActivity(<Activity />)
    expect(await screen.findByText('Lidl')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Kiosk')).toBeNull())
    expect(await screen.findByText('Coffee Island')).toBeInTheDocument()
    expect(screen.getAllByText('Waiting to sync')).toHaveLength(2)
  })
})
