import { useLiveQuery } from 'dexie-react-hooks'
import { db } from './db'

export function useQueue(): { pending: number; failed: number } {
  const counts = useLiveQuery(async () => ({
    pending: await db.queue.where('status').equals('pending').count(),
    failed: await db.queue.where('status').equals('failed').count(),
  }))
  return counts ?? { pending: 0, failed: 0 }
}
