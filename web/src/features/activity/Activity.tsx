import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useReducer, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useOnline } from '../../data/online'
import { TopBar } from '../../shell/TopBar'
import { BulkBar } from '../../ui/BulkBar'
import { Chip } from '../../ui/Chip'
import { Money } from '../../ui/Money'
import { Sheet } from '../../ui/Sheet'
import { useToast } from '../../ui/Toast'
import { type BulkField, BulkSheet } from './BulkSheet'
import { SwipeRow } from '../../ui/SwipeRow'
import { SearchField } from '../../ui/SearchField'
import { Duplicates } from './Duplicates'
import { Feed } from './Feed'
import {
  type FeedState, type TransactionFilter, activeFilterCount, fromSearch, isEmpty, monthLabel, monthRange, toSearch, toggle,
} from './filters'
import { useRecurringItems } from '../../data/reads'
import { FiltersSheet } from './FiltersSheet'
import { ACTIVITY_WRITES, type Txn, useCounts, useRefData } from './hooks'
import { useHeldDeletes } from './heldDeletes'
import { OptionSheet } from './OptionSheet'
import { RecentBulk } from './RecentBulk'
import { OFF, type Selection, isSelected, reduce, selectedCount } from './selection'
import { useDeleteWithUndo } from './useDeleteWithUndo'
import { useUndoBulk } from './useUndoBulk'
import './activity.css'

export function withoutDates(f: TransactionFilter): TransactionFilter {
  const { from_date: _f, to_date: _t, ...rest } = f
  return rest
}

