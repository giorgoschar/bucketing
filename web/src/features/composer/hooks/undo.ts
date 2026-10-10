import { useCallback } from 'react'
import { useAction } from '../../../data/action'
import { isOnline } from '../../../data/online'
import { toast } from '../../../ui/Toast'
import { afterTxnWrite } from '../bridge'
import { affects } from '../../../data/keys'
import { pendingStore } from './pendingStore'

const UNDO_FAILED = "Couldn't undo. Check the entry."
const UNDO_OFFLINE = 'Undo needs a connection.'

/**
 * Undo of an online save (spec §4.12): DELETE the new row. Runs from a toast, after the composer closed.
 * Online only (spec decision 8): never queued. A 404 means the row is already gone, so it counts as done;
 * any other failure, ambiguous or not, brings the row back and says the undo failed. Resolves true when the row is gone.
 */
export function useUndoCreate(): (id: string) => Promise<boolean> {
  const { run } = useAction<string>({
    method: 'DELETE',
    path: (id) => `/api/v1/transactions/${id}`,
    // The undone entry may be a cash expense (cash spec §4.7): refresh the cash reads too.
    invalidates: [...afterTxnWrite, ...affects.cash],
    queue: 'offline-only',
    toastRejections: false,
  })
  return useCallback(
    async (id: string) => {
      if (!isOnline()) {
        toast(UNDO_OFFLINE, { tone: 'error' })
        return false
      }
      pendingStore.hide(id)
      const r = await run(id)
      // 'queued' only if the browser went offline between the check and the send: the DELETE will replay
      // (a replayed DELETE's 404 is done), so the row stays hidden.
      if (r.status !== 'rejected' || r.code === 404) return true
      pendingStore.unhide(id)
      if (r.code === 401) return false // the session handler takes over
      toast(UNDO_FAILED, { tone: 'error' })
      return false
    },
    [run],
  )
}
