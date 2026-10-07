import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys } from '../../data/keys'
import { useOnline } from '../../data/online'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { Money } from '../../ui/Money'
import { useToast } from '../../ui/Toast'
import { dayLabel, gapLabel, METHOD_LABELS, rowTitle } from './format'
import { useHeldDeletes } from './heldDeletes'
import { type DuplicateGroup, type RefData, type Txn, dismissDuplicates, useDuplicates, useRefData } from './hooks'
import { usePendingActivity } from './pending'
import { useDeleteWithUndo } from './useDeleteWithUndo'

const CLOSE_MINUTES = 10

function minutesApart(a: Txn, b: Txn) {
  return Math.abs(Date.parse(b.created_at ?? '') - Date.parse(a.created_at ?? '')) / 60000
}

function Well({ t, index, drop, refData, onToggle }: {
  t: Txn; index: number; drop: string | null; refData?: RefData; onToggle: () => void
}) {
  const dropping = drop === t.id
  const payer = t.payer_mode === 'own_share'
    ? 'each their share'
    : refData?.members.find((m) => m.user_id === t.paid_by)?.display_name ?? 'no payer'
  const category = refData?.categories.find((c) => c.id === t.category_id)?.name
  const time = t.created_at && t.created_at.length >= 16 ? ` ${t.created_at.slice(11, 16)}` : ''
  const label = dropping ? 'Will be deleted' : drop ? 'Kept' : index === 0 ? 'First' : 'Second'
  return (
    <button type="button" className={dropping ? 'well drop' : 'well'} aria-pressed={dropping} onClick={onToggle}>
      <span className={dropping ? 'well__tag neg' : 'well__tag'}>{label}</span>
      <span className="well__title">{rowTitle(t, refData)}</span>
      <b className="well__when">{dayLabel(t.transaction_date ?? '').replace(/^(Today|Yesterday) · /, '')}{time}</b>
      <span className="well__meta">{METHOD_LABELS[t.payment_method] ?? t.payment_method} · {payer}</span>
      {(category || t.receipt_path) && (
        <span className="well__meta">{[category, t.receipt_path ? 'receipt' : null].filter(Boolean).join(' · ')}</span>
      )}
    </button>
  )
}

function PairCard({ group, refData }: { group: DuplicateGroup; refData?: RefData }) {
  const qc = useQueryClient()
  const toast = useToast()
  const isOnline = useOnline()
  const deleteWithUndo = useDeleteWithUndo()
  const [drop, setDrop] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const rows = group.transactions
  const first = rows[0]
  const last = rows[rows.length - 1]
  const close = minutesApart(first, last) <= CLOSE_MINUTES

  const keepBoth = async () => {
    setBusy(true)
    try {
      await dismissDuplicates(rows.map((t) => t.id))
      await Promise.all([
        qc.invalidateQueries({ queryKey: keys.duplicates() }),
        qc.invalidateQueries({ queryKey: keys.transactions.counts() }),
      ])
    } catch (e) {
      toast.show((e as Error).message, { tone: 'error' })
    } finally {
      setBusy(false)
    }
  }
  const deleteOne = () => {
    const t = rows.find((r) => r.id === drop)
    if (!t) return
    setDrop(null)
    deleteWithUndo(t)
  }

  const title = rowTitle(first, refData)
  return (
    <article className="ui-card dup" aria-label={`Possible duplicate: ${title}`}>
      <div className="dup__head">
        <span className="dup__title">{title} · <Money amount={group.amount} currency={first.currency ?? 'EUR'} /></span>
        <Badge tone={close ? 'warn' : 'neutral'}>{gapLabel(first, last)}</Badge>
      </div>
      <div className="pair">
        {rows.map((t, i) => (
          <Well key={t.id} t={t} index={i} drop={drop} refData={refData} onToggle={() => setDrop(drop === t.id ? null : t.id)} />
        ))}
      </div>
      <div className="dup__actions">
        <button type="button" className="btn" disabled={!isOnline || busy} onClick={keepBoth}>Keep both</button>
        <button type="button" className="btn btn--danger" disabled={!drop} onClick={deleteOne}>Delete this one</button>
      </div>
      <p className="dup__hint" aria-live="polite">
        {!isOnline ? 'Keep both needs a connection' : drop ? 'Delete this one removes the marked entry. You can undo it.' : 'Tap the entry to delete.'}
      </p>
    </article>
  )
}

export function Duplicates() {
  const q = useDuplicates()
  const refData = useRefData()
  const held = useHeldDeletes()
  const queued = usePendingActivity().hidden
  if (!q.data) {
    if (q.noData) {
      return (
        <div role="status">
          <EmptyState title={q.offline ? 'Duplicates need a connection' : "Couldn't load duplicates"}
            action={q.offline ? undefined : { label: 'Try again', onClick: q.refetch }} />
        </div>
      )
    }
    return <p className="screen__note" aria-busy="true">Loading…</p>
  }
  // A pair with a held or queued delete is resolved: drop it at once.
  const groups = q.data.groups
    .map((g) => ({ ...g, transactions: g.transactions.filter((t) => !held.has(t.id) && !queued.has(t.id)) }))
    .filter((g) => g.transactions.length > 1)
  if (groups.length === 0) {
    return <div role="status"><EmptyState title="No possible duplicates in the last 90 days" /></div>
  }
  return (
    <div className="dups">
      <p className="dups__intro">Same amount within 3 days. Tap the one to delete, or keep both if they were really two buys.</p>
      {groups.map((g) => <PairCard key={g.transactions.map((t) => t.id).join()} group={g} refData={refData} />)}
      <p className="dups__foot">“Keep both” hides a pair from this list for good.</p>
    </div>
  )
}
