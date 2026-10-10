import { BackHeader } from '../../../ui/BackHeader'
import { EmptyState } from '../../../ui/EmptyState'
import { QueryView } from '../../../ui/QueryView'
import { BillRowLink } from './BillRowLink'
import { useBills } from './hooks'
import { BILLS_SCOPE_NOTE } from './format'
import { OfflineNote } from './OfflineNote'
import '../insights.css'
import './bills.css'

/** /insights/bills: every recurring out item with its trend and, when it changed, how much (spec §5.2). */
export function BillsList() {
  const bills = useBills()
  return (
    <>
      <BackHeader title="Bills" back="/insights" />
      <section className="screen insights bills">
        <QueryView result={bills} showBanner={false} noDataText="No saved bills yet. Connect once to load Bills.">
          {(rows) => {
            const active = rows.filter((b) => b.is_active)
            const paused = rows.filter((b) => !b.is_active)
            return (
              <>
                {bills.stale && <OfflineNote />}
                {rows.length === 0 ? (
                  <EmptyState title="No recurring bills yet" action={{ label: 'Open items', to: '/plan/items' }} />
                ) : (
                  <>
                    <p className="insights__note">{BILLS_SCOPE_NOTE}</p>
                    {active.length > 0 && (
                      <div className="ui-card bills__group">
                        {active.map((b) => <BillRowLink key={b.item_id} bill={b} />)}
                      </div>
                    )}
                    {paused.length > 0 && (
                      <>
                        <h2 className="bills__heading">Paused</h2>
                        <div className="ui-card bills__group">
                          {paused.map((b) => <BillRowLink key={b.item_id} bill={b} />)}
                        </div>
                      </>
                    )}
                  </>
                )}
              </>
            )
          }}
        </QueryView>
      </section>
    </>
  )
}
