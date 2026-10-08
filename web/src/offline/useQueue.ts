import { useLiveQuery } from 'dexie-react-hooks'
import { db } from './db'

export function useQueue(): { pending: number; failed: number } {
  const counts = useLiveQuery(async () => ({
    pending: await db.queue.where('status').equals('pending').count(),
    failed: await db.queue.where('status').equals('failed').count(),
  }))
  return counts ?? { pending: 0, failed: 0 }
}

export interface FailedQueueRow { id: number; error: string; createdAt: number }
const NO_ROWS: FailedQueueRow[] = []

/** Queued changes the server refused on replay (spec §3.2 step 4), oldest first. Only `error` is plaintext. */
export function useFailedQueueRows(): FailedQueueRow[] {
  const rows = useLiveQuery(async () =>
    (await db.queue.where('status').equals('failed').sortBy('id')).map((r) => ({
      id: r.id!,
      error: r.error || 'The server refused this change.',
      createdAt: r.createdAt,
    })))
  return rows ?? NO_ROWS
}

export function dismissFailed(id: number): Promise<void> {
  return db.queue.delete(id)
}
