import { type FormEvent, useEffect, useState } from 'react'
import { Segmented } from '../../ui/Segmented'
import { Sheet } from '../../ui/Sheet'
import { toQuery, type TransactionFilter, type TxnType } from './filters'
import { METHOD_LABELS } from './format'
import type { RecurringItem, RefData } from './hooks'

const NONE = '__none'
type Props = {
  open: boolean
  filter: TransactionFilter
  refData?: RefData
  items?: RecurringItem[]
  onApply: (f: TransactionFilter) => void
  onClose: () => void
}

const clean = (f: TransactionFilter) => toQuery(f) as TransactionFilter

export function FiltersSheet({ open, filter, refData, items, onApply, onClose }: Props) {
  const [draft, setDraft] = useState<TransactionFilter>(filter)
  useEffect(() => {
    if (open) setDraft(filter)
  }, [open, filter])
  const set = (patch: TransactionFilter) => setDraft((d) => ({ ...d, ...patch }))
  const text = (key: keyof TransactionFilter) => ({
    value: (draft[key] as string | undefined) ?? '',
    onChange: (e: { target: { value: string } }) => set({ [key]: e.target.value || undefined }),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onApply(clean(draft))
    onClose()
  }

  return (
    <Sheet open={open} onClose={onClose} title="Filters">
      <form className="filters" onSubmit={submit}>
        <Segmented
          label="Type"
          options={[
            { value: '', label: 'All' },
            { value: 'expense', label: 'Out' },
            { value: 'income', label: 'In' },
            { value: 'transfer', label: 'Transfer' },
          ]}
          value={draft.type ?? ''}
          onChange={(v: string) => set({ type: (v || undefined) as TxnType | undefined })}
        />
        <label className="ui-field"><span className="ui-field__label">Category</span>
          <select className="ui-input" {...text('category_id')}>
            <option value="">Any</option>
            {refData?.categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="ui-field"><span className="ui-field__label">Bucket</span>
          <select className="ui-input"
            value={draft.no_bucket ? NONE : (draft.bucket_id ?? '')}
            onChange={(e) => {
              const v = e.target.value
              set({ bucket_id: v && v !== NONE ? v : undefined, no_bucket: v === NONE || undefined })
            }}
          >
            <option value="">Any</option>
            <option value={NONE}>No bucket</option>
            {refData?.buckets.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
        <label className="ui-field"><span className="ui-field__label">Paid by</span>
          <select className="ui-input" {...text('paid_by')}>
            <option value="">Anyone</option>
            {refData?.members.map((m) => <option key={m.user_id} value={m.user_id}>{m.display_name}</option>)}
          </select>
        </label>
        <label className="ui-field"><span className="ui-field__label">Method</span>
          <select className="ui-input" {...text('payment_method')}>
            <option value="">Any</option>
            {Object.entries(METHOD_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="ui-field"><span className="ui-field__label">Recurring item</span>
          <select className="ui-input" {...text('recurring_bill_id')}>
            <option value="">Any</option>
            {items?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </label>
        <div className="grid2">
          <label className="ui-field"><span className="ui-field__label">From</span>
          <input className="ui-input" type="date" {...text('from_date')} /></label>
          <label className="ui-field"><span className="ui-field__label">To</span>
          <input className="ui-input" type="date" {...text('to_date')} /></label>
        </div>
        <div className="grid2">
          <label className="ui-field"><span className="ui-field__label">Min €</span>
          <input className="ui-input" inputMode="decimal" {...text('min_amount')} /></label>
          <label className="ui-field"><span className="ui-field__label">Max €</span>
          <input className="ui-input" inputMode="decimal" {...text('max_amount')} /></label>
        </div>
        <div className="filters__actions">
          <button type="button" className="btn btn--ghost" onClick={() => { onApply(clean({ q: filter.q })); onClose() }}>Reset</button>
          <button type="submit" className="btn btn--primary">Show results</button>
        </div>
      </form>
    </Sheet>
  )
}
