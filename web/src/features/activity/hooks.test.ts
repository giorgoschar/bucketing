
import { describe, expect, it } from 'vitest'
import { editBody, type Txn } from './hooks'

const ROW = {
  id: 't1', bucket_id: 'b1', household_id: 'h', amount: 100, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: null, payer_mode: 'own_share', category_id: 'c1', notes: 'rent', transaction_date: '2026-10-01',
  receipt_path: null, payment_method: 'transfer', merchant: null, fuel_price_per_litre: null, fuel_litres: null,
  exclude_from_forecast: false, exclude_from_settlement: false, recurring_bill_id: null, created_at: '2026-10-01T08:00:00',
  splits: [{ user_id: 'u1', amount: 60, is_settled: false }, { user_id: 'u2', amount: 40, is_settled: false }],
  has_take: false, missing_payer: false,
} as Txn

describe('editBody', () => {
  it('copies splits and payer_mode, since a PUT without splits deletes them', () => {
    const body = editBody(ROW, { category_id: 'c2' })
    expect(body.category_id).toBe('c2')
    expect(body.payer_mode).toBe('own_share')
    expect(body.splits).toEqual([{ user_id: 'u1', amount: 60 }, { user_id: 'u2', amount: 40 }])
    expect(body).toMatchObject({ amount: 100, bucket_id: 'b1', notes: 'rent', transaction_date: '2026-10-01' })
  })
})
