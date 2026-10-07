import type { QueryClient } from '@tanstack/react-query'
import { liveQuery } from 'dexie'
import { db } from '../offline/db'
// queueDrain, not queue: listening must not depend on the replay module (AppShell's tests mock it).
import { onQueueDrained } from '../offline/queueDrain'
import { affects } from './keys'
import { clearPending } from './pending'

/**
 * After the offline queue sends (or fails) rows, the server's view has changed: refetch what writes touch.
 * The "Waiting to sync" markers drop whenever the live pending count reaches 0, whoever drained the
 * queue (this tab, another tab, or a wipe). Installed by AppShell while signed in.
 */
export function installQueueBridge(qc: QueryClient): () => void {
  const stopDrain = onQueueDrained(() => {
    for (const queryKey of affects.sync) void qc.invalidateQueries({ queryKey })
  })
  const sub = liveQuery(() => db.queue.where('status').equals('pending').count()).subscribe({
    next: (n) => { if (n === 0) clearPending() },
    error: () => {},
  })
  return () => {
    stopDrain()
    sub.unsubscribe()
  }
}
