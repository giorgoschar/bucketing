import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, expect, it } from 'vitest'
import { affects, keys } from '../../data/keys'
import { setIdentity } from '../../offline/identity'
import { fakeApi } from '../../test/fakeApi'
import { Providers, resetTestEnv, TEST_IDENTITY, testQueryClient } from '../../test/render'
import { ACTIVITY_WRITES, useDeleteTransaction, useEditTransaction, type Txn } from './hooks'

afterEach(resetTestEnv)

// Plan › Cash §4.7 (review I3): an Activity edit or delete of a cash expense changes `logged` (the wallets,
// Home's cash row) and maybe the stash, so the cash reads go stale too.
const CASH = [keys.cashWallets('2026-10'), keys.cashMovements('2026-10'), keys.cashStash()]
const CASH_TXN = {
  id: 't7', bucket_id: 'b1', household_id: 'h1', amount: 20, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: 'u1', payer_mode: 'single', category_id: null, notes: null, transaction_date: '2026-10-05',
  receipt_path: null, payment_method: 'cash', merchant: 'Laiki', fuel_price_per_litre: null, fuel_litres: null,
  exclude_from_forecast: false, exclude_from_settlement: false, recurring_bill_id: null, created_at: '2026-10-05T08:00:00',
  splits: [], has_take: true, missing_payer: false,
} as unknown as Txn

function setup() {
  setIdentity(TEST_IDENTITY)
  const client = testQueryClient()
  for (const k of CASH) client.setQueryData(k, { seeded: true })
  const wrapper = ({ children }: { children: ReactNode }) => <Providers client={client}>{children}</Providers>
  return { client, wrapper }
}
const stale = (client: ReturnType<typeof testQueryClient>) => CASH.map((k) => client.getQueryState(k)?.isInvalidated)

it('affects.entry (Activity, Plan entry Done) includes the cash reads and the stash', () => {
  for (const list of [affects.entry, ACTIVITY_WRITES]) {
    expect(list).toEqual(expect.arrayContaining([keys.cashAll(), keys.cashStash()]))
  }
})

it('an Activity delete of a cash expense invalidates cashWallets, cashMovements and cashStash', async () => {
  const api = fakeApi({ 'DELETE /api/v1/transactions/{txn_id}': () => null })
  const { client, wrapper } = setup()
  const { result } = renderHook(() => useDeleteTransaction(), { wrapper })
  await result.current.run({ id: 't7' })
  expect(api.callsTo('DELETE /api/v1/transactions/{txn_id}')).toHaveLength(1)
  await waitFor(() => expect(stale(client)).toEqual([true, true, true]))
})

it('an Activity edit of a cash expense invalidates the cash reads', async () => {
  fakeApi({ 'PUT /api/v1/transactions/{txn_id}': () => CASH_TXN as never })
  const { client, wrapper } = setup()
  const { result } = renderHook(() => useEditTransaction(), { wrapper })
  await result.current.run({ txn: CASH_TXN, patch: { notes: 'market' } })
  await waitFor(() => expect(stale(client)).toEqual([true, true, true]))
})
