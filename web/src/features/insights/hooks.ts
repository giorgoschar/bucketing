import { api } from '../../api/client'
import { useCachedQuery } from '../../data/cachedQuery'
import { unwrap } from '../../data/http'
import { insightsKeys } from '../../data/keys'
import { useHousehold } from '../../data/reads'
import { useSession } from '../../session/SessionProvider'
import { type Lens, lensQuery } from './lens'
import { type Period, periodKey, periodQuery } from './period'
import { type CategoryDetail, type InsightFilters, type InsightsData, type PersonShare, filtersKey } from './types'

// 2a's reads, shared so Insights, Plan and Settings use one cache entry each.
export { useCategoriesVsUsual, usePlanMonth } from '../plan/hooks'
export const useMembers = useHousehold

export const useHouseholdId = () => useSession().me?.household_id ?? ''

/** Filter params only when set: an empty list means "all", so nothing is sent. */
function filterQuery(f: InsightFilters): { bucket_ids?: string; category_ids?: string } {
  return {
    ...(f.bucketIds.length ? { bucket_ids: f.bucketIds.join(',') } : {}),
    ...(f.categoryIds.length ? { category_ids: f.categoryIds.join(',') } : {}),
  }
}

/** `months` (6, 12 or 24) sets the length of monthly_in_out (Phase A §3.9); left out, the server's default of 6.
 *  Only the desktop Months table asks for 12, so the phone never sends it. */
export function useInsights(period: Period, lens: Lens, filters: InsightFilters, months?: 12 | 24) {
  const hh = useHouseholdId()
  return useCachedQuery(insightsKeys.overview(hh, periodKey(period), lens, filtersKey(filters), months), async (signal) =>
    (await unwrap(
      api.GET('/api/v1/insights', {
        params: { query: { ...periodQuery(period), ...lensQuery(lens), ...filterQuery(filters), ...(months === undefined ? {} : { months: String(months) }) } },
        signal,
      }),
    )) as unknown as InsightsData,
  )
}

/** Paid out vs my share; disabled (no request) for the Household lens. */
export function usePersonShare(period: Period, userId: string | null) {
  const hh = useHouseholdId()
  return useCachedQuery(
    insightsKeys.person(hh, periodKey(period), userId ?? 'household'),
    (signal): Promise<PersonShare> =>
      unwrap(api.GET('/api/v1/insights/person', { params: { query: { user_id: userId ?? '', ...periodQuery(period) } }, signal })),
    { enabled: !!userId },
  )
}

export function useCategoryDetail(id: string, period: Period, lens: Lens) {
  const hh = useHouseholdId()
  return useCachedQuery(insightsKeys.category(hh, id, periodKey(period), lens), (signal): Promise<CategoryDetail> =>
    unwrap(
      api.GET('/api/v1/insights/categories/{category_id}', {
        params: { path: { category_id: id }, query: { ...periodQuery(period), ...lensQuery(lens) } },
        signal,
      }),
    ),
  )
}
