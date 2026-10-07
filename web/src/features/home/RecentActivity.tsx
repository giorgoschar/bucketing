import { Link } from 'react-router'
import { useBuckets } from '../../data/reads'
import type { TransactionRow } from '../../data/types'
import { EmptyState } from '../../ui/EmptyState'
import { formatShortDate } from '../../ui/format'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { useRecentTransactions } from './hooks'
import './home.css'

const label = (t: TransactionRow) => t.merchant || t.notes || (t.type === 'income' ? 'Income' : 'Expense')

export function RecentActivity() {
  const recent = useRecentTransactions()
  const buckets = useBuckets().data
  const bucketName = (id: string | null) => (id ? buckets?.find((b) => b.id === id)?.name : undefined)
  return (
    <section className="home-recent" aria-labelledby="recent-title">
      <div className="ui-sec">
        <h2 id="recent-title" className="ui-sec__title">Recent activity</h2>
        <Link to="/activity">See all</Link>
      </div>
      <QueryView result={recent} noDataText="No saved activity yet." showBanner={false}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState title="No payments yet" />
          ) : (
            <div className="ui-list">
              {rows.map((t) => (
                <ListRow key={t.id}
                  title={label(t)}
                  subtitle={[formatShortDate(t.transaction_date), bucketName(t.bucket_id)].filter(Boolean).join(' · ')}
                  trailing={<Money amount={t.type === 'income' ? t.amount : -t.amount} currency={t.currency} signed tone="auto" />} />
              ))}
            </div>
          )
        }
      </QueryView>
    </section>
  )
}
