import { useState } from 'react'
import { type Category, Sheet } from '../bridge'
import { fold } from '../defaults'
import { Option, pickThenClose } from './Option'

export interface CategorySheetProps {
  open: boolean
  onClose: () => void
  categories: Category[]
  recentIds: string[]
  /** The rule or receipt suggestion, shown first with why. */
  suggestion: { id: string; reason: string } | null
  selectedId: string | null
  onPick: (id: string) => void
}

const FUEL_HINT = 'Asks for price per litre'

function Glyph({ c }: { c: Category }) {
  return (
    <span className="ck-glyph" style={c.color ? { ['--tint' as string]: c.color } : undefined}>
      {c.icon || c.name.slice(0, 1).toUpperCase()}
    </span>
  )
}

export function CategorySheet({ open, onClose, categories, recentIds, suggestion, selectedId, onPick }: CategorySheetProps) {
  const [query, setQuery] = useState('')
  const close = () => {
    setQuery('')
    onClose()
  }
  const pick = pickThenClose(onPick, close)
  const q = fold(query)
  const match = (c: Category) => q === '' || fold(c.name).includes(q)
  const byId = new Map(categories.map((c) => [c.id, c]))
  const suggested = suggestion ? byId.get(suggestion.id) : undefined
  const recent = recentIds.map((id) => byId.get(id)).filter((c): c is Category => !!c).slice(0, 4)
  const row = (c: Category, sub?: string | null) => (
    <Option key={c.id} name={c.name} lead={<Glyph c={c} />}
      sub={sub ?? (c.system_key === 'fuel' ? FUEL_HINT : null)}
      selected={c.id === selectedId} onPress={() => pick(c.id)} />
  )
  const all = categories.filter(match)
  return (
    <Sheet open={open} onClose={close} title="Category">
      <input type="search" className="ck-search" aria-label="Search categories" placeholder="Search categories"
        value={query} onChange={(e) => setQuery(e.target.value)} enterKeyHint="search" autoComplete="off" />
      {suggested && match(suggested) && (
        <section className="ck-section">
          <h3 className="ck-section__title">Suggested</h3>
          <div className="ck-options">{row(suggested, suggestion?.reason)}</div>
        </section>
      )}
      {recent.some(match) && (
        <section className="ck-section">
          <h3 className="ck-section__title">Recent</h3>
          <div className="ck-chips">
            {recent.filter(match).map((c) => (
              <button key={c.id} type="button" className={c.id === selectedId ? 'ck-chip on' : 'ck-chip'}
                aria-pressed={c.id === selectedId} onClick={() => pick(c.id)}>
                {c.icon && <span aria-hidden="true">{c.icon}</span>}
                {c.name}
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="ck-section">
        <h3 className="ck-section__title">All categories</h3>
        {all.length > 0
          ? <div className="ck-options">{all.map((c) => row(c))}</div>
          : <p className="ck-empty">No category matches “{query.trim()}”</p>}
      </section>
    </Sheet>
  )
}
