import { useCallback, useImperativeHandle, useRef, useState, type Ref } from 'react'
import { SearchInput, SearchResultsLazy } from './SearchInput'
import { useSearchField } from './useSearchField'

export interface SearchBoxHandle { focus: () => void }

/** Desktop (spec §4.2): the sidebar field with its results in a panel under it. */
export function SearchBox({ ref }: { ref?: Ref<SearchBoxHandle> }) {
  const input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const onClose = useCallback(() => { setOpen(false); input.current?.blur() }, [])
  const field = useSearchField({ onEscape: onClose, afterPick: onClose })
  useImperativeHandle(ref, () => ({ focus: () => { setOpen(true); input.current?.focus(); input.current?.select() } }), [])
  return (
    <div
      className="search search--box"
      onFocus={() => setOpen(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false) }}
    >
      <SearchInput field={field} ref={input} hint="/" />
      {open && <div className="search__panel"><SearchResultsLazy field={field} /></div>}
    </div>
  )
}
