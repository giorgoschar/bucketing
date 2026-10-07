import { formatCents } from './currencies'
import { shortDate } from './dates'
import type { Duplicate } from './types'

/** Advisory (spec §4.11): the likely match, with a way to open it or save this one anyway. */
export function DuplicateCard({ dup, onOpen, onSaveAnyway }: { dup: Duplicate; onOpen: () => void; onSaveAnyway: () => void }) {
  const what = dup.merchant ?? dup.bucket ?? 'an entry'
  return (
    <div className="composer__dup" role="alert">
      <p className="composer__dup-text">
        {`Looks like ${what} ${formatCents(Math.round(dup.amount * 100), dup.currency)} from ${shortDate(dup.date)}. Save anyway?`}
      </p>
      <div className="composer__dup-actions">
        <button type="button" className="btn btn--sm composer__dup-open" onClick={onOpen}>Open that one</button>
        <button type="button" className="btn btn--sm btn--primary" onClick={onSaveAnyway}>Save anyway</button>
      </div>
    </div>
  )
}
