/**
 * GET /api/v1/ingest/attempts: what the server received from the Apple Pay Shortcut, newest 50. Hand-written
 * while the server stream adds it; the integration step runs gen:api and turns these into aliases.
 */
export type AttemptOutcome = 'created' | 'duplicate' | 'rejected'

export interface IngestAttempt {
  id: string
  created_at: string
  status_code: number
  outcome: AttemptOutcome
  /** Why it was rejected (or noted as a duplicate), in the server's words. */
  reason: string | null
  merchant: string | null
  /** The amount exactly as the Shortcut sent it, e.g. "€12,50". */
  amount_raw: string | null
  transaction_id: string | null
  token_name: string | null
}

export interface IngestAttemptsOut { items: IngestAttempt[] }

/** Replies of routes the generated schema doesn't have yet (test/fakeApi.ts uses this). */
export interface IngestReplies {
  'GET /api/v1/ingest/attempts': IngestAttemptsOut
}
