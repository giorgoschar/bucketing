import { Sheet } from '../bridge'
import { type Method, METHODS } from '../state'
import { METHOD_LABELS } from './labels'
import { Option, pickThenClose } from './Option'

export function MethodSheet({ open, onClose, selected, onPick }: {
  open: boolean; onClose: () => void; selected: Method; onPick: (m: Method) => void
}) {
  const pick = pickThenClose(onPick, onClose)
  return (
    <Sheet open={open} onClose={onClose} title="Payment method">
      <div className="ck-options">
        {METHODS.map((m) => <Option key={m} name={METHOD_LABELS[m]} selected={m === selected} onPress={() => pick(m)} />)}
      </div>
    </Sheet>
  )
}
