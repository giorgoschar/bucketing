import { fetchJson } from '../../data/rawJson'
import { unwrap } from '../../data/http'
import { useSession } from '../../session/SessionProvider'
import type { IngestAttemptsOut } from './attemptTypes'
import { useLiveQuery } from './hooks'

/** Timestamps without a zone are UTC (the server's naive datetimes). */
const utc = (iso: string) => Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)

/** "just now", "5m ago", "3h ago", "4d ago". */
export function ago(iso: string, now = Date.now()): string {
  const mins = Math.max(0, Math.floor((now - utc(iso)) / 60_000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 48 * 60) return `${Math.round(mins / 60)}h ago`
  return `${Math.round(mins / 1440)}d ago`
}

const EXACT = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
/** "8 Oct 2026, 13:05:09" in the phone's time zone. */
export const exactTime = (iso: string): string => EXACT.format(new Date(utc(iso)))

/**
 * The Shortcut's recent attempts. Diagnostic, and it carries merchant names: online only, fetched fresh
 * every time (useLiveQuery: gcTime 0), never written to the device cache.
 */
export function useAttempts() {
  const hh = useSession().me?.household_id ?? ''
  return useLiveQuery(['settings', 'ingest-attempts', hh], async (): Promise<IngestAttemptsOut> =>
    unwrap(fetchJson<IngestAttemptsOut>('GET', '/api/v1/ingest/attempts')))
}
