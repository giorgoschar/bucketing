/** 2a's shared shapes (data/types.ts, with C1-1's fields); type-only, so pure modules stay React-free. */
export type { Bucket, Category, Household, Member } from './bridge'

/** The full transaction for edit and copy (app/api/transactions.py _txn_dict); 2a's TransactionRow is a subset. */
export interface TxnSplit { user_id: string; amount: number; is_settled: boolean }
export interface Txn {
  id: string
  bucket_id: string | null
  household_id: string
  amount: number
  currency: string
  exchange_rate: number
  type: 'expense' | 'income' | 'transfer'
  paid_by: string | null
  payer_mode: string | null
  category_id: string | null
  notes: string | null
  transaction_date: string | null
  receipt_path: string | null
  payment_method: string | null
  merchant: string | null
  fuel_price_per_litre: number | null
  fuel_litres: number | null
  exclude_from_forecast: boolean
  exclude_from_settlement: boolean
  recurring_bill_id: string | null
  created_at: string | null
  splits: TxnSplit[]
}
export interface CashMovements { items: unknown[]; stash: number }
/** 2d's GET /settings/category-rules row; 2b reads only these three fields. */
export interface Rule { id: string; pattern: string; category_id: string }
/** POST /api/v1/transactions/scan/qr (B1); kept local so the pure modules do not need generated types. */
export interface QrReceipt {
  amount: number | null
  currency: string
  date: string | null
  merchant: string | null
  category_hint: string | null
  category_id: string | null
}
/** GET /api/v1/transactions/check-duplicate row (B2). */
export interface Duplicate {
  id: string
  amount: number
  currency: string
  date: string
  notes: string | null
  merchant: string | null
  bucket: string | null
  paid_by: string | null
  same_bucket: boolean
}
