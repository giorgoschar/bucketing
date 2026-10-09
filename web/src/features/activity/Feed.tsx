import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { EmptyState } from '../../ui/EmptyState'
import { Money } from '../../ui/Money'
import { DEFAULT_SORT, type Sort, type TransactionFilter, activeFilterCount, isEmpty } from './filters'
import { groupByDay } from './format'
import { FeedRow } from './FeedRow'
import { type RefData, type Txn, type TxnPage, useFeedPage, useRefData } from './hooks'
import { type PendingTxn, toPendingTxn, usePendingActivity } from './pending'

export type RenderRow = (t: Txn, row: ReactNode, opts: { pending: boolean }) => ReactNode

type Props = {
  filter: TransactionFilter
  onClear: () => void
  renderRow?: RenderRow
  hidden?: ReadonlySet<string>
  /** Selection mode: each day's list becomes a multi-select listbox of option rows. */
  selecting?: boolean
  rowProps?: (t: Txn) => { selecting?: boolean; selected?: boolean; onOpen?: (id: string) => void }
  onLoaded?: (rows: Txn[], total: number, info: LoadedInfo) => void
  /** Desktop (spec §4.4): the server's order. Absent or the default = the day-grouped phone list. */
  sort?: Sort
  /** Desktop: draw the rows as a table instead of day groups. Load more, paging and merging stay here. */
  renderTable?: (t: TableArgs) => ReactNode
}

export type TableArgs = {
  rows: Txn[]
  refData: RefData | undefined
  rowProps?: Props['rowProps']
  selecting?: boolean
}

/** How many extra pages the table had loaded per filter and sort. Opening a row mounts a different route
 *  (router.tsx), so the table starts again; this puts back the pages the user had already loaded. */
const pagesLoaded = new Map<string, number>()

/** What "Select › All" needs to know about the list beyond its selectable rows. */
export type LoadedInfo = {
  /** Every server row of the filter is loaded. */
  complete: boolean
  /** Loaded server rows that can't be selected: a queued edit or delete, or a swipe-delete hold. */
  excluded: number
  /** Anything pending or held anywhere (it may match the filter on a page not loaded yet). */
  pending: boolean
}

export function Feed(props: Props) {
  // A new filter starts a new list: drop the pages of the old one.
  return <FeedList key={JSON.stringify(props.filter) + (props.sort ?? '')} {...props} />
}

function PageLoader({ filter, sort, page, index, onLoad }: {
  filter: TransactionFilter; sort: Sort; page: number; index: number; onLoad: (index: number, p: TxnPage) => void
}) {
  const q = useFeedPage(filter, page, sort)
  useEffect(() => {
    if (q.data) onLoad(index, q.data)
  }, [q.data, index, onLoad])
  return null
}

function Empty({ title, action }: { title: string; action?: { label: string; onClick: () => void } }) {
  return (
    <div role="status">
      <EmptyState title={title} action={action} />
    </div>
  )
}

