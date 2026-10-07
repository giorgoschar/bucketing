import type { ReactNode } from 'react'
import { CheckIcon } from '../bridge'
import './pickers.css'

export interface OptionProps {
  name: string
  sub?: string | null
  /** A leading glyph (category icon, member initial). */
  lead?: ReactNode
  selected: boolean
  onPress: () => void
}

/** One row in a picker sheet: tap once to pick and close. */
export function Option({ name, sub, lead, selected, onPress }: OptionProps) {
  return (
    <button type="button" className="ck-option" aria-pressed={selected} onClick={onPress}>
      {lead && <span className="ck-option__lead" aria-hidden="true">{lead}</span>}
      <span className="ck-option__main">
        <span className="ck-option__name">{name}</span>
        {sub && <span className="ck-option__sub">{sub}</span>}
      </span>
      {selected && <span className="ck-option__check"><CheckIcon /></span>}
    </button>
  )
}

/** Picks, then closes: every picker sheet's tap. */
export const pickThenClose = <T,>(onPick: (v: T) => void, onClose: () => void) => (v: T) => {
  onPick(v)
  onClose()
}
