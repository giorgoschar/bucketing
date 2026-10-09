import { type ReactNode, useRef, useState } from 'react'
import { CheckIcon } from '../bridge'
import { fold } from '../defaults'
import { usePanel } from '../panel'
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

/** The panel's pickers (spec §4.5) open as lists that filter as you type; Enter picks the first match. On the
 *  phone `active` is false and none of this renders. */
export function useFilterBox() {
  const active = usePanel() !== null
  const [text, setText] = useState('')
  const ref = useRef<HTMLInputElement>(null)
  return { active, text, setText, ref, q: fold(text) }
}

export function FilterField({ label, box, onEnter }: { label: string; box: ReturnType<typeof useFilterBox>; onEnter: () => void }) {
  if (!box.active) return null
  return (
    <input ref={box.ref} type="search" className="ck-search" aria-label={label} placeholder="Type to filter" autoComplete="off"
      value={box.text} onChange={(e) => box.setText(e.target.value)}
      onKeyDown={(e) => {
        if (e.key !== 'Enter' || e.nativeEvent.isComposing) return
        e.preventDefault()
        e.stopPropagation() // not the panel's Enter-saves
        onEnter()
      }} />
  )
}
