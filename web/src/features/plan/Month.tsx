import { useState } from 'react'
import { useSearchParams } from 'react-router'
import type { BucketMonthRowOut, CategoryUsualOut, MonthPictureOut, MonthRowOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { ChevronDownIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { Segmented } from '../../ui/Segmented'
import { useCategoriesVsUsual, usePlanMonth } from './hooks'
import { MonthStepper } from './MonthStepper'
import { MAX_MONTH_SHIFT, useShownMonth } from './shownMonth'
import { Year } from './Year'
import './plan.css'

export { MAX_MONTH_SHIFT }

const SCALES = [
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
] as const
type Scale = (typeof SCALES)[number]['value']

/** Plan › Month, with Year folded in as a scale (cash spec §4.1): ?view=month&scale=year. */
export function Month() {
  const [params, setParams] = useSearchParams()
  const scale: Scale = params.get('scale') === 'year' || params.get('view') === 'year' ? 'year' : 'month'
  const choose = (v: Scale) => {
    const next = new URLSearchParams(params)
    next.set('view', 'month')
    if (v === 'year') next.set('scale', 'year')
    else next.delete('scale')
    setParams(next, { replace: true })
  }
  return (
    <div className="plan-month">
      <div className="plan-scale">
        <Segmented label="Month or year" options={SCALES} value={scale} onChange={choose} />
      </div>
      {scale === 'year' ? <Year /> : <MonthScale />}
    </div>
  )
}

function MonthScale() {
  const { month, go } = useShownMonth()
  const picture = usePlanMonth(month)
  const usual = useCategoriesVsUsual(month)

  return (
    <>
      <MonthStepper month={month} onStep={go} />
      <QueryView result={picture} noDataText="No saved data yet. Connect once to load Plan.">
        {(p) => <MonthPicture picture={p} />}
      </QueryView>
      {usual.data && usual.data.length > 0 && <CategoriesVsUsual rows={usual.data} />}
    </>
  )
}

function MonthPicture({ picture: p }: { picture: MonthPictureOut }) {
  const est = p.estimated
  const rows: [string, MonthRowOut][] = [['In', p.income], ['Out · Fixed', p.fixed], ['Out · Buckets', p.buckets]]
  return (
    <>
      <div className="ui-card plan-net">
        <p className="ui-eyebrow">Net (projected)</p>
        <Money className="ui-figure plan-net__figure" amount={p.net_projected} signed estimated={est} />
      </div>
      <table className="plan-table">
        <caption className="ui-sr">In and out this month</caption>
        <thead>
          <tr><th scope="col"><span className="ui-sr">Line</span></th><th scope="col">So far</th><th scope="col">To come</th><th scope="col">Projected</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, r]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td><Money amount={r.so_far} whole /></td>
              <td><Money amount={r.still_to_come} whole estimated={est} /></td>
              <td><Money amount={r.projected} whole estimated={est} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <BucketRows rows={p.buckets.rows} estimated={est} />
      <ul className="plan-aside">
        <li>Trips & events: <Money amount={p.events_spent} /></li>
        <li>Cash not yet logged: <Money amount={p.cash} /></li>
      </ul>
      <p className="plan-aside__note">Not counted in Net.</p>
    </>
  )
}

function BucketRows({ rows, estimated }: { rows: BucketMonthRowOut[]; estimated: boolean }) {
  const [open, setOpen] = useState<string | null>(null)
  if (rows.length === 0) return null
  return (
    <div className="ui-list">
      {rows.map((b) => {
        const expanded = open === b.bucket_id
        return (
          <div key={b.bucket_id} className="plan-bucket">
            <button type="button" className="ui-row" aria-expanded={expanded}
              onClick={() => setOpen(expanded ? null : b.bucket_id)}>
              <span className="ui-row__main"><span className="ui-row__title">{b.name}</span></span>
              <span className="ui-row__end"><Money amount={b.projected} whole estimated={estimated} /></span>
              <span className="plan-bucket__chev" aria-hidden="true"><ChevronDownIcon /></span>
            </button>
            {expanded && (
              <dl className="plan-bucket__detail">
                <div><dt>Budget</dt><dd>{b.budget === null ? 'No budget' : <Money amount={b.budget} whole />}</dd></div>
                <div><dt>So far</dt><dd><Money amount={b.so_far} whole /></dd></div>
                <div><dt>Projected</dt><dd><Money amount={b.projected} whole estimated={estimated} /></dd></div>
              </dl>
            )}
          </div>
        )
      })}
    </div>
  )
}

function CategoriesVsUsual({ rows }: { rows: CategoryUsualOut[] }) {
  return (
    <section aria-labelledby="usual-title">
      <div className="ui-sec"><h3 id="usual-title" className="ui-sec__title">Categories vs usual</h3></div>
      <div className="ui-list">
        {rows.map((c) => (
          <ListRow key={c.category_id ?? c.name}
            className={c.flagged ? 'plan-usual__row--flagged' : undefined}
            leading={<span className="plan-usual__icon" aria-hidden="true">{c.icon}</span>}
            title={c.name}
            subtitle={c.usual === null ? 'Usual —' : <>Usual <Money amount={c.usual} whole /></>}
            badges={c.flagged ? <Badge tone="warn">above usual</Badge> : undefined}
            trailing={<Money amount={c.this_month} whole />} />
        ))}
      </div>
    </section>
  )
}
