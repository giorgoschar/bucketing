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

export function FeedRow({ t, refData, onOpen, pending, selecting, selected }: Props) {
  const fixed = t.type === 'expense' && !!t.recurring_bill_id && !t.bucket_id
  const sign = t.type === 'income' ? 1 : t.type === 'expense' ? -1 : 0
  const icon = refData?.categories.find((c) => c.id === t.category_id)?.icon ?? '•'
  const badges = [
    t.payment_method === 'apple_pay' && <Badge key="ap">Apple Pay</Badge>,
    fixed && <Badge key="fx">Fixed</Badge>,
    pending && <Badge key="p" tone="warn">Waiting to sync</Badge>,
  ].filter(Boolean)
  // TODO(Task 18): aria-selected on a plain div is not valid ARIA; give the row a role when selection lands.
  return (
    <div className="feedrow" aria-selected={selecting ? !!selected : undefined} data-pending={pending || undefined}>
      {selecting && <Check checked={!!selected} />}
      <ListRow
        leading={<span aria-hidden="true">{icon}</span>}
        title={rowTitle(t, refData)}
        subtitle={rowSubtitle(t, refData)}
        trailing={<Money amount={sign === 0 ? t.amount : sign * t.amount} currency={t.currency ?? 'EUR'} signed={sign !== 0} />}
        badges={badges}
        onClick={() => onOpen(t.id)}
      />
    </div>
  )
}
