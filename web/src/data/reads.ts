import { api } from '../api/client'
import { useCachedQuery, type CachedQuery } from './cachedQuery'
import { unwrap } from './http'
import { keys } from './keys'
import type { Bucket, Category, Household, Member, RecurringItemOut, TransactionPage, TransactionRow } from './types'

type Dict = Record<string, unknown>
const asDict = (x: unknown): Dict => (typeof x === 'object' && x !== null ? (x as Dict) : {})
const str = (x: unknown, fallback = ''): string => (typeof x === 'string' ? x : x == null ? fallback : String(x))
const strOrNull = (x: unknown): string | null => (x == null || x === '' ? null : String(x))
const num = (x: unknown): number => (typeof x === 'number' ? x : Number(x ?? 0))
const numOrNull = (x: unknown): number | null => (x == null || x === '' ? null : Number(x))
const list = (x: unknown): unknown[] => (Array.isArray(x) ? x : [])

export function toMember(raw: unknown): Member {
  const d = asDict(raw)
  return {
    user_id: str(d.user_id), role: str(d.role, 'member'), display_name: strOrNull(d.display_name),
    username: strOrNull(d.username), avatar_color: strOrNull(d.avatar_color),
  }
}

export function toHousehold(raw: unknown): Household {
  const d = asDict(raw)
  return { id: str(d.id), name: str(d.name), default_currency: str(d.default_currency, 'EUR'), members: list(d.members).map(toMember) }
}

export function toBuckets(raw: unknown): Bucket[] {
  return list(raw).map((b) => {
    const d = asDict(b)
    return { id: str(d.id), name: str(d.name), kind: str(d.kind, 'monthly'), status: str(d.status, 'active'), budget: numOrNull(d.budget),
      start_date: strOrNull(d.start_date), end_date: strOrNull(d.end_date), show_income: d.show_income === true,
    }
  })
}

export function toCategories(raw: unknown): Category[] {
  return list(raw).map((c) => {
    const d = asDict(c)
    return { id: str(d.id), name: str(d.name), icon: strOrNull(d.icon), color: strOrNull(d.color), system_key: strOrNull(d.system_key) }
  })
}

export function toTransactionRow(raw: unknown): TransactionRow {
  const d = asDict(raw)
  return {
    id: str(d.id), type: d.type === 'income' ? 'income' : 'expense', amount: num(d.amount), currency: str(d.currency, 'EUR'),
    transaction_date: str(d.transaction_date), merchant: strOrNull(d.merchant), notes: strOrNull(d.notes),
    bucket_id: strOrNull(d.bucket_id), category_id: strOrNull(d.category_id), paid_by: strOrNull(d.paid_by),
    payment_method: strOrNull(d.payment_method), recurring_bill_id: strOrNull(d.recurring_bill_id),
  }
}

export function toTransactionPage(raw: unknown): TransactionPage {
  const d = asDict(raw)
  return { total: num(d.total), page: num(d.page ?? 1), page_size: num(d.page_size ?? 50), items: list(d.items).map(toTransactionRow) }
}

export const memberName = (m: Member): string => m.display_name || m.username || 'Member'

export function useHousehold(): CachedQuery<Household> {
  return useCachedQuery(keys.household(), async (signal) =>
    toHousehold(await unwrap(api.GET('/api/v1/settings/household', { signal }))))
}

export function useRecurringItems(): CachedQuery<RecurringItemOut[]> {
  return useCachedQuery(keys.recurring.list(), (signal) => unwrap(api.GET('/api/v1/recurring', { signal })))
}

export function useBuckets(): CachedQuery<Bucket[]> {
  return useCachedQuery(keys.buckets(), async (signal) => toBuckets(await unwrap(api.GET('/api/v1/buckets', { signal }))))
}

export function useCategories(): CachedQuery<Category[]> {
  return useCachedQuery(keys.categories(), async (signal) =>
    toCategories(await unwrap(api.GET('/api/v1/settings/categories', { signal }))))
}
