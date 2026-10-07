import { Link } from 'react-router'
import { useBuckets } from '../../data/reads'
import type { TransactionRow } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatShortDate } from '../../ui/format'
import { ClockIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import type { PendingRow } from '../composer/hooks/pendingStore'
import { usePendingTransactions } from '../composer/hooks/usePendingTransactions'
import { useRecentTransactions } from './hooks'
import { mergePending } from './mergePending'
import './home.css'

const label = (t: TransactionRow) => t.merchant || t.notes || (t.type === 'income' ? 'Income' : 'Expense')

/** A change still in the offline queue (or being sent): 2b spec §4.8. */
const waiting = <Badge tone="neutral" icon={<ClockIcon />}>Waiting to sync</Badge>
const signedAmount = (type: string, amount: number) => (type === 'income' ? amount : -amount)

export function RecentActivity() {
  const recent = useRecentTransactions()
  const pending = usePendingTransactions()
  const buckets = useBuckets().data
  const bucketName = (id: string | null) => (id ? buckets?.find((b) => b.id === id)?.name : undefined)
  const pendingRow = (r: PendingRow, key: string) => (
    <ListRow key={key}
      title={r.merchant || bucketName(r.bucket_id) || (r.type === 'income' ? 'Income' : 'Expense')}
      subtitle={[formatShortDate(r.transaction_date), bucketName(r.bucket_id)].filter(Boolean).join(' · ')}
      badges={waiting}
      trailing={<Money amount={signedAmount(r.type, Number(r.amount))} currency={r.currency} signed tone="auto" />} />
  )
  return (
    <section className="home-recent" aria-labelledby="recent-title">
      <div className="ui-sec">
        <h2 id="recent-title" className="ui-sec__title">Recent activity</h2>
        <Link to="/activity">See all</Link>
      </div>
      {recent.data === undefined && recent.noData && (() => {
        // Nothing loaded and nothing coming, but this phone's own queued saves are still worth showing.
        const queued = mergePending([], pending)
        return queued.length > 0 && (
          <div className="ui-list">
            {queued.map((it) => (it.kind === 'pending' ? pendingRow(it.row, `p:${it.row.key}`) : null))}
          </div>
        )
      })()}
      <QueryView result={recent} noDataText="No saved activity yet." showBanner={false}>
        {(rows) => {
          const items = mergePending(rows, pending)
          if (items.length === 0) return <EmptyState title="No payments yet" />
          return (
            <div className="ui-list">
              {items.map((it) => {
                if (it.kind === 'pending') return pendingRow(it.row, `p:${it.row.key}`)
                const t = it.txn
                if (it.edit) return pendingRow(it.edit, t.id)
                return (
                  <ListRow key={t.id} className={it.highlight ? 'is-new' : undefined}
                    title={label(t)}
                    subtitle={[formatShortDate(t.transaction_date), bucketName(t.bucket_id)].filter(Boolean).join(' · ')}
                    trailing={<Money amount={signedAmount(t.type, t.amount)} currency={t.currency} signed tone="auto" />} />
                )
              })}
            </div>
          )
        }}
      </QueryView>
    </section>
  )
}
