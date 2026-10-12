import { useCallback, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { SearchInput, SearchResultsLazy } from './SearchInput'
import { useSearchField } from './useSearchField'

export interface SearchBoxHandle { focus: () => void }

/** Desktop (spec §4.2): the sidebar field with its results in a panel under it. */
export function SearchBox({ ref }: { ref?: Ref<SearchBoxHandle> }) {
  const input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  // Where the user was when a shortcut pulled them here; Esc gives focus back. A click on the field leaves it null.
  const from = useRef<HTMLElement | null>(null)
  const afterPick = useCallback(() => { setOpen(false); input.current?.blur() }, [])
  const onEscape = useCallback(() => {
    setOpen(false)
    const back = from.current
    from.current = null
    if (back === document.body) input.current?.blur()
    else if (back?.isConnected) back.focus()
  }, [])
  const field = useSearchField({ onEscape, afterPick })
  useImperativeHandle(ref, () => ({
    focus: () => {
      const here = document.activeElement
      if (here !== input.current && here instanceof HTMLElement) from.current = here
      setOpen(true)
      input.current?.focus()
      input.current?.select()
    },
  }), [])
  return (
    <div
      className="search--box"
      onFocus={() => setOpen(true)}
      onInput={() => setOpen(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) { setOpen(false); from.current = null } }}
    >
      <SearchInput field={field} ref={input} hint="/" />
      {/* A click inside the panel (its padding, a group title) must not take focus from the field. */}
      {open && <div className="search__panel" onMouseDown={(e) => e.preventDefault()}><SearchResultsLazy field={field} /></div>}
    </div>
  )
}
