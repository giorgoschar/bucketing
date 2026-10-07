import { useQueryClient } from '@tanstack/react-query'
import { keys } from '../../data/keys'
import { useToast } from '../../ui/Toast'
import { ACTIVITY_WRITES, undoBulk } from './hooks'

export type UndoSkip = { id: string; reason: string }

export function undoMessage(restored: number, skipped: number): string {
  return skipped ? `Restored ${restored} · ${skipped} changed since, left as they are` : `Restored ${restored}`
}

/** Undo a batch from anywhere (toast, detail history, Recent bulk changes). */
export function useUndoBulk(onDetails?: (skipped: UndoSkip[]) => void) {
  const qc = useQueryClient()
  const toast = useToast()
  return async (batchId: string) => {
    try {
      const r = await undoBulk(batchId)
      for (const key of ACTIVITY_WRITES) void qc.invalidateQueries({ queryKey: key }) // recurring.all is in it, for a restored bill
      toast.show(undoMessage(r.restored, r.skipped.length), {
        action: r.skipped.length && onDetails ? { label: 'Details', onClick: () => onDetails(r.skipped) } : undefined,
      })
    } catch (e) {
      void qc.invalidateQueries({ queryKey: keys.bulkRecent() }) // the Undo button goes away
      toast.show((e as Error).message, { tone: 'error' })
    }
  }
}
