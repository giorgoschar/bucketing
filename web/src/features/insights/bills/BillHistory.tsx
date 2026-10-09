import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useOnline } from '../../../data/online'
import { BackHeader } from '../../../ui/BackHeader'
import { QueryView } from '../../../ui/QueryView'
import { formatMoney, formatShortDate, todayISO } from '../../../ui/format'
import { UnitPriceLine, YearBars } from './charts'
import { changeSentence } from './format'
import { againstLastYear, twelveMonth, unitPriceOf, usualOf, yearCells, yearsOf } from './history'
import { useItemHistory } from './hooks'
import { OfflineNote } from './OfflineNote'
import { UsageSheet, type UsageSheetTarget } from './UsageSheet'
import type { HistoryPoint, ItemHistoryOut } from './types'
import '../insights.css'
import './bills.css'

const usageFmt = new Intl.NumberFormat('en-IE', { maximumFractionDigits: 3 })
const dateFull = (iso: string) => `${formatShortDate(iso)} ${iso.slice(0, 4)}`
const symbolOf = (currency: string) => formatMoney(0, { currency }).replace(/[\d.,\s]+/g, '')

/** The route element: /insights/bills/:id. */
export function BillHistory() {
  const { id = '' } = useParams()
  return <BillHistoryView id={id} />
}

/** One recurring item's history: tiles, year charts, and the table that is their text alternative (spec §5.3). */
export function BillHistoryView({ id }: { id: string }) {
  const history = useItemHistory(id)
  return (
    <>
      <BackHeader title={history.data?.item.name ?? 'Bill'} back="/insights/bills" />
      <section className="screen insights bills billhist">
        <QueryView result={history} showBanner={false} noDataText="No saved history yet. Connect once to load it.">
          {(h) => (
            <>
              {history.stale && <OfflineNote />}
              <HistoryBody h={h} id={id} />
            </>
          )}
        </QueryView>
      </section>
    </>
  )
}