const BULK_ACTIONS: { field: BulkField; label: string }[] = [
  { field: 'bucket', label: 'Bucket' },
  { field: 'category', label: 'Category' },
  { field: 'payer', label: 'Payer' },
  { field: 'method', label: 'Method' },
]

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
)

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
  const [sel, dispatch] = useReducer(reduce, OFF)
  // A new filter is a new list: a selection made on the old one no longer means anything.
  const set = useCallback((next: FeedState) => {
    dispatch({ type: 'cancel' })
    setParams(toSearch(next), { replace: true })
  }, [setParams])
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
  const online = useOnline()
  const [loaded, setLoaded] = useState<{ ids: string[]; rows: Txn[]; total: number }>({ ids: [], rows: [], total: 0 })
  const onLoaded = useCallback((rows: Txn[], total: number) => setLoaded({ ids: rows.map((r) => r.id), rows, total }), [])
  const [menu, setMenu] = useState(false)
  const [recentOpen, setRecentOpen] = useState(false)
  const undo = useUndoBulk()
  const [bulk, setBulk] = useState<null | BulkField>(null)
  const qc = useQueryClient()
  const toast = useToast()
  const selecting = sel.kind !== 'off'
  const count = selectedCount(sel)
  // The BulkBar's "N · €X" (spec §4.5): money out, in base currency. Hand-picked rows are summed here; for a
  // filter or bill selection only the server knows, so it shows once a preview of this selection gave it.
  const [previewed, setPreviewed] = useState<{ sel: Selection; out: number } | null>(null)
  const moneyOut = sel.kind === 'picked'
    ? loaded.rows.filter((r) => sel.ids.includes(r.id) && r.type === 'expense')
      .reduce((sum, r) => sum + r.amount * (r.exchange_rate || 1), 0)
    : previewed?.sel === sel ? previewed.out : null
  // Select by filter needs a filter: the server refuses an empty one (400).
  const canSelectAll = loaded.total > 0 && !isEmpty(f)
  const selectAll = () => {
    dispatch({ type: 'enter' })
    dispatch({ type: 'all', filter: f, total: loaded.total })
  }

  return (
    <>
      {selecting ? (
        <header className="selbar" role="toolbar" aria-label="Selection">
          <button type="button" onClick={() => dispatch({ type: 'cancel' })}>Cancel</button>
          <h1 className="selbar__title num" aria-live="polite">{count} selected</h1>
          <button type="button" disabled={!canSelectAll} onClick={() => dispatch({ type: 'all', filter: f, total: loaded.total })}>
            All
          </button>
        </header>
      ) : (
        <TopBar
          title="Activity"
          actions={
            <button type="button" className="ui-iconbtn" aria-label="More" aria-haspopup="dialog" onClick={() => setMenu(true)}>
              <MoreIcon />
            </button>
          }
        />
      )}
      <section className={selecting ? 'screen activity activity--selecting' : 'screen activity'}>
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
          {(state.dups || !!counts?.duplicate_groups) && (
            <Chip
              label="Duplicates?"
              count={counts?.duplicate_groups || undefined}
              pressed={state.dups}
              onClick={() => set(state.dups ? { filter: monthRange(new Date()), dups: false } : { filter: {}, dups: true })}
            />
          )}
          <Chip label="Income" pressed={f.type === 'income'} disabled={state.dups} onClick={() => setFilter(toggle(f, { type: 'income' }))} />
          <Chip label="Cash" pressed={f.payment_method === 'cash'} disabled={state.dups} onClick={() => setFilter(toggle(f, { payment_method: 'cash' }))} />
        </div>
        {!state.dups && f.missing_payer && canSelectAll && sel.kind !== 'filter' && sel.kind !== 'bill' && (
          <button type="button" className="btn btn--ghost btn--sm select-all" onClick={selectAll}>
            Select all {loaded.total}
          </button>
        )}
        {state.dups ? <Duplicates /> : (
          <Feed
            filter={f}
            onClear={clear}
            hidden={held}
            onLoaded={onLoaded}
            selecting={selecting}
            rowProps={selecting
              ? (t) => ({ selected: isSelected(sel, t.id), onOpen: (id) => dispatch({ type: 'toggle', id, loadedIds: loaded.ids }) })
              : undefined}
            renderRow={selecting ? undefined : (t, row, { pending }) => (
              <SwipeRow
                disabled={pending}
                onDelete={() => deleteWithUndo(t)}
                onCopy={() => navigate(`/new?from=${encodeURIComponent(t.id)}`)}
                onLongPress={() => dispatch({ type: 'enter', id: t.id })}
              >
                {row}
              </SwipeRow>
            )}
          />
        )}
      </section>
      {selecting && (
        <BulkBar
          count={count}
          total={moneyOut ? <Money amount={moneyOut} /> : undefined}
          disabled={!online}
          disabledReason="Needs a connection"
          actions={BULK_ACTIONS.map((a) => ({ label: a.label, onClick: () => setBulk(a.field) }))}
        />
      )}
      <BulkSheet
        open={bulk !== null}
        initial={bulk ?? 'bucket'}
        selection={sel}
        rows={loaded.rows}
        refData={refData}
        items={items}
        onClose={() => setBulk(null)}
        onPreview={(r) => setPreviewed({ sel, out: r.total_out })}
        onApplied={(result, req) => {
          setBulk(null)
          dispatch({ type: 'cancel' })
          // ACTIVITY_WRITES includes keys.recurring.all, for "Also move the bill".
          for (const key of ACTIVITY_WRITES) void qc.invalidateQueries({ queryKey: key })
          const n = result.changed
          toast.show('bucket_id' in req.changes ? `Moved ${n} ${n === 1 ? 'payment' : 'payments'}` : `Changed ${n}`, {
            durationMs: 10_000,
            action: result.batch_id ? { label: 'Undo', onClick: () => void undo(result.batch_id!) } : undefined,
          })
        }}
      />
      <Sheet open={menu} onClose={() => setMenu(false)} title="Activity">
        <ul className="ui-list feed__list menu-list">
          <li>
            <button type="button" className="ui-row option" disabled={state.dups}
              onClick={() => { setMenu(false); dispatch({ type: 'enter' }) }}>
              <span className="ui-row__main">
                <span className="ui-row__title">Select</span>
                <span className="ui-row__sub">Pick payments to change together</span>
              </span>
            </button>
          </li>
          <li>
            <button type="button" className="ui-row option" onClick={() => { setMenu(false); setRecentOpen(true) }}>
              <span className="ui-row__main">
                <span className="ui-row__title">Recent bulk changes</span>
                <span className="ui-row__sub">See or undo the last 10</span>
              </span>
            </button>
          </li>
        </ul>
      </Sheet>
      <RecentBulk open={recentOpen} onClose={() => setRecentOpen(false)} />
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
