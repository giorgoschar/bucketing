import { lazy, Suspense, type Ref } from 'react'
import { SearchIcon } from '../../shell/icons'
import { MAX_CHARS } from './useSearch'
import type { SearchField } from './useSearchField'
import './search.css'

const SearchResults = lazy(() => import('./SearchResults'))

/** The field (not lazy): a combobox over the results listbox. */
export function SearchInput({ field, ref, autoFocus, hint, onFocus }: {
  field: SearchField
  ref?: Ref<HTMLInputElement>
  autoFocus?: boolean
  /** Shortcut hint shown inside the field, hidden from assistive tech (the shortcut is on aria-keyshortcuts). */
  hint?: string
  onFocus?: () => void
}) {
  const { search } = field
  return (
    <div className="search__field">
      <SearchIcon />
      <input
        ref={ref}
        type="search"
        className="search__input"
        placeholder="Search"
        aria-label="Search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={search.options.length > 0}
        aria-controls={search.options.length > 0 ? field.listId : undefined}
        aria-activedescendant={field.activeId}
        aria-keyshortcuts={hint ? '/ Control+K Meta+K' : undefined}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="search"
        maxLength={MAX_CHARS}
        autoFocus={autoFocus}
        value={field.value}
        onFocus={onFocus}
        onChange={(e) => field.setValue(e.target.value)}
        onKeyDown={field.onKeyDown}
      />
      {hint && field.value === '' && <kbd className="search__key" aria-hidden="true">{hint}</kbd>}
    </div>
  )
}

export function SearchResultsLazy({ field }: { field: SearchField }) {
  return <Suspense fallback={null}><SearchResults field={field} /></Suspense>
}
