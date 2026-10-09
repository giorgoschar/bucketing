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
  classified: { label: 'Category set', tone: 'pos' },
}

/**
 * The server's payload summary ({key: {type, value}, unknown_keys: n}, compact JSON) as one "key: preview"
 * line per field. Defensive: anything that is not that shape (a plain sentence such as "not a JSON object
 * (12 bytes, text/plain)", or JSON of another shape) comes back as null and the caller shows it as text.
 */
export function summaryLines(payload: string): string[] | null {
  let data: unknown
  try { data = JSON.parse(payload) } catch { return null }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  const lines: string[] = []
  for (const [key, field] of Object.entries(data)) {
    if (key === 'unknown_keys') {
      if (typeof field === 'number' && field > 0) lines.push(`other keys: ${field}`)
    } else if (field && typeof field === 'object' && !Array.isArray(field)) {
      const { type, value } = field as { type?: unknown; value?: unknown }
      const shown = typeof value === 'string' || typeof value === 'number' ? String(value)
        : type === 'missing' ? 'not sent' : type === 'null' ? 'empty' : '?'
      lines.push(`${key}: ${shown}`)
    } else return null
  }
  return lines
}

function Payload({ payload }: { payload: string | null | undefined }) {
  if (payload == null) return <p className="attempt__reason">Older entry: details not kept</p>
  const lines = summaryLines(payload)
  // Rendered as text nodes only: nothing here is ever HTML.
  if (!lines || lines.length === 0) return <p className="attempt__what">{payload}</p>
  return <div className="attempt__fields">{lines.map((l, i) => <p key={i}>{l}</p>)}</div>
}

function Row({ a }: { a: IngestAttempt }) {
  // Relative by default; a tap swaps in the exact time (also the title, for a pointer).
  const [exact, setExact] = useState(false)
  const at = exactTime(a.created_at)
  const rel = ago(a.created_at)
  const result = RESULT[a.outcome] ?? RESULT.rejected
  const meta = [a.token_prefix, a.outcome === 'rejected' ? `HTTP ${a.status}` : null].filter(Boolean).join(' · ')
  return (
    <li className="attempt">
      <div className="attempt__head">
        <Badge tone={result.tone}>{result.label}</Badge>
        <button type="button" className="attempt__time ui-num" title={at} aria-label={`${rel}, ${at}`}
          onClick={() => setExact((v) => !v)}>
          {exact ? at : rel}
        </button>
      </div>
      <Payload payload={a.payload} />
      {a.detail && a.detail !== 'created' && a.detail !== '[older entry]' && <p className="attempt__reason">{a.detail}</p>}
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
