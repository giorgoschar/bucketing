import { type Bucket, Sheet } from '../bridge'
import { rangeLabel } from '../dates'
import type { TxnType } from '../state'
import { FilterField, Option, pickThenClose, useFilterBox } from './Option'
import { fold } from '../defaults'

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
  const box = useFilterBox()
  const close = () => { box.setText(''); onClose() }
  const pick = pickThenClose(onPick, close)
  const shown = buckets.filter((b) => b.status === 'active' && (type === 'expense' || b.show_income) && fold(b.name).includes(box.q))
  return (
    <Sheet open={open} onClose={close} title="Budget" initialFocus={box.active ? box.ref : undefined}>
      <FilterField label="Search budgets" box={box} onEnter={() => shown[0] && pick(shown[0].id)} />
      <div className="ck-options">
        {type === 'income' && box.q === '' && <Option name="None" selected={selectedId === null} onPress={() => pick(null)} />}
        {shown.map((b) => (
          <Option key={b.id} name={b.name} sub={b.kind === 'event' ? rangeLabel(b.start_date, b.end_date) || null : null}
            selected={b.id === selectedId} onPress={() => pick(b.id)} />
        ))}
      </div>
    </Sheet>
  )
}
