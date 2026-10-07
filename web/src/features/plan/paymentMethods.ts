import type { PaymentMethod } from '../../data/types'

export const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'card', label: 'Card' },
  { value: 'cash', label: 'Cash' },
  { value: 'apple_pay', label: 'Apple Pay' },
  { value: 'transfer', label: 'Transfer' },
  { value: 'other', label: 'Other' },
]

/** A stored method as the union (an unknown value reads as card). */
export const asPaymentMethod = (v: string | null | undefined): PaymentMethod =>
  PAYMENT_METHODS.find((m) => m.value === v)?.value ?? 'card'
