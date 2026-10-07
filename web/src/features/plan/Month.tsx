import { useState } from 'react'
import { useSearchParams } from 'react-router'
import type { BucketMonthRowOut, CategoryUsualOut, MonthPictureOut, MonthRowOut } from '../../data/types'
import { Badge } from '../../ui/Badge'
import { formatMonthLabel, monthsBetween, shiftMonth, todayISO } from '../../ui/format'
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon } from '../../ui/icons'
import { ListRow } from '../../ui/ListRow'
import { Money } from '../../ui/Money'
import { QueryView } from '../../ui/QueryView'
import { useCategoriesVsUsual, usePlanMonth } from './hooks'
import './plan.css'

export const MAX_MONTH_SHIFT = 11
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/

export function Month() {
  const [params, setParams] = useSearchParams()
  const current = todayISO().slice(0, 7)
  const asked = params.get('month')
  const month = asked && MONTH.test(asked) && Math.abs(monthsBetween(current, asked)) <= MAX_MONTH_SHIFT ? asked : current
  const offset = monthsBetween(current, month)
  const go = (by: number) => {
    const next = new URLSearchParams(params)
    next.set('month', shiftMonth(month, by))
    setParams(next, { replace: true })
  }
  const picture = usePlanMonth(month)
  const usual = useCategoriesVsUsual(month)

  return (
    <div className="plan-month">
      <div className="plan-switch">
        <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Previous month"
          disabled={offset <= -MAX_MONTH_SHIFT} onClick={() => go(-1)}><ChevronLeftIcon /></button>
        <h3 className="plan-switch__label" aria-live="polite">{formatMonthLabel(month)}</h3>
        <button type="button" className="ui-iconbtn ui-iconbtn--bare" aria-label="Next month"
          disabled={offset >= MAX_MONTH_SHIFT} onClick={() => go(1)}><ChevronRightIcon /></button>
      </div>
      <QueryView result={picture} noDataText="No saved data yet. Connect once to load Plan.">
        {(p) => <MonthPicture picture={p} />}
      </QueryView>
      {usual.data && usual.data.length > 0 && <CategoriesVsUsual rows={usual.data} />}
    </div>
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
          <tr><td /><th scope="col">So far</th><th scope="col">To come</th><th scope="col">Projected</th></tr>
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
