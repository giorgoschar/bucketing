import type { RefData, Txn, TxnPatch } from './hooks'
import type { Option } from './OptionSheet'

export const OWN_SHARE = '__own'
const NO_BUCKET = ''

/** The Bucket picker (spec §4.4, R7): income may have no bucket and only
 * goes to buckets that track income; a bucket-less Fixed cost may stay
 * bucket-less; a bill payment that has a bucket keeps one. */
export function bucketOptions(t: Txn, ref: RefData): { options: Option[]; note?: string } {
  const active = ref.buckets.filter((b) => b.status === 'active')
  const asOption = (b: RefData['buckets'][number]): Option => ({
    value: b.id, label: b.name, hint: b.kind === 'event' ? 'Event' : undefined,
  })
  if (t.type === 'income') {
    return { options: [{ value: NO_BUCKET, label: 'No bucket' }, ...active.filter((b) => b.show_income).map(asOption)] }
  }
  const fixedCost = t.type === 'expense' && !!t.recurring_bill_id && !t.bucket_id
  return {
    options: [...(fixedCost ? [{ value: NO_BUCKET, label: 'No bucket (Fixed cost)' }] : []), ...active.map(asOption)],
    note: t.recurring_bill_id && t.bucket_id ? 'Bill payments keep a bucket. Move the bill instead.' : undefined,
  }
}

export function payerOptions(ref: RefData): Option[] {
  return [
    ...ref.members.map((m) => ({ value: m.user_id, label: m.display_name ?? 'Member' })),
    { value: OWN_SHARE, label: 'Each paid their own share' },
  ]
}

export function payerPatch(value: string): TxnPatch {
  return value === OWN_SHARE ? { paid_by: null, payer_mode: 'own_share' } : { paid_by: value, payer_mode: 'single' }
}
