import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { EmptyState } from '../../ui/EmptyState'
import { Money } from '../../ui/Money'
import { type TransactionFilter, activeFilterCount, isEmpty } from './filters'
import { groupByDay } from './format'
import { FeedRow } from './FeedRow'
import { type RefData, type Txn, type TxnPage, useFeedPage, useRefData } from './hooks'
import { type PendingTxn, usePendingTransactions } from './pending'

export type RenderRow = (t: Txn, row: ReactNode, opts: { pending: boolean }) => ReactNode

type Props = {
  filter: TransactionFilter
  onClear: () => void
  renderRow?: RenderRow
  hidden?: ReadonlySet<string>
  rowProps?: (t: Txn) => { selecting?: boolean; selected?: boolean; onOpen?: (id: string) => void }
  onLoaded?: (rows: Txn[], total: number) => void
}

export function Feed(props: Props) {
  // A new filter starts a new list: drop the pages of the old one.
  return <FeedList key={JSON.stringify(props.filter)} {...props} />
}

function PageLoader({ filter, page, index, onLoad }: {
  filter: TransactionFilter; page: number; index: number; onLoad: (index: number, p: TxnPage) => void
}) {
  const q = useFeedPage(filter, page)
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

function FeedList({ filter, onClear, renderRow, hidden, rowProps, onLoaded }: Props) {
  const navigate = useNavigate()
  const refData: RefData | undefined = useRefData()
  const first = useFeedPage(filter, 1)
  const [more, setMore] = useState<TxnPage[]>([])
  const [extra, setExtra] = useState(0)
  const pendingAll = usePendingTransactions()
  const plain = isEmpty({ ...filter, from_date: undefined, to_date: undefined })

  const loaded = useMemo(() => (first.data ? [first.data, ...more.filter(Boolean)] : []), [first.data, more])
  const total = first.data?.total ?? 0
  // A row can shift between pages while the user scrolls: keep the first copy, in first-seen order.
  const serverRows = [...new Map(loaded.flatMap((p) => p.items).map((t) => [t.id, t])).values()]
  const rows = serverRows.filter((t) => !hidden?.has(t.id))
  const pending: PendingTxn[] = plain ? pendingAll : []
  const dayTotals = Object.assign({}, ...loaded.map((p) => p.day_totals)) as Record<string, number>
  const groups = groupByDay(
    [...pending, ...rows].sort((a, b) => (b.transaction_date ?? '').localeCompare(a.transaction_date ?? '')),
    dayTotals,
  )
  const canLoadMore = serverRows.length < total

  useEffect(() => {
    onLoaded?.(serverRows, total)
  }, [serverRows.length, total]) // eslint-disable-line react-hooks/exhaustive-deps

  const onPageLoad = useCallback(
    (i: number, p: TxnPage) => setMore((m) => (m[i] === p ? m : Object.assign([...m], { [i]: p }))),
    [],
  )
  const loadMore = useCallback(() => setExtra((n) => n + 1), [])
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
  return (
    <div className="feed">
      {Array.from({ length: extra }, (_, i) => (
        <PageLoader
          key={i}
          filter={filter}
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
          <ul className="ui-list feed__list">
            {g.rows.map((t) => {
              const isPending = 'pending' in t
              const extraProps = isPending ? {} : rowProps?.(t) ?? {}
              const row = (
                <FeedRow t={t} refData={refData} pending={isPending} onOpen={extraProps.onOpen ?? open} {...extraProps} />
              )
              return <li key={t.id}>{renderRow ? renderRow(t, row, { pending: isPending }) : row}</li>
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
