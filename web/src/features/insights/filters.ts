import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { InsightFilters } from './types'

const list = (v: string | null) => (v ? v.split(',').filter(Boolean) : [])

export function parseFilters(params: URLSearchParams): InsightFilters {
  return { bucketIds: list(params.get('bucket_ids')), categoryIds: list(params.get('category_ids')) }
}

export function writeFilters(params: URLSearchParams, f: InsightFilters): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const [key, ids] of [['bucket_ids', f.bucketIds], ['category_ids', f.categoryIds]] as const) {
    if (ids.length) next.set(key, ids.join(','))
    else next.delete(key)
  }
  return next
}

/** Budget and category filters live in the URL only (not storage): they are a one-off look. */
export function useInsightFilters(): [InsightFilters, (f: InsightFilters) => void] {
  const [params, setParams] = useSearchParams()
  const set = useCallback((f: InsightFilters) => setParams((prev) => writeFilters(prev, f), { replace: true }), [setParams])
  // A stable object per URL, so consumers' effects don't re-run on every render.
  const search = params.toString()
  const filters = useMemo(() => parseFilters(new URLSearchParams(search)), [search])
  return [filters, set]
}
