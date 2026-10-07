import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { usePendingIds } from '../../../data/pending'
import { useRecurringItems } from '../../../data/reads'
import type { EntryOut, RecurringItemOut } from '../../../data/types'
import { TopBar } from '../../../shell/TopBar'
import { Badge } from '../../../ui/Badge'
import { EmptyState } from '../../../ui/EmptyState'
import { formatShortDate } from '../../../ui/format'
import { ChevronLeftIcon, ClockIcon, PauseIcon, PlusIcon } from '../../../ui/icons'
import { ListRow } from '../../../ui/ListRow'
import { Money } from '../../../ui/Money'
import { QueryView } from '../../../ui/QueryView'
import { EntrySheet } from '../EntrySheet'
import { ItemSheet } from './ItemSheet'
import { fromRuleFields, ruleSummary } from './rule'
import './items.css'

export function Items() {
  const items = useRecurringItems()
  const pending = usePendingIds()
  const [params, setParams] = useSearchParams()
  const creating = params.get('new') === '1'
  const [editing, setEditing] = useState<RecurringItemOut | null>(null)
  const [entry, setEntry] = useState<EntryOut | null>(null)
  const closeSheet = () => {
    setEditing(null)
    if (creating) setParams({}, { replace: true })
  }

  return (
    <>
      <TopBar title="Items" actions={
        <>
          <Link to="/plan" className="btn btn--sm btn--ghost" aria-label="Back to Plan"><ChevronLeftIcon />Plan</Link>
          <button type="button" className="ui-iconbtn" aria-label="New item" onClick={() => setParams({ new: '1' })}>
            <PlusIcon />
          </button>
        </>
      } />
      <section className="screen items">
        <QueryView result={items} noDataText="No saved data yet. Connect once to load Plan.">
          {(all) =>
            all.length === 0 ? (
              <EmptyState title="No recurring items yet" body="Add salaries, rent and bills to see what’s coming."
                action={{ label: 'Add a recurring item', onClick: () => setParams({ new: '1' }) }} />
            ) : (
              <>
                <ItemGroup title="In" items={all.filter((i) => i.direction === 'in')} pending={pending} onOpen={setEditing} />
                <ItemGroup title="Out" items={all.filter((i) => i.direction !== 'in')} pending={pending} onOpen={setEditing} />
              </>
            )
          }
        </QueryView>
      </section>
      <ItemSheet open={creating || editing !== null} item={creating ? null : editing} onClose={closeSheet}
        onOpenEntry={(e) => { closeSheet(); setEntry(e) }} />
      <EntrySheet entry={entry} onClose={() => setEntry(null)} />
    </>
  )
}

function ItemGroup({ title, items, pending, onOpen }: {
  title: string; items: RecurringItemOut[]; pending: ReadonlySet<string>; onOpen: (i: RecurringItemOut) => void
}) {
  if (items.length === 0) return null
  const ordered = [...items.filter((i) => i.is_active), ...items.filter((i) => !i.is_active)]
  const id = `items-${title}`
  return (
    <section className="items-group" aria-labelledby={id}>
      <div className="ui-sec"><h2 id={id} className="ui-sec__title">{title}</h2></div>
      <div className="ui-list">
        {ordered.map((i) => {
          const queuedCreate = i.id.startsWith('pending-')
          const next = i.is_active && i.next_entry ? ` · next ${formatShortDate(i.next_entry.due_date)}` : ''
          const badges = [
            !i.is_active && <Badge key="paused" icon={<PauseIcon />}>Paused</Badge>,
            pending.has(i.id) && <Badge key="sync" icon={<ClockIcon />}>Waiting to sync</Badge>,
          ].filter(Boolean)
          return (
            <ListRow key={i.id}
              onClick={queuedCreate ? undefined : () => onOpen(i)}
              muted={!i.is_active}
              title={i.name}
              subtitle={`${ruleSummary(fromRuleFields(i, i.start_date), i.start_date)}${next}`}
              badges={badges.length ? badges : undefined}
              trailing={i.amount === null
                ? <span className="ui-muted">variable</span>
                : <Money amount={i.amount} currency={i.currency} />} />
          )
        })}
      </div>
    </section>
  )
}
