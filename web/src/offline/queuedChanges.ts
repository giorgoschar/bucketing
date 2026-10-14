import { db } from './db'

/** A household change wipes the offline queue, so it must not run while writes are waiting (pending or failed). */
export async function queuedBlock(): Promise<string | null> {
  const n = await db.queue.count()
  return n ? `You have ${n} change${n === 1 ? '' : 's'} waiting to sync. Go online and let them sync first.` : null
}
