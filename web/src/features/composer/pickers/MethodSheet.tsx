import { Sheet } from '../bridge'
import { type Method, METHODS } from '../state'
import { METHOD_LABELS } from './labels'
import { FilterField, Option, pickThenClose, useFilterBox } from './Option'
import { fold } from '../defaults'

export function MethodSheet({ open, onClose, selected, onPick }: {
  open: boolean; onClose: () => void; selected: Method; onPick: (m: Method) => void
}) {
  const box = useFilterBox()
  const close = () => { box.setText(''); onClose() }
  const pick = pickThenClose(onPick, close)
  const shown = METHODS.filter((m) => fold(METHOD_LABELS[m]).includes(box.q))
  return (
    <Sheet open={open} onClose={close} title="Payment method" initialFocus={box.active ? box.ref : undefined}>
      <FilterField label="Search methods" box={box} onEnter={() => shown[0] && pick(shown[0])} />
      <div className="ck-options">
        {shown.map((m) => <Option key={m} name={METHOD_LABELS[m]} selected={m === selected} onPress={() => pick(m)} />)}
      </div>
    </Sheet>
  )
}
