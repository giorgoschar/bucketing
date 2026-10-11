import type { SearchField } from './useSearchField'
import './search.css'

const OFFLINE = 'Connect to search entries, bills and pantry.'
const LIMITED = 'Too many searches. Wait a moment and try again.'
const FAILED = 'Couldn’t search entries, bills and pantry right now.'

/** The results list (lazy): groups in order, each option a `role="option"` the field points at. */
export default function SearchResults({ field }: { field: SearchField }) {
  const { search, listId, active, pick } = field
  if (!search.active) return null
  const { groups, count, status } = search
  const quiet = status === 'offline' ? OFFLINE : status === 'limited' ? LIMITED : status === 'failed' ? FAILED : null
  const nothing = count === 0 && !quiet && status !== 'loading'
  const announce = status === 'loading' && count === 0 ? '' : nothing ? 'No results' : `${count} ${count === 1 ? 'result' : 'results'}`
  return (
    <div className="search__results">
      <p className="search__live" role="status">{announce}</p>
      {groups.length > 0 && (
        <div id={listId} role="listbox" aria-label="Search results" className="search__list">
          {groups.map((g) => (
            <div key={g.key} role="group" aria-labelledby={`${listId}-${g.key}`} className="search__group">
              <p id={`${listId}-${g.key}`} className="search__title">{g.title}</p>
              {g.options.map((o) => (
                <div
                  key={o.id}
                  id={o.id}
                  role="option"
                  aria-selected={active >= 0 && search.options[active]?.id === o.id}
                  className={`search__opt${o.seeAll ? ' search__opt--all' : ''}`}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => pick(o.to)}
                >
                  <span className="search__main">
                    <span className="search__label">{o.label}</span>
                    {o.sub && <span className="search__sub">{o.sub}</span>}
                  </span>
                  {o.end && <span className="search__end ui-num">{o.end}</span>}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {nothing && <p className="search__none">Nothing found for “{search.query}”.</p>}
      {quiet && <p className="search__quiet">{quiet}</p>}
    </div>
  )
}
