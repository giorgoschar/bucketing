import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { wipe } from '../../../offline/db'
import { setIdentity } from '../../../offline/identity'
import { enqueue } from '../../../offline/queue'
import { pendingStore, rowFromBody } from './pendingStore'
import { usePendingTransactions } from './usePendingTransactions'

const BODY = { client_id: 'c-1', type: 'expense', amount: '3.00', currency: 'EUR', bucket_id: 'b-day', category_id: null, merchant: 'Coffee Island', transaction_date: '2026-10-07' }

beforeEach(async () => {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
})
afterEach(() => setIdentity(null))

it('rebuilds Waiting-to-sync rows from the queue after a reload', async () => {
  await enqueue({ method: 'POST', path: '/api/v1/transactions', body: BODY })
  await enqueue({ method: 'PUT', path: '/api/v1/transactions/t8', body: { ...BODY, client_id: undefined, amount: '9.00' } })
  await enqueue({ method: 'DELETE', path: '/api/v1/transactions/t9' })
  await enqueue({ method: 'POST', path: '/api/v1/transactions/t7/receipt', body: {} })
  const { result } = renderHook(() => usePendingTransactions())
  await waitFor(() => expect(result.current.rows).toHaveLength(1))
  expect(result.current.rows[0]).toMatchObject({ key: 'c-1', amount: '3.00', merchant: 'Coffee Island', state: 'waiting' })
  expect(result.current.edits.get('t8')).toMatchObject({ amount: '9.00', state: 'waiting' })
  expect([...result.current.hiddenIds]).toEqual(['t9'])
  expect(result.current.waitingCount).toBe(3)
})

it('shows a save in flight, and the same client_id only once once it is queued', async () => {
  const { result } = renderHook(() => usePendingTransactions())
  act(() => pendingStore.addInFlight(rowFromBody(BODY, 'sending')))
  expect(result.current.rows).toEqual([expect.objectContaining({ key: 'c-1', state: 'sending' })])
  await act(async () => { await enqueue({ method: 'POST', path: '/api/v1/transactions', body: BODY }) })
  await waitFor(() => expect(result.current.rows).toEqual([expect.objectContaining({ key: 'c-1', state: 'waiting' })]))
})
