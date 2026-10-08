import type { ReactNode } from 'react'

export interface ListRowProps {
  title: ReactNode
  subtitle?: ReactNode
  /** An icon tile or avatar on the left. */
  leading?: ReactNode
  /** Usually a <Money>; right-aligned. */
  trailing?: ReactNode
  badges?: ReactNode
  /** Makes the row a <button>; without it the row is static. */
  onClick?: () => void
  /** Greyed (paused items). Pair it with a text badge: colour is never the only signal. */
  muted?: boolean
  ariaLabel?: string
  className?: string
}

export function ListRow({ title, subtitle, leading, trailing, badges, onClick, muted, ariaLabel, className }: ListRowProps) {
  const cls = ['ui-row', muted ? 'ui-row--muted' : null, className].filter(Boolean).join(' ')
  const inner = (
    <>
      {leading && <span className="ui-row__lead">{leading}</span>}
      <span className="ui-row__main">
        <span className="ui-row__title">{title}</span>
        {subtitle && <span className="ui-row__sub">{subtitle}</span>}
        {badges && <span className="ui-row__badges">{badges}</span>}
      </span>
      {trailing !== undefined && trailing !== null && <span className="ui-row__end">{trailing}</span>}
    </>
  )
  return onClick ? (
    <button type="button" className={cls} onClick={onClick} aria-label={ariaLabel}>{inner}</button>
  ) : (
    <div className={cls}>{inner}</div>
  )
}

/** The grouped-list surface (mock `.list`). `label` names it for screen readers. */
export function List({ children, label }: { children: ReactNode; label?: string }) {
  return <div className="ui-list" role={label ? 'group' : undefined} aria-label={label}>{children}</div>
}
