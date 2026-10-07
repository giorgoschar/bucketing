import { useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { api } from '../../../api/client'
import { enqueue } from '../../../offline/queue'
import { afterTxnWrite } from '../bridge'
import { pendingStore } from './pendingStore'

/** Undo of an online save (spec §4.12): DELETE the new row. Runs from a toast, after the composer closed. */
export function useUndoCreate(): (id: string) => Promise<void> {
  const qc = useQueryClient()
  return useCallback(
    async (id: string) => {
      pendingStore.hide(id)
      try {
        const { response } = await api.DELETE('/api/v1/transactions/{txn_id}', { params: { path: { txn_id: id } } })
        if (!response.ok && response.status !== 404) pendingStore.unhide(id)
      } catch {
        await enqueue({ method: 'DELETE', path: `/api/v1/transactions/${id}` }).catch(() => pendingStore.unhide(id))
      }
      await Promise.all(afterTxnWrite.map((queryKey) => qc.invalidateQueries({ queryKey })))
    },
    [qc],
  )
}
