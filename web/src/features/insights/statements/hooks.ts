import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import { useCachedQuery } from '../../../data/cachedQuery'
import { ApiError, unwrap } from '../../../data/http'
import { keys } from '../../../data/keys'
import { useOnlineAction } from '../../../data/onlineAction'
import type { StatementListOut, StatementOut } from './types'

// The Phase B routes are not in the generated schema yet, so these two are the ONLY casts in the feature: the typed
// client, called with paths it does not know. Drop them (and call api.GET / api.POST directly) after `npm run gen:api`.
interface RawResult { data?: unknown; error?: unknown; response: Response }
type RawGet = (path: string, init: { signal?: AbortSignal }) => Promise<RawResult>
type RawPost = (path: string, init?: object) => Promise<RawResult>
const rawGet = api.GET as unknown as RawGet
const rawPost = api.POST as unknown as RawPost

/** A YYYY-MM month. Only a malformed one is refused here: whether it is past is the server's call (§3.2), so a
 *  device clock or time zone that disagrees with the household's cannot lock a month out. */
export const isMonth = (month: string): boolean => /^\d{4}-(0[1-9]|1[0-2])$/.test(month)

/** GET /api/v1/insights/statements (§3.3): the review banner and every past month. Household-wide. */
export function useStatements() {
  return useCachedQuery(keys.statements(), (signal) =>
    unwrap(rawGet('/api/v1/insights/statements', { signal })) as Promise<StatementListOut>)
}

/** GET /api/v1/insights/statements/{month} (§3.2). The server's 400 or 404 (not a past month) is cached as `null`,
 *  which the page shows as "No statement for this month yet." */
export function useStatement(month: string) {
  return useCachedQuery<StatementOut | null>(
    keys.statement(month),
    async (signal) => {
      try {
        return await (unwrap(rawGet(`/api/v1/insights/statements/${encodeURIComponent(month)}`, { signal })) as Promise<StatementOut>)
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 400)) return null
        throw e
      }
    },
    { enabled: isMonth(month) },
  )
}

/** POST /api/v1/insights/statements/{month}/review (§3.4). Online only; the answer replaces the cached page.
 *  Through the API client, so an expired session (401) is announced like everywhere else. */
export function useMarkReviewed(month: string) {
  const act = useOnlineAction()
  const qc = useQueryClient()
  return async () => {
    const out = await act(
      () => rawPost(`/api/v1/insights/statements/${encodeURIComponent(month)}/review`) as Promise<RawResultOf<StatementOut>>,
      // The page is replaced by the answer below; only the list (the review banner, the marks) needs a refetch.
      { invalidates: [keys.statements()] },
    )
    if (out.ok && out.data) qc.setQueryData(keys.statement(month), out.data)
    return out
  }
}
type RawResultOf<T> = { data?: T; error?: unknown; response: Response }

/** The recurring entries due on one day (the same read Plan uses), so an open entry can open Plan's sheet in place. */
export function useEntriesOn(date: string | null) {
  const day = date ?? ''
  return useCachedQuery(
    keys.recurring.entries(day, day),
    (signal) => unwrap(api.GET('/api/v1/recurring/entries', { params: { query: { from: day, to: day } }, signal })),
    { enabled: date !== null },
  )
}