function HistoryBody({ h, id }: { h: ItemHistoryOut; id: string }) {
  const online = useOnline()
  const { item, points, change } = h
  const unit = item.usage_unit
  const cur = item.currency
  const money = (n: number) => formatMoney(n, { currency: cur })
  const years = yearsOf(points)
  const latest = years.length ? years[years.length - 1] : Number(todayISO().slice(0, 4))
  const [picked, setPicked] = useState<number | null>(null)
  const year = Math.min(Math.max(picked ?? latest, years[0] ?? latest), latest)
  const [editing, setEditing] = useState<UsageSheetTarget | null>(null)

  const last = points.at(-1)
  const usual = usualOf(points, change)
  const twelve = twelveMonth(points, todayISO())
  const cells = yearCells(points, year)
  const priced = points.filter((p) => p.unit_price !== null).length
  const metered = points.filter((p) => p.usage !== null).length
  const enough = points.length >= 2

  return (
    <>
      <dl className="billhist__tiles ui-card" role="group" aria-label="Summary">
        <div>
          <dt>Last</dt>
          <dd className="ui-num">{last ? money(last.amount) : '—'}{last && <span className="billhist__tilenote">{formatShortDate(last.due_date)}</span>}</dd>
        </div>
        <div><dt>Usual</dt><dd className="ui-num">{usual !== null ? money(usual) : '—'}</dd></div>
        <div><dt>12 months</dt><dd className="ui-num">{twelve ? money(twelve.total) : '—'}</dd></div>
        <div><dt>Average</dt><dd className="ui-num">{twelve ? money(twelve.average) : '—'}</dd></div>
      </dl>

      {change && <p className="billhist__change insights__sentence" role="note">{changeSentence(item.name, change, unit, cur)}</p>}

      {enough ? (
        <>
          <div className="billhist__year" role="group" aria-label="Year">
            <button type="button" className="ui-iconbtn" aria-label="Previous year" disabled={year <= years[0]} onClick={() => setPicked(year - 1)}>‹</button>
            <span className="ui-num billhist__yearlabel">{year}</span>
            <button type="button" className="ui-iconbtn" aria-label="Next year" disabled={year >= latest} onClick={() => setPicked(year + 1)}>›</button>
          </div>
          <div className="billhist__charts">
            <section className="ui-card insights__card" aria-label="Amount by month">
              <h2 className="insights__cardtitle">Amount by month</h2>
              <YearBars title={`Amount by month, ${year}`} year={year} cells={cells} value={(c) => c.amount} compare={(c) => c.lastYear} format={money} />
            </section>
            {unit && priced >= 2 && (
              <section className="ui-card insights__card" aria-label={`Price per ${unit}`}>
                <h2 className="insights__cardtitle">{`Price per ${unit}`}</h2>
                {cells.some((c) => c.unitPrice !== null)
                  ? <UnitPriceLine title={`Price per ${unit} by month, ${year}`} year={year} cells={cells} format={(n) => `${symbolOf(cur)}${n.toFixed(3)}`} />
                  : <p className="insights__note">{`No price per ${unit} in ${year}.`}</p>}
              </section>
            )}
            {unit && metered >= 2 && (
              <section className="ui-card insights__card" aria-label="Usage">
                <h2 className="insights__cardtitle">Usage</h2>
                <YearBars title={`Usage by month, ${year} (${unit})`} year={year} cells={cells} value={(c) => c.usage}
                  format={(n) => `${usageFmt.format(n)} ${unit}`} />
              </section>
            )}
          </div>
        </>
      ) : (
        <p className="insights__note billhist__thin">Not enough history yet. It fills in as you pay this bill.</p>
      )}

      <div className="billhist__scroll">
        <table className="billhist__table">
          <caption className="billhist__cap">{`${item.name} history`}</caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col" className="billhist__r">Amount</th>
              {unit && <th scope="col" className="billhist__r">Usage</th>}
              {unit && <th scope="col" className="billhist__r">Per unit</th>}
              <th scope="col" className="billhist__r">Against last year</th>
              {unit && <th scope="col"><span className="billhist__cap">Edit</span></th>}
            </tr>
          </thead>
          <tbody>
            {[...points].reverse().map((p) => (
              <tr key={p.entry_id}>
                <th scope="row">
                  {p.transaction_id
                    ? <Link to={`/activity/${encodeURIComponent(p.transaction_id)}`}>{dateFull(p.due_date)}</Link>
                    : dateFull(p.due_date)}
                </th>
                <td className="ui-num billhist__r">{money(p.amount)}</td>
                {unit && <td className="ui-num billhist__r">{p.usage !== null ? `${usageFmt.format(p.usage)} ${unit}` : '—'}</td>}
                {unit && <td className="ui-num billhist__r">{perUnit(p, cur)}</td>}
                <td className="ui-num billhist__r">{vsLastYear(points, p, cur)}</td>
                {unit && (
                  <td>
                    <button type="button" className="btn btn--sm btn--ghost" disabled={!online}
                      aria-label={`Edit usage, ${dateFull(p.due_date)}`}
                      onClick={() => setEditing({ entryId: p.entry_id, dueDate: p.due_date, usage: p.usage })}>
                      Edit usage
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {unit && !online && <p className="billhist__offline">Connect to change usage</p>}
      <p className="insights__note">Bills cover all time. The lens and period do not apply.</p>
      {unit && <UsageSheet itemId={id} unit={unit} target={editing} onClose={() => setEditing(null)} />}
    </>
  )
}

function perUnit(p: HistoryPoint, currency: string): string {
  const v = p.unit_price ?? unitPriceOf(p.amount, p.usage)
  return v === null ? '—' : `${symbolOf(currency)}${v.toFixed(4)}`
}

function vsLastYear(points: HistoryPoint[], p: HistoryPoint, currency: string): string {
  const d = againstLastYear(points, p)
  if (!d) return '—'
  const sign = (n: number) => (n > 0 ? '+' : n < 0 ? '−' : '')
  const eur = `${sign(d.delta)}${formatMoney(Math.abs(d.delta), { currency })}`
  return d.pct === null ? eur : `${eur} (${sign(d.pct)}${Math.abs(d.pct)}%)`
}
