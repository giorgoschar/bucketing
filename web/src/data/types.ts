import type { components } from '../api/schema'

type S = components['schemas']

// Typed by the API's response models.
export type EntryOut = S['EntryOut']
export type UpcomingDayOut = S['UpcomingDayOut']
export type MonthPictureOut = S['MonthPictureOut']
export type MonthRowOut = S['MonthRowOut']
export type BucketMonthRowOut = S['BucketMonthRowOut']
export type YearOut = S['YearOut']
export type YearMonthOut = S['YearMonthOut']
export type BudgetRowOut = S['BudgetRowOut']
export type PaceOut = S['PaceOut']
export type RecurringItemOut = S['RecurringItemOut']
export type RecurringItemIn = S['RecurringItemIn']
export type EntryDoneIn = S['EntryDoneIn']
export type MatchOut = S['MatchOut']
export type CategoryUsualOut = S['CategoryUsualOut']

export type Direction = 'in' | 'out'
export type EntryStatus = 'expected' | 'done' | 'skipped'
export type PaymentMethod = 'card' | 'cash' | 'apple_pay' | 'transfer' | 'other'

// These endpoints return plain dicts (untyped in the schema); data/reads.ts narrows them to these shapes.
export interface Member {
  user_id: string
  role: string
  display_name: string | null
  username: string | null
  avatar_color: string | null
}
export interface Household { id: string; name: string; default_currency: string; members: Member[] }
export interface Bucket {
  id: string
  name: string
  kind: string
  status: string
  budget: number | null
  /** Event buckets: shown as "12–19 Aug" in the composer's budget picker. */
  start_date: string | null
  end_date: string | null
  /** Income may be filed under this budget (composer income picker). */
  show_income: boolean
}
export interface Category { id: string; name: string; icon: string | null; color: string | null; system_key: string | null }
/** One row of GET /transactions. `keys.transactions.recent()` holds TransactionRow[] (newest first). */
export interface TransactionRow {
  id: string
  type: 'expense' | 'income'
  amount: number
  currency: string
  transaction_date: string
  merchant: string | null
  notes: string | null
  bucket_id: string | null
  category_id: string | null
  paid_by: string | null
  payment_method: string | null
  recurring_bill_id: string | null
}
export interface TransactionPage { total: number; page: number; page_size: number; items: TransactionRow[] }
