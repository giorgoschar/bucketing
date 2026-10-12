import { useCallback, useEffect, useRef, type KeyboardEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { trapTab } from '../../ui/focusTrap'
import { ChevronLeftIcon } from '../../ui/icons'
import { SearchInput, SearchResultsLazy } from './SearchInput'
import { useSearchField } from './useSearchField'

/** Phone (spec §4.2): a full-screen modal search with the field focused. Esc clears, then closes; so does Back.
 *  Closing returns focus to the top bar's search icon. */
export function SearchScreen() {
  const navigate = useNavigate()
  const { pathname, search, hash } = useLocation()
  const picked = useRef(false)
  const close = useCallback(() => {
    // The search is a pushed history entry. After a reload there may be nothing before it: replace it instead.
    const idx = (window.history.state as { idx?: number } | null)?.idx
    if (typeof idx === 'number' && idx > 0) void navigate(-1)
    else void navigate({ pathname, search, hash }, { replace: true, state: null })
  }, [navigate, pathname, search, hash])
  // A result replaces the search entry, so Back from it returns to the screen the search opened over.
  const afterPick = useCallback(() => { picked.current = true }, [])
  const field = useSearchField({ onEscape: close, afterPick, replace: true })

  useEffect(() => () => {
    if (picked.current) return
    // Deferred, and only if the screen is really gone (development re-runs effects on mount).
    setTimeout(() => {
      if (!document.querySelector('.search--screen')) document.querySelector<HTMLElement>('.topbar__search')?.focus()
    }, 0)
  }, [])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => trapTab(e.currentTarget, e.nativeEvent)
  return (
    <div className="search--screen" role="dialog" aria-modal="true" aria-label="Search" onKeyDown={onKeyDown}>
      <header className="search__bar">
        <button type="button" className="search__back" aria-label="Close search" onClick={close}><ChevronLeftIcon /></button>
        <SearchInput field={field} autoFocus />
      </header>
      <div className="search__body"><SearchResultsLazy field={field} /></div>
    </div>
  )
}
