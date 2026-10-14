import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { FeedRow } from '../../activity/FeedRow'
import { useFeedPage, useRefData } from '../../activity/hooks'
import { BackHeader } from '../../../ui/BackHeader'
import { Badge } from '../../../ui/Badge'
import { EmptyState } from '../../../ui/EmptyState'
import { formatShortDate } from '../../../ui/format'
import { List } from '../../../ui/ListRow'
import { Money } from '../../../ui/Money'
import { ProgressBar } from '../../../ui/ProgressBar'
import { QueryView } from '../../../ui/QueryView'
import { BucketSheet } from '../BucketSheet'
import { type BucketSummary, useBucket, useBucketSummary } from './hooks'
import '../plan.css'

type Trip = NonNullable<BucketSummary['trip']>
type Savings = NonNullable<BucketSummary['savings']>

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

/** /plan/buckets/:id: what the bucket holds. Balance against budget, the trip or savings card, and its entries. */
export function BucketDetail() {
  const { id = '' } = useParams()
  const bucket = useBucket(id)
  const summary = useBucketSummary(id)
  const [editing, setEditing] = useState(false)
  const b = bucket.data
  return (
    <>
      <BackHeader
        title={b ? `${b.icon} ${b.name}` : 'Bucket'}
        back="/plan?view=buckets"
        action={b && (
          <button type="button" className="plan-bucket__edit" aria-label="Edit bucket" onClick={() => setEditing(true)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" />
            </svg>
          </button>
        )}
      />
      <section className="screen plan-bucket">
        <QueryView result={bucket} noDataText="No saved data yet. Connect once to load this bucket.">
          {(bk) => (
            <>
              <div className="ui-card plan-trip">
                <div className="plan-budget__top">
                  <span className="plan-budget__name">Spent</span>
                  <span className="plan-budget__fig">
                    {bk.budget == null
                      ? <Money amount={bk.balance.expenses} whole />
                      : <><Money amount={bk.balance.expenses} whole /> of <Money amount={bk.budget} whole /></>}
                  </span>
                </div>
                {bk.budget != null && bk.budget > 0 && <ProgressBar value={bk.balance.expenses} max={bk.budget} label={bk.name} />}
                <div className="plan-budget__foot">
                  {bk.balance.income > 0 && <span>Income <Money amount={bk.balance.income} whole /></span>}
                  {bk.status === 'archived' && <Badge>Archived</Badge>}
                  {bk.budget != null && bk.balance.expenses > bk.budget && <Badge tone="neg">over budget</Badge>}
                </div>
              </div>
              <QueryView result={summary} showBanner={false} noDataText="">
                {({ trip, savings }) => <>{trip && <TripCard trip={trip} />}{savings && <SavingsCard s={savings} />}</>}
              </QueryView>
              <Entries id={id} />
            </>
          )}
        </QueryView>
      </section>
      {b && <BucketSheet open={editing} bucket={b} onClose={() => setEditing(false)} />}
    </>
  )
}

function TripCard({ trip }: { trip: Trip }) {
  const over = trip.remaining !== null && trip.remaining < 0
  return (
    <div className="ui-card plan-trip">
      <div className="plan-budget__top">
        <span className="plan-budget__name">Trip</span>
        {trip.status === 'upcoming' && <Badge>in {trip.days_until}d</Badge>}
        {trip.status === 'active' && <Badge tone="pos">{trip.days_remaining}d left</Badge>}
        {trip.status === 'past' && <Badge>finished</Badge>}
      </div>
      <p className="plan-trip__dates">
        {trip.start && trip.end
          ? <>{formatShortDate(trip.start)} – {formatShortDate(trip.end)}{trip.days ? ` · ${plural(trip.days, 'day')}` : ''}</>
          : 'Set trip dates to see daily spend.'}
      </p>
      <dl className="plan-trip__stats">
        <div><dt>Total</dt><dd><Money amount={trip.total} whole /></dd></div>
        <div><dt>Per day</dt><dd><Money amount={trip.per_day} whole /></dd></div>
        <div><dt>{over ? 'Over budget' : 'Left'}</dt><dd><Money amount={trip.remaining === null ? null : Math.abs(trip.remaining)} whole /></dd></div>
      </dl>
      {trip.people.length > 1 && (
        <ul className="plan-trip__people" aria-label="Per person">
          {trip.people.map((p) => (
            <li key={p.user_id}>
              <span className="plan-trip__name">{p.name}</span>
              <span>paid <Money amount={p.paid} whole /></span>
              <span>share <Money amount={p.share} whole /></span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SavingsCard({ s }: { s: Savings }) {
  return (
    <div className="ui-card plan-trip">
      <div className="plan-budget__top">
        <span className="plan-budget__name">Savings goal</span>
        {s.reached && <Badge tone="pos">goal reached</Badge>}
      </div>
      {s.goal === null ? <p className="plan-trip__dates">Set a goal amount to track progress.</p> : (
        <>
          <span className="plan-budget__fig"><Money amount={s.saved} whole /> of <Money amount={s.goal} whole /></span>
          <ProgressBar value={s.saved} max={s.goal} label="Savings goal" />
          <div className="plan-budget__foot">
            {s.per_month !== null && s.months_left !== null
              ? <span><Money amount={s.per_month} whole /> a month for {plural(s.months_left, 'month')}</span>
              : s.remaining !== null && s.remaining > 0 && <span><Money amount={s.remaining} whole /> to go</span>}
          </div>
        </>
      )}
    </div>
  )
}

/** The bucket's entries, newest first, 50 a page; a row opens it in Activity. */
function Entries({ id }: { id: string }) {
  const [pages, setPages] = useState(1)
  return (
    <>
      <h2 className="plan-bucket__heading">Entries</h2>
      {Array.from({ length: pages }, (_, i) => (
        <EntryPage key={i} id={id} page={i + 1} last={i + 1 === pages} more={() => setPages(i + 2)} />
      ))}
    </>
  )
}

function EntryPage({ id, page, last, more }: { id: string; page: number; last: boolean; more(): void }) {
  const result = useFeedPage({ bucket_id: id }, page)
  const refData = useRefData()
  const navigate = useNavigate()
  return (
    <QueryView result={result} showBanner={false} noDataText="No saved entries yet. Connect once to load them.">
      {(p) => (
        <>
          {p.total === 0 && <EmptyState title="Nothing in this bucket yet" />}
          {p.items.length > 0 && (
            <List label={`Entries, page ${page}`}>
              {p.items.map((t) => <FeedRow key={t.id} t={t} refData={refData} onOpen={(tid) => { void navigate(`/activity/${tid}`) }} />)}
            </List>
          )}
          {last && p.page * p.page_size < p.total && (
            <button type="button" className="btn" onClick={more}>Show more</button>
          )}
          {last && p.total > 0 && <Link className="btn" to={`/activity?bucket_id=${encodeURIComponent(id)}`}>See all in Activity</Link>}
        </>
      )}
    </QueryView>
  )
}
