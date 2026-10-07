/** Errors and response unwrapping for openapi-fetch results (which never throw on HTTP errors). */

export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** The server's message for a failed request, made safe to show in a toast. */
export function detailOf(error: unknown, status?: number): string {
  const detail = typeof error === 'object' && error !== null ? (error as { detail?: unknown }).detail : undefined
  if (typeof detail === 'string' && detail.trim()) return detail
  // FastAPI's 422: a list of {loc, msg, type}. Never show "[object Object]".
  if (Array.isArray(detail)) return 'Some values aren’t valid. Check them and try again.'
  if (status === 401) return 'Your session has ended. Sign in again.'
  return status ? `Something went wrong (HTTP ${status}). Try again.` : 'Something went wrong. Try again.'
}

interface Raw { data?: unknown; error?: unknown; response: Response }

/** For useCachedQuery fetchers: the data on 2xx, an ApiError otherwise (so TanStack sees a failure). */
export async function unwrap<R extends Raw>(p: Promise<R>): Promise<NonNullable<R['data']>> {
  const { data, error, response } = await p
  if (!response.ok) throw new ApiError(response.status, detailOf(error, response.status))
  return data as NonNullable<R['data']>
}

/** Worth retrying a read: a network error, a timeout or a server-side failure. A 4xx (401 above all) never is. */
export function isRetryable(err: unknown): boolean {
  if (err instanceof ApiError) return err.status >= 500 || err.status === 408 || err.status === 429
  if (err instanceof DOMException && err.name === 'AbortError') return false
  return true // fetch's TypeError: no connection
}
