import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { TopBar } from '../../shell/TopBar'
import { Chip } from '../../ui/Chip'
import { SwipeRow } from '../../ui/SwipeRow'
import { SearchField } from '../../ui/SearchField'
import { Feed } from './Feed'
import {
  type FeedState, type TransactionFilter, activeFilterCount, fromSearch, monthLabel, monthRange, toSearch, toggle,
} from './filters'
import { useRecurringItems } from '../../data/reads'
import { FiltersSheet } from './FiltersSheet'
import { useCounts, useRefData } from './hooks'
import { useHeldDeletes } from './heldDeletes'
import { OptionSheet } from './OptionSheet'
import { useDeleteWithUndo } from './useDeleteWithUndo'
import './activity.css'

export function withoutDates(f: TransactionFilter): TransactionFilter {
  const { from_date: _f, to_date: _t, ...rest } = f
  return rest
}

function monthOptions(today = new Date()) {
  const opts = Array.from({ length: 6 }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1)
    const r = monthRange(d)
    return { value: `${r.from_date}|${r.to_date}`, label: i === 0 ? 'This month' : monthLabel(r) }
  })
  return [...opts, { value: 'all', label: 'All time' }]
}

export function Activity() {
  const [params, setParams] = useSearchParams()
  const state = useMemo(() => fromSearch(params), [params])
  const set = useCallback((next: FeedState) => setParams(toSearch(next), { replace: true }), [setParams])
  const f = state.filter
  const setFilter = (filter: TransactionFilter) => set({ ...state, filter })
  const onSearch = useCallback(
    (q: string) => set({ ...state, filter: { ...state.filter, q: q || undefined } }),
    [set, state],
  )
  const counts = useCounts().data
  const refData = useRefData()
  const items = useRecurringItems().data
  const [sheet, setSheet] = useState<null | 'month' | 'filters'>(null)
  const clear = () => set({ filter: monthRange(new Date()), dups: false })
  const filters = activeFilterCount(f)
  const held = useHeldDeletes()
  const deleteWithUndo = useDeleteWithUndo()
  const navigate = useNavigate()

  return (
    <>
      <TopBar title="Activity" />
      <section className="screen activity">
        <SearchField value={f.q ?? ''} onChange={onSearch} />
        <div className="chips" role="group" aria-label="Quick filters">
          <Chip label="Filters" count={filters || undefined} pressed={filters > 0} disabled={state.dups} onClick={() => setSheet('filters')} />
          <Chip label={monthLabel(f)} pressed={!!(f.from_date || f.to_date)} disabled={state.dups} onClick={() => setSheet('month')} />
          {!!counts?.no_payer && (
            <Chip
              label="No payer"
              count={counts.no_payer}
              pressed={!!f.missing_payer}
              disabled={state.dups}
              onClick={() => setFilter(withoutDates(toggle(f, { missing_payer: true })))}
            />
          )}
          <Chip label="Income" pressed={f.type === 'income'} disabled={state.dups} onClick={() => setFilter(toggle(f, { type: 'income' }))} />
          <Chip label="Cash" pressed={f.payment_method === 'cash'} disabled={state.dups} onClick={() => setFilter(toggle(f, { payment_method: 'cash' }))} />
        </div>
        <Feed
          filter={f}
          onClear={clear}
          hidden={held}
          renderRow={(t, row, { pending }) => (
            <SwipeRow
              disabled={pending}
              onDelete={() => deleteWithUndo(t)}
              onCopy={() => navigate(`/new?from=${encodeURIComponent(t.id)}`)}
            >
              {row}
            </SwipeRow>
          )}
        />
      </section>
      <OptionSheet
        open={sheet === 'month'}
        title="Month"
        options={monthOptions()}
        value={f.from_date && f.to_date ? `${f.from_date}|${f.to_date}` : 'all'}
        onPick={(v) => {
          if (v === 'all') return setFilter(withoutDates(f))
          const [from_date, to_date] = v.split('|')
          setFilter({ ...f, from_date, to_date })
        }}
        onClose={() => setSheet(null)}
      />
      <FiltersSheet
        open={sheet === 'filters'}
        filter={f}
        refData={refData}
        items={items}
        onApply={setFilter}
        onClose={() => setSheet(null)}
      />
    </>
  )
}
