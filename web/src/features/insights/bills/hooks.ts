import { useCachedQuery } from '../../../data/cachedQuery'
import { unwrap } from '../../../data/http'
import { affects, keys } from '../../../data/keys'
import { useOnlineAction } from '../../../data/onlineAction'
import { fetchJson } from '../../../data/rawJson'
import { api } from '../../../api/client'
import type { BillRow, ItemHistoryOut } from './types'

// The generated schema does not know the Phase A endpoints yet, so the path is not in its `paths` type.
// This one cast carries them until integration runs `npm run gen:api` and replaces it with api.GET(...).
type Raw = { data?: unknown; error?: unknown; response: Response }
const get = (path: string, signal: AbortSignal): Promise<Raw> =>
  (api as unknown as { GET: (p: string, init: { signal: AbortSignal }) => Promise<Raw> }).GET(path, { signal })

/** GET /api/v1/insights/bills (spec §3.6). Ignores the Insights lens and period. */
export function useBills() {
  return useCachedQuery(keys.insightsBills(), async (signal) => (await unwrap(get('/api/v1/insights/bills', signal))) as BillRow[])
}

/** GET /api/v1/recurring/{id}/history (spec §3.5). */
export function useItemHistory(id: string) {
  return useCachedQuery(keys.itemHistory(id), async (signal) =>
    (await unwrap(get(`/api/v1/recurring/${encodeURIComponent(id)}/history`, signal))) as ItemHistoryOut)
}

/** PUT /api/v1/recurring/entries/{id}/usage (spec §3.3). Online only: never queued, so a failure changes nothing. */
export function useSetUsage(itemId: string) {
  const act = useOnlineAction()
  return (entryId: string, usage: number | null) =>
    act(() => fetchJson('PUT', `/api/v1/recurring/entries/${encodeURIComponent(entryId)}/usage`, { usage }), {
      // `usage` rides on EntryOut too (Plan, Home): refresh what every entry write refreshes, plus this history.
      invalidates: [keys.itemHistory(itemId), keys.insightsBills(), ...affects.entry],
      success: 'Usage saved',
    })
}
