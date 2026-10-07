import type { BudgetRowOut, PaceOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatShortDate } from '../../ui/format'
import { Money } from '../../ui/Money'
import { ProgressBar } from '../../ui/ProgressBar'
import { QueryView } from '../../ui/QueryView'
import { useBudgets, usePace } from './hooks'
import './plan.css'

export function Budgets() {
  const budgets = useBudgets()
  const pace = usePace()
  return (
    <QueryView result={budgets} noDataText="No saved data yet. Connect once to load Plan.">
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState title="No budgets yet" body="Budgets are set on buckets." />
        ) : (
          <div className="ui-list">
            {rows.map((b) => (
              <BudgetRow key={b.bucket_id} row={b} pace={pace.data?.find((p) => p.bucket_id === b.bucket_id)} />
            ))}
          </div>
        )
      }
    </QueryView>
  )
}

function BudgetRow({ row, pace }: { row: BudgetRowOut; pace?: PaceOut }) {
  const event = row.kind === 'event'
  const days = row.days_left
  return (
    <div className="plan-budget">
      <div className="plan-budget__top">
        <span className="plan-budget__name">{row.name}</span>
        <span className="plan-budget__fig">
          {row.budget === null
            ? <><Money amount={row.spent} whole /> spent</>
            : <><Money amount={row.spent} whole /> of <Money amount={row.budget} whole /></>}
        </span>
      </div>
      {row.budget !== null && row.budget > 0 && <ProgressBar value={row.spent} max={row.budget} label={row.name} />}
      <div className="plan-budget__foot">
        {event && row.period_start && row.period_end && (
          <span>{formatShortDate(row.period_start)} – {formatShortDate(row.period_end)}</span>
        )}
        {event && days !== null && <span>{days === 1 ? '1 day left' : `${days} days left`}</span>}
        {pace && pace.pace !== null && <span>on pace for <Money amount={pace.pace} whole /></span>}
        {pace && pace.pace !== null && pace.over_pace && <Badge tone="warn">over pace</Badge>}
        {row.pct !== null && row.pct >= 100 && <Badge tone="neg">over budget</Badge>}
        {event && row.archive_suggested && <Badge>Archive?</Badge>}
      </div>
    </div>
  )
}
