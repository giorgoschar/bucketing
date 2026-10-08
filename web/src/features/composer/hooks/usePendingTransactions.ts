import { useLiveQuery } from 'dexie-react-hooks'
import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { db } from '../../../offline/db'
import { listQueuedBodies, type QueuedBody } from '../../../offline/queuedBodies'
import { type BodyLike, type PendingRow, pendingStore, rowFromBody } from './pendingStore'

const PREFIX = '/api/v1/transactions'
const ONE = /^\/api\/v1\/transactions\/([^/]+)$/

export interface PendingView {
  /** Newest first: saves in flight, then queued creates. */
  rows: PendingRow[]
  /** Queued full edits by transaction id: show these values on the server row. */
  edits: ReadonlyMap<string, PendingRow>
  /** Deleted (queued or in flight): hide these server rows. */
  hiddenIds: ReadonlySet<string>
  /** Home's "N entries waiting to sync". */
  waitingCount: number
  justSaved: string | null
}

export function pendingFromQueue(queued: QueuedBody[]) {
  const creates: PendingRow[] = []
  const edits = new Map<string, PendingRow>()
  const deletes = new Set<string>()
  for (const q of queued) {
    const one = ONE.exec(q.path)
    if (q.method === 'POST' && q.path === PREFIX) creates.push(rowFromBody(q.body as BodyLike, 'waiting'))
    else if (one && q.method === 'PUT') edits.set(one[1], rowFromBody(q.body as BodyLike, 'waiting', one[1]))
    else if (one && q.method === 'DELETE') deletes.add(one[1])
  }
  return { creates, edits, deletes }
}

export function usePendingTransactions(): PendingView {
  // Dexie live query on the raw row ids only; decryption runs outside it (WebCrypto is not a Dexie promise).
  const ids = useLiveQuery(() => db.queue.where('status').equals('pending').primaryKeys(), [], [] as number[])
  const sig = ids.join(',')
  const [queued, setQueued] = useState<QueuedBody[]>([])
  useEffect(() => {
    let live = true
    void listQueuedBodies(PREFIX).then((b) => { if (live) setQueued(b) })
    return () => { live = false }
  }, [sig])
  const snap = useSyncExternalStore(pendingStore.subscribe, pendingStore.snapshot)
  return useMemo(() => {
    const q = pendingFromQueue(queued)
    const waitingKeys = new Set(q.creates.map((r) => r.key))
    return {
      rows: [...snap.inFlight.filter((r) => !waitingKeys.has(r.key)), ...q.creates.reverse()],
      edits: q.edits,
      hiddenIds: new Set([...snap.hidden, ...q.deletes]),
      waitingCount: q.creates.length + q.edits.size + q.deletes.size,
      justSaved: snap.justSaved,
    }
  }, [queued, snap])
}
