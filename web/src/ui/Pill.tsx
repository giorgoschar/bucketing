import type { ReactNode } from 'react'
import { ChevronDownIcon } from './icons'
import './composer-kit.css'

export interface PillProps {
  label: string
  value: string
  /** Nothing chosen yet: dashed outline (e.g. "Choose a budget"). */
  empty?: boolean
  icon?: ReactNode
  /** "rule: coffee island", "from receipt". */
  tag?: string | null
  /** Shown, not changeable (Fixed cost budget, payer locked to you). */
  readOnly?: boolean
  onPress?: () => void
}

export function Pill({ label, value, empty, icon, tag, readOnly, onPress }: PillProps) {
  const cls = ['pill', 'ck-pill', empty ? 'pill--empty' : '', readOnly ? 'pill--static' : ''].filter(Boolean).join(' ')
  const body = (
    <>
      {icon && <span className="ck-pill__icon" aria-hidden="true">{icon}</span>}
      <span className="ck-pill__text">
        <span className="ck-pill__label">{label}</span>
        <span className="ck-pill__value">{value}</span>
        {tag && <span className="ck-pill__tag">{tag}</span>}
      </span>
    </>
  )
  if (readOnly || !onPress) {
    return <span className={cls} role="group" aria-label={`${label}: ${value}`}>{body}</span>
  }
  return (
    <button type="button" className={cls} onClick={onPress} aria-label={`${label}: ${value}${tag ? `, ${tag}` : ''}. Change`}>
      {body}
      <ChevronDownIcon />
    </button>
  )
}
