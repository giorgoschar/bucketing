import type { ReactElement } from 'react'
import { Route, Routes, useLocation } from 'react-router'
import { renderWithProviders } from '../../test/render'
import type { Routes as ApiRoutes } from '../../test/fakeApi'
import type { Txn, TxnPage } from './hooks'

function Where() {
  const loc = useLocation()
  return <output data-testid="location">{loc.pathname + loc.search}</output>
}

/** 2a's renderWithProviders (query client, memory router, Toaster, signed-in identity) renders `ui` at every path.
 * This mounts it at `path` so a screen can read `:id`, and adds the location readout the tests assert on. */
export function renderActivity(ui: ReactElement, { route = '/activity', path = '/activity' } = {}) {
  return renderWithProviders(
    <>
      <Routes>
        <Route path={path} element={ui} />
      </Routes>
      <Where />
    </>,
    { route },
  )
}

const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export const TODAY = iso(new Date())
export const YESTERDAY = iso(new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate() - 1))

let n = 0
export function makeTxn(over: Partial<Txn> = {}): Txn {
  n += 1
  return {
    id: `t${n}`, bucket_id: 'b-day', household_id: 'h', amount: 10, currency: 'EUR', exchange_rate: 1,
    type: 'expense', paid_by: 'u-me', payer_mode: 'single', category_id: null, notes: null,
    transaction_date: TODAY, receipt_path: null, payment_method: 'card', merchant: null,
    fuel_price_per_litre: null, fuel_litres: null, exclude_from_forecast: false, exclude_from_settlement: false,
    recurring_bill_id: null, created_at: `${TODAY}T09:00:00`, splits: [], has_take: false, missing_payer: false,
    ...over,
  } as Txn
}

export const REF = {
  buckets: [
    { id: 'b-day', name: 'Day to day', kind: 'monthly', status: 'active', show_income: true, icon: '🛒' },
    { id: 'b-bills', name: 'Bills', kind: 'monthly', status: 'active', show_income: false, icon: '🧾' },
    { id: 'b-trip', name: 'Crete', kind: 'event', status: 'active', show_income: false, icon: '🏝' },
  ],
  categories: [{ id: 'c-groc', name: 'Groceries', icon: '🛒', system_key: null }],
  members: [{ user_id: 'u-me', display_name: 'Giorgos' }, { user_id: 'u-maria', display_name: 'Maria' }],
}

/** The reference reads every Activity screen makes, as 2a fakeApi routes. Spread it, then add the screen's own routes. */
export function refRoutes(counts = { no_payer: 0, duplicate_groups: 0 }): ApiRoutes {
  return {
    'GET /api/v1/buckets': () => REF.buckets as never,
    'GET /api/v1/settings/categories': () => REF.categories as never,
    'GET /api/v1/settings/household': () => ({ id: 'h', name: 'Home', default_currency: 'EUR', members: REF.members }) as never,
    'GET /api/v1/transactions/counts': () => counts as never,
    'GET /api/v1/recurring': () => [] as never,
  }
}

export function pageOf(items: Txn[], extra: Partial<{ total: number; page: number; day_totals: Record<string, number> }> = {}): TxnPage {
  return { total: items.length, page: 1, page_size: 50, items, day_totals: {}, ...extra } as TxnPage
}
