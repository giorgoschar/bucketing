import { useRecurringItems } from '../../data/reads'
import { useToast } from '../../ui/Toast'
import { HOLD_MS, holdDelete, undoDelete } from './heldDeletes'
import { type Txn, useDeleteTransaction } from './hooks'

const MONTH = new Intl.DateTimeFormat('en-GB', { month: 'short' })

/** Delete with a 5 s Undo: the row hides at once, the DELETE goes when the toast ends. */
export function useDeleteWithUndo() {
  const del = useDeleteTransaction()
  const toast = useToast()
  const items = useRecurringItems().data
  return (t: Txn) => {
    holdDelete(t.id, () => void del.run({ id: t.id }))
    const bill = t.recurring_bill_id ? items?.find((i) => i.id === t.recurring_bill_id) : undefined
    const month = t.transaction_date ? MONTH.format(new Date(`${t.transaction_date}T12:00:00`)) : ''
    toast.show(bill ? `Deleted · ${bill.name} ${month} is expected again` : 'Deleted', {
      action: { label: 'Undo', onClick: () => undoDelete(t.id) },
      durationMs: HOLD_MS,
    })
  }
}