function FeedList({ filter, onClear, renderRow, hidden, selecting, rowProps, onLoaded, sort = DEFAULT_SORT, renderTable }: Props) {
  const navigate = useNavigate()
  const refData: RefData | undefined = useRefData()
  const first = useFeedPage(filter, 1, sort)
  const [more, setMore] = useState<TxnPage[]>([])
  const memoKey = JSON.stringify([filter, sort])
  const [extra, setExtra] = useState(() => (renderTable ? pagesLoaded.get(memoKey) ?? 0 : 0))
  const pendingAll = usePendingActivity()
  const plain = isEmpty({ ...filter, from_date: undefined, to_date: undefined })

  const loaded = useMemo(() => (first.data ? [first.data, ...more.filter(Boolean)] : []), [first.data, more])
  const total = first.data?.total ?? 0
  // A row can shift between pages while the user scrolls: keep the first copy, in first-seen order.
  const serverRows = [...new Map(loaded.flatMap((p) => p.items).map((t) => [t.id, t])).values()]
  // Held (swipe) deletes and 2b's queued deletes stay out of view; a queued edit shows its new values.
  const rows: Txn[] = serverRows
    .filter((t) => !hidden?.has(t.id) && !pendingAll.hidden.has(t.id))
    .map((t) => {
      const edit = pendingAll.edits.get(t.id)
      return edit ? toPendingTxn(edit, t) : t
    })
  const pending: PendingTxn[] = plain ? pendingAll.creates : []
  const dayTotals = Object.assign({}, ...loaded.map((p) => p.day_totals)) as Record<string, number>
  const dated = (a: Txn, b: Txn) => (b.transaction_date ?? '').localeCompare(a.transaction_date ?? '')
  const tableRows: Txn[] = sort === 'date_desc' ? [...pending, ...rows].sort(dated)
    : sort === 'date_asc' ? [...rows, ...pending].sort((a, b) => dated(b, a))
      : [...pending, ...rows] // an amount sort keeps the server's order; unsent creates wait at the top
  const groups = groupByDay([...pending, ...rows].sort(dated), dayTotals)
  const canLoadMore = serverRows.length < total

  // What selection may pick: rows on screen that aren't held, deleted or waiting on a queued edit.
  const selectable = rows.filter((t) => !('pending' in t))
  const selectableKey = selectable.map((t) => t.id).join()
  const complete = !canLoadMore
  const excluded = serverRows.length - selectable.length
  const anyPending = pendingAll.edits.size > 0 || pendingAll.hidden.size > 0 || (hidden?.size ?? 0) > 0
  useEffect(() => {
    onLoaded?.(selectable, total, { complete, excluded, pending: anyPending })
  }, [selectableKey, total, complete, excluded, anyPending]) // eslint-disable-line react-hooks/exhaustive-deps

  const onPageLoad = useCallback(
    (i: number, p: TxnPage) => setMore((m) => (m[i] === p ? m : Object.assign([...m], { [i]: p }))),
    [],
  )
  const loadMore = useCallback(() => setExtra((n) => {
    if (renderTable) pagesLoaded.set(memoKey, n + 1)
    return n + 1
  }), [renderTable, memoKey])
  const sentinel = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const el = sentinel.current
    if (!el || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver((entries) => entries[0]?.isIntersecting && loadMore(), { rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [canLoadMore, loadMore])

  if (!first.data) {
    // CachedQuery: noData means offline (or failing) with no saved copy; isLoading means it may still arrive.
    if (first.noData && first.offline) {
      return <Empty title="Search needs a connection" action={{ label: 'Show saved list', onClick: onClear }} />
    }
    if (first.noData) return <Empty title="Couldn't load activity" action={{ label: 'Try again', onClick: first.refetch }} />
    return <p className="screen__note" aria-busy="true">Loading…</p>
  }
  if (groups.length === 0) {
    return plain && activeFilterCount(filter) === 0
      ? <Empty title="Nothing here yet" />
      : <Empty title="No matches" action={{ label: 'Clear filters', onClick: onClear }} />
  }

  const open = (id: string) => navigate(`/activity/${encodeURIComponent(id)}`)
  if (renderTable) {
    return (
      <div className="feed feed--table">
        {Array.from({ length: extra }, (_, i) => (
          <PageLoader key={i} filter={filter} sort={sort} page={i + 2} index={i} onLoad={onPageLoad} />
        ))}
        {renderTable({ rows: tableRows, refData, rowProps, selecting })}
        {canLoadMore && (
          <button ref={sentinel} type="button" className="btn btn--ghost load-more" onClick={loadMore}>Load more</button>
        )}
      </div>
    )
  }
  return (
    <div className="feed">
      {Array.from({ length: extra }, (_, i) => (
        <PageLoader
          key={i}
          filter={filter}
          sort={sort}
          page={i + 2}
          index={i}
          onLoad={onPageLoad}
        />
      ))}
      {groups.map((g) => (
        <section key={g.date} aria-labelledby={`day-${g.date}`}>
          <h3 className="daygroup" id={`day-${g.date}`}>
            <span>{g.label}</span>
            <span className="num"><Money amount={g.net} signed /></span>
          </h3>
          <ul
            className="ui-list feed__list"
            role={selecting ? 'listbox' : undefined}
            aria-multiselectable={selecting || undefined}
            aria-labelledby={selecting ? `day-${g.date}` : undefined}
          >
            {g.rows.map((t) => {
              const isPending = 'pending' in t
              const extraProps = isPending ? {} : rowProps?.(t) ?? {}
              const row = (
                <FeedRow t={t} refData={refData} pending={isPending} onOpen={extraProps.onOpen ?? open}
                  {...extraProps} selecting={selecting || extraProps.selecting} />
              )
              return (
                <li key={t.id} role={selecting ? 'none' : undefined}>
                  {renderRow ? renderRow(t, row, { pending: isPending }) : row}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
      {canLoadMore && (
        <button ref={sentinel} type="button" className="btn btn--ghost load-more" onClick={loadMore}>Load more</button>
      )}
    </div>
  )
}
