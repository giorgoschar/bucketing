import type { QueryClient } from '@tanstack/react-query'
import { db } from '../offline/db'
// queueDrain, not queue: listening must not depend on the replay module (AppShell's tests mock it).
import { onQueueDrained } from '../offline/queueDrain'
import { affects } from './keys'
import { clearPending } from './pending'

/**
 * After the offline queue sends (or fails) rows, the server's view has changed: refetch what writes touch,
 * and drop the "Waiting to sync" markers once no row is pending. Installed by AppShell while signed in.
 */
export function installQueueBridge(qc: QueryClient): () => void {
  return onQueueDrained(() => {
    for (const queryKey of affects.sync) void qc.invalidateQueries({ queryKey })
    void db.queue.where('status').equals('pending').count().then(
      (n) => { if (n === 0) clearPending() },
      () => {},
    )
  })
}
