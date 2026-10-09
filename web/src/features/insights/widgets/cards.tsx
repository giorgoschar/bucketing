import { Link, useNavigate } from 'react-router'
import { HBarList, MonthBars, seriesColor, StackBar } from '../../../ui/charts'
import { formatShortDate } from '../../../ui/format'
import { Money } from '../../../ui/Money'
import { ProgressBar } from '../../../ui/ProgressBar'
import type { WidgetCtx } from '../Insights'
import { eur, eurWhole, monthEnd } from '../format'
import { useCategoriesVsUsual, usePlanMonth } from '../hooks'
import { HOUSEHOLD, insightsSearch } from '../lens'
import { singleMonth } from '../overview'
import { CASH_NOT_LOGGED, UNCATEGORISED } from '../types'
import { BillRowLink } from '../bills/BillRowLink'
import { useBills } from '../bills/hooks'
import { Card } from './Card'

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)
const firstName = (s: string | null | undefined) => (s ?? '').split(' ')[0]

/** "On track for €2,310 by Oct 31": Out projected (Fixed + Buckets) from 2a's month picture,
 *  not the straight-line forecast (which ignores bills and income). */
export function OnTrack({ data }: WidgetCtx) {
  const month = (data.start_date ?? '').slice(0, 7)
  const plan = usePlanMonth(month).data
  if (!plan) return null
  const out = plan.fixed.projected + plan.buckets.projected
  return (
    <Card title="This month">
      <p className="insights__lead">On track for {eurWhole(out)} by {monthEnd(`${plan.month}-01`)}</p>
      <p className="insights__note">Spent so far plus the bills and budgets still to come.</p>
    </Card>
  )
}

export function InOut({ data, lens, members }: WidgetCtx) {
  const who = members.find((m) => m.user_id === lens)
  const inLabel = lens === HOUSEHOLD || !who ? 'In' : `In · received by ${firstName(who.display_name || who.username)}`
  const net = data.in_out.net
  return (
    <Card title="In / Out / Net">
      <dl className="insights__trio">
        <div><dt>{inLabel}</dt><dd className="ui-num">{eur(data.in_out.in)}</dd></div>
        <div><dt>Out</dt><dd className="ui-num">{eur(data.in_out.out)}</dd></div>
        <div><dt>Net</dt><dd className={net >= 0 ? 'ui-num ui-pos' : 'ui-num'}>{eur(net)}</dd></div>
      </dl>
    </Card>
  )
}

/** Top 8 categories to scale, plus the hatched cash row; each category opens its drill-down. */
export function WhereItWent({ data, period, lens }: WidgetCtx) {
  const navigate = useNavigate()
  const cats = data.categories.filter((c) => c.category_id !== CASH_NOT_LOGGED).slice(0, 8)
  const cash = data.categories.find((c) => c.category_id === CASH_NOT_LOGGED)
  const rows = [...cats, ...(cash ? [cash] : [])].map((c) => ({
    id: c.category_id === null ? UNCATEGORISED : c.category_id,
    label: c.name,
    icon: c.icon,
    value: c.amount,
    hatched: c.category_id === CASH_NOT_LOGGED,
  }))
  return (
    <Card title="Where it went">
      <HBarList label="Where it went" rows={rows} format={eur}
        onSelect={(row) => navigate(`/insights/category/${encodeURIComponent(row.id)}${insightsSearch(period, lens)}`)} />
    </Card>
  )
}

export function InOutMonths({ data }: WidgetCtx) {
  const m = data.monthly_in_out
  const totIn = sum(m.map((r) => r.in))
  const totOut = sum(m.map((r) => r.out))
  return (
    <Card title="In and Out by month">
      <MonthBars title="In and Out by month" months={m.map((r) => r.label)} current format={eur}
        series={[{ name: 'In', values: m.map((r) => r.in) }, { name: 'Out', values: m.map((r) => r.out) }]} />
      <p className="insights__foot ui-num">{m.length} months: In {eur(totIn)} · Out {eur(totOut)} · Net {eur(totIn - totOut)}</p>
    </Card>
  )
}

export function SpendTrend({ data }: WidgetCtx) {
  const t = data.monthly_trend
  const done = t.filter((r) => !r.is_current)
  const avg = done.length ? sum(done.map((r) => r.total)) / done.length : null
  return (
    <Card title="Spend trend">
      <MonthBars title="Spend by month" months={t.map((r) => r.label)} current={t.at(-1)?.is_current}
        series={[{ name: 'Spent', values: t.map((r) => r.total) }]} format={eur} />
      {avg != null && <p className="insights__foot ui-num">Average {eur(avg)} a month</p>}
    </Card>
  )
}

export function Biggest({ data }: WidgetCtx) {
  const l = data.kpis.largest
  if (!l) return null
  return (
    <Card title="Biggest expense">
      <div className="insights__item">
        <span className="insights__item-main">
          <span className="insights__item-title">{l.notes || l.category || 'Expense'}</span>
          <span className="insights__note">{[l.category, formatShortDate(l.date)].filter(Boolean).join(' · ')}</span>
        </span>
        <Money amount={l.amount} className="insights__item-value" />
      </div>
    </Card>
  )
}

