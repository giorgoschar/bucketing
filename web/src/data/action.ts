import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { api } from '../api/client'
import { enqueue } from '../offline/queue'
import { toast } from '../ui/Toast'
import { detailOf } from './http'
import { isOnline } from './online'
import { markPending } from './pending'

export type ActionMethod = 'POST' | 'PUT' | 'PATCH' | 'DELETE'
export type ActionResult<T> =
  | { status: 'done'; data: T }
  | { status: 'queued' }
  | { status: 'rejected'; code: number; detail: string }

type OrFn<V, R> = R | ((vars: V) => R)

export interface ActionSpec<V, T> {
  method: ActionMethod
  /** A concrete path ("/api/v1/recurring/entries/e1/done"): the queue replays exactly this. */
  path: OrFn<V, string>
  body?: OrFn<V, unknown>
  /** Patch cached queries at once. Must stay inside `invalidates` (that is what rollback restores). */
  optimistic?: (qc: QueryClient, vars: V) => void
  invalidates: readonly QueryKey[]
  /** The row to mark "Waiting to sync" when the change is queued. */
  pendingId?: OrFn<V, string | undefined>
  /** false: the caller shows the rejection itself (Entry sheet's Fixed-cost undo). */
  toastRejections?: boolean
  /** Unused at runtime; carries the response type. */
  readonly _result?: T
}

interface Raw { data?: unknown; error?: unknown; response: Response }

const resolve = <V, R>(x: OrFn<V, R>, vars: V): R =>
  typeof x === 'function' ? (x as (v: V) => R)(vars) : x

function send(method: ActionMethod, path: string, body: unknown): Promise<Raw> {
  // A dynamic path goes through the typed client untyped, so the CSRF header and 401 handling still apply.
  const init = (body === undefined ? {} : { body }) as never
  const p =
    method === 'POST' ? api.POST(path as never, init)
    : method === 'PUT' ? api.PUT(path as never, init)
    : method === 'PATCH' ? api.PATCH(path as never, init)
    : api.DELETE(path as never, init)
  return p as unknown as Promise<Raw>
}

const queueable = (status: number) => status >= 500 || status === 408 || status === 429

/** One write: optimistic patch, then the API, the offline queue, or a rollback (spec §3.2). Exported for tests. */
export async function perform<V, T>(qc: QueryClient, s: ActionSpec<V, T>, vars: V): Promise<ActionResult<T>> {
  const path = resolve(s.path, vars)
  const body = s.body === undefined ? undefined : resolve(s.body, vars)
  const pendingId = s.pendingId === undefined ? undefined : resolve(s.pendingId, vars)

  await Promise.all(s.invalidates.map((queryKey) => qc.cancelQueries({ queryKey })))
  const snapshot = s.invalidates.flatMap((queryKey) => qc.getQueriesData({ queryKey }))
  s.optimistic?.(qc, vars)
  const rollback = () => { for (const [k, data] of snapshot) qc.setQueryData(k, data) }
  const invalidate = () => { for (const queryKey of s.invalidates) void qc.invalidateQueries({ queryKey }) }

  const queue = async (): Promise<ActionResult<T>> => {
    try {
      await enqueue({ method: s.method, path, body })
    } catch {
      rollback()
      const detail = 'Couldn’t save this change on the phone. Try again.'
      toast(detail, { tone: 'error' })
      return { status: 'rejected', code: 0, detail }
    }
    if (pendingId) markPending(pendingId)
    return { status: 'queued' }
  }

  if (!isOnline()) return queue()
  let res: Raw
  try {
    res = await send(s.method, path, body)
  } catch {
    return queue() // failed at the network level
  }
  if (res.response.ok) {
    invalidate()
    return { status: 'done', data: res.data as T }
  }
  const code = res.response.status
  if (queueable(code)) return queue()
  rollback()
  const detail = detailOf(res.error, code)
  if (code === 401) return { status: 'rejected', code, detail }
  if (s.toastRejections !== false) toast(detail, { tone: 'error' })
  invalidate()
  return { status: 'rejected', code, detail }
}

export function useAction<V = void, T = unknown>(spec: ActionSpec<V, T>): { run: (vars: V) => Promise<ActionResult<T>>; busy: boolean } {
  const qc = useQueryClient()
  const ref = useRef(spec)
  useEffect(() => { ref.current = spec })
  const [busy, setBusy] = useState(false)
  const run = useCallback(async (vars: V) => {
    setBusy(true)
    try {
      return await perform(qc, ref.current, vars)
    } finally {
      setBusy(false)
    }
  }, [qc])
  return { run, busy }
}
