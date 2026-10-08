import type { Method } from '../state'
import type { Member } from '../types'

export const METHOD_LABELS: Record<Method, string> = {
  card: 'Card', cash: 'Cash', apple_pay: 'Apple Pay', transfer: 'Transfer', other: 'Other',
}

export const memberName = (m: Member | undefined): string => m?.display_name ?? m?.username ?? 'Member'
