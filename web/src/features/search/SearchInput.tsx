import { lazy, Suspense, type Ref } from 'react'
import { SearchIcon } from '../../shell/icons'
import { MAX_CHARS, type Search } from './useSearch'
import type { SearchField } from './useSearchField'
import './search.css'

/** "3 results" or "No results", only when the answer for the text in the field is complete. */
function announcement({ active, status, count }: Search): string {
  if (!active || status === 'loading') return ''
  if (count === 0) return status === 'offline' || status === 'failed' ? '' : 'No results'
  return `${count} ${count === 1 ? 'result' : 'results'}`
}

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
      {/* Always mounted, outside the results panel, and only changed once the answer has settled. */}
      <p className="search__live" role="status" aria-live="polite">{announcement(search)}</p>
    </div>
  )
}

export function SearchResultsLazy({ field }: { field: SearchField }) {
  return <Suspense fallback={null}><SearchResults field={field} /></Suspense>
}
