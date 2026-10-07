import { useCallback } from 'react'
import { api } from '../../../api/client'
import type { Duplicate } from '../types'

export const DUPLICATE_TIMEOUT_MS = 2000

/** Advisory, never blocking (spec §4.11): offline, an error or 2 s without an answer all mean "none". */
export function useDuplicateCheck() {
  return useCallback(async (q: { amount: string; transaction_date: string; bucket_id: string | null }): Promise<Duplicate[]> => {
    if (!navigator.onLine) return []
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const timeout = new Promise<Duplicate[]>((resolve) => {
      timer = setTimeout(() => {
        ctl.abort()
        resolve([])
      }, DUPLICATE_TIMEOUT_MS)
    })
    const request = api
      .GET('/api/v1/transactions/check-duplicate', {
        params: { query: { amount: q.amount, transaction_date: q.transaction_date, bucket_id: q.bucket_id ?? '' } },
        signal: ctl.signal,
      })
      .then(({ data, response }) => (response.ok && data ? (data.duplicates as Duplicate[]) : []))
      .catch(() => [] as Duplicate[])
    try {
      return await Promise.race([request, timeout])
    } finally {
      clearTimeout(timer)
    }
  }, [])
}
