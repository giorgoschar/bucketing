import { Sheet } from './bridge'

export interface ConfirmSheetProps {
  open: boolean
  title: string
  confirmLabel: string
  cancelLabel: string
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmSheet({ open, title, confirmLabel, cancelLabel, danger, onConfirm, onCancel }: ConfirmSheetProps) {
  return (
    <Sheet open={open} onClose={onCancel} title={title}>
      <div className="composer__confirm">
        <button type="button" className={danger ? 'btn btn--lg btn--block btn--danger' : 'btn btn--lg btn--block btn--primary'}
          onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button type="button" className="btn btn--lg btn--block composer__cancel" onClick={onCancel}>{cancelLabel}</button>
      </div>
    </Sheet>
  )
}
