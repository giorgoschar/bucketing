import { formatMoney } from './format'

export interface MoneyProps {
  amount: number | null
  currency?: string
  signed?: boolean
  whole?: boolean
  estimated?: boolean
  /** 'auto' tints positive amounts with --pos (income); the sign carries the meaning either way. */
  tone?: 'auto' | 'none'
  nullText?: string
  className?: string
}

export function Money({
  amount, currency = 'EUR', signed = false, whole = false, estimated = false, tone = 'none', nullText = '—', className,
}: MoneyProps) {
  if (amount === null || !Number.isFinite(amount)) {
    return <span className={['ui-money', className].filter(Boolean).join(' ')}>{nullText}</span>
  }
  const cls = ['ui-money', tone === 'auto' && amount > 0 ? 'ui-pos' : null, className].filter(Boolean).join(' ')
  return <span className={cls}>{`${estimated ? '≈ ' : ''}${formatMoney(amount, { currency, signed, whole })}`}</span>
}
