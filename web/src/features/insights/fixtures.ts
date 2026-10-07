import type { InsightsData } from './types'

export function makeInsights(over: Partial<InsightsData> = {}): InsightsData {
  return {
    preset: 'this_month', period_label: 'October 2026', start_date: '2026-10-01', end_date: '2026-10-06',
    total_spent: 1284.6, logged_total: 1239.6, cash_not_logged: 45, income_total: 3000,
    in_out: { in: 3000, out: 1284.6, logged: 1239.6, cash_not_logged: 45, net: 1715.4 },
    kpis: {
      total: 1284.6, count: 31, avg_per_month: 1284.6,
      largest: { amount: 420, notes: 'IKEA', date: '2026-10-03', category: 'Home' },
      previous_total: 1396.3, change_pct: -8, savings_rate: 57.2, range_start: '2026-10-01', range_end: '2026-10-06',
    },
    categories: [
      { category_id: 'g', name: 'Groceries', icon: '🛒', color: '#10b981', amount: 362.4, pct: 28.2 },
      { category_id: null, name: 'Uncategorised', icon: '📦', color: '#9ca3af', amount: 80, pct: 6.2 },
      { category_id: '__cash_not_logged__', name: 'Cash (not yet logged)', icon: '💵', color: '#a8a29e', amount: 45, pct: 3.5 },
    ],
    monthly_trend: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'].map((label, i) => ({ label, year: 2026, month: i + 5, total: [2180, 2410, 2050, 2960, 2240, 1284.6][i], is_current: i === 5 })),
    monthly_in_out: ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct'].map((label, i) => ({ label, year: 2026, month: i + 5, in: 3000, out: [2180, 2410, 2050, 2960, 2240, 1284.6][i], net: 3000 - [2180, 2410, 2050, 2960, 2240, 1284.6][i] })),
    by_method: [
      { method: 'card', label: 'Card', amount: 1100, pct: 85.6 },
      { method: 'cash', label: 'Cash', amount: 184.6, pct: 14.4 },
    ],
    cash_share: 14.4,
    budget_status: [{ bucket_id: 'b1', bucket_name: 'Daily', icon: null, color: null, spent: 1310, budget: 1200, pct: 109, remaining: -110, over_budget: true }],
    fuel: {
      litres: 64, spend: 114.6, avg_price_per_litre: 1.84, fills: 2, unpriced_count: 1,
      months: [], cars: [
        { bucket_id: 'car1', name: 'Golf', icon: '🚗', litres: 40, spend: 72, avg_price_per_litre: 1.8, fills: 1, months: [], refuels: [{ date: '2026-10-02', price_per_litre: 1.8, litres: 40, spend: 72 }] },
        { bucket_id: 'car2', name: 'Yaris', icon: '🚙', litres: 24, spend: 42.6, avg_price_per_litre: 1.775, fills: 1, months: [], refuels: [{ date: '2026-10-05', price_per_litre: 1.775, litres: 24, spend: 42.6 }] },
      ],
    },
    ...over,
  }
}

/** A 2a CachedQuery-shaped value for mocked read hooks. */
export function query<T>(data: T | undefined, over: Record<string, unknown> = {}) {
  return {
    data, dataUpdatedAt: data === undefined ? 0 : Date.now(), fromCache: false, isLoading: data === undefined,
    isError: false, offline: false, stale: false, noData: false, refetch: () => {}, ...over,
  }
}
