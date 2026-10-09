import type { components } from '../../api/schema'

/** GET /api/v1/ingest/attempts: what the server received from the Apple Pay Shortcut, newest 50. */
export type IngestAttempt = components['schemas']['IngestAttemptOut']
export type IngestAttemptsOut = components['schemas']['IngestAttemptsOut']
export type AttemptOutcome = IngestAttempt['outcome']
