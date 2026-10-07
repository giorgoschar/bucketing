import { ChevronDownIcon } from './icons'
import './composer-kit.css'

export interface AmountDisplayProps {
  /** The typed amount formatted for display, e.g. "1,234.5"; "0" when empty. */
  text: string
  symbol: string
  currency: string
  /** Read by screen readers, e.g. "Amount 4.10 euro". */
  spoken: string
  tone?: 'default' | 'income'
  /** "≈ €23.06" when the currency is not the household's. */
  converted?: string | null
  /** Absent: the currency is shown but not changeable. */
  onCurrency?: () => void
  /** "from receipt" after a QR scan, until the amount is edited. */
  tag?: string | null
}

export function AmountDisplay(p: AmountDisplayProps) {
  return (
    <div className={p.tone === 'income' ? 'amount amount--income' : 'amount'}>
      <div role="status" className="ck-visually-hidden">{p.spoken}</div>
      <div className={p.text.length > 9 ? 'amount__big amount__big--small' : 'amount__big'} aria-hidden="true">
        <span className="amount__symbol">{p.symbol}</span>
        {p.text}
        <span className="amount__caret" />
      </div>
      {p.onCurrency ? (
        <button type="button" className="amount__cur" onClick={p.onCurrency} aria-label={`Currency: ${p.currency}. Change`}>
          {p.currency}
          <ChevronDownIcon />
        </button>
      ) : (
        <span className="amount__cur">{p.currency}</span>
      )}
      {p.converted && <p className="amount__converted">{p.converted}</p>}
      {p.tag && <span className="amount__tag">{p.tag}</span>}
    </div>
  )
}
