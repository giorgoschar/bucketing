import { Sheet } from '../bridge'
import { CURRENCIES, currencyName, currencySymbol } from '../currencies'
import { Option, pickThenClose } from './Option'

export function CurrencySheet({ open, onClose, selected, onPick }: {
  open: boolean; onClose: () => void; selected: string; onPick: (code: string) => void
}) {
  const pick = pickThenClose(onPick, onClose)
  return (
    <Sheet open={open} onClose={onClose} title="Currency">
      <div className="ck-options">
        {CURRENCIES.map((code) => (
          <Option key={code} name={`${code} · ${currencyName(code)}`}
            lead={<span className="ck-glyph ck-glyph--cur">{currencySymbol(code)}</span>}
            selected={code === selected} onPress={() => pick(code)} />
        ))}
      </div>
    </Sheet>
  )
}
