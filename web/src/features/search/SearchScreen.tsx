import { useCallback } from 'react'
import { useNavigate } from 'react-router'
import { ChevronLeftIcon } from '../../ui/icons'
import { SearchInput, SearchResultsLazy } from './SearchInput'
import { useSearchField } from './useSearchField'

/** Phone (spec §4.2): a full-screen search with the field focused. Esc clears, then closes; so does Back. */
export function SearchScreen() {
  const navigate = useNavigate()
  const close = useCallback(() => { void navigate(-1) }, [navigate])
  // A result replaces the search entry, so Back from it returns to the screen the search opened over.
  const field = useSearchField({ onEscape: close, replace: true })
  return (
    <div className="search search--screen" role="dialog" aria-label="Search">
      <header className="search__bar">
        <button type="button" className="search__back" aria-label="Close search" onClick={close}><ChevronLeftIcon /></button>
        <SearchInput field={field} autoFocus />
      </header>
      <div className="search__body"><SearchResultsLazy field={field} /></div>
    </div>
  )
}
