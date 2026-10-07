import type { components } from '../../api/schema'

/** GET /insights returns an untyped dict; these mirror app/api/insights.py's keys. */
export interface CategoryRow { category_id: string | null; name: string; icon: string; color: string; amount: number; pct: number }
export interface FuelMonth { year: number; month: number; label: string; litres: number; spend: number; avg_price_per_litre: number | null }
export interface FuelRefuel { date: string; price_per_litre: number; litres: number; spend: number }
export interface FuelCar {
  bucket_id: string; name: string; icon: string; litres: number; spend: number
  avg_price_per_litre: number | null; fills: number; months: FuelMonth[]; refuels: FuelRefuel[]
}
export interface FuelData {
  litres: number; spend: number; avg_price_per_litre: number | null; fills: number
  unpriced_count: number; months: FuelMonth[]; cars: FuelCar[]
}
export interface InsightsData {
  preset: string
  period_label: string
  start_date: string | null
  end_date: string | null
  total_spent: number
  logged_total: number
  cash_not_logged: number
  income_total: number
  in_out: { in: number; out: number; logged: number; cash_not_logged: number; net: number }
  kpis: {
    total: number; count: number; avg_per_month: number
    largest: { amount: number; notes: string | null; date: string; category: string | null } | null
    previous_total: number | null; change_pct: number | null; savings_rate: number | null
    range_start: string | null; range_end: string | null
  }
  categories: CategoryRow[]
  monthly_trend: { label: string; year: number; month: number; total: number; is_current: boolean }[]
  monthly_in_out: { year: number; month: number; label: string; in: number; out: number; net: number }[]
  by_method: { method: string; label: string; amount: number; pct: number }[]
  cash_share: number
  budget_status: {
    bucket_id: string; bucket_name: string; icon: string | null; color: string | null
    spent: number; budget: number | null; pct: number | null; remaining: number | null; over_budget: boolean
  }[]
  fuel: FuelData | null
}

export const CASH_NOT_LOGGED = '__cash_not_logged__'
export const UNCATEGORISED = 'uncategorised'

export interface InsightFilters { bucketIds: string[]; categoryIds: string[] }
export const NO_FILTERS: InsightFilters = { bucketIds: [], categoryIds: [] }
export const filtersKey = (f: InsightFilters) => `${[...f.bucketIds].sort().join(',')}|${[...f.categoryIds].sort().join(',')}`

export type PersonShare = components['schemas']['PersonShareOut']
export type CategoryDetail = components['schemas']['CategoryDetailOut']
export type CategoryUsual = components['schemas']['CategoryUsualOut']
export type MonthPicture = components['schemas']['MonthPictureOut']
