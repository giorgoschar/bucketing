import type { ReactNode } from 'react'
import './ui-2c.css'

type Props = {
  count: number
  total?: ReactNode
  disabled?: boolean
  disabledReason?: string
  actions: { label: string; onClick: () => void }[]
}

/** The floating bar for a multi-select: the count, an optional total, and one button per bulk action.
 * It sits above the tab bar, inside the safe area. */
export function BulkBar({ count, total, disabled, disabledReason, actions }: Props) {
  return (
    <div className="bulkbar" role="toolbar" aria-label={`Bulk actions for ${count} selected`}>
      <span className="bulkbar__sum">
        <span><b className="num">{count}</b>{total !== undefined && <> · <span className="num">{total}</span></>}</span>
        {disabled && disabledReason && <span className="bulkbar__why">{disabledReason}</span>}
      </span>
      {actions.map((a) => (
        <button key={a.label} type="button" className="bulkbar__btn" disabled={disabled || count === 0} onClick={a.onClick}>
          {a.label}
        </button>
      ))}
    </div>
  )
}
