import type { KeyboardEvent } from 'react'
import { Badge } from '../../ui/Badge'
import { Check } from '../../ui/Check'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { rowSubtitle, rowTitle } from './format'
import type { RefData, Txn } from './hooks'

type Props = {
  t: Txn
  refData?: RefData
  onOpen: (id: string) => void
  pending?: boolean
  selecting?: boolean
  selected?: boolean
}

/** One feed row. Browsing, it is a button that opens the detail. Selecting, it is an `option` in the day's
 * multi-select listbox (Feed sets that role): aria-selected plus a tick, toggled by tap, Space or Enter.
 * A queued row can't be selected (aria-disabled). */
export function FeedRow({ t, refData, onOpen, pending, selecting, selected }: Props) {
  const fixed = t.type === 'expense' && !!t.recurring_bill_id && !t.bucket_id
  const sign = t.type === 'income' ? 1 : t.type === 'expense' ? -1 : 0
  const icon = refData?.categories.find((c) => c.id === t.category_id)?.icon ?? '•'
  const badges = [
    t.payment_method === 'apple_pay' && <Badge key="ap">Apple Pay</Badge>,
    fixed && <Badge key="fx">Fixed</Badge>,
    pending && <Badge key="p" tone="warn">Waiting to sync</Badge>,
  ].filter(Boolean)
  const row = (
    <ListRow
      leading={<span aria-hidden="true">{icon}</span>}
      title={rowTitle(t, refData)}
      subtitle={rowSubtitle(t, refData)}
      trailing={<Money amount={sign === 0 ? t.amount : sign * t.amount} currency={t.currency ?? 'EUR'} signed={sign !== 0} />}
      badges={badges}
      onClick={selecting ? undefined : () => onOpen(t.id)}
    />
  )
  if (!selecting) return <div className="feedrow" data-pending={pending || undefined}>{row}</div>

  const toggle = () => {
    if (!pending) onOpen(t.id)
  }
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      toggle()
    }
  }
  return (
    <div
      className="feedrow feedrow--select"
      role="option"
      aria-selected={!!selected}
      aria-disabled={pending || undefined}
      tabIndex={pending ? -1 : 0}
      data-pending={pending || undefined}
      onClick={toggle}
      onKeyDown={onKey}
    >
      <Check checked={!!selected} />
      {row}
    </div>
  )
}
