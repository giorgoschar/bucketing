import { type Member, Sheet } from '../bridge'
import { memberName } from './labels'
import { Option, pickThenClose } from './Option'

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
  const pick = pickThenClose(onPick, onClose)
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <div className="ck-options">
        {members.map((m) => (
          <Option key={m.user_id} name={memberName(m)}
            lead={<span className="ck-glyph ck-glyph--person">{memberName(m).slice(0, 1).toUpperCase()}</span>}
            selected={!ownShare && m.user_id === selectedId} onPress={() => pick(m.user_id)} />
        ))}
        {allowOwnShare && (
          <Option name="Each paid own share" selected={ownShare} onPress={onOwnShare} />
        )}
      </div>
    </Sheet>
  )
}
