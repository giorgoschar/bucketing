import { Link } from 'react-router'
import { formatShortDate } from '../../../ui/format'
import { Money } from '../../../ui/Money'
import { changeLabel } from './format'
import { Sparkline } from './Sparkline'
import './bills.css'
import type { BillRow } from './types'

const TITLE = (b: BillRow) =>
  `${b.name}: last ${b.recent.length} ${b.recent.length === 1 ? 'payment' : 'payments'}, ${b.recent.map((n) => n.toFixed(2)).join(', ')}`

/** One bill in the list and in the Insights panel: name, last amount and date, trend, 12-month total, change. */
export function BillRowLink({ bill, compact = false }: { bill: BillRow; compact?: boolean }) {
  const { last, change } = bill
  return (
    <Link className="billrow" to={`/insights/bills/${encodeURIComponent(bill.item_id)}`}>
      <span className="billrow__main">
        <span className="billrow__name">{bill.name}</span>
        <span className="billrow__sub">
          {!last ? 'No payments yet'
            : compact ? formatShortDate(last.due_date)
            : <><Money amount={last.amount} className="ui-num" /> · {formatShortDate(last.due_date)}</>}
        </span>
        {change && (
          <span className={`billrow__change billrow__change--${change.direction}`}>{changeLabel(change)}</span>
        )}
      </span>
      {!compact && bill.recent.length > 0 && <Sparkline values={bill.recent} title={TITLE(bill)} />}
      {!compact && (
        <span className="billrow__total">
          {bill.total_12m !== null ? <><Money amount={bill.total_12m} className="ui-num" /><span className="billrow__totalnote">12 months</span></> : null}
        </span>
      )}
      {compact && last && <Money amount={last.amount} className="ui-num billrow__amount" />}
    </Link>
  )
}
