import { Link } from 'react-router'
import { BillRowLink } from '../bills/BillRowLink'
import { BILLS_SCOPE_NOTE } from '../bills/format'
import { useBills } from '../bills/hooks'
import { Card } from '../widgets/Card'
import '../bills/bills.css'

export const PANEL_ROWS = 8

/** The Bills list inline on the desktop dashboard: up to 8 bills, then "All bills" (spec §5.4). */
export function BillsPanel() {
  const bills = useBills().data
  if (!bills) return null
  // Paused bills follow the active ones (the server's order), so a household with only paused bills still sees them.
  const shown = bills.slice(0, PANEL_ROWS)
  return (
    <Card title="Bills" action={bills.length > 0 ? <Link to="/insights/bills">All bills</Link> : undefined}>
      {shown.length === 0 ? (
        <p className="insights__note">No recurring bills yet. <Link to="/plan/items">Open items</Link></p>
      ) : (
        <>
          <div className="billscard__list">{shown.map((b) => <BillRowLink key={b.item_id} bill={b} />)}</div>
          <p className="insights__note">{BILLS_SCOPE_NOTE}</p>
        </>
      )}
    </Card>
  )
}
