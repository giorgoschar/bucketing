import { useState } from 'react'
import { usePendingIds } from '../../data/pending'
import type { EntryOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatDayHeader } from '../../ui/format'
import { ArrowInIcon, ArrowOutIcon, CheckIcon, ClockIcon } from '../../ui/icons'
import { List, ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { EntrySheet } from './EntrySheet'
import { usePlanUpcoming } from './hooks'
import './plan.css'

export function Upcoming() {
  const upcoming = usePlanUpcoming()
  const pending = usePendingIds()
  const [open, setOpen] = useState<EntryOut | null>(null)

  return (
    <>
      <QueryView result={upcoming} noDataText="No saved data yet. Connect once to load Plan.">
        {(all) => {
          const days = all.filter((d) => d.entries.length > 0)
          if (days.length === 0) {
            return (
              <EmptyState title="Nothing due in the next 30 days"
                action={{ label: 'Add a recurring item', to: '/plan/items?new=1' }} />
            )
          }
          return (
            <div className="plan-days">
              {days.map((d) => (
                <section key={d.date} className="plan-day" aria-labelledby={`day-${d.date}`}>
                  <header className="plan-day__head">
                    <h3 id={`day-${d.date}`} className="plan-day__title">{formatDayHeader(d.date)}</h3>
                    <span className="plan-day__net">Net this month <Money amount={d.net_this_month} signed /></span>
                  </header>
                  <List>
                    {d.entries.map((e) => (
                      <EntryRow key={e.id} entry={e} pending={pending.has(e.id)} onOpen={() => setOpen(e)} />
                    ))}
                  </List>
                </section>
              ))}
            </div>
          )
        }}
      </QueryView>
      <EntrySheet entry={open} onClose={() => setOpen(null)} />
    </>
  )
}

function EntryRow({ entry, pending, onOpen }: { entry: EntryOut; pending: boolean; onOpen: () => void }) {
  const isIn = entry.direction === 'in'
  const badges = [
    pending && <Badge key="sync" icon={<ClockIcon />}>Waiting to sync</Badge>,
    entry.status === 'done' && <Badge key="done" tone="pos" icon={<CheckIcon />}>{isIn ? 'Received' : 'Paid'}</Badge>,
    entry.status === 'skipped' && <Badge key="skip">Skipped</Badge>,
  ].filter(Boolean)
  return (
    <ListRow
      onClick={onOpen}
      leading={<span className={isIn ? 'ui-ico ui-ico--pos' : 'ui-ico ui-ico--neutral'}>{isIn ? <ArrowInIcon /> : <ArrowOutIcon />}</span>}
      title={entry.name}
      subtitle={isIn ? 'In' : 'Out'}
      badges={badges.length ? badges : undefined}
      trailing={
        <Money amount={entry.amount} currency={entry.currency} estimated={entry.estimated}
          signed={isIn} tone={isIn ? 'auto' : 'none'} nullText="No amount yet" />
      }
    />
  )
}
