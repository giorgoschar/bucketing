import { useQueryClient } from '@tanstack/react-query'
import { isOnline } from '../../data/online'
import { markPending } from '../../data/pending'
import { useRecurringItems } from '../../data/reads'
import { enqueue } from '../../offline/queue'
import { useToast } from '../../ui/Toast'
import { HOLD_MS, holdDelete, settle, undoDelete } from './heldDeletes'
import { ACTIVITY_WRITES, deleteKeepalive, patchRows, type Txn, useDeleteTransaction } from './hooks'

const MONTH = new Intl.DateTimeFormat('en-GB', { month: 'short' })

/** Delete with a 5 s Undo: the row hides at once, the DELETE goes when the toast ends. */
export function useDeleteWithUndo() {
  const del = useDeleteTransaction()
  const qc = useQueryClient()
  const toast = useToast()
  const items = useRecurringItems().data
  /** The page is going away: a keepalive fetch survives teardown where useAction's request may not.
   * If it can't reach the server, fall back to the offline queue. */
  const sendOnTeardown = async (id: string) => {
    patchRows(qc, id, () => null)
    const refresh = () => { for (const key of ACTIVITY_WRITES) void qc.invalidateQueries({ queryKey: key }) }
    try {
      await deleteKeepalive(id) // a 404 means it is already gone; any other failure shows on the refetch
      refresh()
    } catch {
      try {
        await enqueue({ method: 'DELETE', path: `/api/v1/transactions/${id}` })
        markPending(id)
      } catch {
        refresh()
      }
    }
  }
  return (t: Txn) => {
    // Undo works for as long as its toast is on screen, even past 5 s while a finger rests on it (P3 M5).
    let toastShown = true
    holdDelete(t.id, (reason) => {
      // Flushed early (page hidden): the delete is gone, so an Undo still on screen would do nothing.
      if (reason === 'hidden') {
        toast.dismiss()
        if (isOnline()) return void sendOnTeardown(t.id)
      }
      void del.run({ id: t.id }) // offline it queues; on the timer it is an ordinary delete
    }, HOLD_MS, () => toastShown)
    const bill = t.recurring_bill_id ? items?.find((i) => i.id === t.recurring_bill_id) : undefined
    const month = t.transaction_date ? MONTH.format(new Date(`${t.transaction_date}T12:00:00`)) : ''
    toast.show(bill ? `Deleted · ${bill.name} ${month} is expected again` : 'Deleted', {
      action: { label: 'Undo', onClick: () => undoDelete(t.id) },
      durationMs: HOLD_MS,
      onClose: () => {
        toastShown = false
        settle(t.id)
      },
    })
  }
}
