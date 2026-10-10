import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/client'
import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import { keys } from '../../../data/keys'
import { useOnlineAction } from '../../../data/onlineAction'
import { fetchJson } from '../../../data/rawJson'
import { todayISO } from '../../../ui/format'
import type { StatementListOut, StatementOut } from './types'

// The Phase B routes are not in the generated schema yet, so this is the ONE cast in the feature: the typed
// client, called with a path it does not know. Drop it (and use api.GET directly) after `npm run gen:api`.
type RawGet = (path: string, init: { signal?: AbortSignal }) => Promise<{ data?: unknown; error?: unknown; response: Response }>
const rawGet = api.GET as unknown as RawGet

/** A past month as the route takes it: YYYY-MM, strictly before the current one (§3.2). */
export function isPastMonth(month: string, today: string = todayISO()): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(month) && month < today.slice(0, 7)
}

/** GET /api/v1/insights/statements (§3.3): the review banner and every past month. Household-wide. */
export function useStatements() {
  return useCachedQuery(keys.statements(), (signal) =>
    unwrap(rawGet('/api/v1/insights/statements', { signal })) as Promise<StatementListOut>)
}

/** GET /api/v1/insights/statements/{month} (§3.2). Not asked for a month the server would refuse. */
export function useStatement(month: string) {
  return useCachedQuery(
    keys.statement(month),
    (signal) => unwrap(rawGet(`/api/v1/insights/statements/${encodeURIComponent(month)}`, { signal })) as Promise<StatementOut>,
    { enabled: isPastMonth(month) },
  )
}

/** POST /api/v1/insights/statements/{month}/review (§3.4). Online only; the answer replaces the cached page. */
export function useMarkReviewed(month: string) {
  const act = useOnlineAction()
  const qc = useQueryClient()
  return async () => {
    const out = await act(
      () => fetchJson<StatementOut>('POST', `/api/v1/insights/statements/${encodeURIComponent(month)}/review`),
      { invalidates: [keys.statementsAll()], success: 'Marked as reviewed' },
    )
    if (out.ok && out.data) qc.setQueryData(keys.statement(month), out.data)
    return out
  }
}
