import { useId, useState } from 'react'
import { Chips } from '../../ui/Chips'
import { Sheet } from '../../ui/Sheet'
import { useBuckets, useCategories } from '../settings/hooks'
import { type Period, rangeError } from './period'
import { type InsightFilters, filtersKey } from './types'

export interface RangeSheetProps {
  open: boolean
  onClose(): void
  initialFrom: string
  initialTo: string
  filters: InsightFilters
  onApply(p: Period, f: InsightFilters): void
  onReset(): void
}

interface Draft { from: string; to: string; bucketIds: string[]; categoryIds: string[]; error: string | null }

/** Custom range (native date inputs, both required, From ≤ To) and budget/category chips.
 *  "Paid by" is the lens, so it is not repeated here. */
export function RangeSheet({ open, onClose, initialFrom, initialTo, filters, onApply, onReset }: RangeSheetProps) {
  const fresh = (): Draft => ({ from: initialFrom, to: initialTo, bucketIds: filters.bucketIds, categoryIds: filters.categoryIds, error: null })
  const [draft, setDraft] = useState(fresh)
  // Start again from the props each time the sheet opens (or what it opens with changes), never on
  // an ordinary re-render: a refetch while it is open must not wipe what the user typed.
  const opening = `${open}|${initialFrom}|${initialTo}|${filtersKey(filters)}`
  const [seen, setSeen] = useState(opening)
  if (seen !== opening) {
    setSeen(opening)
    if (open) setDraft(fresh())
  }
  const errorId = useId()
  const buckets = useBuckets().data ?? []
  const categories = useCategories().data ?? []
  const patch = (p: Partial<Draft>) => setDraft((d) => ({ ...d, ...p }))

  const apply = () => {
    const problem = rangeError(draft.from, draft.to)
    if (problem) return patch({ error: problem })
    onApply({ preset: 'custom', from: draft.from, to: draft.to }, { bucketIds: draft.bucketIds, categoryIds: draft.categoryIds })
  }
  const invalid = draft.error ? true : undefined

  return (
    <Sheet open={open} onClose={onClose} title="Filters"
      footer={
        <div className="insights__sheetbtns">
          <button type="button" className="btn" onClick={onReset}>Reset</button>
          <button type="button" className="btn btn--primary" onClick={apply}>Apply</button>
        </div>
      }>
      <div className="insights__range">
        <label className="ui-field">
          <span className="ui-field__label">From</span>
          <input className="ui-input" type="date" value={draft.from} max={draft.to || undefined} required
            aria-invalid={invalid} aria-describedby={draft.error ? errorId : undefined}
            onChange={(e) => patch({ from: e.target.value, error: null })} />
        </label>
        <label className="ui-field">
          <span className="ui-field__label">To</span>
          <input className="ui-input" type="date" value={draft.to} min={draft.from || undefined} required
            aria-invalid={invalid} aria-describedby={draft.error ? errorId : undefined}
            onChange={(e) => patch({ to: e.target.value, error: null })} />
        </label>
      </div>
      {draft.error && <p id={errorId} className="ui-field__error" role="alert">{draft.error}</p>}
      {buckets.length > 0 && (
        <div className="insights__filtergroup">
          <p className="ui-field__label">Budgets</p>
          <div className="insights__chipwrap">
            <Chips multiple label="Budgets" options={buckets.map((b) => ({ value: b.id, label: b.name }))}
              value={draft.bucketIds} onChange={(bucketIds) => patch({ bucketIds })} />
          </div>
        </div>
      )}
      {categories.length > 0 && (
        <div className="insights__filtergroup">
          <p className="ui-field__label">Categories</p>
          <div className="insights__chipwrap">
            <Chips multiple label="Categories" options={categories.map((c) => ({ value: c.id, label: c.name }))}
              value={draft.categoryIds} onChange={(categoryIds) => patch({ categoryIds })} />
          </div>
        </div>
      )}
    </Sheet>
  )
}
