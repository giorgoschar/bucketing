import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { cachePut, wipe } from '../../offline/db'
import { setIdentity } from '../../offline/identity'
import { fakeApi } from '../../test/fakeApi'
import { testQueryClient } from '../../test/render'
import { type Bucket, type Category, type Household, ToastHost } from './bridge'
import { Composer } from './Composer'
import { type DefaultsRecord, defaultsKey, EMPTY_DEFAULTS } from './defaults'
import { pendingStore } from './hooks/pendingStore'
import { loose } from './testHelpers'
import type { Txn } from './types'

const bucket = (id: string, name: string, over: Partial<Bucket> = {}): Bucket => ({
  id, name, kind: 'monthly', status: 'active', budget: null, start_date: null, end_date: null, show_income: false, ...over,
})
const category = (id: string, name: string, over: Partial<Category> = {}): Category => ({
  id, name, icon: null, color: null, system_key: null, ...over,
})

export const BUCKETS: Bucket[] = [
  bucket('b-day', 'Day to day'),
  bucket('b-car', 'Car'),
  bucket('b-old', 'Old budget', { status: 'archived' }),
  bucket('b-salary', 'Salary', { show_income: true }),
  bucket('b-crete', 'Crete', { kind: 'event', start_date: '2026-08-12', end_date: '2026-08-19' }),
]
export const CATEGORIES: Category[] = [
  category('c-coffee', 'Coffee'),
  category('c-eat', 'Eating out'),
  category('c-fuel', 'Fuel', { system_key: 'fuel' }),
  category('c-food', 'Groceries'),
]
export const HOUSEHOLD: Household = {
  id: 'h1', name: 'Home', default_currency: 'EUR',
  members: [
    { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'giorgos', avatar_color: null },
    { user_id: 'u2', role: 'member', display_name: 'Maria', username: 'maria', avatar_color: null },
  ],
}
export const DEFAULTS: DefaultsRecord = {
  ...EMPTY_DEFAULTS,
  last: { bucket_id: 'b-day', category_id: 'c-coffee', paid_by: 'u1', payment_method: 'apple_pay' },
}
export const TXN: Txn = {
  id: 't9', bucket_id: 'b-day', household_id: 'h1', amount: 64.2, currency: 'EUR', exchange_rate: 1, type: 'expense',
  paid_by: 'u2', payer_mode: 'single', category_id: 'c-eat', notes: 'dinner', transaction_date: '2026-10-01',
  receipt_path: null, payment_method: 'card', merchant: 'Taverna', fuel_price_per_litre: null, fuel_litres: null,
  exclude_from_forecast: false, exclude_from_settlement: true, recurring_bill_id: null, created_at: null, splits: [],
}

export const created = (over: Record<string, unknown> = {}) => Response.json({ ...TXN, id: 't1', ...over }, { status: 201 })

/** Plain values or handlers by "METHOD /path" (concrete paths are fine); see testHelpers.loose. */
export function baseRoutes(): Record<string, unknown> {
  return {
    'GET /api/v1/auth/me': { id: 'u1', household_id: 'h1' },
    'GET /api/v1/buckets': BUCKETS,
    'GET /api/v1/settings/categories': CATEGORIES,
    'GET /api/v1/settings/household': HOUSEHOLD,
    'GET /api/v1/transactions': { total: 2, page: 1, page_size: 200, items: [{ ...TXN, merchant: 'Coffee Island' }, { ...TXN, id: 't8', merchant: 'Coffeeway' }] },
    'GET /api/v1/cash/movements': { items: [], stash: 50 },
    'GET /api/v1/transactions/check-duplicate': { duplicates: [] },
    'POST /api/v1/transactions': () => created(),
  }
}

/** Fresh store, identity and stored defaults (null = first use), then the composer in a data router. */
export async function renderComposer(url = '/new', opts: { routes?: Record<string, unknown>; defaults?: DefaultsRecord | null } = {}) {
  await wipe()
  setIdentity({ user_id: 'u1', household_id: 'h1' })
  pendingStore.reset()
  if (opts.defaults !== null) await cachePut(defaultsKey('h1'), opts.defaults ?? DEFAULTS)
  const api = fakeApi(loose({ ...baseRoutes(), ...opts.routes }))
  const router = createMemoryRouter(
    [
      { path: '/new', element: <Composer /> },
      { path: '/edit/:id', element: <Composer /> },
      { path: '/', element: <p>home screen</p> },
    ],
    { initialEntries: [url] },
  )
  render(
    <QueryClientProvider client={testQueryClient()}>
      <ToastHost>
        <RouterProvider router={router} />
      </ToastHost>
    </QueryClientProvider>,
  )
  return { api, router }
}
