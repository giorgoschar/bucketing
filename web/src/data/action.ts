import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient, type QueryKey } from '@tanstack/react-query'
import { api } from '../api/client'
import { enqueue, kick } from '../offline/queue'
import { toast } from '../ui/Toast'
import { detailOf } from './http'
import { inLane, laneLength } from './lanes'
import { isOnline } from './online'
import { isPending, markPending } from './pending'

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
  /**
   * When a failed send may go to the offline queue.
   * - 'always' (default): offline, a network error, a timeout, 408, 429 or 5xx all queue the change. Right
   *   for idempotent writes (mark done, skip, set amount, PUT an item): replaying one twice is harmless.
   * - 'offline-only': queue only when the browser is offline at send time. A failure while online is
   *   ambiguous (the server may have applied it), so roll back and say so instead of risking a duplicate.
   *   Non-idempotent creates must use this; item create (`POST /api/v1/recurring`) in particular.
   */
  queue?: 'always' | 'offline-only'
  /**
   * A row's send lane (polish P2). Writes in one lane are sent one after another, never overlapping; the
   * optimistic patch still applies at once. While the row has a change in the offline queue (its pendingId
   * is marked), a later write in the lane queues behind it instead of overtaking it online.
   */
  serial?: OrFn<V, string>
  /** Unused at runtime; carries the response type. */
  readonly _result?: T
}

interface Raw { data?: unknown; error?: unknown; response: Response }

const resolve = <V, R>(x: OrFn<V, R>, vars: V): R =>
  typeof x === 'function' ? (x as (v: V) => R)(vars) : x

/** A send that takes longer than this is abandoned and treated as a network error. */
export const SEND_TIMEOUT_MS = 15_000
/** The rejection for an ambiguous failure under queue: 'offline-only'. */
export const UNCONFIRMED_DETAIL = 'Couldn’t confirm the change; check and try again.'

function send(method: ActionMethod, path: string, body: unknown): Promise<Raw> {
  const ctrl = new AbortController()
  // A dynamic path goes through the typed client untyped, so the CSRF header and 401 handling still apply.
  const init = (body === undefined ? { signal: ctrl.signal } : { body, signal: ctrl.signal }) as never
  const p =
    method === 'POST' ? api.POST(path as never, init)
    : method === 'PUT' ? api.PUT(path as never, init)
    : method === 'PATCH' ? api.PATCH(path as never, init)
    : api.DELETE(path as never, init)
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      ctrl.abort()
      reject(new DOMException('The request timed out.', 'TimeoutError'))
    }, SEND_TIMEOUT_MS)
  })
  return Promise.race([p as unknown as Promise<Raw>, timeout]).finally(() => clearTimeout(timer))
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

  /** `online`: queued after a failure while online, so no online/visibility trigger will replay it: kick one. */
  const queue = async (online: boolean): Promise<ActionResult<T>> => {
    try {
      await enqueue({ method: s.method, path, body })
    } catch {
      rollback()
      const detail = 'Couldn’t save this change on the phone. Try again.'
      toast(detail, { tone: 'error' })
      return { status: 'rejected', code: 0, detail }
    }
    if (pendingId) markPending(pendingId)
    if (online) kick()
    return { status: 'queued' }
  }

  /** queue: 'offline-only' and the send failed while online: we can't tell whether it was applied. */
  const unconfirmed = (code: number): ActionResult<T> => {
    rollback()
    if (s.toastRejections !== false) toast(UNCONFIRMED_DETAIL, { tone: 'error' })
    invalidate()
    return { status: 'rejected', code, detail: UNCONFIRMED_DETAIL }
  }
  const offlineOnly = s.queue === 'offline-only'

  if (!isOnline()) return queue(false)
  const lane = s.serial === undefined ? undefined : resolve(s.serial, vars)
  if (!lane) return sendOnline()
  return inLane(lane, () => {
    // Waited behind an earlier write: the connection may have gone, or that write may sit in the queue.
    if (!isOnline()) return queue(false)
    if (pendingId && isPending(pendingId)) return queue(true)
    return sendOnline()
  })

  async function sendOnline(): Promise<ActionResult<T>> {
    let res: Raw
    try {
      res = await send(s.method, path, body)
    } catch {
      // Failed at the network level, or timed out.
      return offlineOnly ? unconfirmed(0) : queue(true)
    }
    if (res.response.ok) {
      // Later writes to the row are still to be sent: refetching now would briefly undo their patches.
      if (!lane || laneLength(lane) <= 1) invalidate()
      return { status: 'done', data: res.data as T }
    }
    const code = res.response.status
    if (queueable(code)) return offlineOnly ? unconfirmed(code) : queue(true)
    rollback()
    const detail = detailOf(res.error, code)
    if (code === 401) return { status: 'rejected', code, detail }
    if (s.toastRejections !== false) toast(detail, { tone: 'error' })
    invalidate()
    return { status: 'rejected', code, detail }
  }
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
