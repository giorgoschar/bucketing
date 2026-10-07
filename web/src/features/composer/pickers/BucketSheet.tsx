import { type Bucket, Sheet } from '../bridge'
import { rangeLabel } from '../dates'
import type { TxnType } from '../state'
import { Option, pickThenClose } from './Option'

export interface BucketSheetProps {
  open: boolean
  onClose: () => void
  buckets: Bucket[]
  type: TxnType
  selectedId: string | null
  onPick: (id: string | null) => void
}

/** Active budgets only; income offers "None" first and only budgets that track income. */
export function BucketSheet({ open, onClose, buckets, type, selectedId, onPick }: BucketSheetProps) {
  const pick = pickThenClose(onPick, onClose)
  const shown = buckets.filter((b) => b.status === 'active' && (type === 'expense' || b.show_income))
  return (
    <Sheet open={open} onClose={onClose} title="Budget">
      <div className="ck-options">
        {type === 'income' && <Option name="None" selected={selectedId === null} onPress={() => pick(null)} />}
        {shown.map((b) => (
          <Option key={b.id} name={b.name} sub={b.kind === 'event' ? rangeLabel(b.start_date, b.end_date) || null : null}
            selected={b.id === selectedId} onPress={() => pick(b.id)} />
        ))}
      </div>
    </Sheet>
  )
}
