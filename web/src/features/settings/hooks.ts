import { useQuery, type QueryKey } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { components } from '../../api/schema'
import { type CachedQuery, useCachedQuery } from '../../data/cachedQuery'
import { ApiError, detailOf, unwrap } from '../../data/http'
import { settingsKeys } from '../../data/keys'
import { useOnline } from '../../data/online'
import type { Bucket, Category, Household, Member } from '../../data/types'
import { useSession } from '../../session/SessionProvider'

// 2a's narrowed reads, shared (one cache entry each).
export { useBuckets, useCategories, useHousehold } from '../../data/reads'
export type HouseholdInfo = Household
export type HouseholdMember = Member
export type BucketRef = Bucket
export type CategoryItem = Category

/* Untyped dict endpoints (no response_model): local types mirroring app/api/settings.py. */
export interface Profile { id: string; username: string; display_name: string; email: string | null; avatar_color: string | null; totp_enabled: boolean; household_id: string }
export interface TokenItem { id: string; name: string; prefix: string; scopes: string[]; can_classify?: boolean; default_bucket_id: string | null; last_used_at: string | null; created_at: string | null }
export type NotificationPrefs = components['schemas']['NotificationPrefsOut']
export type Security = components['schemas']['SecurityOut']
export type Rule = components['schemas']['CategoryRuleOut']

const useHh = () => useSession().me?.household_id ?? ''

/**
 * A read that lives only in memory: never written to the encrypted device cache, so it shows nothing
 * offline. For the security status (2FA, passkey, backup codes left): it is fetched fresh every time.
 * Same shape as useCachedQuery so QueryView renders it.
 */
export function useLiveQuery<T>(key: QueryKey, fetcher: (signal: AbortSignal) => Promise<T>): CachedQuery<T> {
  const online = useOnline()
  const q = useQuery({ queryKey: key, queryFn: ({ signal }) => fetcher(signal), networkMode: 'offlineFirst', gcTime: 0, staleTime: 0 })
  const has = q.data !== undefined
  return {
    data: q.data,
    dataUpdatedAt: has ? q.dataUpdatedAt : 0,
    fromCache: false,
    isLoading: !has && online && !q.isError,
    isError: q.isError,
    offline: !online,
    stale: has && (!online || q.isError),
    noData: !has && (!online || q.isError),
    refetch: () => { void q.refetch() },
  }
}

export const useProfile = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.profile(hh), async (signal) => (await unwrap(api.GET('/api/v1/settings/profile', { signal }))) as unknown as Profile)
}
export const useSecurity = () => {
  const hh = useHh()
  return useLiveQuery(settingsKeys.security(hh), (signal): Promise<Security> => unwrap(api.GET('/api/v1/settings/security', { signal })))
}
export const useRules = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.rules(hh), (signal): Promise<Rule[]> => unwrap(api.GET('/api/v1/settings/category-rules', { signal })))
}
/** The token list carries names and prefixes only; a token's full value is shown once, never fetched or stored. */
export const useTokens = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.tokens(hh), async (signal) => (await unwrap(api.GET('/api/v1/settings/tokens', { signal }))) as unknown as TokenItem[])
}

/** Alert types and push devices. Null when the server has no such endpoint (an older backend). */
export const useNotificationPrefs = () => {
  const hh = useHh()
  return useCachedQuery(settingsKeys.notifications(hh), async (signal): Promise<NotificationPrefs | null> => {
    const { data, error, response } = await api.GET('/api/v1/settings/notifications', { signal })
    if (response.status === 404) return null
    if (!response.ok) throw new ApiError(response.status, detailOf(error, response.status))
    return data ?? null
  })
}
