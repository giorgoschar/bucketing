import { useState } from 'react'
import { Link } from 'react-router'
import { useOnline } from '../../data/online'
import { Sheet } from '../../ui/Sheet'
import { useRecentBulk } from './hooks'
import { type UndoSkip, useUndoBulk } from './useUndoBulk'

const WHEN = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

/** The last 10 bulk changes, newest first; Undo on the ones still within 24 h and not undone. */
export function RecentBulk({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useRecentBulk()
  const recent = q.data ?? []
  const isOnline = useOnline()
  const [details, setDetails] = useState<UndoSkip[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const undo = useUndoBulk(setDetails)
  const run = async (id: string) => {
    setBusy(id)
    setDetails(null)
    try {
      await undo(id)
    } finally {
      setBusy(null)
    }
  }
  return (
    <Sheet open={open} onClose={onClose} title="Recent bulk changes">
      {q.data && recent.length === 0 && <p className="recent-bulk__empty">No bulk changes yet</p>}
      {!q.data && <p className="recent-bulk__empty" aria-busy={!q.noData}>{q.noData ? 'Needs a connection' : 'Loading…'}</p>}
      {recent.length > 0 && (
        <ul className="ui-list recent-bulk">
          {recent.map((b) => (
            <li key={b.id} className="ui-row recent-bulk__row">
              <span className="ui-row__main">
                <span className="recent-bulk__text">{b.summary}</span>
                <span className="ui-row__sub">
                  {WHEN.format(new Date(b.created_at))}{b.created_by ? ` · ${b.created_by}` : ''}{b.undone_at ? ' · Undone' : ''}
                </span>
              </span>
              {b.can_undo && (
                <button type="button" className="btn btn--ghost btn--sm" disabled={!isOnline || busy !== null}
                  onClick={() => void run(b.id)}>
                  {busy === b.id ? 'Undoing…' : 'Undo'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {!isOnline && recent.some((b) => b.can_undo) && <p className="recent-bulk__empty">Undo needs a connection</p>}
      {details && (
        <section className="recent-bulk__details" aria-labelledby="left-h">
          <h3 id="left-h" className="detail__h">Left as they are</h3>
          <ul>
            {details.map((d) => (
              <li key={d.id}><Link to={`/activity/${encodeURIComponent(d.id)}`} onClick={onClose}>{d.reason}</Link></li>
            ))}
          </ul>
        </section>
      )}
    </Sheet>
  )
}
