import { useState } from 'react'
import { Link } from 'react-router'
import { usePendingIds } from '../../../data/pending'
import { useOnline } from '../../../data/online'
import { Chip } from '../../../ui/Chip'
import { EmptyState } from '../../../ui/EmptyState'
import { CloudOffIcon, PlusIcon } from '../../../ui/icons'
import { QueryView } from '../../../ui/QueryView'
import { AddSheet } from './AddSheet'
import { usePantryShoppingCount, useStockList } from './hooks'
import { CartIcon, SearchIcon } from './icons'
import { PantryRow } from './PantryRow'
import type { StockItem } from './types'
import './pantry.css'

type Filter = 'all' | 'low' | 'tracked'
const FILTERS: { value: Filter; label: string; keep: (i: StockItem) => boolean }[] = [
  { value: 'all', label: 'All', keep: () => true },
  { value: 'low', label: 'Running low', keep: (i) => i.low },
  { value: 'tracked', label: 'Price tracked', keep: (i) => i.track_price },
]

const matches = (i: StockItem, q: string) =>
  !q || i.name.toLowerCase().includes(q) || (i.brand ?? '').toLowerCase().includes(q)

/** Plan › Pantry (pantry spec §4.2): search, filter chips, the stock rows, and the shopping list button. */
export function Pantry() {
  const list = useStockList()
  const online = useOnline()
  const [adding, setAdding] = useState(false)
  return (
    <div className="pantry">
      {list.stale && (
        <p className="ui-banner" role="status">
          <CloudOffIcon />{online ? 'Couldn’t refresh · showing saved pantry' : 'Offline · showing saved pantry'}
        </p>
      )}
      <QueryView result={list} showBanner={false} noDataText="No saved pantry yet. Connect once to load Pantry.">
        {(items) => <PantryBody items={items} onAdd={() => setAdding(true)} adding={adding} />}
      </QueryView>
      {adding && <AddSheet open onClose={() => setAdding(false)} />}
    </div>
  )
}

function PantryBody({ items, onAdd, adding }: { items: StockItem[]; onAdd: () => void; adding: boolean }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const pending = usePendingIds()
  const q = query.trim().toLowerCase()
  const keep = FILTERS.find((f) => f.value === filter)!.keep
  const shown = items.filter((i) => keep(i) && matches(i, q))

  if (items.length === 0) {
    return (
      <EmptyState title="Nothing in your pantry yet"
        body="Add what you keep at home, tap it up and down as you use it, and see where it’s cheapest."
        action={{ label: 'Add a product', onClick: onAdd }} />
    )
  }
  return (
    <>
      <div className="pantry-head">
        <label className="pantry-search">
          <SearchIcon />
          <input type="search" inputMode="search" enterKeyHint="search" autoComplete="off" placeholder="Search pantry"
            aria-label="Search pantry" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <button type="button" className="ui-iconbtn pantry-plus" aria-label="Add to pantry" aria-expanded={adding}
          onClick={onAdd}>
          <PlusIcon />
        </button>
      </div>
      <div className="chips pantry-chips" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <Chip key={f.value} label={f.label} count={items.filter(f.keep).length} pressed={filter === f.value}
            onClick={() => setFilter(f.value)} />
        ))}
      </div>
      {shown.length ? (
        <ul className="pantry-list" aria-label="Pantry">
          {shown.map((i) => <PantryRow key={i.id} item={i} pending={pending.has(i.id)} />)}
        </ul>
      ) : (
        <p className="pantry-none">
          {q ? `Nothing matches “${query.trim()}”` : filter === 'low' ? 'Nothing is running low' : 'No price-tracked products'}
        </p>
      )}
      <ShoppingListButton />
    </>
  )
}

/** "Shopping list (N)": N is the list's items, low or running out (spec §4.2). */
function ShoppingListButton() {
  const count = usePantryShoppingCount().data?.items.length
  return (
    <Link to="/plan/pantry/list" className="btn btn--primary btn--lg pantry-float">
      <CartIcon />{count === undefined ? 'Shopping list' : `Shopping list (${count})`}
    </Link>
  )
}
