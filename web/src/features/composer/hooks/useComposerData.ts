import { api } from '../../../api/client'
import { useSession } from '../../../session/SessionProvider'
import {
  ApiError, type Bucket, type Category, editKey, keys, type Member, merchantsKey, toTransactionPage, unwrap,
  useBuckets, useCachedQuery, useCategories, useHousehold,
} from '../bridge'
import { fuelCategoryId } from '../defaults'
import type { CashMovements, Rule, Txn } from '../types'

export interface ComposerData {
  hh: string
  meId: string
  buckets: Bucket[]
  categories: Category[]
  members: Member[]
  householdCurrency: string
  rules: Rule[]
  /** Distinct recent merchants, newest first (suggestions only). */
  merchants: string[]
  fuelCategoryId: string | null
  /** Buckets, categories and household have data or are definitely unavailable: the composer can open. */
  ready: boolean
}

/**
 * 2d's list (2d spec §7.4), cached as the server sends it, since 2d's Settings shares this key; the
 * composer reads only id, pattern and category_id.
 */
const fetchRules = (signal: AbortSignal) => unwrap(api.GET('/api/v1/settings/category-rules', { signal }))

export function useComposerData(): ComposerData {
  const { me } = useSession()
  const household = useHousehold()
  const buckets = useBuckets()
  const categories = useCategories()
  const rules = useCachedQuery(keys.categoryRules(), fetchRules)
  const recent = useCachedQuery(merchantsKey, async (signal) =>
    toTransactionPage(await unwrap(api.GET('/api/v1/transactions', { params: { query: { page_size: 200 } }, signal }))),
  )
  const cats = categories.data ?? []
  const merchants = [...new Set((recent.data?.items ?? []).map((t) => t.merchant).filter((m): m is string => !!m))]
  return {
    hh: me?.household_id ?? '',
    meId: me?.id ?? '',
    buckets: buckets.data ?? [],
    categories: cats,
    members: household.data?.members ?? [],
    householdCurrency: household.data?.default_currency ?? 'EUR',
    rules: (rules.data ?? []).map((r): Rule => ({ id: r.id, pattern: r.pattern, category_id: r.category_id })),
    merchants,
    fuelCategoryId: fuelCategoryId(cats),
    ready: !buckets.isLoading && !categories.isLoading && !household.isLoading,
  }
}

/** The signed-in user's wallet in cents; null when never loaded. Mount only where cash is in play. */
export function useStash(): number | null {
  const q = useCachedQuery(keys.cashStash(), async (signal) =>
    (await unwrap(api.GET('/api/v1/cash/movements', { params: { query: { limit: 1 } }, signal }))) as CashMovements,
  )
  return q.data ? Math.round(Number(q.data.stash) * 100) : null
}

/** The stored transaction for edit and copy; a 404 is cached as null ("This entry no longer exists"). */
export function useTransaction(id: string): { txn: Txn | undefined; status: 'loading' | 'ready' | 'missing' | 'offline' } {
  const q = useCachedQuery<Txn | null>(editKey(id), async (signal) => {
    try {
      return (await unwrap(api.GET('/api/v1/transactions/{txn_id}', { params: { path: { txn_id: id } }, signal }))) as Txn
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null
      throw e
    }
  })
  if (q.data === null) return { txn: undefined, status: 'missing' }
  if (q.data) return { txn: q.data, status: 'ready' }
  return { txn: undefined, status: q.noData ? 'offline' : 'loading' }
}
