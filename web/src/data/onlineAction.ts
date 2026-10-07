import { type QueryKey, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useToast } from '../ui/Toast'
import { detailOf } from './http'
import { isOnline } from './online'
import type { RawResult } from './rawJson'

export const OFFLINE_MESSAGE = "You're offline. This change needs a connection."
export const RATE_MESSAGE = 'Too many attempts. Try again in a minute.'

export type OnlineOutcome<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; status: number | null; message: string; kind: 'offline' | 'rate' | 'rejected' | 'auth' }

/** Settings writes are never queued (2d §6.2): offline or a network failure changes nothing. */
export async function runOnline<T>(call: () => Promise<RawResult<T>>, online: () => boolean = isOnline): Promise<OnlineOutcome<T>> {
  const offline = { ok: false as const, status: null, kind: 'offline' as const, message: OFFLINE_MESSAGE }
  if (!online()) return offline
  let res: RawResult<T>
  try {
    res = await call()
  } catch {
    return offline
  }
  const { status } = res.response
  if (res.response.ok) return { ok: true, status, data: res.data as T }
  if (status === 401) return { ok: false, status, kind: 'auth', message: '' }
  if (status === 429) return { ok: false, status, kind: 'rate', message: RATE_MESSAGE }
  if (status >= 500) return { ...offline, status }
  return { ok: false, status, kind: 'rejected', message: detailOf(res.error, status) }
}

/** Run a write online only; toast its failure as an error (except 401, which Phase 1's session handles);
 *  invalidate keys on success. The caller keeps its sheet open when `ok` is false. */
export function useOnlineAction() {
  const qc = useQueryClient()
  const toast = useToast()
  return useCallback(
    async <T,>(call: () => Promise<RawResult<T>>, opts: { invalidates?: readonly QueryKey[]; success?: string } = {}) => {
      const out = await runOnline(call)
      if (out.ok) {
        await Promise.all((opts.invalidates ?? []).map((queryKey) => qc.invalidateQueries({ queryKey })))
        if (opts.success) toast.show(opts.success)
      } else if (out.kind !== 'auth') {
        toast.show(out.message, { tone: 'error' })
      }
      return out
    },
    [qc, toast],
  )
}
