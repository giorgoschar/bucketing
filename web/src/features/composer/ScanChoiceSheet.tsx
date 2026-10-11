import { Sheet } from './bridge'
import './pickers/pickers.css'

/** The Add form's one scan button opens this (Phase C spec §2.4): a receipt's QR, or a pantry item's barcode. */
export function ScanChoiceSheet({ open, onClose, onReceipt, onPantry }: {
  open: boolean; onClose: () => void; onReceipt: () => void; onPantry: () => void
}) {
  const choose = (go: () => void) => () => {
    onClose()
    go()
  }
  return (
    <Sheet open={open} onClose={onClose} title="Scan">
      <div className="ck-options">
        <button type="button" className="ck-option" onClick={choose(onReceipt)}>
          <span className="ck-option__main">
            <span className="ck-option__name">Receipt QR</span>
            <span className="ck-option__sub">Fill this entry from a myDATA receipt</span>
          </span>
        </button>
        <button type="button" className="ck-option" onClick={choose(onPantry)}>
          <span className="ck-option__main">
            <span className="ck-option__name">Pantry barcode</span>
            <span className="ck-option__sub">Look up an item and add it to your pantry</span>
          </span>
        </button>
      </div>
    </Sheet>
  )
}
