import { open } from './crypto'
import { db } from './db'
import { getIdentity, type Identity } from './identity'

export interface QueuedBody { id: number; method: 'POST' | 'PUT' | 'PATCH' | 'DELETE'; path: string; body: unknown }
interface Stored { method: QueuedBody['method']; path: string; body?: unknown; owner?: Identity }

/**
 * Decrypted pending writes under `pathPrefix`, oldest first (2b spec §3.1). Rebuilds "Waiting to sync"
 * rows after a reload, since optimistic patches live only in memory. Read-only: never sends or deletes.
 */
export async function listQueuedBodies(pathPrefix: string): Promise<QueuedBody[]> {
  const me = getIdentity()
  if (!me) return []
  const rows = await db.queue.where('status').equals('pending').sortBy('id')
  const out: QueuedBody[] = []
  for (const row of rows) {
    try {
      const req = await open<Stored>(row)
      if (req.owner?.user_id !== me.user_id || req.owner?.household_id !== me.household_id) continue
      if (!req.path.startsWith(pathPrefix)) continue
      out.push({ id: row.id!, method: req.method, path: req.path, body: req.body })
    } catch {
      // Undecryptable or wiped mid-read: the drain handles it; just don't show it.
    }
  }
  return out
}
