import { api } from '../../../api/client'
import type { components } from '../../../api/schema'
import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import type { RawBucket } from '../BucketSheet'

export type BucketSummary = components['schemas']['BucketSummary']
export type BucketOne = Omit<RawBucket, 'budget'> & { budget: number | null; status: string; balance: { income: number; expenses: number; net: number } }

// Under the ['buckets'] prefix, so an edit, an archive or a synced expense refreshes them.
/** GET /buckets/{id}: the bucket with its balance (untyped in OpenAPI, so the shape is here). */
export function useBucket(id: string) {
  return useCachedQuery(['buckets', 'one', id], async (signal) =>
    (await unwrap(api.GET('/api/v1/buckets/{bucket_id}', { params: { path: { bucket_id: id } }, signal }))) as unknown as BucketOne)
}

/** GET /buckets/{id}/summary: the trip and savings cards. */
export function useBucketSummary(id: string) {
  return useCachedQuery(['buckets', 'summary', id], (signal) =>
    unwrap(api.GET('/api/v1/buckets/{bucket_id}/summary', { params: { path: { bucket_id: id } }, signal })))
}
