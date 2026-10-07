import { Link } from 'react-router'
import { Money } from '../../ui/Money'
import { ProgressBar } from '../../ui/ProgressBar'
import { rowTitle } from './format'
import type { BulkResult, RefData, Txn } from './hooks'

const eur = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })

/** The dry-run result, before → after in words as well as bars (spec §7). Each skipped reason is a
 * native <details> listing its rows. */
export function BulkPreview({ result, rows = [], refData }: { result: BulkResult; rows?: Txn[]; refData?: RefData }) {
  const reasons = new Map<string, string[]>()
  for (const s of result.skipped) reasons.set(s.reason, [...(reasons.get(s.reason) ?? []), s.id])
  const title = (id: string) => {
    const t = rows.find((r) => r.id === id)
    return t ? rowTitle(t, refData) : `Payment ${id.slice(0, 8)}`
  }
  return (
    <div className="bulk-preview" aria-live="polite">
      <p className="bulk-preview__sum">
        <b className="num">{result.changed}</b> of <span className="num">{result.matched}</span> change
        {result.total_out > 0 && <> · out <Money amount={result.total_out} /></>}
        {result.total_in > 0 && <> · in <Money amount={result.total_in} /></>}
      </p>
      {result.unchanged > 0 && <p className="bulk-preview__note">{result.unchanged} already set</p>}
      {result.buckets.map((b) => (
        <div key={b.bucket_id ?? 'none'} className="bulk-preview__bucket">
          <p className="bulk-preview__line num">
            {b.name}: {eur.format(b.spent_before)} → {eur.format(b.spent_after)}{b.budget != null ? ` of ${eur.format(b.budget)}` : ''}
          </p>
          {b.budget != null && <ProgressBar value={b.spent_after} max={b.budget} label={`${b.name} after the change`} thin />}
          <p className="bulk-preview__note">
            {b.kind === 'event' ? `${b.period_start ?? '…'} to ${b.period_end ?? '…'}` : 'This month'}
          </p>
          {b.outside_period > 0 && <p className="bulk-preview__note">+{b.outside_period} from other periods, not in this budget</p>}
        </div>
      ))}
      {result.bill && (
        <p className="bulk-preview__line">
          {result.bill.name} moves from {result.bill.bucket_before ?? 'no bucket'} to {result.bill.bucket_after ?? 'no bucket'}
        </p>
      )}
      {[...reasons].map(([reason, ids]) => (
        <details key={reason} className="bulk-preview__skip">
          <summary>{ids.length} skipped: {reason}</summary>
          <ul>
            {ids.map((id) => <li key={id}><Link to={`/activity/${encodeURIComponent(id)}`}>{title(id)}</Link></li>)}
          </ul>
        </details>
      ))}
    </div>
  )
}
