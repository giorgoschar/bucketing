import { useState } from 'react'
import type { BudgetRowOut, PaceOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatShortDate } from '../../ui/format'
import { Money } from '../../ui/Money'
import { ProgressBar } from '../../ui/ProgressBar'
import { QueryView } from '../../ui/QueryView'
import { Sheet } from '../../ui/Sheet'
import { BucketSheet, useRawBuckets, type RawBucket } from './BucketSheet'
import { useArchiveBucket, useBudgets, usePace } from './hooks'
import './plan.css'

export function Budgets() {
  const budgets = useBudgets()
  const pace = usePace()
  const archive = useArchiveBucket()
  const [archiving, setArchiving] = useState<BudgetRowOut | null>(null)
  const [busy, setBusy] = useState(false)
  const raw = useRawBuckets().data ?? []
  // undefined: closed, null: a new bucket
  const [editing, setEditing] = useState<RawBucket | null | undefined>(undefined)
  const confirmArchive = async () => {
    if (!archiving) return
    setBusy(true)
    const out = await archive(archiving.bucket_id)
    setBusy(false)
    if (out.ok) setArchiving(null)
  }
  return (
    <>
    <div className="plan-buckets__bar">
      <button type="button" className="btn btn--sm btn--primary" onClick={() => setEditing(null)}>New bucket</button>
    </div>
    <QueryView result={budgets} noDataText="No saved data yet. Connect once to load Plan.">
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState title="No buckets yet" body="Add a bucket to give your spending a place." />
        ) : (
          <div className="ui-list">
            {rows.map((b) => (
              <BudgetRow key={b.bucket_id} row={b} pace={pace.data?.find((p) => p.bucket_id === b.bucket_id)} onArchive={setArchiving} onEdit={setEditing} raw={raw.find((r) => r.id === b.bucket_id)} />
            ))}
          </div>
        )
      }
    </QueryView>
    <Sheet open={archiving !== null} onClose={() => setArchiving(null)} title="Archive bucket">
      <div className="plan-archive">
        <p className="plan-archive__text">{archiving ? `Archive ${archiving.name}? There is no undo: it leaves Plan and the new app.` : ''}</p>
        <div className="plan-archive__actions">
          <button type="button" className="btn" onClick={() => setArchiving(null)}>Cancel</button>
          <button type="button" className="btn btn--danger" disabled={busy} onClick={() => void confirmArchive()}>Archive</button>
        </div>
      </div>
    </Sheet>
    <BucketSheet open={editing !== undefined} bucket={editing ?? null} onClose={() => setEditing(undefined)} />
    </>
  )
}

function BudgetRow({ row, pace, raw, onArchive, onEdit }: {
  row: BudgetRowOut; pace?: PaceOut; raw?: RawBucket; onArchive(row: BudgetRowOut): void; onEdit(b: RawBucket): void
}) {
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
        {raw && (
          <button type="button" className="btn btn--sm plan-budget__edit" aria-label={`Edit ${row.name}`} onClick={() => onEdit(raw)}>Edit</button>
        )}
        {event && row.archive_suggested && (
          <button type="button" className="btn btn--sm plan-budget__archive" aria-label={`Archive ${row.name}`} onClick={() => onArchive(row)}>
            Archive?
          </button>
        )}
      </div>
    </div>
  )
}
