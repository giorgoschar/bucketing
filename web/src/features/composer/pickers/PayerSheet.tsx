import { type Member, Sheet } from '../bridge'
import { memberName } from './labels'
import { FilterField, Option, pickThenClose, useFilterBox } from './Option'
import { fold } from '../defaults'

export interface PayerSheetProps {
  open: boolean
  onClose: () => void
  title: 'Payer' | 'Received by'
  members: Member[]
  selectedId: string | null
  ownShare: boolean
  /** Expense, more than one member, Took from is Not tracked. */
  allowOwnShare: boolean
  onPick: (userId: string) => void
  /** The parent decides what opens next (the split sheet in own-share mode). */
  onOwnShare: () => void
}

export function PayerSheet({ open, onClose, title, members, selectedId, ownShare, allowOwnShare, onPick, onOwnShare }: PayerSheetProps) {
  const box = useFilterBox()
  const close = () => { box.setText(''); onClose() }
  const pick = pickThenClose(onPick, close)
  const shown = members.filter((m) => fold(memberName(m)).includes(box.q))
  return (
    <Sheet open={open} onClose={close} title={title} initialFocus={box.active ? box.ref : undefined}>
      <FilterField label="Filter people" box={box} onEnter={() => shown[0] && pick(shown[0].user_id)} />
      <div className="ck-options">
        {shown.map((m) => (
          <Option key={m.user_id} name={memberName(m)}
            lead={<span className="ck-glyph ck-glyph--person">{memberName(m).slice(0, 1).toUpperCase()}</span>}
            selected={!ownShare && m.user_id === selectedId} onPress={() => pick(m.user_id)} />
        ))}
        {allowOwnShare && box.q === '' && (
          <Option name="Each paid own share" selected={ownShare} onPress={onOwnShare} />
        )}
      </div>
    </Sheet>
  )
}
