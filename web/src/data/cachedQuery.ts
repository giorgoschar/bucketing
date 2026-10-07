import { useEffect, useState } from 'react'
import { useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { keyGeneration } from '../offline/crypto'
import { cacheEntry, cachePut } from '../offline/db'
import { getIdentity } from '../offline/identity'
import { useSession } from '../session/SessionProvider'
import { useOnline } from './online'

export interface CachedQuery<T> {
  data: T | undefined
  /** When the shown data was fetched (ms); 0 without data. */
  dataUpdatedAt: number
  /** The shown data came from the device cache, not from a fetch in this session. */
  fromCache: boolean
  /** Nothing to show yet, and it may still arrive. */
  isLoading: boolean
  isError: boolean
  offline: boolean
  /** Show "Offline · updated HH:MM": data is shown but we are offline or the last fetch failed. */
  stale: boolean
  /** Nothing to show and nothing coming: offline (or failing) with no saved copy. */
  noData: boolean
  refetch: () => void
}

/**
 * The device-cache key, "q:<household>:<hex SHA-256 of the JSON query key>". Scoped to the household so a
 * switch never shows another household's data. Cache keys are stored in plain text (only values are
 * sealed), so the query key is digested: search text and other user input in a key never reach the disk.
 */
export async function cacheKeyFor(householdId: string, key: QueryKey): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(key)))
  const hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
  return `q:${householdId}:${hex}`
}

/**
 * A TanStack query that renders the last saved copy at once (online or offline) and saves every
 * successful fetch to the encrypted device cache. `fetcher` must throw on failure (use `unwrap`).
 */
export function useCachedQuery<T>(
  key: QueryKey,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: { enabled?: boolean } = {},
): CachedQuery<T> {
  const qc = useQueryClient()
  const online = useOnline()
  const { me } = useSession()
  // The session's household; the queue identity covers the first render before SessionProvider's effect.
  const household = me?.household_id ?? getIdentity()?.household_id ?? null
  const hash = JSON.stringify(key)
  const [seed, setSeed] = useState<{ hash: string; at: number } | null>(null)
  const [checked, setChecked] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    const done = () => { if (live) setChecked(hash) }
    if (!household) {
      done()
      return () => { live = false }
    }
    cacheKeyFor(household, JSON.parse(hash) as QueryKey).then((storeKey) => cacheEntry<T>(storeKey)).then((row) => {
      if (!live) return
      const k = JSON.parse(hash) as QueryKey
      // Only fill an empty query: data that is already there (a fetch that landed first) is newer.
      if (row && !qc.getQueryState(k)?.dataUpdatedAt) {
        qc.setQueryData(k, row.value, { updatedAt: row.updatedAt })
        setSeed({ hash, at: row.updatedAt })
      }
      done()
    }, done)
    return () => { live = false }
  }, [qc, hash, household])

  const q = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      // Captured before the fetch and the digest: a wipe (sign-out) during either drops the write.
      const gen = keyGeneration()
      const data = await fetcher(signal)
      if (household) {
        // A racing wipe wins; nothing to persist.
        void cacheKeyFor(household, key).then((storeKey) => cachePut(storeKey, data, gen)).catch(() => {})
      }
      return data
    },
    networkMode: 'offlineFirst',
    enabled: opts.enabled ?? true,
  })

  const has = q.data !== undefined
  const cacheChecked = checked === hash
  // setQueryData clears `error` but not errorUpdatedAt: a failure newer than the shown data still counts.
  const lastFetchFailed = q.isError || q.errorUpdatedAt > q.dataUpdatedAt
  return {
    data: q.data,
    dataUpdatedAt: has ? q.dataUpdatedAt : 0,
    fromCache: has && seed?.hash === hash && q.dataUpdatedAt === seed.at,
    isLoading: !has && !(cacheChecked && (!online || q.isError)),
    isError: q.isError,
    offline: !online,
    stale: has && (!online || lastFetchFailed),
    noData: !has && cacheChecked && (!online || q.isError),
    refetch: () => { void q.refetch() },
  }
}
