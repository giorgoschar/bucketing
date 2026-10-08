import type { PendingRow } from '../composer/hooks/pendingStore'
import type { PendingView } from '../composer/hooks/usePendingTransactions'

export type RecentItem<T> =
  | { kind: 'server'; txn: T; edit: PendingRow | null; highlight: boolean }
  | { kind: 'pending'; row: PendingRow }

/** Home › Recent: pending rows on top, deleted rows hidden, queued edits shown, the new row highlighted. */
export function mergePending<T extends { id: string }>(server: T[], view: PendingView, limit = 10): RecentItem<T>[] {
  const pending: RecentItem<T>[] = view.rows.map((row) => ({ kind: 'pending', row }))
  const rest: RecentItem<T>[] = server
    .filter((t) => !view.hiddenIds.has(t.id))
    .map((t) => ({ kind: 'server', txn: t, edit: view.edits.get(t.id) ?? null, highlight: t.id === view.justSaved }))
  return [...pending, ...rest].slice(0, limit)
}
