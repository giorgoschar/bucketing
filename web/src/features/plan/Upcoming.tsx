import { useState } from 'react'
import { usePendingIds } from '../../data/pending'
import type { EntryOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { EmptyState } from '../../ui/EmptyState'
import { formatMonthShort, todayISO } from '../../ui/format'
import { CheckIcon, ClockIcon } from '../../ui/icons'
import { List, ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { EntrySheet } from './EntrySheet'
import { usePlanUpcoming } from './hooks'
import { formatWeekdayDay, groupUpcomingWeeks, type UpcomingWeek } from './upcomingWeeks'
import './plan.css'

export function Upcoming() {
  const upcoming = usePlanUpcoming()
  const pending = usePendingIds()
  const [open, setOpen] = useState<EntryOut | null>(null)

  return (
    <>
      <QueryView result={upcoming} noDataText="No saved data yet. Connect once to load Plan.">
        {(all) => {
          const weeks = groupUpcomingWeeks(all, todayISO())
          if (weeks.length === 0) {
            return (
              <EmptyState title="Nothing due in the next 30 days"
                action={{ label: 'Add a recurring item', to: '/plan/items?new=1' }} />
            )
          }
          return (
            <div className="plan-days">
              {weeks.map((w) => (
                <section key={w.start} className="plan-day" aria-labelledby={`week-${w.start}`}>
                  <header className="plan-day__head">
                    <h3 id={`week-${w.start}`} className="plan-day__title">{w.label}</h3>
                    <WeekNet week={w} />
                  </header>
                  <List>
                    {w.entries.map((e) => (
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

/** "Net this month" once per week; a week that crosses a month names each month it touches. */
function WeekNet({ week }: { week: UpcomingWeek }) {
  return (
    <span className="plan-day__net">
      {week.nets.map((n) => (
        <span key={n.month} className="plan-day__netpart">
          {week.nets.length > 1 ? `Net ${formatMonthShort(n.month)}` : 'Net this month'} <Money amount={n.net} signed />
        </span>
      ))}
    </span>
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
      leading={<span className="plan-up__day">{formatWeekdayDay(entry.due_date)}</span>}
      title={entry.name}
      subtitle={isIn ? 'In' : undefined}
      badges={badges.length ? badges : undefined}
      trailing={
        <Money amount={entry.amount} currency={entry.currency} estimated={entry.estimated}
          signed={isIn} tone={isIn ? 'auto' : 'none'} nullText="No amount yet" />
      }
    />
  )
}
