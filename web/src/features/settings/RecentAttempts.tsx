import { useState } from 'react'
import { Link } from 'react-router'
import { Badge, type BadgeTone } from '../../ui/Badge'
import { ago, exactTime, useAttempts } from './attemptHooks'
import type { AttemptOutcome, IngestAttempt } from './attemptTypes'
import './settings.css'

const RESULT: Record<AttemptOutcome, { label: string; tone: BadgeTone }> = {
  created: { label: 'Added', tone: 'pos' },
  duplicate: { label: 'Duplicate', tone: 'warn' },
  rejected: { label: 'Rejected', tone: 'neg' },
}

function Row({ a }: { a: IngestAttempt }) {
  // Relative by default; a tap swaps in the exact time (also the title, for a pointer).
  const [exact, setExact] = useState(false)
  const at = exactTime(a.created_at)
  const rel = ago(a.created_at)
  const result = RESULT[a.outcome] ?? RESULT.rejected
  const meta = [a.token_name, a.outcome === 'rejected' ? `HTTP ${a.status_code}` : null].filter(Boolean).join(' · ')
  return (
    <li className="attempt">
      <div className="attempt__head">
        <Badge tone={result.tone}>{result.label}</Badge>
        <button type="button" className="attempt__time ui-num" title={at} aria-label={`${rel}, ${at}`}
          onClick={() => setExact((v) => !v)}>
          {exact ? at : rel}
        </button>
      </div>
      {/* As received: the amount is the Shortcut's own text, quoted, so a wrong format is visible. */}
      <p className="attempt__what">{`${a.merchant || 'No merchant'} · ${a.amount_raw ? `'${a.amount_raw}'` : 'no amount'}`}</p>
      {a.reason && <p className="attempt__reason">{a.reason}</p>}
      {(meta || a.transaction_id) && (
        <div className="attempt__foot">
          <span className="attempt__meta">{meta}</span>
          {a.transaction_id && (
            <Link className="attempt__link" to={`/activity/${encodeURIComponent(a.transaction_id)}`}>View transaction</Link>
          )}
        </div>
      )}
    </li>
  )
}

/** Settings › Apple Pay › Recent attempts: what the server received from the Shortcut (newest 50), to debug
 *  it. Online only and never saved on the phone (see useAttempts). */
export function RecentAttempts() {
  const q = useAttempts()
  const items = q.data?.items
  return (
    <section aria-labelledby="attempts-h" className="attempts">
      <div className="attempts__head">
        <h2 id="attempts-h" className="settings__group">Recent attempts</h2>
        <button type="button" className="btn btn--sm" disabled={q.offline} onClick={q.refetch}>Refresh</button>
      </div>
      {items && items.length > 0 ? (
        <ul className="ui-list attempts__list" aria-label="Recent attempts">
          {items.map((a) => <Row key={a.id} a={a} />)}
        </ul>
      ) : items ? (
        <p className="settings__help">No attempts yet. Run the Shortcut or pay with Apple Pay, then tap Refresh.</p>
      ) : q.offline ? (
        <p className="settings__help">Recent attempts need a connection.</p>
      ) : q.isError ? (
        <p className="settings__help attempts__error">
          <span>Couldn’t load the attempts.</span>
          <button type="button" className="btn btn--sm" onClick={q.refetch}>Try again</button>
        </p>
      ) : (
        <div className="ui-skeleton" role="status" aria-busy="true" aria-label="Loading" />
      )}
    </section>
  )
}