/** One stacked bar plus the list underneath (its text equivalent); unlogged cash is left out of Cash. */
export function HowYouPaid({ data }: WidgetCtx) {
  const notLogged = data.in_out.cash_not_logged
  const segments = data.by_method
    .map((m, i) => ({ id: m.method, label: m.label, color: i, value: m.method === 'cash' ? Math.max(0, m.amount - notLogged) : m.amount }))
    .filter((s) => s.value > 0)
  const total = sum(segments.map((s) => s.value))
  return (
    <Card title="How you paid">
      <StackBar label="How you paid" segments={segments} format={eur} />
      <ul className="insights__legend">
        {segments.map((s) => (
          <li key={s.id}>
            <span className="insights__dot" style={{ background: seriesColor(s.color) }} aria-hidden="true" />
            <span className="insights__legend-name">{s.label}</span>
            <span className="ui-num">{eur(s.value)}</span>
            <span className="ui-num insights__legend-pct">{total ? Math.round((s.value / total) * 100) : 0}%</span>
          </li>
        ))}
      </ul>
      {notLogged > 0 && <p className="insights__foot">Leaves out the {eur(notLogged)} cash not logged yet</p>}
    </Card>
  )
}

export function BudgetsCard({ data }: WidgetCtx) {
  return (
    <Card title="Budgets" action={<Link to="/plan?view=budgets">Plan › Budgets</Link>}>
      <ul className="insights__budgets">
        {data.budget_status.map((b) => (
          <li key={b.bucket_id}>
            <div className="insights__budget-head">
              <span className="insights__budget-name">{b.bucket_name}</span>
              <span className="ui-num">{b.budget != null ? `${eur(b.spent)} of ${eur(b.budget)}${b.over_budget ? ' · over' : ''}` : eur(b.spent)}</span>
            </div>
            {b.budget != null && <ProgressBar value={b.spent} max={b.budget} label={`${b.bucket_name} budget`} thin />}
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function SavingsRate({ data }: WidgetCtx) {
  const r = data.kpis.savings_rate
  if (r == null) return null
  return (
    <Card title="Savings rate">
      <p className="insights__lead">{r >= 0 ? `You kept ${Math.round(r)}% of what came in` : `You spent ${Math.abs(Math.round(r))}% more than came in`}</p>
    </Card>
  )
}

export function VsUsual({ data, period }: WidgetCtx) {
  // Only shown for single-month periods (visibleWidgets), so the month is known.
  const rows = useCategoriesVsUsual(singleMonth(period, data) ?? '').data ?? []
  const sorted = [...rows].sort((a, b) => Number(b.flagged) - Number(a.flagged))
  if (!sorted.length) return null
  return (
    <Card title="Categories vs usual">
      <ul className="insights__rows" aria-label="Categories vs usual">
        {sorted.map((c) => (
          <li key={c.category_id ?? c.name} className="insights__item">
            <span className="insights__item-main">
              <span className="insights__item-title"><span aria-hidden="true">{c.icon}</span> {c.name}</span>
              {c.flagged && <span className="insights__flag">above usual</span>}
            </span>
            <span className="insights__item-value ui-num">{eur(c.this_month)}<span className="insights__note"> · usual {c.usual != null ? eur(c.usual) : '—'}</span></span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export function FuelCard({ data, period, lens }: WidgetCtx) {
  const fuel = data.fuel
  if (!fuel) return null
  const search = insightsSearch(period, lens)
  return (
    <Card title="Fuel" action={<Link to={`/insights/fuel${search}`}>All cars</Link>}>
      <ul className="insights__rows">
        {fuel.cars.map((c) => (
          <li key={c.bucket_id}>
            <Link className="insights__item insights__item--link" to={`/insights/fuel${search}&car=${encodeURIComponent(c.bucket_id)}`}>
              <span className="insights__item-main">
                <span className="insights__item-title"><span aria-hidden="true">{c.icon}</span> {c.name}</span>
                <span className="insights__note">{c.fills} {c.fills === 1 ? 'fill-up' : 'fill-ups'}</span>
              </span>
              <span className="insights__item-value ui-num">
                {c.litres} L · {c.avg_price_per_litre != null ? `€${c.avg_price_per_litre.toFixed(3)}/L` : '—'}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

/** The three bills with the highest 12-month total, and a way into all of them (Phase A §5.2).
 *  Not tied to the lens or period (a bill's history is the household's), and quiet until it has data. */
export function BillsCard() {
  const bills = useBills().data
  if (!bills) return null
  const top = [...bills].sort((a, b) => (b.total_12m ?? 0) - (a.total_12m ?? 0)).slice(0, 3)
  return (
    <Card title="Bills" action={bills.length > 0 ? <Link to="/insights/bills">All bills</Link> : undefined}>
      {top.length === 0 ? (
        <p className="insights__note">No recurring bills yet. <Link to="/plan/items">Open items</Link></p>
      ) : (
        <>
          <div className="billscard__list">{top.map((b) => <BillRowLink key={b.item_id} bill={b} compact />)}</div>
          <p className="insights__note">All time. The lens and period do not apply.</p>
        </>
      )}
    </Card>
  )
}
